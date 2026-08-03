from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import posixpath
import random
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

import httpx
from platformdirs import user_cache_dir, user_config_dir

from . import __version__
from .storage import sha256_file

CONFIG_DIR = Path(user_config_dir("blend-farm", "BlendFarm"))
CACHE_DIR = Path(user_cache_dir("blend-farm", "BlendFarm"))
CONFIG_FILE = CONFIG_DIR / "worker.json"
CHUNK_SIZE = 32 * 1024**2


class WorkerError(RuntimeError):
    pass


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise WorkerError(f"Worker is not enrolled. Run 'blend-farm-worker enroll'. Expected {CONFIG_FILE}")
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, CONFIG_FILE)


def capabilities(device: str = "AUTO") -> dict:
    gpu = "unknown"
    for command in (["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], ["rocminfo"]):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
            if result.returncode == 0 and result.stdout.strip():
                gpu = result.stdout.strip().splitlines()[0][:200]
                break
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {
        "worker_version": __version__, "os": platform.system(), "os_version": platform.version(),
        "architecture": platform.machine(), "cpu_count": os.cpu_count(), "gpu": gpu,
        "render_device": device, "free_disk_bytes": shutil.disk_usage(CACHE_DIR.parent).free,
    }


class Api:
    def __init__(self, config: dict):
        self.base = config["server_url"].rstrip("/")
        self.token = config["token"]
        self.client = httpx.Client(timeout=httpx.Timeout(60, connect=20), follow_redirects=True, headers={"Authorization": f"Bearer {self.token}", "User-Agent": f"blend-farm-worker/{__version__}"})

    def post(self, path: str, body: dict | None = None, **kwargs):
        response = self.client.post(self.base + path, json=body or {}, **kwargs)
        response.raise_for_status()
        return response


def official_build(version: str) -> tuple[str, str, str]:
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise WorkerError("The farm Blender version must use x.y.z format")
    release = f"Blender{parts[0]}.{parts[1]}"
    root = f"https://download.blender.org/release/{release}"
    system = platform.system()
    machine = platform.machine().lower()
    if machine not in {"x86_64", "amd64"}:
        raise WorkerError(f"Unsupported worker architecture: {machine}")
    if system == "Windows":
        filename = f"blender-{version}-windows-x64.zip"
    elif system == "Linux":
        filename = f"blender-{version}-linux-x64.tar.xz"
    else:
        raise WorkerError(f"Unsupported worker OS: {system}")
    return f"{root}/{filename}", f"{root}/blender-{version}.sha256", filename


def safe_extract_zip(archive: Path, target: Path) -> None:
    with ZipFile(archive) as source:
        for item in source.infolist():
            path = PurePosixPath(item.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise WorkerError("Downloaded archive contains an unsafe path")
        source.extractall(target)


def safe_extract_tar(archive: Path, target: Path) -> None:
    with tarfile.open(archive) as source:
        for item in source.getmembers():
            path = PurePosixPath(item.name)
            if path.is_absolute() or ".." in path.parts:
                raise WorkerError("Downloaded Blender archive contains an unsafe path")
            if item.ischr() or item.isblk() or item.isfifo():
                raise WorkerError("Downloaded Blender archive contains an unsafe special file")
            if item.issym() or item.islnk():
                link = PurePosixPath(item.linkname)
                if link.is_absolute():
                    raise WorkerError("Downloaded Blender archive contains an unsafe link")
                # Symbolic link targets are relative to the link's directory. Tar
                # hard-link targets are relative to the archive root.
                base = path.parent if item.issym() else PurePosixPath()
                resolved = posixpath.normpath(str(base / link))
                if resolved == ".." or resolved.startswith("../"):
                    raise WorkerError("Downloaded Blender archive contains an unsafe link")
        source.extractall(target)


def ensure_blender(version: str) -> Path:
    install = CACHE_DIR / "blender"
    marker = install / ".version"
    executable = install / ("blender.exe" if platform.system() == "Windows" else "blender")
    if marker.exists() and marker.read_text().strip() == version and executable.exists():
        return executable
    url, checksum_url, filename = official_build(version)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="blend-farm-install-") as temp_name:
        temp = Path(temp_name)
        archive = temp / filename
        print(f"Downloading Blender {version}…")
        with httpx.stream("GET", url, follow_redirects=True, timeout=600) as response:
            response.raise_for_status()
            with archive.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    output.write(chunk)
        checksums = httpx.get(checksum_url, follow_redirects=True, timeout=60)
        checksums.raise_for_status()
        expected = None
        for line in checksums.text.splitlines():
            if line.strip().endswith(filename):
                expected = line.split()[0].lower()
                break
        if not expected or sha256_file(archive) != expected:
            raise WorkerError("Blender download did not match the official published checksum")
        extracted = temp / "extracted"
        extracted.mkdir()
        safe_extract_zip(archive, extracted) if filename.endswith(".zip") else safe_extract_tar(archive, extracted)
        roots = [p for p in extracted.iterdir() if p.is_dir()]
        source = roots[0] if len(roots) == 1 else extracted
        staged = CACHE_DIR / "blender.new"
        backup = CACHE_DIR / "blender.old"
        shutil.rmtree(staged, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        shutil.move(str(source), staged)
        (staged / ".version").write_text(version)
        if install.exists():
            shutil.move(install, backup)
        try:
            shutil.move(staged, install)
        except Exception:
            if backup.exists():
                shutil.move(backup, install)
            raise
        shutil.rmtree(backup, ignore_errors=True)
    if not executable.exists():
        raise WorkerError("Blender installation completed but its executable was not found")
    return executable


def download_project(api: Api, lease: dict) -> Path:
    projects = CACHE_DIR / "projects"
    root = projects / lease["package_sha256"]
    ready = root / ".ready"
    if ready.exists():
        os.utime(ready, None)
        return root
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    archive = root / "project.zip"
    request = api.client.build_request("GET", lease["package_url"], headers={"X-Lease-Token":lease["lease_token"]})
    response = api.client.send(request, stream=True)
    remote_client = None
    if response.headers.get("content-type", "").startswith("application/json"):
        response.read()
        remote_url = response.json()["url"]
        response.close()
        remote_client = httpx.Client(timeout=600)
        response = remote_client.send(httpx.Request("GET", remote_url), stream=True)
    try:
        with response:
            response.raise_for_status()
            digest = hashlib.sha256()
            with archive.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
    finally:
        if remote_client:
            remote_client.close()
    if digest.hexdigest() != lease["package_sha256"]:
        shutil.rmtree(root, ignore_errors=True)
        raise WorkerError("Project package checksum mismatch")
    safe_extract_zip(archive, root)
    archive.unlink()
    ready.write_text(lease["package_sha256"])
    return root


def trim_cache(max_bytes: int, keep: Path | None = None) -> None:
    root = CACHE_DIR / "projects"
    if not root.exists():
        return
    entries = sorted((p for p in root.iterdir() if p.is_dir() and p != keep), key=lambda p: (p / ".ready").stat().st_mtime if (p / ".ready").exists() else 0)
    def size(): return sum(f.stat().st_size for p in root.iterdir() for f in p.rglob("*") if f.is_file())
    current = size()
    for entry in entries:
        if current <= max_bytes:
            break
        entry_size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
        shutil.rmtree(entry)
        current -= entry_size


def upload_artifact(api: Api, lease_token: str, path: Path, purpose: str, content_type: str) -> str:
    checksum = sha256_file(path)
    frame_id = path.parent.name
    # The caller places outputs in a directory named with the assigned frame id.
    init = api.post(f"/api/v1/worker/leases/{frame_id}/uploads", {"purpose":purpose,"filename":path.name,"total_size":path.stat().st_size,"sha256":checksum,"content_type":content_type}, headers={"X-Lease-Token":lease_token}).json()
    completed = []
    with path.open("rb") as source:
        part = 1
        while chunk := source.read(init["chunk_size"]):
            digest = hashlib.sha256(chunk).hexdigest()
            if init["backend"] == "s3":
                response = httpx.put(init["parts"][part-1]["url"], content=chunk, timeout=600)
                response.raise_for_status()
                completed.append({"part_number":part,"etag":response.headers["etag"]})
            else:
                response = api.client.put(api.base + f"/api/v1/worker/leases/{frame_id}/uploads/{init['id']}/parts/{part}", content=chunk, headers={"X-Lease-Token":lease_token,"X-Chunk-SHA256":digest})
                response.raise_for_status()
            part += 1
    api.post(f"/api/v1/worker/leases/{frame_id}/uploads/{init['id']}/complete", {"parts":completed}, headers={"X-Lease-Token":lease_token})
    return init["id"]


def render(api: Api, config: dict, lease: dict) -> None:
    started = time.monotonic()
    blender = ensure_blender(lease["blender_version"])
    stopped = threading.Event()
    lease_lost = threading.Event()
    process_holder: list[subprocess.Popen] = []

    def heartbeats():
        while not stopped.wait(15):
            try:
                result = api.post("/api/v1/worker/heartbeat", {"lease_token":lease["lease_token"]}).json()
                if result.get("lease_active") is False:
                    lease_lost.set()
                    if process_holder:
                        process_holder[0].terminate()
                    return
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 401:
                    lease_lost.set()
                    if process_holder:
                        process_holder[0].terminate()
                    return
                print(f"Heartbeat warning: {exc}", file=sys.stderr)
            except Exception as exc:
                print(f"Heartbeat warning: {exc}", file=sys.stderr)
    thread = threading.Thread(target=heartbeats, daemon=True)
    thread.start()
    try:
        project = download_project(api, lease)
        trim_cache(int(config.get("cache_gb", 50)) * 1024**3, project)
        blend = project.joinpath(*PurePosixPath(lease["blend_path"]).parts)
        extension = {"PNG":"png","JPEG":"jpg","OPEN_EXR":"exr"}[lease["output_format"]]
        output_dir = CACHE_DIR / "outputs" / lease["frame_id"]
        shutil.rmtree(output_dir, ignore_errors=True)
        output_dir.mkdir(parents=True)
        output = output_dir / f"frame-{lease['frame']:06d}.{extension}"
        preview = output_dir / f"frame-{lease['frame']:06d}-preview.jpg"
        runner = Path(__file__).with_name("blender_runner.py")
        command = [str(blender), "--disable-autoexec", "-b", str(blend), "--python-exit-code", "1", "--python", str(runner), "--", str(lease["frame"]), str(output), lease["output_format"], str(preview), config.get("device", "AUTO")]
        print(f"Rendering job {lease['job_id']} frame {lease['frame']}…")
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        process_holder.append(process)
    except Exception:
        stopped.set()
        thread.join(timeout=2)
        raise
    if lease_lost.is_set():
        stopped.set()
        thread.join(timeout=2)
        raise WorkerError("Assignment was cancelled while preparing the project")
    logs: list[str] = []
    assert process.stdout
    for line in process.stdout:
        print(line, end="")
        logs.append(line)
        if sum(map(len, logs)) > 65536:
            logs = logs[len(logs)//2:]
    code = process.wait()
    log_text = "".join(logs)[-65536:]
    if code != 0 or not output.exists():
        try:
            api.post(f"/api/v1/worker/leases/{lease['frame_id']}/fail", {"error":f"Blender exited with code {code}","logs":log_text}, headers={"X-Lease-Token":lease["lease_token"]})
        finally:
            stopped.set()
            thread.join(timeout=2)
        return
    try:
        output_id = upload_artifact(api, lease["lease_token"], output, "output", {"png":"image/png","jpg":"image/jpeg","exr":"image/x-exr"}[extension])
        preview_id = upload_artifact(api, lease["lease_token"], preview, "preview", "image/jpeg") if preview.exists() else None
        api.post(f"/api/v1/worker/leases/{lease['frame_id']}/complete", {"output_upload_id":output_id,"preview_upload_id":preview_id,"duration_seconds":time.monotonic()-started,"logs":log_text}, headers={"X-Lease-Token":lease["lease_token"]})
        shutil.rmtree(output_dir, ignore_errors=True)
    finally:
        stopped.set()
        thread.join(timeout=2)


def enroll(args) -> None:
    server = args.server.rstrip("/")
    body = {"code":args.code.upper(),"name":args.name or platform.node() or "worker","capabilities":capabilities(args.device)}
    response = httpx.post(server + "/api/v1/worker/enroll", json=body, timeout=30)
    response.raise_for_status()
    result = response.json()
    save_config({"server_url":server,"worker_id":result["worker_id"],"token":result["token"],"device":args.device,"cache_gb":args.cache_gb})
    print(f"Enrolled {body['name']} as {result['worker_id']}. Configuration saved to {CONFIG_FILE}")


def run_worker(_args) -> None:
    config = load_config()
    api = Api(config)
    print(f"Blend Farm worker {__version__} connected to {api.base}")
    while True:
        try:
            heartbeat = api.post("/api/v1/worker/heartbeat", {"capabilities":capabilities(config.get("device", "AUTO"))}).json()
            ensure_blender(heartbeat["blender_version"])
            response = api.post("/api/v1/worker/lease?wait=20")
            if response.status_code == 204:
                time.sleep(random.uniform(1, 3))
                continue
            render(api, config, response.json())
        except KeyboardInterrupt:
            print("Stopping worker.")
            return
        except (httpx.HTTPError, WorkerError, OSError) as exc:
            print(f"Worker error: {exc}; retrying…", file=sys.stderr)
            time.sleep(random.uniform(5, 15))


def doctor(_args) -> None:
    config = load_config()
    api = Api(config)
    result = api.post("/api/v1/worker/heartbeat", {"capabilities":capabilities(config.get("device", "AUTO"))}).json()
    blender = ensure_blender(result["blender_version"])
    device = config.get("device", "AUTO")
    probe = Path(__file__).with_name("blender_probe.py")
    check = subprocess.run(
        [str(blender), "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(probe), "--", device],
        capture_output=True, text=True, errors="replace", timeout=120, check=False,
    )
    probe_output = (check.stdout + "\n" + check.stderr).strip()
    if check.returncode != 0 or "BLEND_FARM_PROBE=" not in probe_output:
        raise WorkerError(f"Blender {device} device check failed:\n{probe_output[-8000:]}")
    print(probe_output)
    print(json.dumps({"server":"ok","blender":str(blender),"blender_version":result["blender_version"],"capabilities":capabilities(device)}, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="blend-farm-worker", description="Blend Farm worker")
    commands = parser.add_subparsers(dest="command", required=True)
    enroll_cmd = commands.add_parser("enroll", help="enroll this machine")
    enroll_cmd.add_argument("--server", required=True, help="central server URL")
    enroll_cmd.add_argument("--code", required=True, help="one-time enrollment code")
    enroll_cmd.add_argument("--name")
    enroll_cmd.add_argument("--device", choices=["AUTO","CPU","CUDA","OPTIX","HIP"], default="AUTO")
    enroll_cmd.add_argument("--cache-gb", type=int, default=50)
    enroll_cmd.set_defaults(function=enroll)
    run_cmd = commands.add_parser("run", help="start requesting frames")
    run_cmd.set_defaults(function=run_worker)
    doctor_cmd = commands.add_parser("doctor", help="test configuration and connectivity")
    doctor_cmd.set_defaults(function=doctor)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.function(args)
    except (WorkerError, httpx.HTTPError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

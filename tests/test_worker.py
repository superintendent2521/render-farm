import io
import hashlib
import tarfile
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

import renderfarm.worker as worker_module
from renderfarm.worker import WorkerError, download_project, safe_extract_tar


def make_tar(path: Path, entries: list[tuple[str, bytes | None, str | None]]) -> None:
    with tarfile.open(path, "w") as archive:
        for name, contents, linkname in entries:
            info = tarfile.TarInfo(name)
            if linkname is not None:
                info.type = tarfile.SYMTYPE
                info.linkname = linkname
                archive.addfile(info)
            else:
                payload = contents or b""
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))


def test_safe_extract_tar_allows_internal_symlink(tmp_path: Path) -> None:
    archive = tmp_path / "blender.tar"
    make_tar(archive, [("blender/lib/library.so", b"library", None), ("blender/library.so", None, "lib/library.so")])

    target = tmp_path / "output"
    target.mkdir()
    safe_extract_tar(archive, target)

    assert (target / "blender/library.so").read_bytes() == b"library"


@pytest.mark.parametrize("linkname", ["/etc/passwd", "../../outside"])
def test_safe_extract_tar_rejects_escaping_symlink(tmp_path: Path, linkname: str) -> None:
    archive = tmp_path / "blender.tar"
    make_tar(archive, [("blender/link", None, linkname)])

    target = tmp_path / "output"
    target.mkdir()
    with pytest.raises(WorkerError, match="unsafe link"):
        safe_extract_tar(archive, target)


def test_download_project_closes_stream_without_response_context_manager(tmp_path: Path, monkeypatch) -> None:
    payload = io.BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr("scene.blend", b"BLENDER")
    package = payload.getvalue()

    class Response:
        headers = {"content-type": "application/zip"}
        closed = False

        def raise_for_status(self):
            return None

        def iter_bytes(self, _size):
            yield package

        def close(self):
            self.closed = True

    response = Response()
    client = SimpleNamespace(build_request=lambda *args, **kwargs: object(), send=lambda *args, **kwargs: response)
    api = SimpleNamespace(client=client)
    checksum = hashlib.sha256(package).hexdigest()
    monkeypatch.setattr(worker_module, "CACHE_DIR", tmp_path)

    project = download_project(api, {"package_sha256": checksum, "package_url": "https://example.test/project", "lease_token": "lease"})

    assert (project / "scene.blend").read_bytes() == b"BLENDER"
    assert response.closed

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import shutil
import tempfile
import urllib.request
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .config import Settings
from .database import Base, make_engine, make_session_factory, utcnow
from .models import Admin, Enrollment, FarmSetting, Frame, FrameStatus, Job, JobStatus, UploadSession, Worker
from .scheduler import Scheduler
from .security import LoginLimiter, enrollment_expiry, hash_password, opaque_token, token_hash, verify_password
from .storage import LocalStorage, StorageError, make_storage, materialize, sha256_file, validate_project_archive

settings = Settings.from_env()
engine = make_engine(settings)
SessionFactory = make_session_factory(engine)
storage = make_storage(settings)
scheduler = Scheduler(SessionFactory)
limiter = LoginLimiter()
package_dir = Path(__file__).parent
templates = Jinja2Templates(directory=str(package_dir / "templates"))


def bootstrap() -> None:
    if settings.secure_cookies and (settings.secret_key == "change-me-before-production" or settings.admin_password == "change-me-before-production"):
        raise RuntimeError("Set a strong SECRET_KEY and ADMIN_PASSWORD before starting an HTTPS deployment")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    with SessionFactory.begin() as db:
        if not db.scalar(select(Admin).limit(1)):
            db.add(Admin(username=settings.admin_username, password_hash=hash_password(settings.admin_password)))
        if not db.get(FarmSetting, "blender_version"):
            db.add(FarmSetting(key="blender_version", value=settings.blender_version))


async def maintenance() -> None:
    while True:
        await asyncio.sleep(15)
        await asyncio.to_thread(scheduler.reconcile)
        await asyncio.to_thread(cleanup_expired_uploads)


def cleanup_expired_uploads() -> int:
    now = utcnow()
    cleaned = 0
    with SessionFactory.begin() as db:
        uploads = db.scalars(select(UploadSession).where(UploadSession.status == "open", UploadSession.expires_at < now)).all()
        for upload in uploads:
            if upload.backend_upload_id:
                try:
                    storage.abort_multipart(upload.storage_key, upload.backend_upload_id)
                except Exception:
                    continue
            shutil.rmtree(settings.data_dir / "uploads" / upload.id, ignore_errors=True)
            upload.status = "expired"
            cleaned += 1
    return cleaned


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap()
    scheduler.reconcile()
    task = asyncio.create_task(maintenance())
    yield
    task.cancel()


app = FastAPI(title="Blend Farm", version="0.1.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, https_only=settings.secure_cookies, same_site="lax", session_cookie="blend_farm_session")
app.mount("/static", StaticFiles(directory=str(package_dir / "static")), name="static")


class TrustedProxyMiddleware:
    """Honor forwarding headers only when the direct peer is a configured proxy."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("client"):
            peer_host, peer_port = scope["client"]
            headers = {key.decode("latin1").lower(): value.decode("latin1") for key, value in scope.get("headers", [])}
            try:
                peer = ipaddress.ip_address(peer_host)
                trusted = any(peer in ipaddress.ip_network(network) for network in settings.trusted_proxy_networks)
                forwarded = headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
                if trusted and forwarded:
                    ipaddress.ip_address(forwarded)
                    scope["client"] = (forwarded, peer_port)
            except ValueError:
                pass
        await self.app(scope, receive, send)


app.add_middleware(TrustedProxyMiddleware)


def db_session():
    db = SessionFactory()
    try:
        yield db
    finally:
        db.close()


def admin_required(request: Request, db: Session = Depends(db_session)) -> Admin:
    admin_id = request.session.get("admin_id")
    admin = db.get(Admin, admin_id) if admin_id else None
    if not admin:
        raise HTTPException(401, "administrator login required")
    return admin


def csrf_required(request: Request, x_csrf_token: str | None = Header(None)) -> None:
    supplied = x_csrf_token or request.query_params.get("csrf")
    expected = request.session.get("csrf")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(403, "invalid CSRF token")


def worker_required(authorization: str | None = Header(None), db: Session = Depends(db_session)) -> Worker:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "worker credential required")
    worker = db.scalar(select(Worker).where(Worker.token_hash == token_hash(authorization[7:])))
    if not worker or worker.disabled:
        raise HTTPException(401, "worker credential is invalid or revoked")
    return worker


def lease_frame(db: Session, worker: Worker, raw_lease: str) -> Frame:
    frame = db.scalar(select(Frame).where(Frame.worker_id == worker.id, Frame.lease_hash == token_hash(raw_lease)))
    if not frame or frame.status not in (FrameStatus.leased.value, FrameStatus.rendering.value):
        raise HTTPException(409, "lease is no longer active")
    if frame.lease_expires_at and frame.lease_expires_at.replace(tzinfo=None) < utcnow().replace(tzinfo=None):
        raise HTTPException(409, "lease has expired")
    return frame


def session_json(request: Request, **extra):
    return {"request": request, "csrf": request.session.get("csrf", ""), **extra}


@app.get("/healthz")
def health():
    try:
        with SessionFactory() as db:
            db.execute(select(1))
        storage.health()
        return {"ok": True, "database": "ok", "storage": "ok"}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("admin_id"):
        return RedirectResponse("/", 303)
    return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(db_session)):
    client = request.client.host if request.client else "unknown"
    if not limiter.allowed(client):
        return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "error": "Too many attempts. Try again later."}, status_code=429)
    admin = db.scalar(select(Admin).where(Admin.username == username))
    if not admin or not verify_password(admin.password_hash, password):
        limiter.fail(client)
        return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "error": "Invalid username or password."}, status_code=401)
    limiter.clear(client)
    request.session.clear()
    request.session["admin_id"] = admin.id
    request.session["csrf"] = opaque_token(24)
    return RedirectResponse("/", 303)


@app.post("/logout")
def logout(request: Request, _admin: Admin = Depends(admin_required), _csrf=Depends(csrf_required)):
    request.session.clear()
    return RedirectResponse("/login", 303)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(db_session)):
    admin_id = request.session.get("admin_id")
    if not admin_id or not db.get(Admin, admin_id):
        return RedirectResponse("/login", 303)
    jobs = db.scalars(select(Job).order_by(Job.queue_order, Job.created_at.desc())).all()
    workers = db.scalars(select(Worker).order_by(Worker.created_at.desc())).all()
    version = db.get(FarmSetting, "blender_version").value
    usage = storage.size()
    counts = {j.id: dict(db.execute(select(Frame.status, func.count()).where(Frame.job_id == j.id).group_by(Frame.status)).all()) for j in jobs}
    active_frames = {worker.id: db.scalar(select(Frame).where(Frame.worker_id == worker.id, Frame.status.in_([FrameStatus.leased.value, FrameStatus.rendering.value]))) for worker in workers}
    tunnel_status = "not configured"
    if settings.exposure_mode == "cloudflare" and settings.tunnel_metrics_url:
        try:
            with urllib.request.urlopen(settings.tunnel_metrics_url, timeout=1) as response:
                tunnel_status = "connected" if response.status == 200 else "degraded"
        except Exception:
            tunnel_status = "disconnected"
    return templates.TemplateResponse(request=request, name="dashboard.html", context=session_json(request, jobs=jobs, workers=workers, active_frames=active_frames, version=version, usage=usage, counts=counts, public_url=settings.public_url, storage_backend=settings.storage_backend, exposure_mode=settings.exposure_mode, tunnel_status=tunnel_status))


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(job_id: str, request: Request, _admin: Admin = Depends(admin_required), db: Session = Depends(db_session)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    frames = db.scalars(select(Frame).where(Frame.job_id == job_id).order_by(Frame.frame_number)).all()
    return templates.TemplateResponse(
        request=request,
        name="job.html",
        context=session_json(request, job=job, frames=frames, has_failed_frames=any(frame.status == FrameStatus.failed.value for frame in frames)),
    )


@app.post("/jobs")
def create_job(request: Request, name: str = Form(...), upload_id: str = Form(...), frame_start: int = Form(...), frame_end: int = Form(...), output_format: str = Form(...), _admin: Admin = Depends(admin_required), _csrf=Depends(csrf_required), db: Session = Depends(db_session)):
    if frame_start > frame_end or frame_end - frame_start > 100000:
        raise HTTPException(400, "invalid frame range")
    if output_format not in {"PNG", "JPEG", "OPEN_EXR"}:
        raise HTTPException(400, "unsupported output format")
    upload = db.get(UploadSession, upload_id)
    if not upload or upload.owner_kind != "admin" or upload.purpose != "project" or upload.status != "ready":
        raise HTTPException(400, "project upload is not ready")
    temp = materialize(storage, upload.storage_key)
    try:
        blend_path = validate_project_archive(temp, settings.max_archive_bytes, settings.max_expanded_bytes)
    finally:
        temp.unlink(missing_ok=True)
    next_order = (db.scalar(select(func.max(Job.queue_order))) or 0) + 1
    job = Job(name=name[:160], frame_start=frame_start, frame_end=frame_end, output_format=output_format, package_key=upload.storage_key, package_sha256=upload.sha256, blend_path=blend_path, queue_order=next_order)
    db.add(job)
    db.flush()
    db.add_all([Frame(job_id=job.id, frame_number=i) for i in range(frame_start, frame_end + 1)])
    upload.owner_id = job.id
    db.commit()
    return RedirectResponse(f"/jobs/{job.id}", 303)


@app.post("/jobs/{job_id}/action")
def job_action(job_id: str, request: Request, action: str = Form(...), _admin: Admin = Depends(admin_required), _csrf=Depends(csrf_required), db: Session = Depends(db_session)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    if action == "pause" and job.status in (JobStatus.queued.value, JobStatus.running.value):
        job.status = JobStatus.paused.value
    elif action == "resume" and job.status == JobStatus.paused.value:
        job.status = JobStatus.queued.value
    elif action == "cancel" and job.status not in (JobStatus.completed.value, JobStatus.failed.value):
        job.status = JobStatus.cancelled.value
    elif action == "retry":
        for frame in job.frames:
            if frame.status == FrameStatus.failed.value:
                frame.status, frame.attempts, frame.error_text = FrameStatus.pending.value, 0, ""
        job.status = JobStatus.queued.value
    elif action in ("up", "down"):
        direction = -1 if action == "up" else 1
        other = db.scalar(select(Job).where((Job.queue_order < job.queue_order) if direction < 0 else (Job.queue_order > job.queue_order)).order_by(Job.queue_order.desc() if direction < 0 else Job.queue_order.asc()).limit(1))
        if other:
            job.queue_order, other.queue_order = other.queue_order, job.queue_order
    else:
        raise HTTPException(400, "action is not valid for this job")
    db.commit()
    return RedirectResponse(request.headers.get("referer", "/"), 303)


@app.post("/jobs/{job_id}/delete")
def delete_job(job_id: str, request: Request, confirm: str = Form(...), _admin: Admin = Depends(admin_required), _csrf=Depends(csrf_required), db: Session = Depends(db_session)):
    job = db.get(Job, job_id)
    if not job or confirm != job.name:
        raise HTTPException(400, "type the job name exactly to confirm deletion")
    storage.delete_prefix(f"jobs/{job.id}")
    storage.delete_prefix(job.package_key)
    db.delete(job)
    db.commit()
    return RedirectResponse("/", 303)


@app.post("/settings")
def update_settings(request: Request, blender_version: str = Form(...), _admin: Admin = Depends(admin_required), _csrf=Depends(csrf_required), db: Session = Depends(db_session)):
    if not blender_version.replace(".", "").isdigit() or len(blender_version) > 20:
        raise HTTPException(400, "invalid Blender version")
    db.get(FarmSetting, "blender_version").value = blender_version
    db.commit()
    return RedirectResponse("/", 303)


@app.post("/workers/enrollment")
def create_enrollment(request: Request, _admin: Admin = Depends(admin_required), _csrf=Depends(csrf_required), db: Session = Depends(db_session)):
    code = "-".join([opaque_token(4)[:6].upper(), opaque_token(4)[:6].upper()])
    db.add(Enrollment(code_hash=token_hash(code), expires_at=enrollment_expiry()))
    db.commit()
    request.session["enrollment_code"] = code
    return RedirectResponse("/", 303)


@app.post("/workers/{worker_id}/toggle")
def toggle_worker(worker_id: str, request: Request, _admin: Admin = Depends(admin_required), _csrf=Depends(csrf_required), db: Session = Depends(db_session)):
    worker = db.get(Worker, worker_id)
    if not worker:
        raise HTTPException(404)
    worker.disabled = not worker.disabled
    db.commit()
    return RedirectResponse("/", 303)


@app.post("/workers/{worker_id}/rename")
def rename_worker(worker_id: str, request: Request, name: str = Form(...), _admin: Admin = Depends(admin_required), _csrf=Depends(csrf_required), db: Session = Depends(db_session)):
    worker = db.get(Worker, worker_id)
    if not worker or not name.strip():
        raise HTTPException(404 if not worker else 400)
    worker.name = name.strip()[:120]
    db.commit()
    return RedirectResponse("/", 303)


def create_upload(db: Session, *, purpose: str, owner_kind: str, owner_id: str | None, filename: str, total_size: int, checksum: str, content_type: str, storage_key: str | None = None) -> tuple[UploadSession, dict]:
    if total_size <= 0 or total_size > settings.max_archive_bytes:
        raise HTTPException(413, "artifact exceeds configured limit")
    upload = UploadSession(purpose=purpose, owner_kind=owner_kind, owner_id=owner_id, storage_key=storage_key or f"uploads/{opaque_token(18)}", filename=Path(filename).name[:240], total_size=total_size, sha256=checksum or "pending", expires_at=utcnow() + timedelta(hours=24))
    db.add(upload)
    db.flush()
    response = {"id": upload.id, "backend": settings.storage_backend, "chunk_size": settings.chunk_size}
    if settings.storage_backend == "s3":
        upload.backend_upload_id = storage.begin_multipart(upload.storage_key, content_type)
        count = (total_size + settings.chunk_size - 1) // settings.chunk_size
        response["parts"] = [{"part_number": n, "url": storage.presign_part(upload.storage_key, upload.backend_upload_id, n)} for n in range(1, count + 1)]
    else:
        (settings.data_dir / "uploads" / upload.id).mkdir(parents=True, exist_ok=True)
    db.commit()
    return upload, response


@app.post("/api/v1/uploads")
async def admin_upload_init(request: Request, _admin: Admin = Depends(admin_required), _csrf=Depends(csrf_required), db: Session = Depends(db_session)):
    body = await request.json()
    upload, response = create_upload(db, purpose="project", owner_kind="admin", owner_id=None, filename=body.get("filename", "project.zip"), total_size=int(body.get("total_size", 0)), checksum=body.get("sha256", ""), content_type="application/zip")
    return response


async def save_local_part(upload: UploadSession, part_number: int, request: Request, checksum: str | None):
    max_parts = (upload.total_size + settings.chunk_size - 1) // settings.chunk_size
    if settings.storage_backend != "local" or part_number < 1 or part_number > max_parts or upload.expires_at.replace(tzinfo=None) < utcnow().replace(tzinfo=None):
        raise HTTPException(400, "invalid local upload part")
    target = settings.data_dir / "uploads" / upload.id / f"{part_number:05d}.part"
    digest = hashlib.sha256()
    size = 0
    with target.open("wb") as output:
        async for chunk in request.stream():
            size += len(chunk)
            if size > settings.chunk_size:
                target.unlink(missing_ok=True)
                raise HTTPException(413, "chunk exceeds 32 MiB")
            digest.update(chunk)
            output.write(chunk)
    if checksum and not hmac.compare_digest(digest.hexdigest(), checksum.lower()):
        target.unlink(missing_ok=True)
        raise HTTPException(422, "chunk checksum mismatch")
    return {"ok": True, "sha256": digest.hexdigest(), "size": size}


@app.put("/api/v1/uploads/{upload_id}/parts/{part_number}")
async def admin_upload_part(upload_id: str, part_number: int, request: Request, x_chunk_sha256: str | None = Header(None), _admin: Admin = Depends(admin_required), _csrf=Depends(csrf_required), db: Session = Depends(db_session)):
    upload = db.get(UploadSession, upload_id)
    if not upload or upload.owner_kind != "admin" or upload.status != "open":
        raise HTTPException(404)
    return await save_local_part(upload, part_number, request, x_chunk_sha256)


def finalize_upload(db: Session, upload: UploadSession, parts: list[dict]) -> UploadSession:
    if upload.status == "ready":
        return upload
    if settings.storage_backend == "s3":
        storage.finish_multipart(upload.storage_key, upload.backend_upload_id, parts)
        temp = materialize(storage, upload.storage_key)
    else:
        folder = settings.data_dir / "uploads" / upload.id
        temp = folder / "assembled.partial"
        with temp.open("wb") as output:
            for part in sorted(folder.glob("*.part")):
                with part.open("rb") as source:
                    shutil.copyfileobj(source, output)
        if temp.stat().st_size != upload.total_size:
            raise HTTPException(422, "assembled upload size does not match")
    try:
        if temp.stat().st_size != upload.total_size:
            raise HTTPException(422, "uploaded artifact size does not match")
        checksum = sha256_file(temp)
        if upload.sha256 != "pending" and not hmac.compare_digest(checksum, upload.sha256):
            raise HTTPException(422, "artifact checksum mismatch")
        upload.sha256 = checksum
        if settings.storage_backend == "local":
            storage.put_file(upload.storage_key, temp)
    finally:
        if settings.storage_backend == "s3":
            temp.unlink(missing_ok=True)
        else:
            shutil.rmtree(settings.data_dir / "uploads" / upload.id, ignore_errors=True)
    upload.status = "ready"
    db.commit()
    return upload


@app.post("/api/v1/uploads/{upload_id}/complete")
async def admin_upload_complete(upload_id: str, request: Request, _admin: Admin = Depends(admin_required), _csrf=Depends(csrf_required), db: Session = Depends(db_session)):
    upload = db.get(UploadSession, upload_id)
    if not upload or upload.owner_kind != "admin":
        raise HTTPException(404)
    body = await request.json()
    finalize_upload(db, upload, body.get("parts", []))
    temp = materialize(storage, upload.storage_key)
    try:
        blend_path = validate_project_archive(temp, settings.max_archive_bytes, settings.max_expanded_bytes)
    finally:
        temp.unlink(missing_ok=True)
    return {"id": upload.id, "sha256": upload.sha256, "blend_path": blend_path}


@app.post("/api/v1/worker/enroll")
async def enroll_worker(request: Request, db: Session = Depends(db_session)):
    body = await request.json()
    enrollment = db.scalar(select(Enrollment).where(Enrollment.code_hash == token_hash(str(body.get("code", "")).upper()), Enrollment.used_at.is_(None), Enrollment.expires_at > utcnow()))
    if not enrollment:
        raise HTTPException(401, "enrollment code is invalid or expired")
    raw_token = opaque_token(32)
    worker = Worker(name=str(body.get("name", "worker"))[:120], token_hash=token_hash(raw_token), capabilities_json=json.dumps(body.get("capabilities", {})))
    enrollment.used_at = utcnow()
    db.add(worker)
    db.commit()
    return {"worker_id": worker.id, "token": raw_token}


@app.post("/api/v1/worker/heartbeat")
async def worker_heartbeat(request: Request, worker: Worker = Depends(worker_required), db: Session = Depends(db_session)):
    body = await request.json()
    worker.last_seen_at = utcnow()
    if "capabilities" in body:
        worker.capabilities_json = json.dumps(body["capabilities"])
    db.commit()
    lease = body.get("lease_token")
    active = scheduler.heartbeat(worker.id, lease) if lease else None
    version = db.get(FarmSetting, "blender_version").value
    return {"ok": True, "lease_active": bool(active) if lease else None, "blender_version": version}


@app.post("/api/v1/worker/lease")
async def acquire_lease(wait: int = 20, count: int = 1, worker: Worker = Depends(worker_required), db: Session = Depends(db_session)):
    worker.last_seen_at = utcnow()
    db.commit()
    deadline = asyncio.get_running_loop().time() + min(max(wait, 0), 20)
    while True:
        results = await asyncio.to_thread(scheduler.lease_batch, worker, min(max(count, 1), 20))
        if results:
            version = db.get(FarmSetting, "blender_version").value
            for result in results:
                result["package_url"] = f"{settings.public_url}/api/v1/worker/package/{result['frame_id']}"
                result["blender_version"] = version
            return {"assignments": results} if count > 1 else results[0]
        if asyncio.get_running_loop().time() >= deadline:
            return Response(status_code=204)
        await asyncio.sleep(1)


@app.get("/api/v1/worker/package/{frame_id}")
def download_package(frame_id: str, x_lease_token: str = Header(...), worker: Worker = Depends(worker_required), db: Session = Depends(db_session)):
    raw_lease = x_lease_token
    frame = lease_frame(db, worker, raw_lease)
    job = db.get(Job, frame.job_id)
    url = storage.presigned_get(job.package_key)
    if url:
        return {"url": url, "sha256": job.package_sha256}
    assert isinstance(storage, LocalStorage)
    return FileResponse(storage.path_for(job.package_key), filename="project.zip", media_type="application/zip")


@app.post("/api/v1/worker/leases/{frame_id}/uploads")
async def worker_upload_init(frame_id: str, request: Request, x_lease_token: str = Header(...), worker: Worker = Depends(worker_required), db: Session = Depends(db_session)):
    raw_lease = x_lease_token
    frame = lease_frame(db, worker, raw_lease)
    body = await request.json()
    purpose = body.get("purpose")
    if purpose not in {"output", "preview"}:
        raise HTTPException(400, "invalid artifact purpose")
    ext = {"PNG": "png", "JPEG": "jpg", "OPEN_EXR": "exr"}[frame.job.output_format] if purpose == "output" else "jpg"
    artifact_key = f"jobs/{frame.job_id}/frames/{frame.frame_number:06d}/{purpose}.{ext}"
    upload, response = create_upload(db, purpose=purpose, owner_kind="worker", owner_id=frame.id, filename=f"{frame.frame_number:06d}.{ext}", total_size=int(body.get("total_size", 0)), checksum=body.get("sha256", ""), content_type=body.get("content_type", "application/octet-stream"), storage_key=artifact_key)
    return response


@app.put("/api/v1/worker/leases/{frame_id}/uploads/{upload_id}/parts/{part_number}")
async def worker_upload_part(frame_id: str, upload_id: str, part_number: int, request: Request, x_lease_token: str = Header(...), x_chunk_sha256: str | None = Header(None), worker: Worker = Depends(worker_required), db: Session = Depends(db_session)):
    raw_lease = x_lease_token
    frame = lease_frame(db, worker, raw_lease)
    upload = db.get(UploadSession, upload_id)
    if not upload or upload.owner_id != frame.id or upload.status != "open":
        raise HTTPException(404)
    return await save_local_part(upload, part_number, request, x_chunk_sha256)


@app.post("/api/v1/worker/leases/{frame_id}/uploads/{upload_id}/complete")
async def worker_upload_complete(frame_id: str, upload_id: str, request: Request, x_lease_token: str = Header(...), worker: Worker = Depends(worker_required), db: Session = Depends(db_session)):
    raw_lease = x_lease_token
    frame = lease_frame(db, worker, raw_lease)
    upload = db.get(UploadSession, upload_id)
    if not upload or upload.owner_id != frame.id:
        raise HTTPException(404)
    body = await request.json()
    finalize_upload(db, upload, body.get("parts", []))
    return {"id": upload.id, "key": upload.storage_key, "sha256": upload.sha256}


@app.post("/api/v1/worker/leases/{frame_id}/complete")
async def complete_frame(frame_id: str, request: Request, x_lease_token: str = Header(...), worker: Worker = Depends(worker_required), db: Session = Depends(db_session)):
    raw_lease = x_lease_token
    frame = lease_frame(db, worker, raw_lease)
    body = await request.json()
    output = db.get(UploadSession, body.get("output_upload_id"))
    preview = db.get(UploadSession, body.get("preview_upload_id")) if body.get("preview_upload_id") else None
    if not output or output.owner_id != frame.id or output.purpose != "output" or output.status != "ready" or (preview and (preview.owner_id != frame.id or preview.status != "ready")):
        raise HTTPException(400, "frame artifacts are not ready")
    ok = scheduler.complete(worker.id, raw_lease, output.storage_key, preview.storage_key if preview else None, output.sha256, float(body.get("duration_seconds", 0)), str(body.get("logs", "")))
    if not ok:
        raise HTTPException(409, "lease is no longer active")
    return {"ok": True}


@app.post("/api/v1/worker/leases/{frame_id}/fail")
async def fail_frame(frame_id: str, request: Request, x_lease_token: str = Header(...), worker: Worker = Depends(worker_required)):
    raw_lease = x_lease_token
    body = await request.json()
    if not scheduler.fail(worker.id, raw_lease, str(body.get("error", "render failed")), str(body.get("logs", ""))):
        raise HTTPException(409, "lease is no longer active")
    return {"ok": True}


@app.get("/frames/{frame_id}/preview")
def frame_preview(frame_id: str, _admin: Admin = Depends(admin_required), db: Session = Depends(db_session)):
    frame = db.get(Frame, frame_id)
    if not frame or not frame.preview_key:
        raise HTTPException(404)
    url = storage.presigned_get(frame.preview_key)
    if url:
        return RedirectResponse(url, 307)
    return FileResponse(storage.path_for(frame.preview_key), media_type="image/jpeg")


def build_results(job: Job, frames: list[Frame]) -> Path:
    handle, name = tempfile.mkstemp(suffix=".zip", prefix="blend-farm-results-")
    os.close(handle)
    target = Path(name)
    manifest = {"job": job.name, "status": job.status, "frames": []}
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for frame in frames:
            row = {"frame": frame.frame_number, "status": frame.status, "attempts": frame.attempts, "error": frame.error_text}
            manifest["frames"].append(row)
            if frame.output_key:
                temp = materialize(storage, frame.output_key)
                try:
                    archive.write(temp, f"frames/frame-{frame.frame_number:06d}{Path(frame.output_key).suffix}")
                finally:
                    temp.unlink(missing_ok=True)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    return target


@app.get("/jobs/{job_id}/results")
def results_zip(job_id: str, _admin: Admin = Depends(admin_required), db: Session = Depends(db_session)):
    job = db.get(Job, job_id)
    if not job or job.status not in (JobStatus.completed.value, JobStatus.failed.value):
        raise HTTPException(409, "job has not reached a terminal state")
    if not job.result_zip_key:
        frames = db.scalars(select(Frame).where(Frame.job_id == job.id).order_by(Frame.frame_number)).all()
        temp = build_results(job, frames)
        try:
            job.result_zip_key = f"jobs/{job.id}/results.zip"
            storage.put_file(job.result_zip_key, temp, "application/zip")
            db.commit()
        finally:
            temp.unlink(missing_ok=True)
    url = storage.presigned_get(job.result_zip_key)
    if url:
        return RedirectResponse(url, 307)
    return FileResponse(storage.path_for(job.result_zip_key), filename=f"{job.name}-results.zip", media_type="application/zip")


def run():
    import uvicorn
    uvicorn.run("renderfarm.app:app", host="0.0.0.0", port=8000, workers=1, proxy_headers=False)

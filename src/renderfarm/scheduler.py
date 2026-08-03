from __future__ import annotations

import json
import secrets
from datetime import timedelta
from threading import Lock

from sqlalchemy import func, select

from .database import utcnow
from .models import Frame, FrameStatus, Job, JobStatus, Worker
from .security import token_hash


class Scheduler:
    def __init__(self, session_factory):
        self.sessions = session_factory
        self.lock = Lock()

    def reconcile(self) -> int:
        now = utcnow()
        changed = 0
        with self.lock, self.sessions.begin() as db:
            expired = db.scalars(select(Frame).where(Frame.status.in_([FrameStatus.leased.value, FrameStatus.rendering.value]), Frame.lease_expires_at < now)).all()
            for frame in expired:
                frame.log_text = (frame.log_text + "\nLease expired; assignment returned to queue.")[-65536:]
                frame.worker_id = None
                frame.lease_hash = None
                frame.lease_expires_at = None
                frame.status = FrameStatus.failed.value if frame.attempts >= 3 else FrameStatus.pending.value
                changed += 1
            for job_id in {f.job_id for f in expired}:
                self._aggregate(db, job_id)
        return changed

    def lease(self, worker: Worker):
        with self.lock, self.sessions.begin() as db:
            now = utcnow()
            expired = db.scalars(select(Frame).where(Frame.status.in_([FrameStatus.leased.value, FrameStatus.rendering.value]), Frame.lease_expires_at < now)).all()
            for stale in expired:
                stale.worker_id = None
                stale.lease_hash = None
                stale.lease_expires_at = None
                stale.status = FrameStatus.failed.value if stale.attempts >= 3 else FrameStatus.pending.value
            frame = db.scalar(
                select(Frame).join(Job).where(
                    Frame.status == FrameStatus.pending.value,
                    Job.status.in_([JobStatus.queued.value, JobStatus.running.value]),
                ).order_by(Job.queue_order.asc(), Job.created_at.asc(), Frame.frame_number.asc()).limit(1)
            )
            if not frame:
                return None
            job = db.get(Job, frame.job_id)
            raw_lease = secrets.token_urlsafe(32)
            frame.status = FrameStatus.leased.value
            frame.worker_id = worker.id
            frame.attempts += 1
            frame.lease_hash = token_hash(raw_lease)
            frame.lease_expires_at = now + timedelta(seconds=60)
            frame.started_at = now
            if job.status == JobStatus.queued.value:
                job.status = JobStatus.running.value
            return {
                "lease_token": raw_lease, "frame_id": frame.id, "job_id": job.id,
                "frame": frame.frame_number, "output_format": job.output_format,
                "package_sha256": job.package_sha256, "blend_path": job.blend_path,
                "lease_expires_at": frame.lease_expires_at.isoformat(),
            }

    def heartbeat(self, worker_id: str, raw_lease: str) -> Frame | None:
        with self.sessions.begin() as db:
            frame = db.scalar(select(Frame).where(Frame.worker_id == worker_id, Frame.lease_hash == token_hash(raw_lease), Frame.status.in_([FrameStatus.leased.value, FrameStatus.rendering.value])))
            if not frame:
                return None
            job = db.get(Job, frame.job_id)
            if job.status in (JobStatus.cancelled.value, JobStatus.paused.value):
                return None
            frame.status = FrameStatus.rendering.value
            frame.lease_expires_at = utcnow() + timedelta(seconds=60)
            db.flush()
            db.expunge(frame)
            return frame

    def fail(self, worker_id: str, raw_lease: str, error: str, logs: str) -> bool:
        with self.lock, self.sessions.begin() as db:
            frame = db.scalar(select(Frame).where(Frame.worker_id == worker_id, Frame.lease_hash == token_hash(raw_lease)))
            if not frame or frame.status not in (FrameStatus.leased.value, FrameStatus.rendering.value):
                return False
            frame.error_text = error[:8192]
            frame.log_text = logs[-65536:]
            frame.status = FrameStatus.failed.value if frame.attempts >= 3 else FrameStatus.pending.value
            frame.worker_id = None
            frame.lease_hash = None
            frame.lease_expires_at = None
            self._aggregate(db, frame.job_id)
            return True

    def complete(self, worker_id: str, raw_lease: str, output_key: str, preview_key: str | None, checksum: str, duration: float, logs: str) -> bool:
        with self.lock, self.sessions.begin() as db:
            frame = db.scalar(select(Frame).where(Frame.worker_id == worker_id, Frame.lease_hash == token_hash(raw_lease)))
            if not frame or frame.status == FrameStatus.succeeded.value:
                return bool(frame and frame.status == FrameStatus.succeeded.value)
            if frame.status not in (FrameStatus.leased.value, FrameStatus.rendering.value):
                return False
            frame.status = FrameStatus.succeeded.value
            frame.output_key = output_key
            frame.preview_key = preview_key
            frame.output_sha256 = checksum
            frame.duration_seconds = duration
            frame.log_text = logs[-65536:]
            frame.completed_at = utcnow()
            frame.lease_expires_at = None
            self._aggregate(db, frame.job_id)
            return True

    def _aggregate(self, db, job_id: str) -> None:
        job = db.get(Job, job_id)
        states = list(db.scalars(select(Frame.status).where(Frame.job_id == job_id)))
        if not states or job.status in (JobStatus.cancelled.value, JobStatus.paused.value):
            return
        if all(s == FrameStatus.succeeded.value for s in states):
            job.status = JobStatus.completed.value
        elif all(s in (FrameStatus.succeeded.value, FrameStatus.failed.value) for s in states):
            job.status = JobStatus.failed.value
        elif any(s in (FrameStatus.leased.value, FrameStatus.rendering.value, FrameStatus.succeeded.value) for s in states):
            job.status = JobStatus.running.value
        else:
            job.status = JobStatus.queued.value

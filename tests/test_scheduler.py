from datetime import timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from renderfarm.database import Base, utcnow
from renderfarm.models import Frame, FrameStatus, Job, JobStatus, Worker
from renderfarm.scheduler import Scheduler


def setup_farm(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as db:
        worker = Worker(name="worker", token_hash="token")
        job = Job(name="job", frame_start=1, frame_end=2, output_format="PNG", package_key="package", package_sha256="a" * 64, blend_path="scene.blend", queue_order=1)
        db.add_all([worker, job])
        db.flush()
        db.add_all([Frame(job_id=job.id, frame_number=1), Frame(job_id=job.id, frame_number=2)])
    return sessions, worker


def test_lease_complete_and_job_aggregation(tmp_path):
    sessions, worker = setup_farm(tmp_path)
    scheduler = Scheduler(sessions)
    first = scheduler.lease(worker)
    assert first["frame"] == 1
    assert scheduler.heartbeat(worker.id, first["lease_token"])
    assert scheduler.complete(worker.id, first["lease_token"], "one.png", None, "b" * 64, 1.2, "ok")
    second = scheduler.lease(worker)
    assert second["frame"] == 2
    assert scheduler.complete(worker.id, second["lease_token"], "two.png", None, "c" * 64, 1.3, "ok")
    with sessions() as db:
        assert db.scalar(select(Job)).status == JobStatus.completed.value


def test_expired_lease_retries_then_fails(tmp_path):
    sessions, worker = setup_farm(tmp_path)
    scheduler = Scheduler(sessions)
    for attempt in range(3):
        lease = scheduler.lease(worker)
        with sessions.begin() as db:
            frame = db.get(Frame, lease["frame_id"])
            frame.lease_expires_at = utcnow() - timedelta(seconds=1)
        scheduler.reconcile()
        with sessions() as db:
            frame = db.get(Frame, lease["frame_id"])
            expected = FrameStatus.failed.value if attempt == 2 else FrameStatus.pending.value
            assert frame.status == expected


def test_queue_order_and_pause(tmp_path):
    sessions, worker = setup_farm(tmp_path)
    with sessions.begin() as db:
        first = db.scalar(select(Job))
        first.status = JobStatus.paused.value
        second = Job(name="priority", frame_start=7, frame_end=7, output_format="PNG", package_key="p2", package_sha256="d" * 64, blend_path="scene.blend", queue_order=0)
        db.add(second)
        db.flush()
        db.add(Frame(job_id=second.id, frame_number=7))
    lease = Scheduler(sessions).lease(worker)
    assert lease["frame"] == 7


def test_batch_leases_consecutive_frames_from_only_one_job(tmp_path):
    sessions, worker = setup_farm(tmp_path)
    with sessions.begin() as db:
        second = Job(name="next", frame_start=10, frame_end=10, output_format="PNG", package_key="p2", package_sha256="d" * 64, blend_path="other.blend", queue_order=2)
        db.add(second)
        db.flush()
        db.add(Frame(job_id=second.id, frame_number=10))

    leases = Scheduler(sessions).lease_batch(worker, 5)

    assert [lease["frame"] for lease in leases] == [1, 2]
    assert len({lease["job_id"] for lease in leases}) == 1
    assert len({lease["lease_token"] for lease in leases}) == 2
    assert Scheduler(sessions).lease(worker)["frame"] == 10

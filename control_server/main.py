from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
import os
import shutil
import json
from datetime import datetime

from database import get_db, create_tables, Job, Worker, RenderTask, Frame
from models import (
    JobCreate, JobResponse, WorkerCreate, WorkerResponse, 
    JobProgress, WorkerStatus, JobAssignment
)

app = FastAPI(title="Render Farm Server", version="1.0.0")

# Configure CORS to allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create upload directories
UPLOAD_DIR = "uploads"
BLENDER_FILES_DIR = os.path.join(UPLOAD_DIR, "blender_files")
RENDERED_IMAGES_DIR = os.path.join(UPLOAD_DIR, "rendered_images")

os.makedirs(BLENDER_FILES_DIR, exist_ok=True)
os.makedirs(RENDERED_IMAGES_DIR, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=UPLOAD_DIR), name="static")
app.mount("/dashboard", StaticFiles(directory="../web_dashboard"), name="dashboard")

# Create tables on startup
@app.on_event("startup")
async def startup_event():
    create_tables()

@app.post("/jobs/", response_model=JobResponse)
async def create_job(job: JobCreate, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Create a new render job and upload the blender file."""
    if not file.filename.endswith('.blend'):
        raise HTTPException(status_code=400, detail="File must be a .blend file")
    
    # Save the blender file
    file_path = os.path.join(BLENDER_FILES_DIR, f"{job.name}_{file.filename}")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Create job
    db_job = Job(
        name=job.name,
        blender_file_path=file_path,
        total_frames=job.total_frames,
        output_format=job.output_format,
        scene_name=job.scene_name
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)
    
    # Create frame records
    for frame_num in range(1, job.total_frames + 1):
        frame = Frame(
            job_id=db_job.id,
            frame_number=frame_num,
            status="pending"
        )
        db.add(frame)
    
    db.commit()
    return db_job

@app.get("/jobs/", response_model=List[JobResponse])
async def list_jobs(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all jobs."""
    jobs = db.query(Job).offset(skip).limit(limit).all()
    return jobs

@app.get("/jobs/{job_id}/progress", response_model=JobProgress)
async def get_job_progress(job_id: int, db: Session = Depends(get_db)):
    """Get progress for a specific job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    frames = db.query(Frame).filter(Frame.job_id == job_id).all()
    
    completed_frames = len([f for f in frames if f.status == "completed"])
    pending_frames = len([f for f in frames if f.status == "pending"])
    failed_frames = len([f for f in frames if f.status == "failed"])
    
    progress_percentage = (completed_frames / job.total_frames) * 100 if job.total_frames > 0 else 0
    
    return JobProgress(
        job_id=job.id,
        job_name=job.name,
        total_frames=job.total_frames,
        completed_frames=completed_frames,
        pending_frames=pending_frames,
        failed_frames=failed_frames,
        progress_percentage=progress_percentage,
        status=job.status
    )

@app.post("/workers/", response_model=WorkerResponse)
async def register_worker(worker: WorkerCreate, db: Session = Depends(get_db)):
    """Register a new worker."""
    db_worker = Worker(
        name=worker.name,
        ip_address=worker.ip_address,
        capabilities=json.dumps(worker.capabilities) if worker.capabilities else None
    )
    db.add(db_worker)
    db.commit()
    db.refresh(db_worker)
    return db_worker

@app.get("/workers/", response_model=List[WorkerResponse])
async def list_workers(db: Session = Depends(get_db)):
    """List all workers."""
    workers = db.query(Worker).all()
    for worker in workers:
        if worker.capabilities:
            worker.capabilities = json.loads(worker.capabilities)
        if worker.assigned_frames:
            worker.assigned_frames = json.loads(worker.assigned_frames)
    return workers

@app.post("/workers/{worker_id}/heartbeat")
async def worker_heartbeat(worker_id: int, db: Session = Depends(get_db)):
    """Update worker last seen timestamp."""
    worker = db.query(Worker).filter(Worker.id == worker_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    
    worker.last_seen = datetime.utcnow()
    db.commit()
    return {"status": "ok"}

@app.get("/workers/poll_job/{worker_id}", response_model=JobAssignment)
async def poll_for_job(worker_id: int, db: Session = Depends(get_db)):
    """Poll for available job assignments."""
    worker = db.query(Worker).filter(Worker.id == worker_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    
    # Update worker last seen
    worker.last_seen = datetime.utcnow()
    
    # Check if worker already has a job
    if worker.current_job_id:
        job = db.query(Job).filter(Job.id == worker.current_job_id).first()
        if job and job.status == "running":
            # Return existing assignment
            assigned_frames = json.loads(worker.assigned_frames) if worker.assigned_frames else []
            return JobAssignment(
                job_id=job.id,
                frame_ranges=[{"start": f, "end": f} for f in assigned_frames],
                blender_file_url=f"/static/blender_files/{os.path.basename(job.blender_file_path)}",
                output_format=job.output_format,
                scene_name=job.scene_name
            )
    
    # Find pending job
    pending_job = db.query(Job).filter(Job.status == "pending").first()
    if not pending_job:
        # Check for running jobs with pending frames
        running_job = db.query(Job).filter(Job.status == "running").first()
        if running_job:
            pending_frames = db.query(Frame).filter(
                Frame.job_id == running_job.id,
                Frame.status == "pending"
            ).all()
            
            if pending_frames:
                pending_job = running_job
    
    if not pending_job or not pending_frames:
        return {"job_id": None, "frame_ranges": [], "blender_file_url": None}
    
    # Start job if it's pending
    if pending_job.status == "pending":
        pending_job.status = "running"
        pending_job.started_at = datetime.utcnow()
    
    # Calculate frame distribution
    all_workers = db.query(Worker).filter(
        Worker.status.in_(["idle", "busy"]),
        Worker.id != worker_id
    ).count() + 1
    
    frames_per_worker = max(1, len(pending_frames) // all_workers)
    
    # Assign frames to this worker
    assigned_frames = pending_frames[:frames_per_worker]
    frame_numbers = [f.frame_number for f in assigned_frames]
    
    # Update frames
    for frame in assigned_frames:
        frame.status = "assigned"
        frame.worker_id = worker_id
    
    # Update worker
    worker.status = "busy"
    worker.current_job_id = pending_job.id
    worker.assigned_frames = json.dumps(frame_numbers)
    
    db.commit()
    
    return JobAssignment(
        job_id=pending_job.id,
        frame_ranges=[{"start": f, "end": f} for f in frame_numbers],
        blender_file_url=f"/static/blender_files/{os.path.basename(pending_job.blender_file_path)}",
        output_format=pending_job.output_format,
        scene_name=pending_job.scene_name
    )

@app.post("/jobs/{job_id}/upload_frame/{frame_number}")
async def upload_rendered_frame(
    job_id: int,
    frame_number: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload a completed rendered frame."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    frame = db.query(Frame).filter(
        Frame.job_id == job_id,
        Frame.frame_number == frame_number
    ).first()
    
    if not frame:
        raise HTTPException(status_code=404, detail="Frame not found")
    
    # Save the rendered image
    file_extension = file.filename.split('.')[-1]
    file_name = f"job_{job_id}_frame_{frame_number}.{file_extension}"
    file_path = os.path.join(RENDERED_IMAGES_DIR, file_name)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Update frame
    frame.status = "completed"
    frame.file_path = file_path
    
    # Update job status if all frames are done
    all_frames = db.query(Frame).filter(Frame.job_id == job_id).all()
    if all(f.status == "completed" for f in all_frames):
        job.status = "completed"
        job.completed_at = datetime.utcnow()
    
    db.commit()
    
    return {"status": "success", "file_path": file_path}

@app.get("/progress/total_frames_done")
async def get_total_frames_done(db: Session = Depends(get_db)):
    """Get total frames completed across all jobs."""
    completed_frames = db.query(Frame).filter(Frame.status == "completed").count()
    total_frames = db.query(Frame).count()
    
    return {
        "total_frames_completed": completed_frames,
        "total_frames": total_frames,
        "completion_percentage": (completed_frames / total_frames * 100) if total_frames > 0 else 0
    }

@app.get("/progress/all_jobs")
async def get_all_jobs_progress(db: Session = Depends(get_db)):
    """Get progress for all jobs."""
    jobs = db.query(Job).all()
    progress_list = []
    
    for job in jobs:
        frames = db.query(Frame).filter(Frame.job_id == job.id).all()
        completed = len([f for f in frames if f.status == "completed"])
        pending = len([f for f in frames if f.status == "pending"])
        failed = len([f for f in frames if f.status == "failed"])
        
        progress_list.append({
            "job_id": job.id,
            "job_name": job.name,
            "total_frames": job.total_frames,
            "completed_frames": completed,
            "pending_frames": pending,
            "failed_frames": failed,
            "progress_percentage": (completed / job.total_frames * 100) if job.total_frames > 0 else 0,
            "status": job.status
        })
    
    return progress_list

@app.get("/")
async def serve_dashboard():
    """Serve the dashboard at root path."""
    return FileResponse("../web_dashboard/index.html")

@app.get("/dashboard")
async def redirect_to_dashboard():
    """Redirect /dashboard to the dashboard."""
    return FileResponse("../web_dashboard/index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

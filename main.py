import os
import shutil
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from datetime import datetime
import pytz
from typing import Optional
import uuid

from database import (
    init_db, submit_job, register_worker, get_available_task, 
    update_task_status, get_worker_status, get_job_status
)

app = FastAPI()

# Initialize database
init_db()

# Create necessary directories
os.makedirs("jobs", exist_ok=True)
os.makedirs("renders", exist_ok=True)

@app.get("/time")
def get_time():
    eastern = pytz.timezone("US/Eastern")
    current_time = datetime.now(eastern).strftime("%Y-%m-%d %H:%M:%S %Z")
    return {"time": current_time}

@app.post("/submit_job")
async def submit_render_job(
    blend_file: UploadFile = File(...),
    start_frame: int = Form(...),
    end_frame: int = Form(...),
):
    """Submit a new render job."""
    # Save blend file
    blend_file_name = f"{uuid.uuid4()}_{blend_file.filename}"
    blend_file_path = os.path.join("jobs", blend_file_name)
    
    with open(blend_file_path, "wb") as buffer:
        shutil.copyfileobj(blend_file.file, buffer)
    
    # Submit job to database
    job_id = submit_job(blend_file_name, start_frame, end_frame)
    
    return {"job_id": job_id, "message": "Job submitted successfully"}

@app.post("/register_worker")
def register_worker_endpoint(worker_id: str = Form(...)):
    """Register a worker with the system."""
    register_worker(worker_id)
    return {"message": "Worker registered successfully"}

@app.post("/get_job")
def get_job_for_worker(worker_id: str = Form(...)):
    """Get an available job for a worker."""
    task = get_available_task(worker_id)
    if task:
        task_id, frame_number, blend_file_name = task
        blend_file_path = os.path.join("jobs", blend_file_name)
        
        # Check if blend file exists
        if not os.path.exists(blend_file_path):
            raise HTTPException(status_code=404, detail="Blend file not found")
        
        return {
            "task_id": task_id,
            "frame_number": frame_number,
            "blend_file_url": f"/download_blend/{blend_file_name}",
            "blend_file_name": blend_file_name
        }
    
    return {"message": "No jobs available"}

@app.get("/download_blend/{blend_file_name}")
def download_blend_file(blend_file_name: str):
    """Download a blend file."""
    blend_file_path = os.path.join("jobs", blend_file_name)
    if not os.path.exists(blend_file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(blend_file_path)

@app.post("/update_task_status")
def update_task_status_endpoint(
    task_id: int = Form(...),
    status: str = Form(...),
    result_path: Optional[str] = Form(None)
):
    """Update the status of a task."""
    update_task_status(task_id, status, result_path)
    return {"message": "Task status updated"}

@app.post("/upload_result")
async def upload_result(
    file: UploadFile = File(...),
    task_id: int = Form(...)
):
    """Upload a rendered result file."""
    # Save result file
    result_file_name = f"task_{task_id}_{file.filename}"
    result_file_path = os.path.join("renders", result_file_name)
    
    with open(result_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Update task status
    update_task_status(task_id, "completed", result_file_path)
    
    return {"message": "Result uploaded successfully"}

@app.get("/job_status/{job_id}")
def get_job_status_endpoint(job_id: int):
    """Get the status of a job."""
    status = get_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return status

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

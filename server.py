import os
import shutil
import time
import threading
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel

app = FastAPI()

# Create necessary directories
os.makedirs("out", exist_ok=True)
os.makedirs("jobs", exist_ok=True)
os.makedirs("blend_files", exist_ok=True)

# Global variable to store available jobs
available_jobs = []
jobs_lock = threading.Lock()

class JobInfo(BaseModel):
    job_id: str
    blend_file_url: str
    frame_start: int
    frame_end: int
    total_workers: int = 1
    worker_id: int = 0

def parse_info_file(info_path: str) -> tuple:
    """Parse the info.txt file to extract frame start and end"""
    frame_start = 1
    frame_end = 250
    
    try:
        with open(info_path, 'r') as f:
            for line in f:
                if line.startswith('framestart:'):
                    frame_start = int(line.split(':')[1].strip())
                elif line.startswith('frameend:'):
                    frame_end = int(line.split(':')[1].strip())
    except Exception as e:
        print(f"Error parsing info file {info_path}: {e}")
    
    return frame_start, frame_end

def scan_jobs():
    """Scan the jobs directory for new jobs"""
    global available_jobs
    
    # Clear the current list
    available_jobs = []
    
    # Scan jobs directory
    jobs_dir = Path("jobs")
    if jobs_dir.exists():
        for job_folder in jobs_dir.iterdir():
            if job_folder.is_dir():
                # Look for info.txt and .blend file
                info_file = job_folder / "info.txt"
                blend_files = list(job_folder.glob("*.blend"))
                
                if info_file.exists() and blend_files:
                    # Parse frame info
                    frame_start, frame_end = parse_info_file(str(info_file))
                    
                    # Check for worker count in info file
                    total_workers = 1
                    try:
                        with open(info_file, 'r') as f:
                            for line in f:
                                if line.startswith('workers:'):
                                    total_workers = int(line.split(':')[1].strip())
                    except Exception as e:
                        print(f"Error parsing worker count in {info_file}: {e}")
                    
                    # Move blend file to blend_files directory
                    blend_file = blend_files[0]
                    new_blend_path = Path("blend_files") / blend_file.name
                    shutil.move(str(blend_file), str(new_blend_path))
                    
                    # Calculate frames per worker
                    total_frames = frame_end - frame_start + 1
                    frames_per_worker = total_frames // total_workers
                    remainder = total_frames % total_workers
                    
                    # Create jobs for each worker
                    for worker_id in range(total_workers):
                        # Calculate frame range for this worker
                        worker_frame_start = frame_start + (worker_id * frames_per_worker)
                        worker_frame_end = worker_frame_start + frames_per_worker - 1
                        
                        # Distribute remainder frames among first few workers
                        if worker_id < remainder:
                            worker_frame_start += worker_id
                            worker_frame_end += worker_id + 1
                        else:
                            worker_frame_start += remainder
                            worker_frame_end += remainder
                        
                        # Add job to available jobs
                        job_info = {
                            "job_id": job_folder.name,
                            "blend_file_url": f"/blend_files/{blend_file.name}",
                            "frame_start": worker_frame_start,
                            "frame_end": worker_frame_end,
                            "total_workers": total_workers,
                            "worker_id": worker_id
                        }
                        available_jobs.append(job_info)
                    
                    # Remove the job folder
                    shutil.rmtree(str(job_folder))

@app.get("/")
async def root():
    return {"message": "Render Farm Server is running"}

@app.get("/job/")
async def get_job() -> Optional[JobInfo]:
    """Get the next available job"""
    with jobs_lock:
        if available_jobs:
            # Return the first job and remove it from the list
            job = available_jobs.pop(0)
            return JobInfo(**job)
        else:
            # Scan for new jobs if none available
            scan_jobs()
            if available_jobs:
                job = available_jobs.pop(0)
                return JobInfo(**job)
            return None

@app.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    try:
        # Save the uploaded file to the 'out' directory
        file_path = os.path.join("out", file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"filename": file.filename, "status": "uploaded successfully"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/upload-multiple/")
async def upload_multiple_files(files: List[UploadFile] = File(...)):
    uploaded_files = []
    for file in files:
        try:
            file_path = os.path.join("out", file.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            uploaded_files.append(file.filename)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e), "filename": file.filename})
    return {"files": uploaded_files, "status": "uploaded successfully"}

# Mount the blend_files directory to serve blend files statically
app.mount("/blend_files", StaticFiles(directory="blend_files"), name="blend_files")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

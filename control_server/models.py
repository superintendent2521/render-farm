from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class JobCreate(BaseModel):
    name: str
    total_frames: int
    output_format: str = "PNG"
    scene_name: Optional[str] = None

class JobResponse(BaseModel):
    id: int
    name: str
    total_frames: int
    status: str
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    output_format: str
    scene_name: Optional[str]
    
    class Config:
        from_attributes = True

class WorkerCreate(BaseModel):
    name: str
    ip_address: Optional[str] = None
    capabilities: Optional[dict] = None

class WorkerResponse(BaseModel):
    id: int
    name: str
    ip_address: Optional[str]
    status: str
    last_seen: datetime
    capabilities: Optional[dict]
    current_job_id: Optional[int]
    assigned_frames: Optional[List[int]]
    
    class Config:
        from_attributes = True

class RenderTaskResponse(BaseModel):
    id: int
    job_id: int
    worker_id: Optional[int]
    frame_number: int
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    output_path: Optional[str]
    error_message: Optional[str]
    
    class Config:
        from_attributes = True

class JobProgress(BaseModel):
    job_id: int
    job_name: str
    total_frames: int
    completed_frames: int
    pending_frames: int
    failed_frames: int
    progress_percentage: float
    status: str

class WorkerStatus(BaseModel):
    worker_id: int
    worker_name: str
    status: str
    current_job: Optional[str]
    assigned_frames: Optional[List[int]]
    last_seen: datetime

class FrameRange(BaseModel):
    start: int
    end: int

class JobAssignment(BaseModel):
    job_id: int
    frame_ranges: List[FrameRange]
    blender_file_url: str
    output_format: str
    scene_name: Optional[str]

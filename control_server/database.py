from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

SQLALCHEMY_DATABASE_URL = "sqlite:///./render_farm.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    blender_file_path = Column(String)
    total_frames = Column(Integer)
    status = Column(String, default="pending")  # pending, running, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    output_format = Column(String, default="PNG")
    scene_name = Column(String, nullable=True)

class Worker(Base):
    __tablename__ = "workers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    ip_address = Column(String)
    status = Column(String, default="idle")  # idle, busy, offline
    last_seen = Column(DateTime, default=datetime.utcnow)
    capabilities = Column(Text)  # JSON string of worker capabilities
    current_job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    assigned_frames = Column(Text)  # JSON string of frame ranges

class RenderTask(Base):
    __tablename__ = "render_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"))
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=True)
    frame_number = Column(Integer)
    status = Column(String, default="pending")  # pending, assigned, rendering, completed, failed
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    output_path = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)

class Frame(Base):
    __tablename__ = "frames"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"))
    frame_number = Column(Integer)
    status = Column(String, default="pending")  # pending, rendering, completed, failed
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=True)
    file_path = Column(String, nullable=True)
    render_time = Column(Integer, nullable=True)  # in seconds

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    Base.metadata.create_all(bind=engine)

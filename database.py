import sqlite3
from typing import List, Optional, Tuple
import os

# Database schema
CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    blend_file TEXT NOT NULL,
    start_frame INTEGER NOT NULL,
    end_frame INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'idle',
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS render_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    frame_number INTEGER NOT NULL,
    worker_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    result_path TEXT,
    assigned_at TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs (id)
);
"""

def init_db(db_path: str = "render_farm.db") -> None:
    """Initialize the database with required tables."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.executescript(CREATE_TABLES)
    conn.commit()
    conn.close()

def submit_job(blend_file: str, start_frame: int, end_frame: int, db_path: str = "render_farm.db") -> int:
    """Submit a new render job to the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO jobs (blend_file, start_frame, end_frame, status) VALUES (?, ?, ?, ?)",
        (blend_file, start_frame, end_frame, "pending")
    )
    job_id = cursor.lastrowid
    conn.commit()
    
    # Create individual tasks for each frame
    for frame in range(start_frame, end_frame + 1):
        cursor.execute(
            "INSERT INTO render_tasks (job_id, frame_number, status) VALUES (?, ?, ?)",
            (job_id, frame, "pending")
        )
    
    conn.commit()
    conn.close()
    return job_id

def register_worker(worker_id: str, db_path: str = "render_farm.db") -> None:
    """Register a new worker or update existing worker's last seen time."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO workers (worker_id, status, last_seen) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (worker_id, "idle")
    )
    conn.commit()
    conn.close()

def get_available_task(worker_id: str, db_path: str = "render_farm.db") -> Optional[Tuple[int, int, str]]:
    """Get an available task for a worker."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Update worker status to 'busy'
    cursor.execute(
        "UPDATE workers SET status = ? WHERE worker_id = ?",
        ("busy", worker_id)
    )
    
    # Get an available task
    cursor.execute(
        """SELECT t.id, t.frame_number, j.blend_file 
           FROM render_tasks t 
           JOIN jobs j ON t.job_id = j.id 
           WHERE t.status = 'pending' 
           LIMIT 1"""
    )
    task = cursor.fetchone()
    
    if task:
        task_id, frame_number, blend_file = task
        # Update task status to 'assigned'
        cursor.execute(
            "UPDATE render_tasks SET status = ?, worker_id = ?, assigned_at = CURRENT_TIMESTAMP WHERE id = ?",
            ("assigned", worker_id, task_id)
        )
        conn.commit()
        conn.close()
        return task_id, frame_number, blend_file
    
    # If no task available, set worker back to 'idle'
    cursor.execute(
        "UPDATE workers SET status = ? WHERE worker_id = ?",
        ("idle", worker_id)
    )
    conn.commit()
    conn.close()
    return None

def update_task_status(task_id: int, status: str, result_path: str = None, db_path: str = "render_farm.db") -> None:
    """Update the status of a render task."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    if status == "completed":
        cursor.execute(
            "UPDATE render_tasks SET status = ?, result_path = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, result_path, task_id)
        )
    else:
        cursor.execute(
            "UPDATE render_tasks SET status = ? WHERE id = ?",
            (status, task_id)
        )
    
    conn.commit()
    conn.close()

def get_worker_status(worker_id: str, db_path: str = "render_farm.db") -> Optional[str]:
    """Get the status of a worker."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM workers WHERE worker_id = ?", (worker_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_job_status(job_id: int, db_path: str = "render_farm.db") -> dict:
    """Get the status of a job."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get job info
    cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    job = cursor.fetchone()
    
    if not job:
        conn.close()
        return {}
    
    # Get task counts
    cursor.execute(
        """SELECT status, COUNT(*) 
           FROM render_tasks 
           WHERE job_id = ? 
           GROUP BY status""", 
        (job_id,)
    )
    task_stats = cursor.fetchall()
    
    conn.close()
    
    # Convert to dict for easier handling
    stats = {status: count for status, count in task_stats}
    total_tasks = sum(stats.values())
    
    return {
        "job_id": job[0],
        "blend_file": job[1],
        "start_frame": job[2],
        "end_frame": job[3],
        "status": job[4],
        "total_tasks": total_tasks,
        "stats": stats
    }

def clear_all_workers(db_path: str = "render_farm.db") -> None:
    """Clear all workers from the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM workers")
    conn.commit()
    conn.close()

import requests
import time
import os
import subprocess
import sys
import uuid

# Configuration
MASTER_URL = "http://localhost:8000"
WORKER_ID = str(uuid.uuid4())
print(f"Worker name is {WORKER_ID}")
RENDERS_DIR = "renders"
BLEND_FILES_DIR = "blend_files"

def register_worker():
    """Register this worker with the master server."""
    try:
        response = requests.post(
            f"{MASTER_URL}/register_worker",
            data={"worker_id": WORKER_ID}
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Failed to register worker: {e}")
        return False

def get_job():
    """Request a job from the master server."""
    try:
        response = requests.post(
            f"{MASTER_URL}/get_job",
            data={"worker_id": WORKER_ID}
        )
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"Failed to get job: {e}")
        return None

def update_task_status(task_id, status, result_path=None):
    """Update the status of a task on the master server."""
    try:
        data = {"task_id": task_id, "status": status}
        if result_path:
            data["result_path"] = result_path
            
        response = requests.post(
            f"{MASTER_URL}/update_task_status",
            data=data
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Failed to update task status: {e}")
        return False

def download_file(url, local_path):
    """Download a file from a URL."""
    try:
        # If URL is relative, prepend the master URL
        if url.startswith('/'):
            full_url = f"{MASTER_URL}{url}"
        else:
            full_url = url
            
        response = requests.get(full_url)
        if response.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(response.content)
            return True
        return False
    except Exception as e:
        print(f"Failed to download file: {e}")
        return False

def upload_file(file_path, task_id):
    """Upload a rendered file to the master server."""
    try:
        with open(file_path, 'rb') as f:
            files = {'file': f}
            data = {'task_id': task_id}
            response = requests.post(
                f"{MASTER_URL}/upload_result",
                files=files,
                data=data
            )
            return response.status_code == 200
    except Exception as e:
        print(f"Failed to upload file: {e}")
        return False

def render_frame(blend_file_path, frame_number):
    """Render a single frame using Blender."""
    # Create output path
    frame_str = f"{frame_number:04d}"
    output_path = os.path.join(RENDERS_DIR, f"frame_{frame_str}.png")
    
    # Ensure renders directory exists
    os.makedirs(RENDERS_DIR, exist_ok=True)
    
    # Command to render a single frame with Blender
    # This assumes Blender is in the system PATH
    cmd = [
        "blender",
        "-b", blend_file_path,
        "-o", os.path.join(RENDERS_DIR, "frame_####.png"),
        "-f", str(frame_number)
    ]
    
    # Add GPU rendering flag if available
    # Note: This requires Blender to be configured for GPU rendering
    # cmd.extend(["-- --cycles-device", "CUDA"])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            # Check if output file was created
            if os.path.exists(output_path):
                return output_path
            else:
                print(f"Blender ran successfully but output file not found: {output_path}")
                return None
        else:
            print(f"Blender error: {result.stderr}")
            return None
    except Exception as e:
        print(f"Failed to run Blender: {e}")
        return None

def main():
    """Main worker loop."""
    print(f"Starting worker {WORKER_ID}")
    
    # Create necessary directories
    os.makedirs(BLEND_FILES_DIR, exist_ok=True)
    os.makedirs(RENDERS_DIR, exist_ok=True)
    
    # Register with master
    if not register_worker():
        print("Failed to register with master server")
        return
    
    print("Worker registered successfully")
    
    while True:
        # Check for available jobs
        job = get_job()
        
        if job and "task_id" in job:
            print(f"Received job: {job}")
            task_id = job["task_id"]
            frame_number = job["frame_number"]
            blend_file_url = job["blend_file_url"]
            blend_file_name = job["blend_file_name"]
            
            # Download blend file
            blend_file_path = os.path.join(BLEND_FILES_DIR, blend_file_name)
            if not download_file(blend_file_url, blend_file_path):
                print("Failed to download blend file")
                update_task_status(task_id, "failed")
                continue
            
            # Update task status to rendering
            update_task_status(task_id, "rendering")
            
            # Render the frame
            result_path = render_frame(blend_file_path, frame_number)
            
            if result_path:
                # Upload result
                if upload_file(result_path, task_id):
                    update_task_status(task_id, "completed", result_path)
                    print(f"Successfully rendered and uploaded frame {frame_number}")
                else:
                    update_task_status(task_id, "failed")
                    print("Failed to upload result")
            else:
                update_task_status(task_id, "failed")
                print(f"Failed to render frame {frame_number}")
        else:
            # No job available, wait before polling again
            time.sleep(5)

if __name__ == "__main__":
    main()

import os
import shutil
from pathlib import Path

def create_test_job():
    """Create a test job with a blend file and info.txt"""
    # Create jobs directory if it doesn't exist
    os.makedirs("jobs", exist_ok=True)
    
    # Create a test job folder
    job_folder = Path("jobs") / "test_job_001"
    os.makedirs(job_folder, exist_ok=True)
    
    # Create a sample info.txt file
    info_content = """framestart:10
frameend:150
"""
    info_file = job_folder / "info.txt"
    with open(info_file, "w") as f:
        f.write(info_content)
    
    # Create a sample blend file (just a text file for testing)
    blend_file = job_folder / "sample.blend"
    with open(blend_file, "w") as f:
        f.write("This is a sample blend file content")
    
    print(f"Created test job in {job_folder}")

if __name__ == "__main__":
    create_test_job()

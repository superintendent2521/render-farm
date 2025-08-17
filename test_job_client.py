import requests
import time

# Server URL - adjust as needed
SERVER_URL = "http://localhost:8000"

def test_get_job():
    """Test getting a job from the server"""
    try:
        response = requests.get(f"{SERVER_URL}/job/")
        if response.status_code == 200:
            job_data = response.json()
            if job_data:
                print("Received job:")
                print(f"  Job ID: {job_data['job_id']}")
                print(f"  Blend file URL: {job_data['blend_file_url']}")
                print(f"  Frame start: {job_data['frame_start']}")
                print(f"  Frame end: {job_data['frame_end']}")
                
                # Test downloading the blend file
                blend_response = requests.get(f"{SERVER_URL}{job_data['blend_file_url']}")
                if blend_response.status_code == 200:
                    print("Blend file downloaded successfully")
                else:
                    print(f"Failed to download blend file: {blend_response.status_code}")
            else:
                print("No jobs available")
        else:
            print(f"Failed to get job: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("Testing job API...")
    test_get_job()

import requests

def submit_job(blend_file_path, start_frame, end_frame, server_url="http://localhost:8000"):
    """Submit a render job to the server."""
    with open(blend_file_path, 'rb') as f:
        files = {'blend_file': f}
        data = {
            'start_frame': start_frame,
            'end_frame': end_frame
        }
        response = requests.post(f"{server_url}/submit_job", files=files, data=data)
        return response.json()

if __name__ == "__main__":
    # Example usage
    result = submit_job("jobs\Spaceship Project.blend", 1, 10)
    print(result)
    print(f"Job ID: {result['job_id']}")
    print("You can check the job status at:")
    print(f"http://localhost:8000/job_status/{result['job_id']}")

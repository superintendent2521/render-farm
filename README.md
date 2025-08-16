# Simple Blender Render Farm

A simple distributed render farm for Blender using a master/worker architecture.

## Architecture

- **Master Server**: Central server that manages jobs and distributes work to workers
- **Workers**: Client machines that render frames and report back to the master
- **Database**: SQLite database to track jobs, workers, and task status

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Install Blender on all worker machines and ensure it's in the system PATH

## Usage

### Starting the Master Server

```bash
python main.py
```

The server will start on `http://localhost:8000`

### Starting a Worker

```bash
python worker.py
```

Workers will automatically register with the master server and start requesting jobs.

### Submitting a Render Job

You can submit a job by sending a POST request to `/submit_job` with:
- `blend_file`: The .blend file to render
- `start_frame`: First frame to render
- `end_frame`: Last frame to render

Example using curl:
```bash
curl -X POST "http://localhost:8000/submit_job" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "blend_file=@path/to/your/file.blend" \
  -F "start_frame=1" \
  -F "end_frame=100"
```

### Checking Job Status

You can check the status of a job by accessing:
```
http://localhost:8000/job_status/{job_id}
```

## Directory Structure

- `jobs/`: Stores uploaded .blend files
- `renders/`: Stores rendered frames from workers
- `blend_files/`: (Worker side) Stores downloaded .blend files
- `renders/`: (Worker side) Stores rendered frames before uploading

## API Endpoints

- `GET /time`: Get current server time
- `POST /submit_job`: Submit a new render job
- `POST /register_worker`: Register a worker
- `POST /get_job`: Worker requests a job
- `GET /download_blend/{blend_file_name}`: Download a blend file
- `POST /update_task_status`: Worker updates task status
- `POST /upload_result`: Worker uploads rendered frame
- `GET /job_status/{job_id}`: Get job status

## How It Works

1. User submits a .blend file with frame range to the master server
2. Master server creates individual tasks for each frame
3. Workers periodically poll the master server for available tasks
4. When a worker gets a task, it downloads the .blend file
5. Worker renders the assigned frame using Blender
6. Worker uploads the rendered frame back to the master server
7. Master server updates the task status in the database

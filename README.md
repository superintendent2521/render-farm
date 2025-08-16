# Render Farm System

A distributed render farm system for Blender that allows you to distribute rendering tasks across multiple machines.

## Architecture

The system consists of:
- **Control Server**: Central server that manages jobs and coordinates workers
- **Worker Clients**: Machines that perform the actual rendering
- **Database**: SQLite database for job tracking and progress monitoring

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the Control Server

```bash
cd control_server
python main.py
```

The server will start on `http://localhost:8000`

### 3. Start Workers

On each machine you want to use as a worker:

```bash
cd worker_client
python worker.py --server http://localhost:8000 --name "Worker1"
```

### 4. Submit a Job

Use the API endpoints to submit rendering jobs:

```bash
# Upload a .blend file with job details
curl -X POST "http://localhost:8000/jobs/" \
  -F "file=@your_scene.blend" \
  -F "name=MyRenderJob" \
  -F "total_frames=100" \
  -F "output_format=PNG" \
  -F "scene_name=Scene"
```

## API Endpoints

### Jobs
- `POST /jobs/` - Create a new render job
- `GET /jobs/` - List all jobs
- `GET /jobs/{job_id}/progress` - Get job progress
- `POST /jobs/{job_id}/upload_frame/{frame_number}` - Upload completed frame

### Workers
- `POST /workers/` - Register a new worker
- `GET /workers/` - List all workers
- `POST /workers/{worker_id}/heartbeat` - Worker heartbeat
- `GET /workers/poll_job/{worker_id}` - Poll for job assignment

### Progress
- `GET /progress/total_frames_done` - Get total progress across all jobs
- `GET /progress/all_jobs` - Get progress for all jobs

## Directory Structure

```
render-farm/
├── control_server/
│   ├── main.py          # FastAPI server
│   ├── database.py      # SQLAlchemy models
│   ├── models.py        # Pydantic models
│   └── uploads/         # Uploaded files
├── worker_client/
│   └── worker.py        # Worker client
├── requirements.txt     # Python dependencies
└── README.md           # This file
```

## Configuration

### Environment Variables
- `BLENDER_PATH`: Path to Blender executable (default: "blender")

### Worker Options
- `--server`: Server URL (required)
- `--name`: Worker name (required)
- `--blender`: Blender executable path (optional)

## Usage Examples

### Basic Usage
1. Start server on main machine
2. Start workers on render machines
3. Submit .blend file with render parameters
4. Monitor progress via API endpoints

### Advanced Usage
- Use different output formats (PNG, JPEG, EXR, etc.)
- Specify specific scenes within .blend files
- Monitor real-time progress across all workers
- Scale workers up/down dynamically

## Troubleshooting

### Common Issues
1. **Blender not found**: Ensure Blender is in PATH or use `--blender` flag
2. **Connection refused**: Check server URL and firewall settings
3. **Render failures**: Check Blender logs and scene settings

### Debug Mode
Enable debug logging by setting environment variable:
```bash
export LOG_LEVEL=DEBUG
```

## Security Notes
- Currently designed for trusted network environments
- No authentication implemented
- Use firewall rules to restrict access
- Consider VPN for remote workers

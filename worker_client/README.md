# Render Farm Worker - Docker Setup

This Docker setup allows you to run the render farm worker in a containerized environment with automatic Blender download and extraction.

## Quick Start

### Using Docker Compose (Recommended)

1. **Build and run the worker:**
   ```bash
   docker-compose up --build
   ```

2. **Customize environment variables:**
   ```bash
   # Edit docker-compose.yml or use environment variables
   SERVER_URL=http://your-server:8000
   WORKER_NAME=worker-1
   ```

### Using Docker directly

1. **Build the image:**
   ```bash
   docker build -t render-worker .
   ```

2. **Run the container:**
   ```bash
   docker run -e SERVER_URL=http://your-server:8000 -e WORKER_NAME=worker-1 render-worker
   ```

## Environment Variables

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `SERVER_URL` | Yes | URL of the render farm server | - |
| `WORKER_NAME` | Yes | Unique name for this worker | - |
| `BLENDER_URL` | No | Custom Blender download URL | Auto-detect |

## Volume Mounts

The container uses the following volume mounts:
- `./renders:/app/renders` - Output directory for rendered frames
- `./downloads:/app/downloads` - Temporary storage for downloaded .blend files

## Custom Blender Version

To use a specific Blender version, set the `BLENDER_URL` environment variable:

```bash
# Example: Use Blender 3.6.0
export BLENDER_URL=https://download.blender.org/release/Blender3.6/blender-3.6.0-linux-x64.tar.xz

# Then run with Docker
docker run -e SERVER_URL=http://localhost:8000 -e WORKER_NAME=worker-1 -e BLENDER_URL=$BLENDER_URL render-worker
```

## Scaling Workers

To run multiple workers, you can scale with Docker Compose:

```bash
# Run 3 workers
docker-compose up --scale worker=3
```

Or create multiple services:

```yaml
# In docker-compose.yml
services:
  worker-1:
    build: .
    environment:
      - SERVER_URL=http://localhost:8000
      - WORKER_NAME=worker-1
    volumes:
      - ./renders:/app/renders
      - ./downloads:/app/downloads

  worker-2:
    build: .
    environment:
      - SERVER_URL=http://localhost:8000
      - WORKER_NAME=worker-2
    volumes:
      - ./renders:/app/renders
      - ./downloads:/app/downloads
```

## Troubleshooting

### Check logs
```bash
docker-compose logs worker
```

### Run with interactive shell
```bash
docker run -it --entrypoint /bin/bash render-worker
```

### Manual testing
```bash
# Test Blender installation
docker run -it render-worker python -c "import subprocess; subprocess.run(['blender', '--version'])"

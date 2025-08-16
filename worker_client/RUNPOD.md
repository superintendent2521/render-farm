# RunPod Deployment Guide

This guide shows you how to deploy the render worker on RunPod using the pre-built Docker image.

## Quick Setup

### 1. GitHub Repository Setup

1. **Create a new GitHub repository** or use an existing one
2. **Copy all files** from the `worker_client` directory to your repository
3. **Push to GitHub** - the GitHub Actions workflow will automatically build and publish the Docker image

### 2. Enable GitHub Container Registry

1. Go to your repository **Settings** → **Packages**
2. Ensure **GitHub Container Registry** is enabled
3. The image will be published at: `ghcr.io/YOUR_USERNAME/YOUR_REPO/render-worker:latest`

### 3. RunPod Deployment

#### Option A: RunPod Web Interface

1. Go to [RunPod.io](https://runpod.io)
2. Click **"Deploy"** → **"Custom Template"**
3. Use these settings:
   - **Container Image**: `ghcr.io/YOUR_USERNAME/YOUR_REPO/render-worker:latest`
   - **Environment Variables**:
     - `SERVER_URL`: Your render server URL (e.g., `http://your-server.com:8000`)
     - `WORKER_NAME`: Unique name for this worker (e.g., `runpod-worker-1`)
   - **Container Disk**: 10GB minimum
   - **Ports**: No ports needed (outbound connections only)

#### Option B: RunPod CLI

```bash
# Install RunPod CLI
npm install -g runpodctl

# Deploy worker
runpodctl create pod \
  --image ghcr.io/YOUR_USERNAME/YOUR_REPO/render-worker:latest \
  --name render-worker-1 \
  --env SERVER_URL=http://your-server.com:8000 \
  --env WORKER_NAME=runpod-worker-1 \
  --gpu 0 \
  --cpu 4 \
  --memory 8
```

## Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `SERVER_URL` | Yes | Your render farm server URL | `http://my-server.com:8000` |
| `WORKER_NAME` | Yes | Unique worker identifier | `runpod-worker-1` |
| `BLENDER_URL` | No | Custom Blender download URL | `https://download.blender.org/release/Blender4.2/blender-4.2.0-linux-x64.tar.xz` |

## GPU Support

The worker runs on CPU by default. For GPU acceleration:

1. **Select GPU-enabled instance** in RunPod
2. **Add GPU environment variables**:
   - `NVIDIA_VISIBLE_DEVICES`: `all`
   - `NVIDIA_DRIVER_CAPABILITIES`: `compute,utility`

## Scaling

Deploy multiple workers by changing the `WORKER_NAME`:

```bash
# Worker 1
runpodctl create pod \
  --image ghcr.io/YOUR_USERNAME/YOUR_REPO/render-worker:latest \
  --name render-worker-1 \
  --env SERVER_URL=http://your-server.com:8000 \
  --env WORKER_NAME=runpod-worker-1

# Worker 2
runpodctl create pod \
  --image ghcr.io/YOUR_USERNAME/YOUR_REPO/render-worker:latest \
  --name render-worker-2 \
  --env SERVER_URL=http://your-server.com:8000 \
  --env WORKER_NAME=runpod-worker-2
```

## Monitoring

### Check worker logs
```bash
runpodctl logs <pod-id>
```

### List running pods
```bash
runpodctl get pods
```

## Troubleshooting

### Image not found
- Ensure your GitHub Actions workflow has completed successfully
- Check that the image is published at: `https://github.com/YOUR_USERNAME/YOUR_REPO/pkgs/container/render-worker`

### Connection issues
- Verify `SERVER_URL` is accessible from RunPod
- Check firewall settings on your render server
- Ensure your server accepts connections from RunPod IPs

### Storage issues
- Increase container disk size if downloads fail
- Workers automatically clean up after each job

## Example Repository Structure

```
your-repo/
├── .github/
│   └── workflows/
│       └── docker-build.yml
├── Dockerfile
├── worker.py
├── entrypoint.sh
├── README.md
├── RUNPOD.md
└── runpod-template.yml
```

## Quick Start Checklist

- [ ] Create GitHub repository
- [ ] Push all files to repository
- [ ] Wait for GitHub Actions to build image
- [ ] Deploy on RunPod with your server URL
- [ ] Monitor worker logs
- [ ] Scale with additional workers

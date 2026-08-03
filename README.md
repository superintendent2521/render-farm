# Blend Farm

Blend Farm is a small, self-hosted Blender render farm. A central web server owns the queue and artifacts; authenticated Windows or Linux workers pull one frame, render it, upload the result, and ask for another.

## What is included

- Single-administrator FastAPI dashboard with job controls, previews, worker enrollment, and ZIP results.
- Atomic frame leases, 15-second heartbeats, 60-second expiry, cancellation, and three-attempt retry policy.
- Resumable 32 MiB local uploads or direct S3-compatible multipart transfers.
- Safe ZIP validation and checksum-addressed worker caches.
- A worker CLI that installs one checksum-verified official Blender build at a time.
- Docker Compose deployment behind Nginx, either directly with Certbot or through Cloudflare Tunnel.

## Direct VPS deployment

Requirements: Docker with Compose, a public server, a DNS A/AAAA record, and ports 80/443 open.

```bash
cp .env.direct.example .env
# Replace every placeholder in .env.
docker compose --profile direct up -d --build
```

Nginx creates a short-lived fallback certificate so it can answer the initial ACME challenge. Certbot obtains the real certificate, renews it twice daily, and Nginx detects certificate changes within five minutes. Visit the `PUBLIC_URL` configured in `.env`.

Back up the `farm-data` and `letsencrypt` Docker volumes. Do not run more than one application process against SQLite.

## Cloudflare Tunnel deployment

Create a remotely managed tunnel in Cloudflare Zero Trust. Add a public hostname whose service is `http://nginx-tunnel:80`, then copy its token.

```bash
cp .env.cloudflare.example .env
# Set PUBLIC_URL, CLOUDFLARE_TUNNEL_TOKEN, admin password, and secret key.
docker compose --profile cloudflare up -d --build
```

No router ports are opened: `cloudflared` makes the outbound connection. The local fallback is `https://127.0.0.1:8443` by default and uses a self-signed certificate. Set `LAN_BIND=0.0.0.0` only when you intentionally want other trusted LAN devices to reach it.

Cloudflare Access can protect browser routes, but configure a bypass for `/api/v1/worker/*`; those endpoints still require revocable worker credentials and active lease tokens. The dashboard itself always requires the Blend Farm administrator login.

Large local-storage uploads are split into 32 MiB requests. S3 uploads bypass the tunnel via presigned URLs.

## S3-compatible storage

Append the values from `.env.s3.example` to the selected `.env` and set `STORAGE_BACKEND=s3`. The bucket must already exist. For browser uploads, its CORS policy must allow `PUT` from `PUBLIC_URL`, allow the `ETag` response header to be read, and allow the headers required by your S3 provider. Credentials need multipart upload, get, put, list, and delete permissions limited to this bucket.

Local storage is the default and needs no additional service. Projects and outputs are retained until a job is explicitly deleted, so monitor the storage figure on the dashboard.

## Install and enroll a worker

For Google Colab, open [the ready-to-run worker notebook](notebooks/colab_worker.ipynb) or launch it directly after pushing this repository:

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/superintendent2521/render-farm/blob/main/notebooks/colab_worker.ipynb)

Select a GPU runtime, enter a unique worker name, and run its cells in order. Each Colab runtime requires its own one-time enrollment code.

Install Python 3.10 or later on Windows or Linux:

```bash
python -m venv .venv
# Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install .
```

In the dashboard, choose **Enroll**. Then run:

```bash
blend-farm-worker enroll --server https://farm.example.com --code ABC123-DEF456 --name gpu-01 --device OPTIX
blend-farm-worker doctor
blend-farm-worker run
```

Supported device choices are `AUTO`, `CPU`, `CUDA`, `OPTIX`, and `HIP`. The worker reports its configured choice; jobs do not override it. `AUTO` preserves Blender's normal device behavior. Workers render five consecutive frames per Blender launch by default; use `--batch-size 1..20` during enrollment (or `BATCH_SIZE` in the Colab notebook) to tune the balance between scene-loading overhead and redistribution latency.

The configuration and credential are saved with user-only permissions where the platform supports them. Projects are cached by SHA-256 and evicted least-recently-used when the configured cache limit is exceeded. Each process renders one frame at once; run separately enrolled worker instances to use multiple GPUs concurrently.

### Run continuously on Linux

Copy [deploy/blend-farm-worker.service](deploy/blend-farm-worker.service), replace `YOUR_USER` and the executable path, then run:

```bash
sudo cp deploy/blend-farm-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now blend-farm-worker
```

### Run continuously on Windows

Open PowerShell as Administrator and use the included scheduled-task helper:

```powershell
.\deploy\worker-service.ps1 -Action Install -Python "C:\path\to\.venv\Scripts\python.exe"
```

The task runs `python -m renderfarm.worker run` at startup as the current user, whose enrollment configuration it uses.

## Submit a project

Pack external assets into the `.blend` where practical, then ZIP the `.blend` and its relative assets. A package must contain exactly one `.blend`; absolute paths, traversal paths, symbolic links, duplicate entries, zip bombs, and oversized expansion are rejected.

Create a job, select its inclusive frame range and PNG, JPEG, or OpenEXR output. Engine, camera, resolution, samples, and color management remain controlled by the `.blend`. Project auto-execution is disabled; the worker runs only the bundled render driver.

Failed or disconnected frames return to the queue and receive at most three attempts. A terminal job with failed frames still provides a ZIP containing successful frames and a failure manifest.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
FARM_DATA_DIR=./data SECURE_COOKIES=false uvicorn renderfarm.app:app --reload
pytest
```

For production, always replace `ADMIN_PASSWORD` and `SECRET_KEY`. Workers process trusted administrator projects but the rendering host can necessarily inspect their assets; do not enroll machines you do not trust with those assets.

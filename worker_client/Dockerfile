FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    unzip \
    tar \
    xz-utils \
    bzip2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy worker script
COPY worker.py .

# Create directories for downloads and renders
RUN mkdir -p downloads renders blender

# Install Python dependencies
RUN pip install requests

# Set environment variables
ENV SERVER_URL=""
ENV WORKER_NAME=""
ENV BLENDER_URL=""

# Create entrypoint script
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]

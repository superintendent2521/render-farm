#!/bin/bash

# Check required environment variables
if [ -z "$SERVER_URL" ]; then
    echo "Error: SERVER_URL environment variable is required"
    exit 1
fi

if [ -z "$WORKER_NAME" ]; then
    echo "Error: WORKER_NAME environment variable is required"
    exit 1
fi

# Build command
CMD="python worker.py --server $SERVER_URL --name $WORKER_NAME"

# Add optional blender path if provided via BLENDER_URL
if [ -n "$BLENDER_URL" ]; then
    echo "Using custom Blender URL: $BLENDER_URL"
    export CUSTOM_BLENDER_URL=$BLENDER_URL
fi

# Execute the worker
exec $CMD

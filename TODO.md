# Render Farm Task Implementation

## Requirements
- FastAPI API that provides:
  - URL to download a blend file
  - Frame start
  - Frame end
- Serve blend files from a static directory
- Remove jobs once processed to prevent duplicate work
- Watch a folder called "jobs"
- Each job in its own folder with:
  - A blend file
  - An info.txt file with format:
    ```
    framestart:1
    frameend:250
    ```

## Implementation Plan

- [x] Create jobs directory structure
- [x] Implement job watching functionality
- [x] Create endpoint to serve job information
- [x] Implement static file serving for blend files
- [x] Add job removal after processing

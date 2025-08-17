# Render Farm Scripts

This repository contains two Python scripts for handling file transfers in a render farm setup:

1. `server.py` - A FastAPI server that receives files and stores them in the `out` directory
2. `client.py` - A script that sends files from the `in` directory to the server

## Setup

1. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage

### Starting the Server

Run the server script:
```
python server.py
```

The server will start on `http://localhost:8000` and create an `out` directory to store received files.

### Using the Client

Place files you want to send in the `in` directory, then run:
```
python client.py
```

To create sample files for testing:
```
python client.py --create-samples
```

## API Endpoints

- `GET /` - Health check endpoint
- `POST /upload/` - Upload a single file
- `POST /upload-multiple/` - Upload multiple files

## File Structure

- `in/` - Directory where client reads files from
- `out/` - Directory where server stores received files
- `server.py` - FastAPI server implementation
- `client.py` - Client script for sending files
- `requirements.txt` - Python dependencies

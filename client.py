import requests
import os
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Server URL - adjust as needed
SERVER_URL = "http://localhost:8000"

class FileHandler(FileSystemEventHandler):
    """
    Handler for file system events
    """
    def on_created(self, event):
        """
        Handle file creation events
        """
        if not event.is_directory:
            # Add a small delay to ensure file is completely written
            time.sleep(0.1)
            self.process_file(event.src_path)
    
    def process_file(self, file_path):
        """
        Process a file by uploading it and then deleting it
        """
        print(f"New file detected: {file_path}")
        result = send_file_to_server(file_path)
        print(f"Upload result: {result}")
        
        # Delete the file only if upload was successful
        if "error" not in result:
            try:
                os.remove(file_path)
                print(f"File {file_path} deleted after successful upload")
            except Exception as e:
                print(f"Error deleting file {file_path}: {e}")
        else:
            print(f"File {file_path} not deleted due to upload error")

def send_file_to_server(file_path):
    """
    Send a single file to the server
    """
    try:
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f)}
            response = requests.post(f"{SERVER_URL}/upload/", files=files)
            return response.json()
    except Exception as e:
        return {"error": str(e)}

def send_all_files_in_directory(directory_path="in"):
    """
    Send all files in the specified directory to the server
    """
    directory = Path(directory_path)
    if not directory.exists():
        print(f"Directory {directory_path} does not exist")
        return
    
    files_sent = 0
    for file_path in directory.iterdir():
        if file_path.is_file():
            print(f"Sending {file_path.name}...")
            result = send_file_to_server(file_path)
            print(f"Result: {result}")
            if "error" not in result:
                files_sent += 1
            time.sleep(0.1)  # Small delay between requests
    
    print(f"Sent {files_sent} files to server")

def create_sample_files():
    """
    Create some sample files in the 'in' directory for testing
    """
    os.makedirs("in", exist_ok=True)
    
    sample_files = {
        "sample1.txt": "This is sample file 1",
        "sample2.txt": "This is sample file 2",
        "sample3.json": '{"name": "sample", "value": 42}'
    }
    
    for filename, content in sample_files.items():
        file_path = os.path.join("in", filename)
        with open(file_path, "w") as f:
            f.write(content)
        print(f"Created sample file: {file_path}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--create-samples":
        create_sample_files()
    else:
        # Set up file watcher
        watch_directory = "in"
        os.makedirs(watch_directory, exist_ok=True)
        
        event_handler = FileHandler()
        observer = Observer()
        observer.schedule(event_handler, watch_directory, recursive=False)
        observer.start()
        
        print(f"Watching directory '{watch_directory}' for new files...")
        print("Press Ctrl+C to stop.")
        
        try:
            # Process any existing files in the directory first
            send_all_files_in_directory(watch_directory)
            
            # Keep watching for new files
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping file watcher...")
            observer.stop()
        except Exception as e:
            print(f"Error: {e}")
            observer.stop()
        finally:
            observer.join()

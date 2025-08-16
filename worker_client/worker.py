import requests
import time
import os
import subprocess
import json
import platform
import zipfile
import tarfile
from typing import List, Dict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RenderWorker:
    def __init__(self, server_url: str, worker_name: str, blender_path: str = None):
        self.server_url = server_url.rstrip('/')
        self.worker_name = worker_name
        self.blender_path = blender_path or self._get_blender_path()
        self.worker_id = None
        
    def _get_blender_path(self) -> str:
        """Get the path to Blender executable, downloading if necessary."""
        # First, check if Blender is already in PATH
        try:
            subprocess.run(["blender", "--version"], capture_output=True, check=True)
            return "blender"
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
            
        # Check for local Blender installation
        local_blender = self._find_local_blender()
        if local_blender:
            return local_blender
            
        # Download and install Blender
        return self._download_and_install_blender()
    
    def _find_local_blender(self) -> str:
        """Find locally installed Blender."""
        system = platform.system()
        
        if system == "Windows":
            # Common Windows installation paths
            paths = [
                os.path.expandvars(r"%PROGRAMFILES%\Blender Foundation\Blender\blender.exe"),
                os.path.expandvars(r"%PROGRAMFILES(X86)%\Blender Foundation\Blender\blender.exe"),
                os.path.join(os.getcwd(), "blender", "blender.exe")
            ]
        elif system == "Darwin":  # macOS
            paths = [
                "/Applications/Blender.app/Contents/MacOS/Blender",
                os.path.join(os.getcwd(), "blender", "Blender")
            ]
        else:  # Linux
            paths = [
                "/usr/bin/blender",
                "/usr/local/bin/blender",
                os.path.expanduser("~/blender/blender"),
                os.path.join(os.getcwd(), "blender", "blender")
            ]
            
        for path in paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
                
        return None
    
    def _download_and_install_blender(self) -> str:
        """Download and install the latest Blender version."""
        logger.info("Downloading latest Blender version...")
        
        system = platform.system()
        arch = platform.machine()
        
        # Get latest version info
        try:
            response = requests.get("https://www.blender.org/download/")
            response.raise_for_status()
            
            # Parse download links based on OS
            if system == "Windows":
                if "64" in arch or "AMD64" in arch:
                    download_url = self._get_windows_download_url(response.text)
                else:
                    raise Exception("32-bit Windows not supported")
            elif system == "Darwin":
                download_url = self._get_macos_download_url(response.text)
            else:  # Linux
                download_url = self._get_linux_download_url(response.text)
                
            if not download_url:
                raise Exception("Could not find download URL")
                
        except Exception as e:
            logger.error(f"Failed to get download URL: {e}")
            # Fallback to known stable URLs
            download_url = self._get_fallback_download_url(system, arch)
            
        # Download and extract
        return self._download_and_extract_blender(download_url, system)
    
    def _get_windows_download_url(self, html: str) -> str:
        """Extract Windows download URL from HTML."""
        import re
        match = re.search(r'href="([^"]*windows-x64\.zip)"', html)
        if match:
            url = match.group(1)
            if not url.startswith("http"):
                url = "https://www.blender.org" + url
            return url
        return None
    
    def _get_macos_download_url(self, html: str) -> str:
        """Extract macOS download URL from HTML."""
        import re
        match = re.search(r'href="([^"]*macos-\d+\.\d+\.\d+\.dmg)"', html)
        if match:
            url = match.group(1)
            if not url.startswith("http"):
                url = "https://www.blender.org" + url
            return url
        return None
    
    def _get_linux_download_url(self, html: str) -> str:
        """Extract Linux download URL from HTML."""
        import re
        match = re.search(r'href="([^"]*linux-x64\.tar\.xz)"', html)
        if match:
            url = match.group(1)
            if not url.startswith("http"):
                url = "https://www.blender.org" + url
            return url
        return None
    
    def _get_fallback_download_url(self, system: str, arch: str) -> str:
        """Get fallback download URL based on system."""
        base_url = "https://download.blender.org/release/Blender4.2/"
        
        if system == "Windows":
            return base_url + "blender-4.2.0-windows-x64.zip"
        elif system == "Darwin":
            return base_url + "blender-4.2.0-macos-x64.dmg"
        else:  # Linux
            return base_url + "blender-4.2.0-linux-x64.tar.xz"
    
    def _download_and_extract_blender(self, download_url: str, system: str) -> str:
        """Download and extract Blender."""
        blender_dir = os.path.join(os.getcwd(), "blender")
        os.makedirs(blender_dir, exist_ok=True)
        
        filename = os.path.basename(download_url)
        local_path = os.path.join(blender_dir, filename)
        
        # Download file
        logger.info(f"Downloading Blender from {download_url}")
        response = requests.get(download_url, stream=True)
        response.raise_for_status()
        
        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # Extract based on file type
        if filename.endswith('.zip'):
            with zipfile.ZipFile(local_path, 'r') as zip_ref:
                zip_ref.extractall(blender_dir)
        elif filename.endswith(('.tar.xz', '.tar.gz', '.tar.bz2')):
            with tarfile.open(local_path, 'r:*') as tar_ref:
                tar_ref.extractall(blender_dir)
        elif filename.endswith('.dmg') and system == "Darwin":
            # For macOS, we need to mount and copy the app
            logger.info("Please install the downloaded .dmg file manually")
            return "/Applications/Blender.app/Contents/MacOS/Blender"
        
        # Clean up downloaded file
        os.remove(local_path)
        
        # Find extracted Blender executable
        for root, dirs, files in os.walk(blender_dir):
            for file in files:
                if file.lower() == "blender" or file.lower() == "blender.exe":
                    blender_path = os.path.join(root, file)
                    if os.access(blender_path, os.X_OK) or system == "Windows":
                        return blender_path
        
        raise Exception("Could not find Blender executable after extraction")
    
    def register(self):
        """Register this worker with the server."""
        try:
            response = requests.post(
                f"{self.server_url}/workers/",
                json={"name": self.worker_name}
            )
            response.raise_for_status()
            data = response.json()
            self.worker_id = data["id"]
            logger.info(f"Registered worker with ID: {self.worker_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to register worker: {e}")
            return False
    
    def send_heartbeat(self):
        """Send heartbeat to server."""
        if not self.worker_id:
            return False
        
        try:
            response = requests.post(
                f"{self.server_url}/workers/{self.worker_id}/heartbeat"
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}")
            return False
    
    def poll_for_job(self) -> Dict:
        """Poll server for available job."""
        if not self.worker_id:
            return {}
        
        try:
            response = requests.get(
                f"{self.server_url}/workers/poll_job/{self.worker_id}"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to poll for job: {e}")
            return {}
    
    def download_file(self, url: str, local_path: str) -> bool:
        """Download file from server."""
        try:
            response = requests.get(f"{self.server_url}{url}", stream=True)
            response.raise_for_status()
            
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            logger.error(f"Failed to download file: {e}")
            return False
    
    def upload_frame(self, job_id: int, frame_number: int, file_path: str) -> bool:
        """Upload completed frame to server."""
        try:
            with open(file_path, 'rb') as f:
                files = {'file': f}
                response = requests.post(
                    f"{self.server_url}/jobs/{job_id}/upload_frame/{frame_number}",
                    files=files
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Failed to upload frame: {e}")
            return False
    
    def render_frame(self, blend_file: str, frame: int, output_dir: str, 
                    output_format: str = "PNG", scene_name: str = None) -> str:
        """Render a single frame using Blender."""
        os.makedirs(output_dir, exist_ok=True)
        
        output_file = os.path.join(output_dir, f"frame_{frame:04d}.{output_format.lower()}")
        
        cmd = [
            self.blender_path,
            "-b", blend_file,
            "-f", str(frame),
            "-o", os.path.join(output_dir, "frame_####"),
            "-F", output_format.upper()
        ]
        
        if scene_name:
            cmd.extend(["-S", scene_name])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                return output_file
            else:
                logger.error(f"Blender render failed: {result.stderr}")
                return None
        except subprocess.TimeoutExpired:
            logger.error("Render timeout")
            return None
        except Exception as e:
            logger.error(f"Render error: {e}")
            return None
    
    def run(self):
        """Main worker loop."""
        if not self.register():
            return
        
        logger.info("Worker started, waiting for jobs...")
        
        while True:
            try:
                # Send heartbeat
                self.send_heartbeat()
                
                # Poll for job
                job_assignment = self.poll_for_job()
                
                if job_assignment.get("job_id"):
                    job_id = job_assignment["job_id"]
                    frame_ranges = job_assignment["frame_ranges"]
                    blender_url = job_assignment["blender_file_url"]
                    output_format = job_assignment["output_format"]
                    scene_name = job_assignment.get("scene_name")
                    
                    logger.info(f"Received job {job_id} with frames {frame_ranges}")
                    
                    # Download blender file
                    blend_file = os.path.join("downloads", f"job_{job_id}.blend")
                    if not self.download_file(blender_url, blend_file):
                        continue
                    
                    # Process each frame range
                    for frame_range in frame_ranges:
                        start_frame = frame_range["start"]
                        end_frame = frame_range["end"]
                        
                        for frame in range(start_frame, end_frame + 1):
                            logger.info(f"Rendering frame {frame} for job {job_id}")
                            
                            # Render frame
                            output_dir = os.path.join("renders", f"job_{job_id}")
                            rendered_file = self.render_frame(
                                blend_file, 
                                frame, 
                                output_dir,
                                output_format,
                                scene_name
                            )
                            
                            if rendered_file and os.path.exists(rendered_file):
                                # Upload completed frame
                                if self.upload_frame(job_id, frame, rendered_file):
                                    logger.info(f"Successfully uploaded frame {frame}")
                                else:
                                    logger.error(f"Failed to upload frame {frame}")
                                
                                # Clean up local file
                                os.remove(rendered_file)
                            else:
                                logger.error(f"Failed to render frame {frame}")
                
                else:
                    logger.debug("No jobs available, waiting...")
                
                time.sleep(5)  # Poll every 5 seconds
                
            except KeyboardInterrupt:
                logger.info("Worker stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
                time.sleep(10)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Render Farm Worker")
    parser.add_argument("--server", required=True, help="Server URL")
    parser.add_argument("--name", required=True, help="Worker name")
    parser.add_argument("--blender", help="Blender executable path (optional)")
    
    args = parser.parse_args()
    
    worker = RenderWorker(args.server, args.name, args.blender)
    worker.run()

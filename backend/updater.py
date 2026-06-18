import json
import logging
import os
import platform
import stat
import sys
import threading
import urllib.request
import urllib.error
import zipfile
import subprocess
import tempfile

logger = logging.getLogger("AuraPresenter.Updater")

GITHUB_REPO = "jbam303/AuraPresenter"
CURRENT_VERSION = "v1.0.0"

def get_executable_path():
    """Return the path of the actual executable."""
    if getattr(sys, 'frozen', False):
        return sys.executable
    return None

def check_for_updates():
    """Check GitHub for a new release and update if found."""
    exe_path = get_executable_path()
    if not exe_path:
        logger.info("Running in dev mode. Skipping auto-update.")
        return

    logger.info(f"Checking for updates. Current version: {CURRENT_VERSION}")
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    
    try:
        req = urllib.request.Request(api_url, headers={'User-Agent': 'AuraPresenter-Updater'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            
        latest_version = data.get("tag_name")
        if latest_version and latest_version != CURRENT_VERSION:
            logger.info(f"New version found: {latest_version}. Downloading...")
            _download_and_apply_update(data.get("assets", []), exe_path)
        else:
            logger.info("AuraPresenter is up to date.")
            
    except urllib.error.URLError as e:
        logger.warning(f"Failed to check for updates: {e}")
    except Exception as e:
        logger.error(f"Error checking for updates: {e}")

def _download_and_apply_update(assets, exe_path):
    """Download the asset and swap executables using OS-specific scripts."""
    system = platform.system().lower()
    asset_url = None
    is_mac = system == "darwin"
    
    try:
        temp_dir = tempfile.mkdtemp(prefix="aurapresenter_update_")
        download_path = os.path.join(temp_dir, "update_file.zip")
        
        logger.info(f"Downloading from {asset_url} to {download_path}...")
        req = urllib.request.Request(asset_url, headers={'User-Agent': 'AuraPresenter-Updater'})
        with urllib.request.urlopen(req) as response, open(download_path, 'wb') as out_file:
            out_file.write(response.read())

        # Extract ZIP for all platforms
        with zipfile.ZipFile(download_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # Find the .app folder (Mac) or the AuraPresenter folder (Windows/Linux)
        app_folder = None
        for item in os.listdir(temp_dir):
            if is_mac and item.endswith(".app"):
                app_folder = os.path.join(temp_dir, item)
                break
            elif not is_mac and os.path.isdir(os.path.join(temp_dir, item)) and "aurapresenter" in item.lower():
                app_folder = os.path.join(temp_dir, item)
                break
                
        if not app_folder:
            raise Exception("No valid app folder found inside the downloaded zip.")
            
        if is_mac:
            # exe_path is typically /Applications/AuraPresenter.app/Contents/MacOS/AuraPresenter
            current_app_bundle = os.path.dirname(os.path.dirname(os.path.dirname(exe_path)))
            script_path = os.path.join(temp_dir, "update.sh")
            with open(script_path, "w") as f:
                f.write(f'''#!/bin/bash
sleep 2
rm -rf "{current_app_bundle}"
mv "{app_folder}" "{current_app_bundle}"
xattr -rc "{current_app_bundle}" 2>/dev/null || true
open "{current_app_bundle}"
rm -rf "{temp_dir}"
''')
            os.chmod(script_path, stat.S_IRWXU)
            logger.info("Update ready. Restarting application...")
            subprocess.Popen([script_path], start_new_session=True)
            sys.exit(0)
            
        else:
            # Windows / Linux: exe_path is AuraPresenter/AuraPresenter.exe
            current_app_bundle = os.path.dirname(exe_path)
            
            if system == "windows":
                script_path = os.path.join(temp_dir, "update.bat")
                with open(script_path, "w") as f:
                    f.write(f'''@echo off
timeout /t 2 /nobreak > nul
rmdir /s /q "{current_app_bundle}"
move /y "{app_folder}" "{current_app_bundle}"
start "" "{exe_path}"
rmdir /s /q "{temp_dir}"
''')
                logger.info("Update ready. Restarting application...")
                subprocess.Popen([script_path], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                sys.exit(0)
            else:
                # Linux
                script_path = os.path.join(temp_dir, "update.sh")
                with open(script_path, "w") as f:
                    f.write(f'''#!/bin/bash
sleep 2
rm -rf "{current_app_bundle}"
mv "{app_folder}" "{current_app_bundle}"
"{exe_path}" &
rm -rf "{temp_dir}"
''')
                os.chmod(script_path, stat.S_IRWXU)
                logger.info("Update ready. Restarting application...")
                subprocess.Popen([script_path], start_new_session=True)
                sys.exit(0)

    except Exception as e:
        logger.error(f"Failed to apply update: {e}")

def start_update_thread():
    """Start the update check in a background thread."""
    t = threading.Thread(target=check_for_updates, daemon=True)
    t.start()

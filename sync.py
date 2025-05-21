import os
import sys
import argparse
import logging
import requests
import shutil
from pathlib import Path
from mutagen import File as MutagenFile

def get_config():
    parser = argparse.ArgumentParser(description="Sync media from ytdl-material and update Plex.")

    parser.add_argument("--ytdl-url", default=os.getenv("YTDL_URL"),
                        help="Base URL of the ytdl-material instance")
    parser.add_argument("--plex-url", default=os.getenv("PLEX_URL"),
                        help="Base URL of Plex server")
    parser.add_argument("--plex-token", default=os.getenv("PLEX_TOKEN"),
                        help="Authentication token for Plex")
    parser.add_argument("--plex-section-id", default=os.getenv("PLEX_MUSIC_SECTION_ID"),
                        help="Plex library section ID for music")
    parser.add_argument("--download-dir", default=os.getenv("LOCAL_DOWNLOAD_DIR", "/music"),
                        help="Directory to store synced media")
    parser.add_argument("--log-path", default=os.getenv("LOG_PATH", None),
                        help="Path to log file (optional, logs to stdout if not set)")
    parser.add_argument("--lock-path", default=os.getenv("LOCK_FILE_PATH", "/tmp/ytdl_sync.lock"),
                        help="Path to lock file")
    parser.add_argument("--ytdl-username", default=os.getenv("YTDL_USERNAME"),
                        help="YTDL-Material username")
    parser.add_argument("--ytdl-password", default=os.getenv("YTDL_PASSWORD"),
                        help="YTDL-Material password")
    args = parser.parse_args()

    missing = []
    for req in ["ytdl_url", "plex_url", "plex_token", "plex_section_id"]:
        if not getattr(args, req):
            missing.append(req)

    if missing:
        parser.error(f"Missing required arguments or environment variables: {', '.join(missing)}")

    if (args.ytdl_username is None) or (args.ytdl_password is None):
        logging.warning("No YTDL username/password provided, will attempt unauthenticated sync (all files).")

    return args

def setup_logging(log_path):
    if log_path:
        log_dir = Path(log_path).parent
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            handlers = [
                logging.FileHandler(log_path),
                logging.StreamHandler(sys.stdout)
            ]
        except Exception as e:
            print(f"Warning: Could not create log directory {log_dir}, logging only to stdout. Error: {e}")
            handlers = [logging.StreamHandler(sys.stdout)]
    else:
        handlers = [logging.StreamHandler(sys.stdout)]

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=handlers
    )

def acquire_lock(lock_path):
    if os.path.isdir(lock_path):
        logging.error(f"Lock path '{lock_path}' is a directory, not a file. Exiting.")
        sys.exit(1)

    if os.path.exists(lock_path):
        logging.warning("Lock file exists. Another sync may be in progress. Exiting.")
        sys.exit(0)

    with open(lock_path, 'w') as f:
        f.write(str(os.getpid()))

def release_lock(lock_path):
    if os.path.exists(lock_path):
        os.remove(lock_path)

def login_ytdl(base_url, username, password):
    login_url = f"{base_url}/api/auth/login"
    try:
        response = requests.post(login_url, json={"username": username, "password": password})
        response.raise_for_status()
        token = response.json().get('token')
        if not token:
            logging.error("No token received from YTDL login response")
            sys.exit(1)
        logging.info(f"Authenticated with YTDL as '{username}'")
        return token
    except requests.RequestException as e:
        logging.error(f"Failed to authenticate with YTDL: {e}")
        sys.exit(1)

def fetch_ytdl_files(base_url, token=None):
    url = f"{base_url}/api/files"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logging.error(f"Failed to contact YTDL API: {e}")
        sys.exit(1)

def download_and_delete_files(base_url, files, download_dir, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for file in files:
        filename = file.get('filename') or file.get('title') or file.get('id')
        if not filename:
            logging.warning(f"Skipping file with missing filename/id: {file}")
            continue

        download_url = f"{base_url}/api/download/{file['uid']}"
        try:
            with requests.get(download_url, headers=headers, stream=True) as r:
                r.raise_for_status()
                dest = Path(download_dir) / filename
                with open(dest, 'wb') as f:
                    shutil.copyfileobj(r.raw, f)
            logging.info(f"Downloaded {filename}")

            tag_file(dest)

            del_url = f"{base_url}/api/files/{file['uid']}"
            del_resp = requests.delete(del_url, headers=headers)
            del_resp.raise_for_status()
            logging.info(f"Deleted {filename} from YTDL")
        except Exception as e:
            logging.error(f"Failed processing file '{filename}': {e}")

def tag_file(file_path):
    try:
        audio = MutagenFile(file_path, easy=True)
        if audio is None:
            logging.warning(f"Cannot read audio metadata for {file_path.name}")
            return
        # Placeholder: musicbrainz tagging logic can be added here
        audio.save()
    except Exception as e:
        logging.warning(f"Failed to tag {file_path.name}: {e}")

def trigger_plex_scan(plex_url, token, section_id):
    try:
        url = f"{plex_url}/library/sections/{section_id}/refresh?X-Plex-Token={token}"
        resp = requests.get(url)
        resp.raise_for_status()
        logging.info("Triggered Plex scan")
    except requests.RequestException as e:
        logging.error(f"Failed to contact Plex: {e}")
        sys.exit(1)

def main():
    args = get_config()
    setup_logging(args.log_path)
    acquire_lock(args.lock_path)

    try:
        Path(args.download_dir).mkdir(parents=True, exist_ok=True)

        jwt_token = None
        if args.ytdl_username and args.ytdl_password:
            jwt_token = login_ytdl(args.ytdl_url, args.ytdl_username, args.ytdl_password)
        else:
            logging.info("No YTDL credentials provided, attempting unauthenticated access")

        files = fetch_ytdl_files(args.ytdl_url, jwt_token)

        if not files:
            logging.info("No files to sync")
        else:
            download_and_delete_files(args.ytdl_url, files, args.download_dir, jwt_token)
            trigger_plex_scan(args.plex_url, args.plex_token, args.plex_section_id)

        logging.info("Sync completed")
    finally:
        release_lock(args.lock_path)

if __name__ == '__main__':
    main()

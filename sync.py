#!/usr/bin/env python3

import os
import sys
import argparse
import logging
import requests
import shutil
import tempfile
import fcntl

from pathlib import Path

LOCKFILE = '/tmp/ytdl_sync.lock'

def setup_logging(log_path=None):
    log_handlers = [logging.StreamHandler(sys.stdout)]
    if log_path:
        try:
            log_dir = Path(log_path).parent
            log_dir.mkdir(parents=True, exist_ok=True)
            log_handlers.append(logging.FileHandler(log_path))
        except Exception as e:
            print(f"Warning: could not open log file {log_path} for writing: {e}")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s',
        handlers=log_handlers
    )


def obtain_lock(lockfile_path=LOCKFILE):
    # If the lockfile path exists but is a directory, error out
    if os.path.exists(lockfile_path) and os.path.isdir(lockfile_path):
        logging.error(f"Lockfile path {lockfile_path} is a directory. Please remove or rename it.")
        sys.exit(1)

    lockfile = open(lockfile_path, 'a+')
    try:
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lockfile
    except IOError:
        logging.error("Another instance is running. Exiting.")
        sys.exit(1)


class YTDLMaterialAPI:
    def __init__(self, base_url, api_key, username=None, password=None):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.username = username
        self.password = password
        self.jwt_token = None
        self.session = requests.Session()

        if self.username and self.password:
            self._login()

    def _login(self):
        auth_url = f"{self.base_url}/api/auth/login"
        params = {'api_key': self.api_key}
        payload = {
            "username": self.username,
            "password": self.password
        }
        try:
            r = self.session.post(auth_url, params=params, json=payload, timeout=10)
            r.raise_for_status()
            data = r.json()
            self.jwt_token = data.get('token')
            if not self.jwt_token:
                logging.error("Login succeeded but no token received.")
                sys.exit(1)
            logging.info(f"Obtained JWT token for user '{self.username}'")
        except requests.RequestException as e:
            logging.error(f"Failed to login to YTDL Material API: {e}")
            sys.exit(1)

    def _headers(self):
        headers = {}
        if self.jwt_token:
            headers['Authorization'] = f"Bearer {self.jwt_token}"
        return headers

    def list_files(self, user=None):
        url = f"{self.base_url}/api/files"
        params = {'api_key': self.api_key}
        if user:
            params['user'] = user
        try:
            r = self.session.get(url, params=params, headers=self._headers(), timeout=15)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            logging.error(f"Failed to list files from YTDL Material API: {e}")
            sys.exit(1)

    def download_file(self, file_id, dest_path):
        url = f"{self.base_url}/api/files/{file_id}/download"
        params = {'api_key': self.api_key}
        try:
            with self.session.get(url, params=params, headers=self._headers(), stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(dest_path, 'wb') as f:
                    shutil.copyfileobj(r.raw, f)
            logging.info(f"Downloaded file ID {file_id} to {dest_path}")
        except requests.RequestException as e:
            logging.error(f"Failed to download file {file_id}: {e}")
            sys.exit(1)

    def delete_file(self, file_id):
        url = f"{self.base_url}/api/files/{file_id}"
        params = {'api_key': self.api_key}
        try:
            r = self.session.delete(url, params=params, headers=self._headers(), timeout=10)
            r.raise_for_status()
            logging.info(f"Deleted file ID {file_id} from YTDL Material")
        except requests.RequestException as e:
            logging.error(f"Failed to delete file {file_id}: {e}")
            sys.exit(1)


class PlexAPI:
    def __init__(self, base_url, token, library_section_id):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.library_section_id = library_section_id
        self.session = requests.Session()

    def trigger_library_scan(self):
        url = f"{self.base_url}/library/sections/{self.library_section_id}/refresh"
        headers = {
            'X-Plex-Token': self.token
        }
        try:
            r = self.session.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            logging.info("Triggered Plex library scan successfully")
        except requests.RequestException as e:
            logging.error(f"Failed to trigger Plex library scan: {e}")
            sys.exit(1)


def rename_and_organize_file(src_path, dest_dir):
    # Placeholder for MusicBrainz tagging and renaming logic
    # For now, just move the file to dest_dir preserving the filename
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / Path(src_path).name
    shutil.move(src_path, dest_path)
    logging.info(f"Moved file to {dest_path}")
    return dest_path


def main():
    parser = argparse.ArgumentParser(description="Sync files from YTDL Material and optionally trigger Plex library scan")
    parser.add_argument('--ytdl-url', default=os.getenv('YTDL_URL'), help='Base URL of YTDL Material API')
    parser.add_argument('--ytdl-api-key', default=os.getenv('YTDL_API_KEY'), help='YTDL Material API key')
    parser.add_argument('--ytdl-user', default=os.getenv('YTDL_USER'), help='YTDL Material username to authenticate as (optional)')
    parser.add_argument('--ytdl-password', default=os.getenv('YTDL_PASSWORD'), help='YTDL Material password for user (optional)')
    parser.add_argument('--plex-url', default=os.getenv('PLEX_URL'), help='Base URL of Plex server')
    parser.add_argument('--plex-token', default=os.getenv('PLEX_TOKEN'), help='Plex token')
    parser.add_argument('--plex-music-section-id', default=os.getenv('PLEX_MUSIC_SECTION_ID'), help='Plex Music library section ID')
    parser.add_argument('--download-dir', default=os.getenv('DOWNLOAD_DIR', '/data'), help='Directory to store downloaded files')
    parser.add_argument('--lock-file', default=os.getenv('LOCK_FILE', LOCKFILE), help='Path to lock file')
    parser.add_argument('--log-path', default=os.getenv('LOG_PATH'), help='Path to log file (optional)')
    args = parser.parse_args()

    if not args.ytdl_url or not args.ytdl_api_key:
        print("YTDL URL and API key must be specified via args or environment variables.")
        sys.exit(1)

    if (args.ytdl_user and not args.ytdl_password) or (args.ytdl_password and not args.ytdl_user):
        print("Both YTDL user and password must be specified to authenticate as a user.")
        sys.exit(1)

    if args.plex_url or args.plex_token or args.plex_music_section_id:
        if not (args.plex_url and args.plex_token and args.plex_music_section_id):
            print("If any Plex argument is specified, all Plex arguments must be specified.")
            sys.exit(1)

    setup_logging(args.log_path)

    lockfile = obtain_lock(args.lock_file)

    ytdl = YTDLMaterialAPI(
        base_url=args.ytdl_url,
        api_key=args.ytdl_api_key,
        username=args.ytdl_user,
        password=args.ytdl_password
    )

    plex = None
    if args.plex_url and args.plex_token and args.plex_music_section_id:
        plex = PlexAPI(args.plex_url, args.plex_token, args.plex_music_section_id)

    files = ytdl.list_files(user=args.ytdl_user)
    if not files:
        logging.info("No files to sync.")
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            for f in files:
                file_id = f['id']
                filename = f['filename']
                logging.info(f"Processing file {file_id} ({filename})")

                tmp_path = os.path.join(tmpdir, filename)
                ytdl.download_file(file_id, tmp_path)

                final_path = rename_and_organize_file(tmp_path, args.download_dir)

                ytdl.delete_file(file_id)

    if plex:
        plex.trigger_library_scan()

    logging.info("Sync completed.")


if __name__ == "__main__":
    main()


#!/usr/bin/env python3

import os
import sys
import json
import time
import shutil
import logging
import argparse
import requests
from pathlib import Path
from filelock import FileLock, Timeout
from dotenv import load_dotenv

# Load .env config


def load_config():
    config_path = os.environ.get("CONFIG_PATH")
    if not config_path:
        home_env = Path.home() / ".ytdl_sync.env"
        local_env = Path(".ytdl_sync.env")
        if home_env.exists():
            config_path = home_env
        elif local_env.exists():
            config_path = local_env
    if config_path:
        load_dotenv(dotenv_path=Path(config_path))

# Setup logging


def setup_logging(log_path=None):
    handlers = [logging.StreamHandler()]
    if log_path:
        try:
            os.makedirs(Path(log_path).parent, exist_ok=True)
            handlers.append(logging.FileHandler(log_path))
        except Exception as e:
            print(f"Warning: Failed to set up file logging: {e}")
    logging.basicConfig(level=logging.INFO,
                        format='%(levelname)s:%(message)s', handlers=handlers)

# Authenticate to YTDL to get JWT token


def ytdl_authenticate(ytdl_url, username, password, api_key):
    try:
        auth_resp = requests.post(
            f"{ytdl_url}/api/auth/login",
            json={"username": username, "password": password},
            params={"apiKey": api_key}
        )
        auth_resp.raise_for_status()
        return auth_resp.json().get("token")
    except Exception as e:
        logging.error(f"Failed to authenticate with YTDL: {e}")
        return None

# Fetch file list


def fetch_file_list(ytdl_url, api_key, jwt_token):
    try:
        params = {"apiKey": api_key}
        if jwt_token:
            params["jwt"] = jwt_token
        resp = requests.get(f"{ytdl_url}/api/getMp3s", params=params)
        import ipdb
        ipdb.set_trace()
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logging.error(f"Failed to contact YTDL API: {e}")
        return None

# Download file


def download_file(url, dest_path):
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(dest_path, 'wb') as f:
            shutil.copyfileobj(r.raw, f)

# Delete file on YTDL


def delete_file(ytdl_url, file_uid, api_key, jwt_token):
    try:
        headers = {"apiKey": api_key}
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"
        resp = requests.delete(
            f"{ytdl_url}/api/files/{file_uid}", headers=headers)
        resp.raise_for_status()
    except Exception as e:
        logging.error(f"Failed to delete file {file_uid}: {e}")

# Trigger Plex rescan


def trigger_plex_rescan(plex_url, plex_token, section_id):
    try:
        url = f"{plex_url}/library/sections/{section_id}/refresh?X-Plex-Token={plex_token}"
        resp = requests.get(url)
        resp.raise_for_status()
        logging.info("Plex rescan triggered.")
    except Exception as e:
        logging.error(f"Failed to trigger Plex rescan: {e}")


def main():
    load_config()

    parser = argparse.ArgumentParser()
    parser.add_argument("--ytdl-url", default=os.environ.get("YTDL_URL"))
    parser.add_argument("--ytdl-user", default=os.environ.get("YTDL_USER"))
    parser.add_argument("--ytdl-password",
                        default=os.environ.get("YTDL_PASSWORD"))
    parser.add_argument(
        "--ytdl-api-key", default=os.environ.get("YTDL_API_KEY"))

    parser.add_argument("--plex-url", default=os.environ.get("PLEX_URL"))
    parser.add_argument("--plex-token", default=os.environ.get("PLEX_TOKEN"))
    parser.add_argument("--plex-section-id",
                        default=os.environ.get("PLEX_MUSIC_SECTION_ID"))

    parser.add_argument(
        "--download-dir", default=os.environ.get("LOCAL_DOWNLOAD_DIR", "/music"))
    parser.add_argument(
        "--lock-file", default=os.environ.get("LOCK_FILE_PATH", "/tmp/ytdl_sync.lock"))
    parser.add_argument("--log-path", default=os.environ.get("LOG_PATH"))

    args = parser.parse_args()

    setup_logging(args.log_path)

    if not args.ytdl_url or not args.ytdl_api_key:
        logging.error("YTDL URL and API key are required.")
        sys.exit(1)

    lock_path = Path(args.lock_file)
    if lock_path.exists() and lock_path.is_dir():
        logging.error(f"Lock file path {lock_path} is a directory. Exiting.")
        sys.exit(1)

    try:
        with FileLock(str(lock_path)):
            jwt_token = None
            if args.ytdl_user and args.ytdl_password:
                jwt_token = ytdl_authenticate(
                    args.ytdl_url, args.ytdl_user, args.ytdl_password, args.ytdl_api_key)
                if not jwt_token:
                    logging.error("Authentication failed, exiting.")
                    sys.exit(1)
            else:
                logging.warning(
                    "No YTDL username/password provided, will attempt unauthenticated sync (all files).")

            files = fetch_file_list(
                args.ytdl_url, args.ytdl_api_key, jwt_token)
            if files is None:
                logging.error("Unable to retrieve files, exiting.")
                sys.exit(1)

            os.makedirs(args.download_dir, exist_ok=True)

            for file in files:
                filename = file["title"]
                file_url = f"{args.ytdl_url}/api/files/download/{file['uid']}?apiKey={args.ytdl_api_key}"
                dest_path = Path(args.download_dir) / filename

                if dest_path.exists():
                    logging.info(f"File already exists: {filename}, skipping.")
                    continue

                try:
                    logging.info(f"Downloading: {filename}")
                    download_file(file_url, dest_path)
                    logging.info(f"Downloaded: {filename}")
                    delete_file(args.ytdl_url,
                                file["uid"], args.ytdl_api_key, jwt_token)
                except Exception as e:
                    logging.error(f"Error processing {filename}: {e}")

            if args.plex_url and args.plex_token and args.plex_section_id:
                trigger_plex_rescan(
                    args.plex_url, args.plex_token, args.plex_section_id)

            logging.info("Sync completed.")
    except Timeout:
        logging.warning("Another instance is running. Exiting.")


if __name__ == "__main__":
    main()

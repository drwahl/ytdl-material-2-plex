#!/usr/bin/env python3

from dotenv import load_dotenv
from filelock import FileLock, Timeout
from pathlib import Path
from pprint import pprint
from xml.dom import minidom
import argparse
import json
import logging
import os
import requests
import shutil
import sys
import time


def load_config():
    """Load .env config"""
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


def setup_logging(log_path=None):
    """Setup logging"""
    handlers = [logging.StreamHandler()]
    if log_path:
        try:
            os.makedirs(Path(log_path).parent, exist_ok=True)
            handlers.append(logging.FileHandler(log_path))
        except Exception as e:
            print(f"Warning: Failed to set up file logging: {e}")
    logging.basicConfig(level=logging.INFO,
                        format='%(levelname)s:%(message)s', handlers=handlers)


def ytdl_authenticate(ytdl_url, username, password, api_key):
    """Authenticate to YTDL to get JWT token"""
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


def fetch_file_list(ytdl_url, auth_params):
    """Fetch file list"""
    try:
        resp = requests.get(f"{ytdl_url}/api/getMp3s", params=auth_params)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logging.error(f"Failed to contact YTDL API: {e}")
        return None


def download_file(args, file, dest_path, auth_params):
    """Download file"""
    try:
        result = requests.post(
            f'{args.ytdl_url}/api/downloadFileFromServer',
            params=auth_params,
            headers={'Content-type': 'application/json'},
            json={"uid": file['uid'], "type": "audio"})
        result.raise_for_status()
        with open(dest_path, 'wb') as f:
            f.write(result.content)
    except Exception as e:
        logging.error(f"Failed to download/save file {file['uid']}: {e}")


def delete_file(args, file, auth_params):
    """Delete file on YTDL"""
    try:
        resp = requests.post(
            f"{args.ytdl_url}/api/deleteFile",
            headers={"Content-type": "application/json"},
            params=auth_params,
            json={"uid": file['uid']})
        resp.raise_for_status()
    except Exception as e:
        logging.error(f"Failed to delete file {file_uid}: {e}")


def trigger_plex_rescan(plex_url, plex_token, section_id):
    """Trigger Plex rescan"""
    try:
        url = f"{plex_url}/library/sections/{section_id}/refresh?X-Plex-Token={plex_token}"
        resp = requests.get(url)
        resp.raise_for_status()
        logging.info("Plex rescan triggered.")
    except Exception as e:
        logging.error(f"Failed to trigger Plex rescan: {e}")


def plex_list_sections(args):
    """List the sections that are registered in Plex"""
    sections = []
    try:
        url = f"{args.plex_url}/library/sections?X-Plex-Token={args.plex_token}"
        resp = requests.get(url)
        resp.raise_for_status()
    except Exception as e:
        logging.error(f"Failed to trigger Plex rescan: {e}")
        raise Exception(e)

    for sect in minidom.parseString(resp.text).getElementsByTagName('Directory'):
        sections.append({
            'Section Name': sect.getAttribute('title'),
            'Section ID': sect.getAttribute('key')})

    return sections


def main():
    load_config()

    parser = argparse.ArgumentParser()
    parser.add_argument("--ytdl-url", default=os.environ.get("YTDL_URL"))
    parser.add_argument("--ytdl-user", default=os.environ.get("YTDL_USER"))
    parser.add_argument("--ytdl-password",
                        default=os.environ.get("YTDL_PASSWORD"))
    parser.add_argument(
        "--ytdl-api-key", default=os.environ.get("YTDL_API_KEY"))
    parser.add_argument("--ytdl-cleanup-synced",
                        default=os.environ.get("YTDL_CLEANUP_SYNCED", False),
                        action='store_true')

    parser.add_argument("--plex-url", default=os.environ.get("PLEX_URL"))
    parser.add_argument("--plex-token", default=os.environ.get("PLEX_TOKEN"))
    parser.add_argument("--plex-section-id",
                        default=os.environ.get("PLEX_MUSIC_SECTION_ID"))
    parser.add_argument("--plex-list-sections",
                        default=False, action='store_true')

    parser.add_argument(
        "--download-dir", default=os.environ.get("LOCAL_DOWNLOAD_DIR", "/music"))
    parser.add_argument(
        "--lock-file", default=os.environ.get("LOCK_FILE_PATH", "/tmp/ytdl_sync.lock"))
    parser.add_argument("--log-path", default=os.environ.get("LOG_PATH"))

    args = parser.parse_args()

    setup_logging(args.log_path)

    if args.plex_list_sections:
        # if the user requested a list of sections, print and exit
        pprint(plex_list_sections(args))
        sys.exit(0)

    if not args.ytdl_url or not args.ytdl_api_key:
        logging.error("YTDL URL and API key are required.")
        sys.exit(1)

    lock_path = Path(args.lock_file)
    if lock_path.exists() and lock_path.is_dir():
        logging.error(f"Lock file path {lock_path} is a directory. Exiting.")
        sys.exit(1)

    try:
        ytdl_auth_params = {"apiKey": args.ytdl_api_key}
        with FileLock(str(lock_path)):
            if args.ytdl_user and args.ytdl_password:
                ytdl_auth_params['jwt'] = ytdl_authenticate(
                    args.ytdl_url, args.ytdl_user, args.ytdl_password, args.ytdl_api_key)
                if not ytdl_auth_params.get('jwt', False):
                    logging.error("Authentication failed, exiting.")
                    sys.exit(1)
            else:
                logging.warning(
                    "No YTDL username/password provided, will attempt unauthenticated sync (all files).")

            files = fetch_file_list(
                args.ytdl_url, ytdl_auth_params)
            if files is None:
                logging.error("Unable to retrieve files, exiting.")
                sys.exit(1)

            os.makedirs(args.download_dir, exist_ok=True)

            for file in files['mp3s']:
                filename = file["title"]
                dest_path = Path(args.download_dir) / \
                    os.path.basename(file['path'])

                if dest_path.exists():
                    logging.info(f"File already exists: {filename}, skipping.")
                    continue

                try:
                    logging.info(f"Downloading: {filename}")
                    download_file(args, file, dest_path, ytdl_auth_params)
                    logging.info(f"Downloaded: {filename}")
                except Exception as e:
                    logging.error(f"Error processing {filename}: {e}")

            if args.plex_url and args.plex_token and args.plex_section_id:
                trigger_plex_rescan(
                    args.plex_url, args.plex_token, args.plex_section_id)

            if args.ytdl_cleanup_synced:
                for file in files['mp3s']:
                    logging.info("Cleaning up synced files from YTDL.")
                    delete_file(args, file, ytdl_auth_params)
                    logging.info("Successfully removed synced files from YTDL.")

            logging.info("Sync completed.")
    except Timeout:
        logging.warning("Another instance is running. Exiting.")


if __name__ == "__main__":
    main()

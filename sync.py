#!/usr/bin/env python3
import os
import sys
import fcntl
import requests
import time
import json
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
import musicbrainzngs

# Configuration from environment
YTDL_BASE_URL = os.getenv("YTDL_URL", "http://localhost:17442/")
YTDL_API_FILES = f"{YTDL_BASE_URL.rstrip('/')}/api/getDownloaded"
YTDL_API_DELETE = f"{YTDL_BASE_URL.rstrip('/')}/api/file/remove"
PLEX_BASE_URL = os.getenv("PLEX_URL", "http://localhost:32400")
PLEX_TOKEN = os.getenv("PLEX_TOKEN", "")
PLEX_MUSIC_SECTION_ID = int(os.getenv("PLEX_MUSIC_SECTION_ID", "4"))

LOCAL_DOWNLOAD_DIR = os.getenv("LOCAL_DOWNLOAD_DIR", "/music")
LOCK_FILE_PATH = os.getenv("LOCK_FILE_PATH", "/tmp/ytdl_sync.lock")

musicbrainzngs.set_useragent("YTDL-Sync", "1.0", "email@example.com")

# Locking
def acquire_lock():
    lock_file = open(LOCK_FILE_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[WARN] Another instance is running. Exiting.")
        sys.exit(0)
    return lock_file

# Get list of downloaded files
def get_downloaded_files():
    response = requests.get(YTDL_API_FILES)
    response.raise_for_status()
    return response.json()

# Download file
def download_file(file_path, destination_dir):
    print(f"[INFO] Downloading: {file_path}")
    url = f"{YTDL_BASE_URL.rstrip('/')}/api/file/download?filename={file_path}"
    response = requests.get(url, stream=True)
    response.raise_for_status()

    local_path = os.path.join(destination_dir, os.path.basename(file_path))
    with open(local_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    return local_path

# Delete file from YTDL server
def delete_file(file_path):
    print(f"[INFO] Deleting from YTDL: {file_path}")
    response = requests.post(YTDL_API_DELETE, json={"filename": file_path})
    response.raise_for_status()

# MusicBrainz tagging and move
def tag_and_move_file(file_path):
    try:
        audio = MP3(file_path, ID3=EasyID3)
        title = audio.get("title", [None])[0]
        artist = audio.get("artist", [None])[0]

        if not title or not artist:
            print(f"[WARN] Missing title or artist for {file_path}. Skipping tagging.")
            return None

        result = musicbrainzngs.search_recordings(recording=title, artist=artist, limit=1)
        if not result["recording-list"]:
            print(f"[WARN] No MusicBrainz match for {title} by {artist}")
            return None

        recording = result["recording-list"][0]
        artist_name = recording["artist-credit"][0]["artist"]["name"]
        track_title = recording["title"]
        album = recording.get("release-list", [{}])[0].get("title", "Unknown Album")

        audio["artist"] = artist_name
        audio["title"] = track_title
        audio["album"] = album
        audio.save()

        return move_to_library(file_path, artist_name, album, track_title)
    except Exception as e:
        print(f"[ERROR] Failed to tag/move {file_path}: {e}")
        return None

# Move to /music/Artist/Album/Title.mp3
def move_to_library(file_path, artist, album, title):
    artist_safe = artist.replace("/", "_")
    album_safe = album.replace("/", "_")
    title_safe = title.replace("/", "_")

    target_dir = os.path.join(LOCAL_DOWNLOAD_DIR, artist_safe, album_safe)
    os.makedirs(target_dir, exist_ok=True)

    dest_path = os.path.join(target_dir, f"{title_safe}.mp3")
    os.rename(file_path, dest_path)
    print(f"[INFO] Moved to {dest_path}")
    return dest_path

# Plex rescan trigger
def trigger_plex_scan():
    if not PLEX_TOKEN:
        print("[WARN] Plex token not set. Skipping scan.")
        return

    url = f"{PLEX_BASE_URL}/library/sections/{PLEX_MUSIC_SECTION_ID}/refresh"
    headers = {"X-Plex-Token": PLEX_TOKEN}
    try:
        print("[INFO] Triggering Plex scan...")
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        print("[INFO] Plex scan triggered.")
    except Exception as e:
        print(f"[ERROR] Failed to trigger Plex scan: {e}")

# Main routine
def main():
    lock_file = acquire_lock()
    print("[INFO] Starting sync process...")

    try:
        files = get_downloaded_files()
        if not files:
            print("[INFO] No files to process.")
            return

        for file in files:
            filename = file.get("id") or file.get("title")  # id = actual filename
            if not filename or not filename.endswith(".mp3"):
                continue

            downloaded_path = download_file(filename, "/tmp")
            final_path = tag_and_move_file(downloaded_path)

            if final_path:
                delete_file(filename)

        trigger_plex_scan()
    finally:
        print("[INFO] Sync complete.")
        lock_file.close()

if __name__ == "__main__":
    main()

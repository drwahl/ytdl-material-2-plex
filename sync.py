#!/usr/bin/env python3

from dotenv import load_dotenv
from filelock import FileLock, Timeout
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC
from mutagen.id3 import error as ID3Error
from mutagen.mp3 import MP3
from pathlib import Path
from pprint import pprint
from xml.dom import minidom
import argparse
import logging
import musicbrainzngs
import os
import re
import requests
import shutil
import sys

MB_APP = "ytdl-material-2-plex"
MB_VERSION = "1.0"
MB_CONTACT = "https://github.com/drwahl/ytdl-material-2-plex"


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


def _parse_bool_env(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('1', 'true', 'yes')
    return default


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


def ytdl_authenticate(session, ytdl_url, username, password, api_key):
    try:
        auth_resp = session.post(
            f"{ytdl_url}/api/auth/login",
            json={"username": username, "password": password},
            params={"apiKey": api_key}
        )
        auth_resp.raise_for_status()
        return auth_resp.json().get("token")
    except Exception as e:
        logging.error(f"Failed to authenticate with YTDL: {e}")
        return None


def fetch_file_list(session, ytdl_url, auth_params):
    try:
        resp = session.get(f"{ytdl_url}/api/getMp3s", params=auth_params)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logging.error(f"Failed to contact YTDL API: {e}")
        return None


def download_file(session, args, file, dest_path, auth_params):
    try:
        with session.post(
            f'{args.ytdl_url}/api/downloadFileFromServer',
            params=auth_params,
            headers={'Content-type': 'application/json'},
            json={"uid": file['uid'], "type": "audio"},
            stream=True,
        ) as result:
            result.raise_for_status()
            with open(dest_path, 'wb') as f:
                for chunk in result.iter_content(chunk_size=8192):
                    f.write(chunk)
        return True
    except Exception as e:
        logging.error(f"Failed to download/save file {file['uid']}: {e}")
        dest_path.unlink(missing_ok=True)
        return False


def delete_file(session, args, file, auth_params):
    try:
        resp = session.post(
            f"{args.ytdl_url}/api/deleteFile",
            headers={"Content-type": "application/json"},
            params=auth_params,
            json={"uid": file['uid']})
        resp.raise_for_status()
    except Exception as e:
        logging.error(f"Failed to delete file {file['uid']}: {e}")


def trigger_plex_rescan(session, plex_url, plex_token, section_id):
    try:
        resp = session.get(
            f"{plex_url}/library/sections/{section_id}/refresh",
            headers={"X-Plex-Token": plex_token},
        )
        resp.raise_for_status()
        logging.info("Plex rescan triggered.")
    except Exception as e:
        logging.error(f"Failed to trigger Plex rescan: {e}")


def plex_list_sections(session, args):
    try:
        resp = session.get(
            f"{args.plex_url}/library/sections",
            headers={"X-Plex-Token": args.plex_token},
        )
        resp.raise_for_status()
    except Exception as e:
        logging.error(f"Failed to list Plex sections: {e}")
        raise Exception(e)

    sections = []
    for sect in minidom.parseString(resp.text).getElementsByTagName('Directory'):
        sections.append({
            'Section Name': sect.getAttribute('title'),
            'Section ID': sect.getAttribute('key')})
    return sections


def sanitize_path_component(name):
    """Replace filesystem-hostile characters so the string is safe as a dir name."""
    name = re.sub(r'[/\\:*?"<>|]', '-', name)
    name = re.sub(r'-{2,}', '-', name).strip(' .-')
    return name or 'Unknown'


def parse_artist_title(raw_title, uploader=None):
    """Split 'Artist - Title' YouTube convention; fall back to uploader as artist."""
    if ' - ' in raw_title:
        artist, title = raw_title.split(' - ', 1)
        return artist.strip(), title.strip()
    return uploader or None, raw_title


def lookup_musicbrainz(title, artist=None):
    """Text-search MusicBrainz for a recording. Returns first match or None."""
    try:
        kwargs = {'recording': title, 'limit': 5}
        if artist:
            kwargs['artist'] = artist
        result = musicbrainzngs.search_recordings(**kwargs)
        recordings = result.get('recording-list', [])
        if recordings:
            return recordings[0]
    except musicbrainzngs.WebServiceError as e:
        logging.warning(f"MusicBrainz lookup failed for '{title}': {e}")
    return None


def tag_file(dest_path, file=None):
    """Tag an MP3 with ID3 metadata from MusicBrainz (falling back to YTDL/filename data).

    Returns a dict of the tags that were applied, or an empty dict on failure.
    The 'file' argument is the YTDL API object; pass None for backlog files.
    """
    file = file or {}
    raw_title = file.get('title', '') or dest_path.stem
    uploader = file.get('uploader', '') or ''
    upload_date = file.get('upload_date', '') or ''

    artist, title = parse_artist_title(raw_title, uploader or None)

    mb = lookup_musicbrainz(title, artist)
    applied = {}

    try:
        audio = MP3(str(dest_path), ID3=ID3)
        try:
            audio.add_tags()
        except ID3Error:
            pass  # tags already present

        if mb:
            mb_title = mb.get('title', title)
            audio.tags['TIT2'] = TIT2(encoding=3, text=mb_title)
            applied['title'] = mb_title

            credits = mb.get('artist-credit', [])
            mb_artist = ''
            for credit in credits:
                if isinstance(credit, dict) and 'artist' in credit:
                    mb_artist = credit['artist'].get('name', '')
                    break
            final_artist = mb_artist or artist or ''
            audio.tags['TPE1'] = TPE1(encoding=3, text=final_artist)
            applied['artist'] = final_artist

            releases = mb.get('release-list', [])
            if releases:
                release = releases[0]
                if release.get('title'):
                    audio.tags['TALB'] = TALB(encoding=3, text=release['title'])
                    applied['album'] = release['title']
                date = release.get('date', '')
                if date:
                    audio.tags['TDRC'] = TDRC(encoding=3, text=date[:4])
                    applied['year'] = date[:4]

            logging.info(f"Tagged from MusicBrainz: {dest_path.name}")
        else:
            audio.tags['TIT2'] = TIT2(encoding=3, text=title)
            applied['title'] = title
            if artist:
                audio.tags['TPE1'] = TPE1(encoding=3, text=artist)
                applied['artist'] = artist
            # upload_date is YYYYMMDD from YTDL; take the year
            if len(upload_date) >= 4:
                audio.tags['TDRC'] = TDRC(encoding=3, text=upload_date[:4])
                applied['year'] = upload_date[:4]
            logging.info(f"Tagged from YTDL metadata (no MusicBrainz match): {dest_path.name}")

        audio.save()
    except Exception as e:
        logging.warning(f"Failed to tag {dest_path.name}: {e}")

    return applied


def organize_file(src_path, music_dir, tags):
    """Move src_path to music_dir/Artist/Album/filename based on applied tags.

    Returns the new Path on success, None if the destination already exists or
    the move fails.
    """
    artist = sanitize_path_component(tags.get('artist') or 'Unknown Artist')
    album = sanitize_path_component(tags.get('album') or 'Unknown Album')
    dest_dir = Path(music_dir) / artist / album
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src_path.name

    if dest.exists():
        logging.warning(f"Destination already exists, skipping move: {dest}")
        return None

    try:
        shutil.move(str(src_path), str(dest))
        logging.info(f"Organized: {src_path.name} -> {artist}/{album}/")
        return dest
    except Exception as e:
        logging.error(f"Failed to move {src_path.name} to {dest}: {e}")
        return None


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
                        default=_parse_bool_env(os.environ.get("YTDL_CLEANUP_SYNCED", False)),
                        action='store_true')

    parser.add_argument("--plex-url", default=os.environ.get("PLEX_URL"))
    parser.add_argument("--plex-token", default=os.environ.get("PLEX_TOKEN"))
    parser.add_argument("--plex-section-id",
                        default=os.environ.get("PLEX_MUSIC_SECTION_ID"))
    parser.add_argument("--plex-list-sections",
                        default=False, action='store_true')

    parser.add_argument(
        "--download-dir", default=os.environ.get("LOCAL_DOWNLOAD_DIR", "/music/incoming"))
    parser.add_argument(
        "--music-dir", default=os.environ.get("PLEX_MUSIC_DIR"))
    parser.add_argument(
        "--lock-file", default=os.environ.get("LOCK_FILE_PATH", "/tmp/ytdl_sync.lock"))
    parser.add_argument("--log-path", default=os.environ.get("LOG_PATH"))
    parser.add_argument("--skip-tagging",
                        default=_parse_bool_env(os.environ.get("YTDL_SKIP_TAGGING", False)),
                        action='store_true')

    args = parser.parse_args()

    setup_logging(args.log_path)

    if not args.skip_tagging:
        musicbrainzngs.set_useragent(MB_APP, MB_VERSION, MB_CONTACT)
        musicbrainzngs.set_rate_limit(True)

    session = requests.Session()

    if args.plex_list_sections:
        pprint(plex_list_sections(session, args))
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
        with FileLock(str(lock_path), timeout=0):
            if args.ytdl_user and args.ytdl_password:
                ytdl_auth_params['jwt'] = ytdl_authenticate(
                    session, args.ytdl_url, args.ytdl_user, args.ytdl_password, args.ytdl_api_key)
                if not ytdl_auth_params.get('jwt', False):
                    logging.error("Authentication failed, exiting.")
                    sys.exit(1)
            else:
                logging.warning(
                    "No YTDL username/password provided, will attempt unauthenticated sync (all files).")

            files = fetch_file_list(session, args.ytdl_url, ytdl_auth_params)
            if files is None:
                logging.error("Unable to retrieve files, exiting.")
                sys.exit(1)

            os.makedirs(args.download_dir, exist_ok=True)

            # Download phase: pull any files not already in the drop-off dir.
            # Track (path, ytdl_file) pairs so the tag phase has YTDL metadata.
            newly_downloaded: list[tuple[Path, dict]] = []
            for file in files['mp3s']:
                filename = file["title"]
                dest_path = Path(args.download_dir) / os.path.basename(file['path'])

                if dest_path.exists():
                    logging.info(f"File already exists: {filename}, skipping.")
                    continue

                logging.info(f"Downloading: {filename}")
                if download_file(session, args, file, dest_path, ytdl_auth_params):
                    logging.info(f"Downloaded: {filename}")
                    newly_downloaded.append((dest_path, file))

            # Tag + organize phase: process every MP3 in the drop-off dir.
            # Newly downloaded files have YTDL metadata available.
            # Backlog files (from prior runs) use filename/MusicBrainz only.
            organized_count = 0
            if not args.skip_tagging:
                newly_downloaded_paths = {p for p, _ in newly_downloaded}

                # Build a map for quick YTDL metadata lookup by path
                ytdl_meta: dict[Path, dict] = {p: f for p, f in newly_downloaded}

                backlog = [
                    p for p in sorted(Path(args.download_dir).glob('*.mp3'))
                    if p not in newly_downloaded_paths
                ]
                if backlog:
                    logging.info(f"Found {len(backlog)} backlog file(s) in drop-off to tag/organize.")

                all_to_process = [p for p, _ in newly_downloaded] + backlog

                for src_path in all_to_process:
                    tags = tag_file(src_path, ytdl_meta.get(src_path))
                    if args.music_dir:
                        if organize_file(src_path, args.music_dir, tags):
                            organized_count += 1

            # Plex rescan: trigger when files actually landed in the music library.
            # If music_dir is set, that means organized files; otherwise, newly downloaded
            # files went directly into download_dir (which is presumably the library).
            needs_rescan = (organized_count > 0) if args.music_dir else (len(newly_downloaded) > 0)
            if needs_rescan and args.plex_url and args.plex_token and args.plex_section_id:
                trigger_plex_rescan(
                    session, args.plex_url, args.plex_token, args.plex_section_id)

            if args.ytdl_cleanup_synced:
                logging.info("Cleaning up synced files from YTDL.")
                for file in files['mp3s']:
                    delete_file(session, args, file, ytdl_auth_params)
                logging.info("Cleanup complete.")

            logging.info("Sync completed.")
    except Timeout:
        logging.warning("Another instance is running. Exiting.")


if __name__ == "__main__":
    main()

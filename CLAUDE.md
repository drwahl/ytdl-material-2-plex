# CLAUDE.md — ytdl-material-2-plex

## Project Overview

Single-script Python tool (`sync.py`) that pulls audio files from a
[ytdl-material](https://github.com/Tzahi12345/YoutubeDL-Material) server and
places them in a local directory for consumption by a Plex music library. It
can optionally trigger a Plex library rescan and clean up the source files from
the ytdl-material server after syncing.

## Architecture

Everything lives in one file (`sync.py`). There is no database, no persistent
state beyond the downloaded files themselves — re-running the script is
idempotent because it checks whether each destination file already exists before
downloading.

A `filelock` mutex (`/tmp/ytdl_sync.lock` by default) prevents concurrent runs.

### Key functions

| Function | Purpose |
|---|---|
| `load_config()` | Loads `.ytdl_sync.env` via `python-dotenv` |
| `ytdl_authenticate()` | POSTs credentials to `/api/auth/login`, returns JWT |
| `fetch_file_list()` | GETs `/api/getMp3s`, returns the full file list JSON |
| `download_file()` | Streams a single file from `/api/downloadFileFromServer` |
| `delete_file()` | POSTs to `/api/deleteFile` to remove a file from YTDL |
| `trigger_plex_rescan()` | GETs the Plex `/library/sections/{id}/refresh` endpoint |
| `plex_list_sections()` | Lists available Plex library sections (XML response) |
| `sanitize_path_component()` | Strips `/`, `:`, `*`, etc. from a string so it's safe as a dir name |
| `parse_artist_title()` | Splits `"Artist - Title"` YouTube convention; falls back to `uploader` |
| `lookup_musicbrainz()` | Text-searches MusicBrainz for a recording; returns first hit or `None` |
| `tag_file()` | Writes ID3 tags; returns `dict` of applied tags (empty dict on failure) |
| `organize_file()` | Moves a tagged file to `music_dir/Artist/Album/filename` |

A single `requests.Session` is passed through all functions to reuse the
underlying TCP connection.

## Environment Variables / CLI Flags

All options can be set via env var or CLI flag:

| Env var | CLI flag | Default | Description |
|---|---|---|---|
| `YTDL_URL` | `--ytdl-url` | — | Base URL of ytdl-material |
| `YTDL_USER` | `--ytdl-user` | — | ytdl-material username |
| `YTDL_PASSWORD` | `--ytdl-password` | — | ytdl-material password |
| `YTDL_API_KEY` | `--ytdl-api-key` | — | ytdl-material API key (required) |
| `YTDL_CLEANUP_SYNCED` | `--ytdl-cleanup-synced` | `false` | Delete files from YTDL after sync |
| `YTDL_SKIP_TAGGING` | `--skip-tagging` | `false` | Skip MusicBrainz lookup, ID3 tagging, and file organization |
| `LOCAL_DOWNLOAD_DIR` | `--download-dir` | `/music/incoming` | Drop-off/staging directory for ytdl files |
| `PLEX_MUSIC_DIR` | `--music-dir` | — | Organized library root; tagged files move to `Artist/Album/` here |
| `PLEX_URL` | `--plex-url` | — | Plex base URL |
| `PLEX_TOKEN` | `--plex-token` | — | Plex API token |
| `PLEX_MUSIC_SECTION_ID` | `--plex-section-id` | — | Plex library section ID |
| `LOCAL_DOWNLOAD_DIR` | `--download-dir` | `/music` | Where to write downloaded files |
| `LOCK_FILE_PATH` | `--lock-file` | `/tmp/ytdl_sync.lock` | Mutex lock file path |
| `LOG_PATH` | `--log-path` | — | Optional file log path |
| `CONFIG_PATH` | — | — | Explicit path to `.env` file |

Boolean env vars (`YTDL_CLEANUP_SYNCED`) accept `1`, `true`, or `yes`
(case-insensitive). Any other value is treated as false.

Config file search order: `$CONFIG_PATH` → `~/.ytdl_sync.env` → `./.ytdl_sync.env`.

## Running Locally

```bash
python -m venv env
source env/bin/activate
pip install -r requirements.txt

# Create a config file
cp .ytdl_sync.env.example ~/.ytdl_sync.env   # edit as needed

python sync.py
# or: python sync.py --plex-list-sections   # discover your Plex section ID
```

## Docker

```bash
make docker   # builds ytdl-sync:latest
# or: docker build -t ytdl-sync .

docker run --rm \
  -v /path/to/music:/music \
  -e YTDL_URL=http://ytdl.local:17442 \
  -e YTDL_API_KEY=your_api_key \
  -e PLEX_URL=http://plex.local:32400 \
  -e PLEX_TOKEN=your_plex_token \
  -e PLEX_MUSIC_SECTION_ID=4 \
  ytdl-sync:latest
```

See `docker-compose.yml` for a full compose example.

## Development

```bash
make virtualenv    # set up env/ with dev deps
source env/bin/activate
make style         # pycodestyle check
make autopep       # auto-fix style
make test          # pytest with coverage
```

Dev dependencies live in `requirements-dev.txt`.

## Tagging and Organization

The tag + organize phase runs on **all** MP3 files currently in `--download-dir` — both files downloaded in the current run (which have YTDL metadata available) and files left over from previous runs (backlog, metadata from filename/MusicBrainz only). It never touches `--music-dir` or anything outside `--download-dir`.

**Artist/title detection order:**
1. If the YTDL `title` field contains ` - `, split it as `Artist - Track title`
2. Otherwise use `uploader` (YouTube channel name) as artist and the full title as track title
3. For backlog files (no YTDL object), fall back to the filename stem

**MusicBrainz lookup:**
- Uses `musicbrainzngs.search_recordings(recording=title, artist=artist)`
- Rate-limited to 1 request/second (MusicBrainz requirement)
- On a match: writes `TIT2` (title), `TPE1` (artist), `TALB` (album), `TDRC` (year) from the first result
- On no match: writes `TIT2`, `TPE1` from parsed YTDL/filename data, `TDRC` from `upload_date`
- `tag_file()` returns a `dict` of what was applied (keys: `title`, `artist`, `album`, `year`)

**File organization:**
- If `--music-dir` is set, `organize_file()` moves the file to `music_dir/Artist/Album/filename`
- Artist and album names are sanitized (`:`, `*`, `/`, etc. → `-`) before becoming directory components
- Files that already exist at the destination are skipped (not overwritten)
- If `--music-dir` is not set, files are tagged in-place in `--download-dir`

**Plex rescan trigger:**
- If `--music-dir` is set: triggers when at least one file was successfully moved there
- If `--music-dir` is not set: triggers when at least one file was newly downloaded

Set `YTDL_SKIP_TAGGING=true` to disable tagging, organization, and the backlog scan entirely.

## Known Behaviour / Gotchas

- `--ytdl-cleanup-synced` deletes **all** files from the YTDL server listed in
  the current API response, not just files downloaded in this run. Files already
  present locally will be deleted from YTDL on the first run after they were
  downloaded.
- Plex rescan is only triggered when at least one new file was downloaded in the
  current run.
- If a download fails, the partial file is removed and the run continues.
  Failed downloads are not retried; the file stays on YTDL for the next run.
- The script is not multi-user aware — the mutex only prevents overlapping runs
  on the same host.

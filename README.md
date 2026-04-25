# ytdl-material-2-plex

Sync audio files from [ytdl-material](https://github.com/Tzahi12345/YoutubeDL-Material) into a local directory for use with a Plex music library.

## Features

- Syncs downloaded audio files via the ytdl-material API
- Skips files that already exist locally (idempotent)
- Optionally deletes files from ytdl-material after syncing
- Triggers a Plex library rescan when new files are downloaded
- Runs cleanly in Docker and supports scheduled execution via cron

## Environment Variables

All options can also be passed as CLI flags (e.g. `--ytdl-url`).

| Variable | Required | Default | Description |
|---|---|---|---|
| `YTDL_URL` | yes | — | Base URL of your ytdl-material server |
| `YTDL_API_KEY` | yes | — | ytdl-material API key |
| `YTDL_USER` | no | — | ytdl-material username (for authenticated sync) |
| `YTDL_PASSWORD` | no | — | ytdl-material password (for authenticated sync) |
| `YTDL_CLEANUP_SYNCED` | no | `false` | Delete files from YTDL after syncing (`true`/`1`/`yes`) |
| `PLEX_URL` | no | — | Plex base URL (e.g. `http://plex.local:32400`) |
| `PLEX_TOKEN` | no | — | Plex API token |
| `PLEX_MUSIC_SECTION_ID` | no | — | Plex library section ID for music |
| `LOCAL_DOWNLOAD_DIR` | no | `/music` | Target directory for downloaded files |
| `LOCK_FILE_PATH` | no | `/tmp/ytdl_sync.lock` | Path to the mutex lock file |
| `LOG_PATH` | no | — | Write logs to this file in addition to stdout |
| `CONFIG_PATH` | no | — | Explicit path to a `.env` config file |

If `YTDL_USER`/`YTDL_PASSWORD` are omitted, the script falls back to an unauthenticated sync (retrieves all files).

## Configuration File

You can store settings in a `.env` file instead of passing env vars or CLI flags. The script checks these locations in order:

1. `$CONFIG_PATH`
2. `~/.ytdl_sync.env`
3. `./.ytdl_sync.env`

Example:

```ini
YTDL_URL=http://ytdl.local:17442
YTDL_API_KEY=your_api_key
YTDL_USER=admin
YTDL_PASSWORD=secret
PLEX_URL=http://plex.local:32400
PLEX_TOKEN=your_plex_token
PLEX_MUSIC_SECTION_ID=4
LOCAL_DOWNLOAD_DIR=/music
YTDL_CLEANUP_SYNCED=false
```

## Discovering Your Plex Section ID

```bash
python sync.py --plex-url http://plex.local:32400 --plex-token YOUR_TOKEN --plex-list-sections
```

## Example Usage (Docker)

```bash
docker run --rm \
  -v /path/on/host/music:/music \
  -e YTDL_URL=http://ytdl.local:17442 \
  -e YTDL_API_KEY=your_api_key \
  -e PLEX_URL=http://plex.local:32400 \
  -e PLEX_TOKEN=your_plex_token \
  -e PLEX_MUSIC_SECTION_ID=4 \
  drwahl/ytdl-sync:latest
```

## Docker Compose

See `docker-compose.yml` for a full example. Schedule recurring syncs with an
external cron job or your container orchestrator.

## Building Locally

```bash
docker build -t ytdl-sync .
```

## Development

```bash
make virtualenv
source env/bin/activate
make style    # check style
make autopep  # auto-fix style
make test     # run tests
```

## GitHub Actions Deployment

This repo includes a GitHub Actions workflow to build and publish the image to Docker Hub on push to `main`. Add the following secrets to your repo:

- `DOCKER_USERNAME` — your Docker Hub username
- `DOCKER_PASSWORD` — your Docker Hub access token

## License

MIT

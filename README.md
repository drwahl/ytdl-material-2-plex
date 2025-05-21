# ytdl-sync

Sync, tag, organize, and manage audio files from [ytdl-material](https://github.com/Tzahi12345/YoutubeDL-Material) for use with a Plex library.

## Features

- 🧲 Syncs downloaded files via the ytdl-material API
- 🔖 Tags audio files using MusicBrainz
- 📁 Organizes into `Artist/Album/Title.mp3` folder structure
- 🗑 Deletes files from the ytdl-material server once processed
- 🎵 Triggers Plex to rescan the music library
- 🚀 Runs cleanly in Docker and supports scheduled execution

## Environment Variables

| Variable                | Description                                            |
|-------------------------|--------------------------------------------------------|
| `YTDL_URL`              | Base URL to your ytdl-material server                  |
| `PLEX_URL`              | Plex base URL                                          |
| `PLEX_TOKEN`            | Plex API token                                         |
| `PLEX_MUSIC_SECTION_ID` | Plex library section ID for music                     |
| `LOCAL_DOWNLOAD_DIR`    | Target folder for organized music (e.g. `/music`)      |
| `LOCK_FILE_PATH`        | Path to mutex lock file (default: `/tmp/ytdl_sync.lock`) |

## Example Usage (Docker)

Run the container, mapping the music directory and optional lockfile path:

    docker run --rm \
      -v /path/to/music:/music \
      -v /tmp/ytdl_sync.lock:/tmp/ytdl_sync.lock \
      -e YTDL_URL=http://host.docker.internal:17442 \
      -e PLEX_URL=http://host.docker.internal:32400 \
      -e PLEX_TOKEN=your_plex_token \
      -e PLEX_MUSIC_SECTION_ID=4 \
      your-dockerhub-username/ytdl-sync:latest

## Building Locally

Build the container image:

    docker build -t ytdl-sync .

## GitHub Actions Deployment

This repo includes a GitHub Actions workflow to build and publish the image to Docker Hub when you push to `main`. Be sure to add the following secrets to your repo:

- `DOCKER_USERNAME` — your Docker Hub username
- `DOCKER_PASSWORD` — your Docker Hub access token

## License

MIT


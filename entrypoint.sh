#!/bin/bash
set -e

echo "[INFO] Starting YTDL sync..."

# Run the Python sync script
python3 /app/sync.py

echo "[INFO] Sync completed."

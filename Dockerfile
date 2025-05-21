FROM python:3.11-slim

LABEL maintainer="david.wahlstrom@gmail.com"
LABEL org.opencontainers.image.source="https://github.com/drwahl/ytdl-material-2-plex"

# Set working directory
WORKDIR /app

# Copy requirements (if you have any external dependencies)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the sync script
COPY sync.py .

# Create a user to run the app (not root)
RUN addgroup --system ytdlgroup && adduser --system ytdluser --ingroup ytdlgroup
RUN chown -R ytdluser:ytdlgroup /app

USER ytdluser

# Default command
CMD ["python", "sync.py"]

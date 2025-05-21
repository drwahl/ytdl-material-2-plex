FROM python:3.11-slim

LABEL maintainer="david.wahlstrom@gmail.com"
LABEL org.opencontainers.image.source="https://github.com/drwahl/ytdl-material-2-plex"

# Install system deps
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create a non-root user and prepare writable dirs
RUN useradd -m appuser
RUN mkdir -p /music /tmp && chown -R appuser:appuser /music /tmp

# Set working directory
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy script
COPY sync.py .

USER appuser

ENTRYPOINT ["python"]
CMD ["sync.py"]

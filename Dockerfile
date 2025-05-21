FROM python:3.11-slim

# Optional for AcoustID fingerprinting
RUN apt-get update && apt-get install -y \
    libchromaprint-tools \
    && rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /app

# Copy in dependencies and script
COPY requirements.txt .
COPY sync.py .
COPY entrypoint.sh .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Make entrypoint executable
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]

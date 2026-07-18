# AutoShorts Engine — Docker Image
# For deployment on Railway, Render, DigitalOcean, AWS, Azure, GCP, or any VPS.
#
# Build:   docker build -t autoshorts .
# Run:     docker run -d --env-file .env \
#            -v $(pwd)/credentials:/app/credentials \
#            -v $(pwd)/output:/app/output \
#            -v $(pwd)/data:/app/data \
#            -v $(pwd)/logs:/app/logs \
#            autoshorts

FROM python:3.11-slim

# System dependencies: ffmpeg for video encoding, fonts for subtitles/thumbnails
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    fonts-dejavu-core \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source
COPY . .

# Create required directories
RUN mkdir -p credentials output downloads thumbnails metadata logs data music cache

# Set font path for Linux (DejaVu Bold instead of Windows Arial)
ENV FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf

# Ensure Python output is not buffered (important for cloud log streaming)
ENV PYTHONUNBUFFERED=1

# Default command: start the scheduler daemon
CMD ["python", "run.py", "--schedule"]

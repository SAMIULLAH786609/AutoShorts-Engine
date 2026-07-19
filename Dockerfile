# AutoShorts Engine — Dockerfile for Hugging Face Spaces
FROM python:3.11-slim

# Install system dependencies: ffmpeg, graphics libraries, and fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    fonts-dejavu-core \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy root requirements (pipeline) and backend requirements
COPY requirements.txt .
COPY backend/requirements.txt ./backend_requirements.txt

# Install all dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r backend_requirements.txt

# Copy project source code
COPY . .

# Create all folders used by the app
RUN mkdir -p credentials output downloads thumbnails metadata logs data music cache && \
    chmod -R 777 /app

# Environment variables
ENV FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
ENV PYTHONUNBUFFERED=1
ENV PORT=7860

# Expose the default Hugging Face Spaces port
EXPOSE 7860

# Run FastAPI backend using uvicorn
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]

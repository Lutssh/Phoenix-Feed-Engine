# Build context: project root (.)
# This is required because celery is invoked as:
#   celery -A smart_ingestion.celery_app ...
# which means smart_ingestion must be a *package subdirectory* of WORKDIR,
# not the WORKDIR itself. docker-compose sets context: . to match.

FROM python:3.10-slim

WORKDIR /app

# System deps: ffmpeg for video, libsm6/libxext6 for OpenCV, curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    git \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer cached until requirements change)
COPY smart_ingestion/requirements.txt ./smart_ingestion/requirements.txt
RUN pip install --no-cache-dir -r smart_ingestion/requirements.txt

# Copy only the smart_ingestion package — keeps the image lean
COPY smart_ingestion/ ./smart_ingestion/

# PYTHONPATH ensures `import smart_ingestion` resolves from /app
ENV PYTHONPATH=/app

# Default CMD — overridden per-worker in docker-compose
CMD ["celery", "-A", "smart_ingestion.celery_app", "worker", "--loglevel=info"]

FROM python:3.12-slim

WORKDIR /app

# libexpat1: geopandas/fiona XML deps
# libimage-exiftool-perl: exiftool, used by 02_extract_metadata.py
# curl, unzip: needed to install rclone below
RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
    libimage-exiftool-perl \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install rclone, used for S3 uploads
RUN curl https://rclone.org/install.sh | bash

# Suppress error about pip installing as root
ENV PIP_ROOT_USER_ACTION=ignore

# Copy requirements first to avoid re-installing if the scripts are changed
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-c", "import sys; print('under-canopy ingest scripts, reference a specific script')"]

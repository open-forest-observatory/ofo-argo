FROM ghcr.io/osgeo/gdal:ubuntu-small-3.8.4

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-pip \
    curl \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install rclone
RUN curl https://rclone.org/install.sh | bash

# Set working directory
WORKDIR /app

# Copy Python scripts and requirements
COPY requirements.txt .
COPY postprocess.py .
COPY entrypoint.py .
COPY docker-entrypoint.sh .

# Install Python packages
RUN pip3 install --no-cache-dir -r requirements.txt

# Make scripts executable
RUN chmod +x docker-entrypoint.sh
RUN chmod +x entrypoint.py

ENTRYPOINT ["./docker-entrypoint.sh"]

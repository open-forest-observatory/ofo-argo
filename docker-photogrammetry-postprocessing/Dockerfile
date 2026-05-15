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

RUN pip3 install --upgrade pip

# Copy requirements first to avoid re-installing if the scripts are changed
COPY requirements.txt .
# Install Python packages
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy files
COPY postprocessing/ postprocessing/
COPY entrypoint.py .
COPY docker-entrypoint.sh .
COPY pyproject.toml .

# Install the package so postprocess is importable from anywhere
RUN pip3 install --no-cache-dir -e .

# Make scripts executable
RUN chmod +x docker-entrypoint.sh
RUN chmod +x entrypoint.py


ENTRYPOINT ["./docker-entrypoint.sh"]

FROM python:3.9-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install rclone for S3 imagery downloads
RUN curl https://rclone.org/install.sh | bash

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Make all Python scripts executable, including those in subdirectories
RUN find /app -name "*.py" -type f -exec chmod +x {} \;


CMD ["python", "-c", "import sys; print('Ofo-argo-utils running, reference a specific script')"]

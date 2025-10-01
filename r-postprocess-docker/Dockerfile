FROM rocker/geospatial:latest

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install rclone
RUN curl https://rclone.org/install.sh | bash

# Set working directory
WORKDIR /app

# Copy R scripts and installation files
COPY scripts/ ./scripts/
COPY install_packages.R .
COPY entrypoint.R .
COPY docker-entrypoint.sh .

# Install R packages
RUN Rscript install_packages.R

# Make entrypoint executable
RUN chmod +x docker-entrypoint.sh
RUN chmod +x entrypoint.R

# Create processing directories
RUN mkdir -p /tmp/processing/{input,boundary,output/full,output/thumbnails,temp}

ENTRYPOINT ["./docker-entrypoint.sh"]
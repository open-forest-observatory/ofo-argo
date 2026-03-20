FROM python:3.12-slim
# Install system dependencies
RUN apt-get update && apt-get install -y libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# Suppress error about pip installing as root
ENV PIP_ROOT_USER_ACTION=ignore
# TODO see if we can drop the dependency on Pillow in the future and replace the functionality
# with that of imageio
RUN pip install geopandas imageio Pillow rasterio scipy tqdm

# Set the container workdir
WORKDIR /app
# Copy files from current directory into /app
COPY . /app

CMD python /app/chip_images.py
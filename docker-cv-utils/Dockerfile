FROM python:3.12-slim

# Suppress error about pip installing as root
ENV PIP_ROOT_USER_ACTION=ignore
# TODO see if we can drop PIL
RUN pip install geopandas imageio Pillow rasterio scipy

# Set the container workdir
WORKDIR /app
# Copy files from current directory into /app
COPY . /app

CMD python /app/chip_images.py
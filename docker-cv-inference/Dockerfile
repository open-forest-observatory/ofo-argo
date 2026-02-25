# Base MMPretrain image
FROM waikatodatamining/mmpretrain:1.2.0_cuda11.1

# Suppress error about pip installing as root
ENV PIP_ROOT_USER_ACTION=ignore

# There's a conflict between geopandas as fiona without forcing a specific version
RUN pip install geopandas fiona==1.9.6

# Set the container workdir
WORKDIR /app
# Copy files from current directory into /app
COPY . /app

CMD python /app/predict_species.py
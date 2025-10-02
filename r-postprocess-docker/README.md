# R Post-Processing Docker Container Architecture

## Overview

The `photogrammetry-postprocess:0.1` docker image was created to containerize the photogrammetry post-processing pipeline for the Open Forest Observatory (OFO) project. This container automates the download, processing, and upload of drone imagery products, transforming raw photogrammetry outputs into publication-ready deliverables.

The container does the following:
- Looks for a directory of metashape outputs in the S3 bucket `ofo-internal`
- Downloads the directory and data to the local machine
- Crop rasters to mission boundaries and convert to Cloud Optimized GeoTIFFs (COGs)
- Generate Canopy Height Models (CHMs) from DSM/DTM differences
- Create thumbnails for web display
- Uploads the finished products to S3 bucket `ofo-public` 


## Docker Commands

### Build Command
```bash
cd r-postprocess-docker
docker build -t ghcr.io/open-forest-observatory/photogrammetry-postprocess:0.1 .
```

**Build Process**:
1. Downloads rocker/geospatial base image (~2GB)
2. Installs system dependencies (curl, unzip, wget)
3. Installs rclone from official script
4. Copies all scripts and sets permissions
5. Installs additional R packages
6. Creates processing directory structure

### Run Command
```bash
docker run --rm \
  -e S3_ENDPOINT=https://js2.jetstream-cloud.org:8001 \
  -e S3_PROVIDER=Other \
  -e S3_ACCESS_KEY=<your_access_key> \
  -e S3_SECRET_KEY=<your_secret_key> \
  -e S3_BUCKET_INPUT_DATA=ofo-internal \
  -e INPUT_DATA_DIRECTORY=<run_folder> \
  -e S3_BUCKET_INPUT_BOUNDARY=ofo-public \
  -e INPUT_BOUNDARY_DIRECTORY=<mission_boundaries_directory> \
  -e S3_BUCKET_OUTPUT=ofo-public \
  -e OUTPUT_DIRECTORY=<processed_products> \
  ghcr.io/open-forest-observatory/photogrammetry-postprocess:0.1
```






## Architecture Overview

The container follows a multi-script architecture where each component has a specific responsibility:

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Container                          │
├─────────────────────────────────────────────────────────────┤
│  docker-entrypoint.sh (Shell orchestration layer)           │
│  ├─ Environment validation                                  │
│  ├─ System checks (R, rclone, packages)                     │
│  └─ Launch entrypoint.R                                     │
├─────────────────────────────────────────────────────────────┤
│  entrypoint.R (Main processing orchestrator)                │
│  ├─ S3 configuration and data downloads                     │
│  ├─ Mission auto-detection and matching                     │
│  ├─ Process each mission via containerized function         │
│  └─ Upload results and cleanup                              │
├─────────────────────────────────────────────────────────────┤
│  20_postprocess-photogrammetry-products.R                   │
│  ├─ Core photogrammetry processing functions                │
│  ├─ Raster cropping, CHM generation, thumbnail creation     │
│  └─ File format conversions (COG, PNG thumbnails)           │
├─────────────────────────────────────────────────────────────┤
│  Supporting Components:                                     │
│  ├─ install_packages.R (Dependency management)              │
│                                                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Dockerfile - Container Foundation

**Location**: `r-postprocess-docker/Dockerfile`

The Dockerfile establishes the container environment using a multi-stage approach:

```dockerfile
FROM rocker/geospatial:latest

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install rclone for S3 operations
RUN curl https://rclone.org/install.sh | bash

# Set working directory and copy scripts
WORKDIR /app
COPY 20_postprocess-photogrammetry-products.R .
COPY install_packages.R .
COPY entrypoint.R .
COPY docker-entrypoint.sh .

# Install R packages and set permissions
RUN Rscript install_packages.R
RUN chmod +x docker-entrypoint.sh
RUN chmod +x entrypoint.R

# Create processing directory structure
RUN mkdir -p /tmp/processing/{input,boundary,output/full,output/thumbnails,temp}

ENTRYPOINT ["./docker-entrypoint.sh"]
```

**Key Design Decisions**:
- **Base Image**: `rocker/geospatial:latest` provides R with geospatial packages (sf, terra, tidyverse) pre-installed
- **rclone Integration**: Essential for S3 operations with Jetstream2 object storage
- **Directory Structure**: Pre-creates organized processing directories for efficient data handling
- **Permission Management**: Ensures all scripts are executable within container context

### 2. docker-entrypoint.sh - System Validation Layer

**Location**: `r-postprocess-docker/docker-entrypoint.sh`

This bash script serves as the container's entry point, providing robust environment validation:

```bash
#!/bin/bash
set -e

# Environment variable validation
required_vars=("S3_ENDPOINT" "S3_ACCESS_KEY" "S3_SECRET_KEY"
               "S3_BUCKET_INPUT_DATA" "S3_BUCKET_INPUT_BOUNDARY")

# System component testing
rclone version
Rscript -e "packages <- c('tidyverse', 'sf', 'terra', 'lidR', 'purrr')..."

# Launch R processing
exec Rscript /app/entrypoint.R "$@"
```

**Responsibilities**:
- **Environment Validation**: Ensures all required S3 credentials and bucket names are provided
- **System Checks**: Verifies rclone and R installations, tests R package availability
- **Default Values**: Sets sensible defaults for optional parameters (TERRA_MEMFRAC=0.9, OUTPUT_MAX_DIM=800)
- **Error Handling**: Provides clear error messages for missing dependencies or configuration

### 3. entrypoint.R - Processing Orchestrator

**Location**: `r-postprocess-docker/entrypoint.R`

The main R script that orchestrates the entire processing pipeline:

#### Key Functions:

**setup_rclone_config()**:
- Creates rclone configuration file with S3 credentials
- Configures connection to Jetstream2 object storage endpoint
- Handles provider-specific settings

**download_photogrammetry_products()** & **download_boundary_polygons()**:
- Downloads all available files from specified S3 buckets/directories
- Uses parallel transfers for efficiency (8 transfers, 8 checkers)
- Implements retry logic for network resilience

**detect_and_match_missions()**:
- **Auto-Detection Logic**: Extracts mission prefixes by parsing filenames
  - Example: `benchmarking_greasewood_ortho.tif` → mission prefix: `benchmarking_greasewood`
  - Strategy: Split by underscore, remove last part (product type)
- **Intelligent Matching**: Pairs photogrammetry products with corresponding boundary polygons
- **Validation**: Ensures each mission has required boundary file before processing

**upload_processed_products()**:
- Uploads processed files back to S3 output location
- Maintains directory structure (full resolution vs thumbnails)
- Handles per-mission uploads to avoid large batch failures

#### Processing Workflow:

```r
main <- function() {
  # 1. Environment setup and validation
  setup_rclone_config()

  # 2. Data acquisition
  download_photogrammetry_products()
  download_boundary_polygons()

  # 3. Mission discovery and matching
  mission_matches <- detect_and_match_missions()

  # 4. Process each mission individually
  for (mission in mission_matches) {
    postprocess_photogrammetry_containerized(
      mission$prefix,
      mission$boundary_file,
      mission$product_files
    )
    upload_processed_products(mission$prefix)
  }

  # 5. Cleanup
  cleanup_working_directory()
}
```

### 4. 20_postprocess-photogrammetry-products.R - Core Processing Engine

**Location**: `r-postprocess-docker/20_postprocess-photogrammetry-products.R`

This script contains the core photogrammetry processing logic, adapted for containerized execution:

#### Key Processing Functions:

**postprocess_photogrammetry_containerized()**:
The main processing function that handles a single mission:

```r
postprocess_photogrammetry_containerized(mission_prefix, boundary_file_path, product_file_paths)
```

**Processing Steps**:

1. **Input Validation**: Verifies all input files exist before processing
2. **File Analysis**: Parses product filenames to determine types (dsm, dtm, ortho, points, etc.)
3. **Raster Processing**:
   - **crop_raster_save_cog()**: Crops rasters to mission boundaries and saves as Cloud Optimized GeoTIFFs
   - **Boundary Matching**: Reprojects mission polygons to match raster CRS
   - **COG Conversion**: Uses GDAL options for optimal web delivery
4. **CHM Generation**:
   - **make_chm()**: Calculates Canopy Height Model from DSM - DTM
   - **Smart Pairing**: Tries different DSM/DTM combinations (dsm-mesh + dtm-ptcloud, etc.)
   - **CRS Alignment**: Ensures DTM is reprojected to match DSM before calculation
5. **Thumbnail Creation**:
   - Scales images to configurable maximum dimension (default 800px)
   - Creates PNG thumbnails for web display
   - Handles single-band and RGB imagery appropriately
6. **File Management**: Copies non-raster files (point clouds, reports, camera files) to output

#### Utility Functions:

**transform_to_local_utm()** & **lonlat_to_utm_epsg()**:
- Reprojects geometries to appropriate UTM zone for accurate processing
- Handles cross-UTM zone validation

**create_dir()** & **drop_units_if_present()**:
- Directory management and unit handling utilities

### 5. install_packages.R - Dependency Management

**Location**: `r-postprocess-docker/install_packages.R`

Handles R package installation during container build:

```r
install_if_missing <- function(pkg) {
  if (!require(pkg, character.only = TRUE, quietly = TRUE)) {
    install.packages(pkg, repos = "https://cran.rstudio.com/", dependencies = TRUE)
  }
}

packages <- c("lidR", "purrr")  # Additional packages beyond rocker/geospatial
```

**Strategy**:
- Leverages rocker/geospatial base image for core packages (tidyverse, sf, terra)
- Only installs additional packages needed for point cloud processing (lidR) and functional programming (purrr)
- Includes verification step to ensure all packages load correctly









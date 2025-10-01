# R Post-Processing Docker Container Architecture

## Overview

The `r-postprocess-docker` container was created to containerize the photogrammetry post-processing pipeline for the Open Forest Observatory (OFO) project. This container automates the download, processing, and upload of drone imagery products, transforming raw photogrammetry outputs into publication-ready deliverables.

The container addresses the need to:
- Process multiple missions simultaneously with automatic mission detection
- Handle S3 data transfers efficiently using rclone
- Crop rasters to mission boundaries and convert to Cloud Optimized GeoTIFFs (COGs)
- Generate Canopy Height Models (CHMs) from DSM/DTM differences
- Create thumbnails for web display
- Maintain data consistency with proper error handling and cleanup

## Architecture Overview

The container follows a multi-script architecture where each component has a specific responsibility:

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Container                          │
├─────────────────────────────────────────────────────────────┤
│  docker-entrypoint.sh (Shell orchestration layer)          │
│  ├─ Environment validation                                  │
│  ├─ System checks (R, rclone, packages)                    │
│  └─ Launch entrypoint.R                                     │
├─────────────────────────────────────────────────────────────┤
│  entrypoint.R (Main processing orchestrator)               │
│  ├─ S3 configuration and data downloads                    │
│  ├─ Mission auto-detection and matching                    │
│  ├─ Process each mission via containerized function        │
│  └─ Upload results and cleanup                             │
├─────────────────────────────────────────────────────────────┤
│  20_postprocess-photogrammetry-products.R                  │
│  ├─ Core photogrammetry processing functions               │
│  ├─ Raster cropping, CHM generation, thumbnail creation    │
│  └─ File format conversions (COG, PNG thumbnails)          │
├─────────────────────────────────────────────────────────────┤
│  Supporting Components:                                     │
│  ├─ install_packages.R (Dependency management)             │
│  ├─ build-and-test.sh (Build automation)                   │
│  └─ test-syntax.R (Validation utilities)                   │
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
COPY scripts/ ./scripts/
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

**Location**: `r-postprocess-docker/scripts/20_postprocess-photogrammetry-products.R`

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

### 6. Supporting Tools

#### build-and-test.sh - Build Automation

**Location**: `r-postprocess-docker/build-and-test.sh`

Automated build and testing pipeline:

```bash
# Prerequisites check
docker --version && docker info

# Container build
docker build -t ofo-r-postprocess:latest .

# Functionality tests
docker run --rm ofo-r-postprocess:latest  # Tests env validation
docker run --rm --entrypoint /bin/bash ofo-r-postprocess:latest -c "rclone version; Rscript --version"
```

#### test-syntax.R - Code Validation

**Location**: `r-postprocess-docker/test-syntax.R`

Syntax and basic functionality testing:

```r
# Syntax validation
parse("/path/to/scripts/20_postprocess-photogrammetry-products.R")
parse("/path/to/entrypoint.R")

# Basic functionality tests
test_data <- data.frame(filename = c("test_mission_ortho.tif", "test_mission_dsm.tif"))
```

## Docker Commands

### Build Command
```bash
cd r-postprocess-docker
docker build -t ofo-r-postprocess:latest .
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
  -e S3_ENDPOINT="https://js2.jetstream-cloud.org:8001" \
  -e S3_PROVIDER="Other" \
  -e S3_ACCESS_KEY="your_access_key" \
  -e S3_SECRET_KEY="your_secret_key" \
  -e S3_BUCKET_INPUT_DATA="ofo-internal" \
  -e INPUT_DATA_DIRECTORY="run_folder" \
  -e S3_BUCKET_INPUT_BOUNDARY="ofo-public" \
  -e INPUT_BOUNDARY_DIRECTORY="mission_boundaries" \
  -e S3_BUCKET_OUTPUT="ofo-public" \
  -e OUTPUT_DIRECTORY="processed_products" \
  -e TERRA_MEMFRAC="0.9" \
  -e OUTPUT_MAX_DIM="800" \
  ofo-r-postprocess:latest
```

## Integration with OFO Argo Workflow

This container integrates into the broader OFO Argo Workflow ecosystem:

### Current Workflow Context:
1. **Metashape Processing**: `automate-metashape` container processes raw drone imagery
2. **Output Storage**: Metashape products stored in `/ofo-share/argo-outputs/`
3. **R Post-Processing**: This container downloads, processes, and uploads final products
4. **Final Storage**: Processed products uploaded to S3 buckets (`ofo-internal`, `ofo-public`)

### Containerization Benefits:
- **Environment Isolation**: Consistent R and system dependencies across different execution environments
- **Scalability**: Can be deployed in Kubernetes pods alongside Metashape processing
- **Flexibility**: Decouples post-processing from main Argo workflow, allowing independent scaling
- **Data Locality**: Processes data where it's stored, reducing data transfer overhead

### Future Integration Possibilities:
- **Argo Workflow Step**: Could replace current post-processing steps in `workflow.yaml`
- **Parallel Processing**: Multiple instances could process different missions simultaneously
- **Resource Management**: Container can be allocated specific CPU/memory resources
- **Monitoring**: Container logs integrate with Kubernetes monitoring systems

## Development Process Summary

The creation of this Docker container involved several key steps:

### 1. Requirements Analysis
- Identified need to containerize existing R post-processing pipeline
- Analyzed dependencies: R packages, system tools (rclone), data flow patterns
- Determined S3 integration requirements for Jetstream2 object storage

### 2. Architecture Design
- Chose multi-script approach for clear separation of concerns
- Selected rocker/geospatial as optimal base image for geospatial R workflows
- Designed auto-detection system for flexible mission processing

### 3. Script Adaptation
- **Containerized Version**: Adapted `20_postprocess-photogrammetry-products.R` from original script
- **Parameter Passing**: Changed from file-based configuration to function parameters
- **Data Flow**: Modified to work with downloaded files rather than network file systems

### 4. S3 Integration
- **rclone Configuration**: Dynamic configuration generation from environment variables
- **Download Strategy**: Bulk download followed by local processing for efficiency
- **Upload Optimization**: Per-mission uploads to handle partial failures gracefully

### 5. Error Handling & Robustness
- **Environment Validation**: Comprehensive checks for required configuration
- **Graceful Degradation**: Continues processing other missions if one fails
- **Resource Management**: Configurable memory limits and cleanup procedures

### 6. Testing & Validation
- **Automated Testing**: Build and test scripts for continuous validation
- **Syntax Checking**: Separate validation scripts for code correctness
- **Integration Testing**: Validation against real S3 data and mission files

This containerized approach represents a significant evolution from the original script-based processing, providing better isolation, reproducibility, and integration capabilities for the OFO processing pipeline.
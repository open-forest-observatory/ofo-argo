# Post-Processing Docker Image


## Overview

This Docker image provides automated post-processing of photogrammetry products from drone surveys. It downloads raw photogrammetry outputs (orthomosaics, DSMs, DTMs) and mission boundary polygons from S3 storage, crops rasters to mission boundaries, generates Canopy Height Models (CHMs), creates Cloud Optimized GeoTIFFs (COGs), produces PNG thumbnails, and uploads processed products back to S3 in organized mission-specific directories.

The image is based on GDAL (Geospatial Data Abstraction Library) and includes Python geospatial tools (rasterio, geopandas) and rclone for S3 operations.

The docker image is located at `ghcr.io/open-forest-observatory/photogrammetry-postprocess:1.2` and is attached as a package to this repo.



## Build Command

```bash
docker build -t ghcr.io/open-forest-observatory/python-photogrammetry-postprocess:latest .
```

## Run Command

```bash
docker run --rm \
  -e S3_ENDPOINT=https://js2.jetstream-cloud.org:8001 \
  -e S3_PROVIDER=Other \
  -e S3_ACCESS_KEY=<your_access_key> \
  -e S3_SECRET_KEY=<your_secret_key> \
  -e S3_BUCKET_INPUT_DATA=ofo-internal \
  -e INPUT_DATA_DIRECTORY=<run_folder> \
  -e S3_BUCKET_INPUT_BOUNDARY=ofo-public \
  -e INPUT_BOUNDARY_DIRECTORY=<boundaries_directory> \
  -e S3_BUCKET_OUTPUT=ofo-public \
  -e OUTPUT_DIRECTORY=<output_directory> \
  -e OUTPUT_MAX_DIM=800 \
  -e WORKING_DIR=/tmp/processing \
  ghcr.io/open-forest-observatory/photogrammetry-postprocess:latest
```

### Required Environment Variables

- `S3_ENDPOINT`: S3-compatible storage endpoint URL
- `S3_ACCESS_KEY`: S3 access key for authentication
- `S3_SECRET_KEY`: S3 secret key for authentication
- `S3_BUCKET_INPUT_DATA`: S3 bucket containing raw photogrammetry products
- `INPUT_DATA_DIRECTORY`: Directory path within input bucket (e.g., run folder name)
- `S3_BUCKET_INPUT_BOUNDARY`: S3 bucket containing mission boundary polygons
- `INPUT_BOUNDARY_DIRECTORY`: Base directory for boundary files

### Optional Environment Variables

- `S3_BUCKET_OUTPUT`: Output S3 bucket (defaults to `S3_BUCKET_INPUT_DATA`)
- `OUTPUT_DIRECTORY`: Output directory path (defaults to `processed`)
- `OUTPUT_MAX_DIM`: Maximum thumbnail dimension in pixels (default: `800`)
- `WORKING_DIR`: Local working directory for processing (default: `/tmp/processing`)
- `S3_PROVIDER`: S3 provider type (default: `Other`)

## Script Functions

### entrypoint.py

**Purpose**: Main orchestration script that coordinates the entire post-processing workflow.

**Key Functions**:

- `setup_rclone_config()`: Creates rclone configuration file from environment variables for S3 access
- `download_photogrammetry_products()`: Discovers mission subdirectories in S3 and downloads all photogrammetry products (orthomosaics, DSMs, DTMs, point clouds) to local storage
- `download_boundary_polygons(mission_dirs)`: Downloads mission boundary polygon files from nested S3 structure (`<boundary_base>/<mission_name>/metadata-mission/<mission_name>_mission-metadata.gpkg`)
- `detect_and_match_missions()`: Auto-detects missions using directory structure and matches photogrammetry products with their corresponding boundary polygons
- `upload_processed_products(mission_prefix)`: Uploads processed full-resolution products and thumbnails to S3 in mission-specific `processed_01` directories
- `cleanup_working_directory()`: Removes temporary processing files after completion
- `main()`: Primary execution function that validates environment, orchestrates downloads, processes each mission, uploads results, and reports summary statistics

**Workflow**:
1. Validates required environment variables
2. Configures rclone for S3 operations
3. Downloads all photogrammetry products from mission subdirectories
4. Downloads boundary polygons for each mission
5. Auto-detects and matches missions with boundaries
6. Processes each mission by calling `postprocess_photogrammetry_containerized()`
7. Uploads processed products for each mission
8. Cleans up temporary files
9. Reports success/failure summary

### postprocess.py

**Purpose**: Core raster processing library containing geospatial analysis and transformation functions.

**Key Functions**:

- `create_dir(path)`: Utility to create directories with parent creation
- `lonlat_to_utm_epsg(lon, lat)`: Calculates UTM zone EPSG code from geographic coordinates (handles northern/southern hemispheres)
- `transform_to_local_utm(gdf)`: Reprojects GeoDataFrame to its local UTM zone based on centroid location
- `crop_raster_save_cog(raster_filepath, output_filename, mission_polygon, output_path)`: Crops input raster to mission boundary polygon and saves as Cloud Optimized GeoTIFF with deflate compression and tiling
- `make_chm(dsm_filepath, dtm_filepath)`: Generates Canopy Height Model by subtracting DTM from DSM, with automatic reprojection to match coordinate systems
- `create_thumbnail(tif_filepath, output_path, max_dim=800)`: Creates PNG thumbnail from GeoTIFF with configurable maximum dimension, handling grayscale and RGB imagery
- `postprocess_photogrammetry_containerized(mission_prefix, boundary_file_path, product_file_paths)`: Main processing function that orchestrates cropping, COG creation, CHM generation, thumbnail creation, and file copying for a single mission

**Processing Pipeline (per mission)**:
1. Validates boundary and product file existence
2. Reads mission boundary polygon from GeoPackage
3. Builds product DataFrame with filename parsing (extracts product types like `ortho`, `dsm`, `dtm`)
4. Crops all raster files (TIF/TIFF) to mission boundary and saves as COGs
5. Attempts CHM creation from available DSM/DTM combinations (tries `dsm-mesh`/`dtm-ptcloud`, `dsm-ptcloud`/`dtm-ptcloud`, etc.)
6. Copies non-raster files (e.g., point clouds, metadata) to output directory
7. Generates PNG thumbnails for all output rasters
8. Reports statistics on created products

## Docker Image Architecture

### Execution Flow

```
docker run → docker-entrypoint.sh → entrypoint.py → postprocess.py
```

### 1. docker-entrypoint.sh (Shell Initialization Layer)

**Responsibilities**:
- Environment variable validation (checks for required S3 credentials and paths)
- System dependency verification (rclone, python3)
- Python package import testing (rasterio, geopandas, numpy, pandas, matplotlib)
- Sets default values for optional variables (`WORKING_DIR`, `OUTPUT_MAX_DIM`)
- Error handling with early exit on validation failures

**Output**: Prints configuration summary and system status before handing control to Python

### 2. entrypoint.py (Orchestration Layer)

**Responsibilities**:
- S3 configuration via rclone
- Data acquisition (downloads products and boundaries from S3)
- Mission detection and matching logic
- Iteration over missions with error handling per mission
- Upload of processed products to S3
- Cleanup and summary reporting

**Key Design Patterns**:
- Uses subprocess calls to rclone for S3 operations
- Handles partial failures gracefully (continues processing other missions if one fails)
- Organizes S3 uploads into mission-specific directories: `<output_base>/<mission_name>/processed_01/{full,thumbnails}/`

### 3. postprocess.py (Processing Layer)

**Responsibilities**:
- Geospatial raster operations (cropping, reprojection, masking)
- COG creation with optimized compression and tiling
- CHM generation with automatic CRS alignment
- Thumbnail rendering with matplotlib

**Key Technologies**:
- **rasterio**: Raster I/O, warping, and masking
- **geopandas/shapely**: Vector polygon operations and CRS transformations
- **numpy**: Array-based CHM calculations
- **matplotlib**: PNG thumbnail generation with exact pixel control

### Directory Structure in Container

```
/app/
├── docker-entrypoint.sh    # Bash validation script
├── entrypoint.py           # Python orchestration script
├── postprocess.py          # Python processing library
└── requirements.txt        # Python dependencies

/tmp/processing/            # Working directory
├── input/                  # Downloaded photogrammetry products
│   └── <mission_name>/     # Per-mission subdirectories
├── boundary/               # Downloaded boundary polygons
│   └── <mission_name>/     # Per-mission subdirectories
├── output/
│   ├── full/              # Full-resolution COGs and CHMs
│   └── thumbnails/        # PNG preview images
└── temp/                  # Temporary processing files
```

### Data Flow

1. **Download Phase**: rclone copies data from S3 to `/tmp/processing/{input,boundary}/`
2. **Processing Phase**: Python reads from input directories, processes rasters, writes to `/tmp/processing/output/`
3. **Upload Phase**: rclone copies from `/tmp/processing/output/` to S3 in mission-specific paths
4. **Cleanup Phase**: Entire `/tmp/processing/` directory removed

### Expected S3 Structure

**Input Data** (raw photogrammetry):
```
s3://<S3_BUCKET_INPUT_DATA>/<INPUT_DATA_DIRECTORY>/
└── <mission_name>/
    ├── <mission_name>_ortho.tif
    ├── <mission_name>_dsm-ptcloud.tif
    ├── <mission_name>_dtm-ptcloud.tif
    └── ...
```

**Boundary Data**:
```
s3://<S3_BUCKET_INPUT_BOUNDARY>/<INPUT_BOUNDARY_DIRECTORY>/
└── <mission_name>/
    └── metadata-mission/
        └── <mission_name>_mission-metadata.gpkg
```

**Output Data** (processed products):
```
s3://<S3_BUCKET_OUTPUT>/<OUTPUT_DIRECTORY>/
└── <mission_name>/
    └── processed_01/
        ├── full/
        │   ├── <mission_name>_ortho.tif        # COG
        │   ├── <mission_name>_dsm-ptcloud.tif  # COG
        │   ├── <mission_name>_dtm-ptcloud.tif  # COG
        │   ├── <mission_name>_chm.tif          # Generated CHM
        │   └── ...
        └── thumbnails/
            ├── <mission_name>_ortho.png
            ├── <mission_name>_dsm-ptcloud.png
            ├── <mission_name>_dtm-ptcloud.png
            ├── <mission_name>_chm.png
            └── ...
```

## Exit Codes

- `0`: All missions processed successfully
- `1`: One or more missions failed (partial success) or validation error

# Post-Processing Docker Image


## Overview

This Docker image provides automated post-processing of photogrammetry products from drone surveys. It downloads raw photogrammetry outputs (orthomosaics, DSMs, DTMs) and mission boundary polygons from S3 storage, crops rasters to mission boundaries, generates Canopy Height Models (CHMs), creates Cloud Optimized GeoTIFFs (COGs), produces PNG thumbnails, and uploads processed products back to S3 in organized mission-specific directories.

The current version PROCESSES ONE MISSION AT A TIME. You cannot use this standalone docker image to process multiple missions in an automated way. For that, please use Argo. 

The image is based on GDAL (Geospatial Data Abstraction Library) and includes Python geospatial tools (rasterio, geopandas) and rclone for S3 operations.

The docker image is located at `ghcr.io/open-forest-observatory/photogrammetry-postprocess:1.4` and is attached as a package to this repo.

<br/>

## Input Requirements

For the standalone docker image to work, there needs to exist a directory in the `S3:ofo-internal` bucket that contains the metashape output imagery products (dsm, dtm, pointcloud, ortho). The directory structure must look like this:

```
/S3:ofo-internal/
├── <INPUT_DATA_DIRECTORY>/
        ├── 01_dataset1_dsm-ptcloud.tif
        ├── 01_dataset1_dtm-ptcloud.tif
        ├── 01_dataset1_ortho-dtm-ptcloud.tif
        ├── 01_dataset1_points-copc.laz
        └── 01_dataset1_report.pdf
        ├── 02_dataset1_dsm-ptcloud.tif
        ├── 02_dataset1_dtm-ptcloud.tif
        ├── 02_dataset1_ortho-dtm-ptcloud.tif
        ├── 02_dataset1_points-copc.laz
        └── 02_dataset1_report.pdf
        ├── 01_dataset2_dsm-ptcloud.tif
        ├── 01_dataset2_dtm-ptcloud.tif
        ├── 01_dataset2_ortho-dtm-ptcloud.tif
        ├── 01_dataset2_points-copc.laz
        └── 01_dataset2_report.pdf
        ├── 02_dataset2_dsm-ptcloud.tif
        ├── 02_dataset2_dtm-ptcloud.tif
        ├── 02_dataset2_ortho-dtm-ptcloud.tif
        ├── 02_dataset2_points-copc.laz
        └── 02_dataset2_report.pdf
```


## Run Command

```bash
docker run --rm \
  -e S3_ENDPOINT=https://js2.jetstream-cloud.org:8001 \
  -e S3_PROVIDER=Other \
  -e S3_ACCESS_KEY=<your_access_key> \
  -e S3_SECRET_KEY=<your_secret_key> \
  -e S3_BUCKET_INPUT_DATA=ofo-internal \
  -e INPUT_DATA_DIRECTORY=gillan_oct10 \
  -e S3_BUCKET_INPUT_BOUNDARY=ofo-public \
  -e INPUT_BOUNDARY_DIRECTORY=jgillan_test \
  -e S3_BUCKET_OUTPUT=ofo-public \
  -e OUTPUT_DIRECTORY=jgillan_test \
  -e DATASET_NAME=01_benchmarking-greasewood \
  -e OUTPUT_MAX_DIM=800 \
  -e WORKING_DIR=/tmp/processing \
  ghcr.io/open-forest-observatory/photogrammetry-postprocess:1.6
```

*S3_ENDPOINT* is the url of the Jetstream2s S3 storage

*S3_PROVIDER* keep as 'Other'

*S3_ACCESS_KEY* is the access key for OFOs S3 buckets

*S3_SECRET_KEY* is the secret key for OFOs S3 buckets

*S3_BUCKET_INPUT_DATA* is the S3 bucket where existing Metashape products reside. Currently on 'ofo-internal'

*INPUT_DATA_DIRECTORY* is the parent directory where existing Metashape products reside.

*S3_BUCKET_INPUT_BOUNDARY* is the bucket where the mission boundary polygons reside. These are used to clip imagery products. Currently in `ofo-public`

*INPUT_BOUNDARY_DIRECTORY* is the parent directory where the mission boundary polygons reside.

*S3_BUCKET_OUTPUT* is the bucket where the postprocessed products will be stored. 'ofo-public'

*OUTPUT_DIRECTORY* is the parent directory where the postprocessed products will be stored

*DATASET_NAME* is the name of the dataset mission you want to process. This docker container will only process one dataset name. 

*OUTPUT_MAX_DIM* **optional** parameter to specify the max dimensions of thumbnails. Defaults to 800 pixels.

*WORKING_DIR* **optional** parameter specifying the directory within the container where the imagery products are downloaded to and postprocessed. The typical place is `/tmp/processing` which means the data will be downloaded to the processing computer and postprocessed there. You have the ability to change the WORKING_DIR to a persistent volume (PVC).



<br/>
<br/>

## Outputs

```
S3:ofo-public/OUTPUT_DIRECTORY/dataset1/processed_01/
├── full/
│   ├── 01_mission_ortho-dtm-ptcloud.tif
│   ├── 01_mission_dsm-ptcloud.tif
│   ├── 01_mission_dtm-ptcloud.tif
│   ├── 01_mission_chm.tif
│   └── 01_mission_points-copc.laz
└── thumbnails/
    ├── 01_mission_ortho-dtm-ptcloud.png
    ├── 01_mission_dsm-ptcloud.png
    ├── 01_mission_dtm-ptcloud.png
    └── 01_mission_chm.png
```
<br/>
<br/>
<br/>
<br/>

## Build Command

```bash
docker build -t ghcr.io/open-forest-observatory/photogrammetry-postprocess:latest .
```

<br/>
<br/>
<br/>


## Post-Processing Docker Container Workflow

This document describes the sequential execution flow of the photogrammetry post-processing Docker container from startup to completion.

## Container Startup Chain

```
docker run → Dockerfile ENTRYPOINT → docker-entrypoint.sh → entrypoint.py → postprocess.py
```

When the container starts, it follows this three-phase execution sequence:

1. **Phase 1**: Shell-based validation and setup (`docker-entrypoint.sh`)
2. **Phase 2**: Python orchestration and S3 operations (`entrypoint.py`)
3. **Phase 3**: Geospatial processing functions (`postprocess.py`)

---
<br/>
<br/>


## Complete Sequential Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ Container Start                                             │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 1: docker-entrypoint.sh                               │
├─────────────────────────────────────────────────────────────┤
│ 1. Print environment variables                              │
│ 2. Validate required env vars (exit if missing)             │
│ 3. Set default values for optional vars                     │
│ 4. Test rclone installation (exit if missing)               │
│ 5. Test Python installation (exit if missing)               │
│ 6. Test Python package imports (exit if failed)             │
│ 7. exec python3 /app/entrypoint.py                          │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2: entrypoint.py (main function)                      │
├─────────────────────────────────────────────────────────────┤
│ 1. Validate environment variables (exit if missing)         │
│ 2. Create working directory structure                       │
│ 3. setup_rclone_config()                                    │
│    └─> Write ~/.config/rclone/rclone.conf                   │
│                                                             │
│ 4. download_photogrammetry_products()                       │
│    ├─> downloads all files with dataset_name prefix         │
│    ├─> Downloads the files to /tmp/processing/input/        │
│    └─> Returns:str: The dataset/mission name                │
│                                                             │
│ 5. download_boundary_polygons(mission_name)                 │
│    ├─> Extract base mission names                           │
│    └─> Download .gpkg file to /tmp/processing/boundary/     │
│                                                             │
│ 6. detect_and_match_missions()                              │
│    ├─> Match products to boundary                           │
│                                                             │
│ 7. For the Dataset_name matched with a boundary             │
│    ├─> postprocess_photogrammetry_containerized()  ─-───┐   │
│    │   (calls Phase 3)                                  │   │
│    ├─> upload_processed_products()                      │   │
│    │   └─> rclone copyto to S3                          │   │
│    └─> Increment success_count                          │   │
│                                                         │   │
│ 8. cleanup_working_directory()                          │   │
│    └─> rm -rf /tmp/processing/                          │   │
│                                                         │   │
│ 9. Print summary                                        │   │
│ 10. Exit with appropriate code (0 or 1)                 │   │
└─────────────────────────────────────────────────────────┼─ ─┘
                                                          │
                                                          ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 3: postprocess.py                                     │
│ (postprocess_photogrammetry_containerized function)         │
├─────────────────────────────────────────────────────────────┤
│ 1. Validate boundary and product files exist                │
│    (raise FileNotFoundError if missing)                     │
│                                                             │
│ 2. Create output directories                                │
│    ├─> /tmp/processing/output/full/                         │
│    └─> /tmp/processing/output/thumbnails/                   │
│                                                             │
│ 3. Read mission boundary polygon (GeoDataFrame)             │
│                                                             │
│ 4. Build product DataFrame                                  │
│    ├─> Parse filenames to extract types                     │
│    └─> Generate output filenames                            │
│                                                             │
│ 5. FOR EACH raster (.tif/.tiff):                            │
│    └─> crop_raster_save_cog()                               │
│        ├─> Reproject polygon to raster CRS                  │
│        ├─> Crop raster to polygon boundary                  │
│        └─> Write as COG to output/full/                     │
│                                                             │
│ 6. Generate CHM (if DSM and DTM available):                 │
│    └─> make_chm()                                           │
│        ├─> Read DSM and DTM                                 │
│        ├─> Reproject DTM to match DSM                       │
│        ├─> Calculate CHM = DSM - DTM                        │
│        └─> Write CHM as COG to output/full/                 │
│                                                             │
│ 7. FOR EACH non-raster file:                                │
│    └─> Copy to output/full/                                 │
│                                                             │
│ 8. FOR EACH TIF in output/full/:                            │
│    └─> create_thumbnail()                                   │
│        ├─> Calculate scale factor                           │
│        ├─> Read raster at reduced resolution                │
│        ├─> Render with matplotlib                           │
│        └─> Save PNG to output/thumbnails/                   │
│                                                             | 
│ 9. Print statistics (file counts)                           │
│ 10. Return True                                             │
└────────────────┬────────────────────────────────────────────┘

```

---






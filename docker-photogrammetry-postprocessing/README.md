# Post-Processing Docker Image


## Overview

This Docker image provides automated post-processing of photogrammetry products from drone surveys. It downloads raw photogrammetry outputs (orthomosaics, DSMs, DTMs) and mission boundary polygons from S3 storage, crops rasters to mission boundaries, generates Canopy Height Models (CHMs), creates Cloud Optimized GeoTIFFs (COGs), produces PNG thumbnails, and uploads processed products back to S3 in organized mission-specific directories.

The current version PROCESSES ONE MISSION AT A TIME. You cannot use this standalone docker image to process multiple missions in an automated way. For that, please use Argo. 

The image is based on GDAL (Geospatial Data Abstraction Library) and includes Python geospatial tools (rasterio, geopandas) and rclone for S3 operations.

The docker image is located at `ghcr.io/open-forest-observatory/photogrammetry-postprocessing` and is attached as a package to this repo.

<br/>

## Input Requirements

For the standalone docker image to work, there needs to exist a directory in the `S3:ofo-internal` bucket that contains the metashape output imagery products (dsm, dtm, pointcloud, ortho). The directory structure must look like this:

```
/S3:ofo-internal/
├── <INPUT_DATA_DIRECTORY>/
        ├── dataset1_dsm-ptcloud.tif
        ├── dataset1_dtm-ptcloud.tif
        ├── dataset1_ortho-dtm-ptcloud.tif
        ├── dataset1_points-copc.laz
        └── dataset1_report.pdf
        ├── dataset2_dsm-ptcloud.tif
        ├── dataset2_dtm-ptcloud.tif
        ├── dataset2_ortho-dtm-ptcloud.tif
        ├── dataset2_points-copc.laz
        └── dataset2_report.pdf
```


## Run Command

```bash
docker run --rm \
  -e S3_ENDPOINT=https://js2.jetstream-cloud.org:8001 \
  -e S3_PROVIDER=Other \
  -e S3_ACCESS_KEY=<your_access_key> \
  -e S3_SECRET_KEY=<your_secret_key> \
  -e S3_BUCKET_PHOTOGRAMMETRY_OUTPUTS=ofo-internal \
  -e S3_PHOTOGRAMMETRY_DIR=gillan_oct10 \
  -e PHOTOGRAMMETRY_CONFIG_SUBFOLDER=photogrammetry_01 \
  -e S3_BUCKET_INPUT_BOUNDARY=ofo-public \
  -e INPUT_BOUNDARY_DIRECTORY=jgillan_test \
  -e S3_BUCKET_POSTPROCESSED_OUTPUTS=ofo-public \
  -e S3_POSTPROCESSED_DIR=jgillan_test \
  -e PROJECT_NAME=benchmarking-greasewood \
  -e OUTPUT_MAX_DIM=800 \
  -e TEMP_WORKING_DIR_POSTPROCESSING=/tmp/processing \
  ghcr.io/open-forest-observatory/photogrammetry-postprocessing:1.6
```

*S3_ENDPOINT* is the url of the Jetstream2s S3 storage

*S3_PROVIDER* keep as 'Other'

*S3_ACCESS_KEY* is the access key for OFOs S3 buckets

*S3_SECRET_KEY* is the secret key for OFOs S3 buckets

*S3_BUCKET_PHOTOGRAMMETRY_OUTPUTS* is the S3 bucket where existing Metashape products reside. Currently on 'ofo-internal'

*S3_PHOTOGRAMMETRY_DIR* is the parent directory in S3 where existing Metashape products reside. When combined with PHOTOGRAMMETRY_CONFIG_SUBFOLDER, the full path becomes `{S3_PHOTOGRAMMETRY_DIR}/{PHOTOGRAMMETRY_CONFIG_SUBFOLDER}/`.

*PHOTOGRAMMETRY_CONFIG_SUBFOLDER* **optional** parameter specifying the photogrammetry configuration subfolder name (e.g., `photogrammetry_01`, `photogrammetry_02`). Used to construct the input path (`{S3_PHOTOGRAMMETRY_DIR}/{PHOTOGRAMMETRY_CONFIG_SUBFOLDER}/`) and output directory (`{S3_POSTPROCESSED_DIR}/{mission_name}/{PHOTOGRAMMETRY_CONFIG_SUBFOLDER}/`). If not specified or set to empty string, products are read from and written to directories without the subfolder (e.g., `{S3_PHOTOGRAMMETRY_DIR}/` and `{S3_POSTPROCESSED_DIR}/{mission_name}/`).

*S3_BUCKET_INPUT_BOUNDARY* is the bucket where the mission boundary polygons reside. These are used to clip imagery products. Currently in `ofo-public`

*INPUT_BOUNDARY_DIRECTORY* is the parent directory where the mission boundary polygons reside.

*S3_BUCKET_POSTPROCESSED_OUTPUTS* is the bucket where the postprocessed products will be stored. 'ofo-public'

*S3_POSTPROCESSED_DIR* is the parent directory where the postprocessed products will be stored. Products are organized as `{S3_POSTPROCESSED_DIR}/{mission_name}/{PHOTOGRAMMETRY_CONFIG_SUBFOLDER}/` when the subfolder is specified, or `{S3_POSTPROCESSED_DIR}/{mission_name}/` when not specified.

*PROJECT_NAME* is the name of the project you want to process. This docker container will only process one project name.

*OUTPUT_MAX_DIM* **optional** parameter to specify the max dimensions of thumbnails. Defaults to 800 pixels.

*TEMP_WORKING_DIR_POSTPROCESSING* **optional** parameter specifying the directory within the container where the imagery products are downloaded to and postprocessed. The typical place is `/tmp/processing` which means the data will be downloaded to the processing computer and postprocessed there. You have the ability to change the TEMP_WORKING_DIR_POSTPROCESSING to a persistent volume (PVC).



<br/>
<br/>

## Outputs

```
S3:ofo-public/S3_POSTPROCESSED_DIR/dataset1/photogrammetry_01/
├── full/
│   ├── mission_ortho-dtm-ptcloud.tif
│   ├── mission_dsm-ptcloud.tif
│   ├── mission_dtm-ptcloud.tif
│   ├── mission_chm-ptcloud.tif
│   └── mission_points-copc.laz
└── thumbnails/
    ├── mission_ortho-dtm-ptcloud.png
    ├── mission_dsm-ptcloud.png
    ├── mission_dtm-ptcloud.png
    └── mission_chm-ptcloud.png
```
<br/>
<br/>
<br/>
<br/>

## Build Command

```bash
docker build -t ghcr.io/open-forest-observatory/photogrammetry-postprocessing:latest .
```

<br/>
<br/>
<br/>


## Post-Processing Docker Container Workflow

This document describes the sequential execution flow of the photogrammetry post-processing Docker container from startup to completion.

<br/>

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
│ 1. Set default values for optional env vars                 │
│    ├─> TEMP_WORKING_DIR_POSTPROCESSING (default: /tmp/processing) │
│    ├─> OUTPUT_MAX_DIM (default: 800)                        │
│    ├─> S3_PROVIDER (default: Other)                         │
│    ├─> S3_BUCKET_POSTPROCESSED_OUTPUTS (default: S3_BUCKET_PHOTOGRAMMETRY_OUTPUTS) │
│    └─> S3_POSTPROCESSED_DIR (default: processed)            │
│                                                             │
│ 2. Print environment variables                              │
│                                                             │
│ 3. Validate required env vars (exit if missing):            │
│    ├─> S3_ENDPOINT                                          │
│    ├─> S3_ACCESS_KEY                                        │
│    ├─> S3_SECRET_KEY                                        │
│    ├─> S3_BUCKET_PHOTOGRAMMETRY_OUTPUTS                     │
│    ├─> S3_BUCKET_INPUT_BOUNDARY                             │
│    └─> PROJECT_NAME                                         │
│                                                             │
│ 4. Test rclone installation (exit if missing)               │
│                                                             │
│ 5. exec python3 /app/entrypoint.py                          │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2: entrypoint.py (main function)                      │
├─────────────────────────────────────────────────────────────┤
│ 1. Validate TEMP_WORKING_DIR_POSTPROCESSING exists and is writable │
│    └─> Create directory if needed                           │
│                                                             │
│ 2. Create working directory structure                       │
│    ├─> $TEMP_WORKING_DIR_POSTPROCESSING/input/              │
│    ├─> $TEMP_WORKING_DIR_POSTPROCESSING/boundary/           │
│    └─> $TEMP_WORKING_DIR_POSTPROCESSING/output/             │
│                                                             │
│ 3. download_photogrammetry_products()                       │
│    ├─> Use rclone with S3 command-line flags                │
│    ├─> Download files matching PROJECT_NAME prefix          │
│    ├─> Save to $TEMP_WORKING_DIR_POSTPROCESSING/input/{project_name}/ │
│    └─> Return: project_name                                 │
│                                                             │
│ 4. download_boundary_polygons(mission_name)                 │
│    ├─> Extract base mission name (strip numeric prefix)     │
│    ├─> Use rclone with S3 command-line flags                │
│    └─> Download .gpkg to $TEMP_WORKING_DIR_POSTPROCESSING/boundary/{mission}/ │
│                                                             │
│ 5. detect_and_match_missions()                              │
│    ├─> Match product files to boundary file                 │
│    └─> Return: mission_match dict                           │
│                                                             │
│ 6. Process the matched mission:                             │
│    ├─> postprocess_photogrammetry_containerized()  ───────┐ │
│    │   (calls Phase 3)                                    │ │
│    │                                                      │ │
│    ├─> upload_processed_products(mission_id)              │ │
│    │   ├─> Get PHOTOGRAMMETRY_CONFIG_SUBFOLDER (may be empty) │ │
│    │   └─> Upload to S3:{mission_id}/{subfolder}/ (or skip subfolder if empty) │ │
│    │                                                      │ │
│    └─> cleanup_working_directory(mission_id)              │ │
│        ├─> Delete $TEMP_WORKING_DIR_POSTPROCESSING/input/{mission_id}/ │ │
│        ├─> Delete $TEMP_WORKING_DIR_POSTPROCESSING/boundary/{mission_id}/ │ │
│        ├─> Delete $TEMP_WORKING_DIR_POSTPROCESSING/output/full/{mission_id}_* │ │
│        └─> Delete $TEMP_WORKING_DIR_POSTPROCESSING/output/thumbnails/{mission_id}_* │ │
│                                                            │ │
│ 7. Print summary and exit                                  │ │
└────────────────────────────────────────────────────────────┼─┘
                                                             │
                                                             ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 3: postprocess.py                                     │
│ (postprocess_photogrammetry_containerized function)         │
├─────────────────────────────────────────────────────────────┤
│ 1. Validate inputs:                                         │
│    ├─> Boundary file exists                                 │
│    └─> Product files exist                                  │
│                                                             │
│ 2. Create output directories:                               │
│    ├─> $TEMP_WORKING_DIR_POSTPROCESSING/output/full/        │
│    └─> $TEMP_WORKING_DIR_POSTPROCESSING/output/thumbnails/  │
│                                                             │
│ 3. Read mission boundary polygon (GeoDataFrame)             │
│                                                             │
│ 4. Build product DataFrame:                                 │
│    ├─> Parse filenames to extract product types             │
│    └─> Generate output filenames                            │
│                                                             │
│ 5. FOR EACH raster file (.tif/.tiff):                       │
│    └─> crop_raster_save_cog()                               │
│        ├─> Reproject boundary polygon to raster CRS         │
│        ├─> Crop raster to polygon boundary                  │
│        └─> Write as Cloud Optimized GeoTIFF (COG)           │
│                                                             │
│ 6. Generate Canopy Height Models (CHMs):                    │
│    ├─> IF dsm-ptcloud AND dtm-ptcloud exist:                │
│    │   └─> make_chm() → chm-ptcloud.tif                     │
│    │                                                         │
│    └─> IF dsm-mesh AND dtm-ptcloud exist:                   │
│        └─> make_chm() → chm-mesh.tif                        │
│                                                             │
│    make_chm() logic:                                        │
│    ├─> Read DSM and DTM rasters                             │
│    ├─> Reproject DTM to match DSM CRS/resolution            │
│    ├─> Calculate: CHM = DSM - DTM                           │
│    └─> Write CHM as COG                                     │
│                                                             │
│ 7. FOR EACH non-raster file (.laz, .pdf, etc.):             │
│    └─> Copy directly to output/full/                        │
│                                                             │
│ 8. FOR EACH .tif file in output/full/:                      │
│    └─> create_thumbnail()                                   │
│        ├─> Calculate scale factor (max dim = OUTPUT_MAX_DIM)│
│        ├─> Read raster at reduced resolution                │
│        ├─> Render with matplotlib colormap                  │
│        └─> Save PNG to output/thumbnails/                   │
│                                                             │
│ 9. Print processing statistics                              │
│ 10. Return True (success)                                   │
└─────────────────────────────────────────────────────────────┘

```

---

<br/>

## Phase 1: Shell Validation (docker-entrypoint.sh)

The bash script performs initial validation and sets up the environment before handing off to Python.

### Key Responsibilities:
- **Single Source of Truth for Defaults**: All optional environment variable defaults are set here at the top of the script
- **Environment Validation**: Checks for required S3 credentials and configuration
- **Dependency Verification**: Confirms rclone is installed and functional
- **Fail-Fast Behavior**: Exits immediately if validation fails, preventing wasted S3 bandwidth

### Environment Variables Validated:
**Required** (container exits if missing):
- `S3_ENDPOINT` - S3 service endpoint URL
- `S3_ACCESS_KEY` - S3 access key
- `S3_SECRET_KEY` - S3 secret key
- `S3_BUCKET_PHOTOGRAMMETRY_OUTPUTS` - Bucket containing Metashape outputs
- `S3_BUCKET_INPUT_BOUNDARY` - Bucket containing mission boundary files
- `PROJECT_NAME` - Specific project to process

**Optional** (defaults applied):
- `TEMP_WORKING_DIR_POSTPROCESSING` → `/tmp/processing`
- `OUTPUT_MAX_DIM` → `800`
- `PHOTOGRAMMETRY_CONFIG_SUBFOLDER` → `""` (empty string, skips subfolder)
- `S3_PROVIDER` → `Other`
- `S3_BUCKET_POSTPROCESSED_OUTPUTS` → `{S3_BUCKET_PHOTOGRAMMETRY_OUTPUTS}`
- `S3_POSTPROCESSED_DIR` → `processed`

---

<br/>

## Phase 2: Python Orchestration (entrypoint.py)

The Python script orchestrates data movement between S3 and local filesystem, manages mission matching, and coordinates the processing pipeline.

### Key Functions:

#### `get_s3_flags()`
Builds rclone command-line flags for S3 authentication. Uses the **flag-based approach** (not config files) for consistency with Argo workflows.

Returns: `['--s3-provider', ..., '--s3-endpoint', ..., '--s3-access-key-id', ..., '--s3-secret-access-key', ...]`

#### `download_photogrammetry_products()`
Downloads Metashape outputs from flat S3 directory structure.

Process:
1. Reads `PROJECT_NAME` from environment
2. Uses rclone to copy files matching `{PROJECT_NAME}_*` pattern
3. Saves to `$TEMP_WORKING_DIR_POSTPROCESSING/input/{project_name}/`
4. Returns the project name

#### `download_boundary_polygons(mission_name)`
Downloads mission boundary polygon (`.gpkg` file) from nested S3 structure.

Process:
1. Constructs path: `{boundary_dir}/{mission_name}/metadata-mission/{mission_name}_mission-metadata.gpkg`
2. Downloads to `$TEMP_WORKING_DIR_POSTPROCESSING/boundary/{mission_name}/`
3. Returns True/False for success

#### `detect_and_match_missions()`
Matches photogrammetry products to boundary files for the single mission being processed.

Returns dict:
```python
{
    'prefix': 'project_name',
    'boundary_file': '/path/to/boundary.gpkg',
    'product_files': [list of file paths]
}
```

#### `upload_processed_products(mission_id)`
Uploads processed outputs to mission-specific S3 directories.

Process:
1. Reads `PHOTOGRAMMETRY_CONFIG_SUBFOLDER` environment variable (defaults to empty string)
2. Constructs remote path: `{mission_id}/{subfolder}/` (subfolder skipped if empty)
3. Uploads files from `$TEMP_WORKING_DIR_POSTPROCESSING/output/full/` and `thumbnails/`
4. Only uploads files matching `{mission_id}_*` pattern

Examples:
- `PHOTOGRAMMETRY_CONFIG_SUBFOLDER=''` (empty) → `mission/`
- `PHOTOGRAMMETRY_CONFIG_SUBFOLDER='photogrammetry_01'` → `mission/photogrammetry_01/`
- `PHOTOGRAMMETRY_CONFIG_SUBFOLDER='photogrammetry_02'` → `mission/photogrammetry_02/`

#### `cleanup_working_directory(mission_id)`
**Parallel-safe cleanup** that only deletes mission-specific files.

Deletes:
- `$TEMP_WORKING_DIR_POSTPROCESSING/input/{mission_id}/` (entire directory)
- `$TEMP_WORKING_DIR_POSTPROCESSING/boundary/{mission_id}/` (entire directory)
- `$TEMP_WORKING_DIR_POSTPROCESSING/output/full/{mission_id}_*` (files only)
- `$TEMP_WORKING_DIR_POSTPROCESSING/output/thumbnails/{mission_id}_*` (files only)

**Why mission-specific?** Multiple containers can safely share the same `TEMP_WORKING_DIR_POSTPROCESSING` (e.g., mounted PVC) during parallel Argo processing without interfering with each other.

#### `main()`
Primary execution function that coordinates the entire workflow:

1. Validates `TEMP_WORKING_DIR_POSTPROCESSING` exists and is writable
2. Downloads photogrammetry products
3. Downloads boundary polygon
4. Matches products to boundary
5. Calls `postprocess_photogrammetry_containerized()` (Phase 3)
6. Uploads processed products to S3
7. Cleans up mission-specific temporary files
8. Prints summary and exits

---

<br/>

## Phase 3: Geospatial Processing (postprocess.py)

The processing module performs raster operations, CHM generation, COG creation, and thumbnail rendering.

### Key Functions:

#### `crop_raster_save_cog(raster_filepath, output_filename, mission_polygon, output_path)`
Crops a raster to mission boundary and saves as Cloud Optimized GeoTIFF.

Process:
1. Opens source raster with rasterio
2. Reprojects mission polygon to match raster CRS
3. Masks raster using polygon geometry
4. Writes cropped raster as COG with compression

#### `make_chm(dsm_file, dtm_file, output_file)`
Generates a Canopy Height Model by subtracting DTM from DSM.

Process:
1. Opens DSM and DTM rasters
2. Reprojects DTM to match DSM CRS and resolution (if needed)
3. Calculates: `CHM = DSM - DTM` (pixel-wise subtraction)
4. Writes CHM as COG

**Important**: Two CHMs can be created independently:
- `chm-ptcloud` (if `dsm-ptcloud` and `dtm-ptcloud` exist)
- `chm-mesh` (if `dsm-mesh` and `dtm-ptcloud` exist)

#### `create_thumbnail(raster_path, thumbnail_path, max_dim)`
Generates PNG thumbnail from GeoTIFF with automatic colormap selection.

Process:
1. Calculates scale factor to fit within `max_dim` pixels
2. Reads raster at reduced resolution (using `out_shape` parameter)
3. Applies matplotlib colormap based on product type:
   - `ortho-*` → RGB (natural color)
   - `dsm-*`, `dtm-*` → `terrain` (elevation)
   - `chm-*` → `viridis` (height)
4. Saves as PNG with transparent background for nodata

#### `postprocess_photogrammetry_containerized(mission_id, boundary_file, product_files)`
Main processing coordinator called from `entrypoint.py`.

Workflow:
1. **Validate inputs**: Check boundary file and product files exist
2. **Create output directories**: `output/full/` and `output/thumbnails/`
3. **Read boundary**: Load mission polygon from `.gpkg` file
4. **Build product catalog**: Parse filenames to identify product types
5. **Process rasters**: Crop each `.tif`/`.tiff` file and save as COG
6. **Generate CHMs**: Create `chm-ptcloud` and/or `chm-mesh` if DEMs available
7. **Copy non-rasters**: Copy `.laz`, `.pdf`, and other files directly
8. **Create thumbnails**: Generate PNG thumbnails for all TIF files
9. **Print statistics**: Report file counts
10. **Return success**: `True` if completed without errors

---

<br/>

## Working Directory Structure

During processing, the `TEMP_WORKING_DIR_POSTPROCESSING` (default: `/tmp/processing`) contains:

```
$TEMP_WORKING_DIR_POSTPROCESSING/
├── input/
│   └── {project_name}/              # Downloaded Metashape products
│       ├── mission_dsm-ptcloud.tif
│       ├── mission_dtm-ptcloud.tif
│       └── ...
│
├── boundary/
│   └── {project_name}/              # Downloaded boundary files
│       └── mission_mission-metadata.gpkg
│
└── output/
    ├── full/                        # Processed COGs
    │   ├── mission_dsm-ptcloud.tif
    │   ├── mission_chm-ptcloud.tif
    │   └── ...
    │
    └── thumbnails/                  # PNG thumbnails
        ├── mission_dsm-ptcloud.png
        ├── mission_chm-ptcloud.png
        └── ...
```

**Parallel Processing Note**: Multiple containers can safely use the same `TEMP_WORKING_DIR_POSTPROCESSING` (e.g., mounted PVC) because cleanup is mission-specific. Each container only deletes its own mission's subdirectories and files.

---

<br/>

## S3 Output Structure

Processed products are uploaded to mission-specific directories:

```
S3:{S3_BUCKET_POSTPROCESSED_OUTPUTS}/{S3_POSTPROCESSED_DIR}/
└── {mission_name}/
    ├── photogrammetry_00/
    │   ├── full/
    │   │   ├── mission_ortho-dtm-ptcloud.tif
    │   │   ├── mission_dsm-ptcloud.tif
    │   │   ├── mission_dtm-ptcloud.tif
    │   │   ├── mission_chm-ptcloud.tif
    │   │   ├── mission_chm-mesh.tif
    │   │   └── mission_points-copc.laz
    │   └── thumbnails/
    │       ├── mission_ortho-dtm-ptcloud.png
    │       ├── mission_dsm-ptcloud.png
    │       ├── mission_dtm-ptcloud.png
    │       ├── mission_chm-ptcloud.png
    │       └── mission_chm-mesh.png
    │
    ├── photogrammetry_01/
    │   ├── full/
    │   └── thumbnails/
    │
    └── photogrammetry_02/
        ├── full/
        └── thumbnails/
```

The `photogrammetry_NN` subfolder is determined by the `PHOTOGRAMMETRY_CONFIG_SUBFOLDER` parameter. If the parameter is empty or not set, products are stored directly under the mission name without a subfolder.

---




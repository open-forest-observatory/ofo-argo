# Post-Processing Docker Image


## Overview

This Docker image provides automated post-processing of photogrammetry products from drone surveys. It downloads raw photogrammetry outputs (orthomosaics, DSMs, DTMs) and mission boundary polygons from S3 storage, crops rasters to mission boundaries, generates Canopy Height Models (CHMs), creates Cloud Optimized GeoTIFFs (COGs), produces PNG thumbnails, and uploads processed products back to S3 in organized mission-specific directories.

The current version PROCESSES ONE MISSION AT A TIME. You cannot use this standalone docker image to process multiple missions in an automated way. For that, please use Argo. 

The image is based on GDAL (Geospatial Data Abstraction Library) and includes Python geospatial tools (rasterio, geopandas) and rclone for S3 operations.

The docker image is located at `ghcr.io/open-forest-observatory/photogrammetry-postprocessing` and is attached as a package to this repo.

<br/>

## Input Requirements

For the standalone docker image to work, there needs to exist a directory in S3 (usually in the `ofo-internal` bucket) that contains the Metashape output imagery products (dsm, dtm, pointcloud, ortho). Files for a project are selected by the prefix `<project-name>_`. The directory structure must look like this:

```
S3:<s3-bucket-internal>/
└── <s3-photogrammetry-dir>/
    └── <photogrammetry-config-subfolder>/    # omitted if the subfolder is empty
        ├── dataset1_dsm-ptcloud.tif
        ├── dataset1_dtm-ptcloud.tif
        ├── dataset1_ortho-dtm-ptcloud.tif
        ├── dataset1_points.copc.laz
        ├── dataset1_cameras.xml
        ├── dataset1_report.pdf
        ├── dataset2_dsm-ptcloud.tif
        └── ...
```

The mission boundary polygon must exist at `S3:<s3-bucket-input-boundary>/<input-boundary-dir>/<project-name>/metadata-mission/<project-name>_mission-metadata.gpkg`.


## Run Command

S3 credentials are passed as environment variables, and everything else is passed as command-line arguments.

```bash
docker run --rm \
  -e S3_ENDPOINT=https://js2.jetstream-cloud.org:8001 \
  -e S3_PROVIDER=Other \
  -e RCLONE_S3_ACCESS_KEY_ID=<your_access_key> \
  -e RCLONE_S3_SECRET_ACCESS_KEY=<your_secret_key> \
  ghcr.io/open-forest-observatory/photogrammetry-postprocessing:latest \
  --project-name=benchmarking-greasewood \
  --s3-bucket-internal=ofo-internal \
  --s3-photogrammetry-dir=gillan_oct10 \
  --photogrammetry-config-subfolder=photogrammetry_01 \
  --s3-bucket-input-boundary=ofo-public \
  --input-boundary-dir=jgillan_test \
  --s3-bucket-public=ofo-public \
  --s3-postprocessed-dir=jgillan_test \
  --output-max-dim=800 \
  --working-dir=/tmp/processing
```

Outside of Docker, the same arguments can be passed to `python3 entrypoint.py` directly, with the S3 environment variables set and rclone installed. Run `python3 entrypoint.py --help` to list all arguments.

### Environment variables

*S3_ENDPOINT* is the url of the Jetstream2s S3 storage

*S3_PROVIDER* **optional**, keep as 'Other' (the default)

*RCLONE_S3_ACCESS_KEY_ID* is the access key for OFOs S3 buckets

*RCLONE_S3_SECRET_ACCESS_KEY* is the secret key for OFOs S3 buckets

### Arguments

*--project-name* is the name of the project you want to process. This docker container will only process one project name.

*--s3-bucket-internal* is the S3 bucket for internal/intermediate outputs where raw Metashape products (orthomosaics, point clouds, DEMs) reside. Currently `ofo-internal`.

*--s3-photogrammetry-dir* is the S3 prefix (directory) within `--s3-bucket-internal` where existing Metashape products reside. When combined with `--photogrammetry-config-subfolder`, the full path becomes `{s3-photogrammetry-dir}/{photogrammetry-config-subfolder}/`.

*--photogrammetry-config-subfolder* **optional** argument specifying the photogrammetry configuration subfolder name (e.g., `photogrammetry_01`, `photogrammetry_02`). Used to construct the input path (`{s3-photogrammetry-dir}/{photogrammetry-config-subfolder}/`) and output directory (`{s3-postprocessed-dir}/{mission_name}/{photogrammetry-config-subfolder}/`). If not specified or set to empty string, products are read from and written to directories without the subfolder (e.g., `{s3-photogrammetry-dir}/` and `{s3-postprocessed-dir}/{mission_name}/`).

*--s3-bucket-input-boundary* is the bucket where the mission boundary polygons reside. These are used to clip imagery products. Currently in `ofo-public` (same as `--s3-bucket-public`).

*--input-boundary-dir* is the S3 prefix (directory) within `--s3-bucket-input-boundary` where the mission boundary polygons reside. Expected subdirectory structure: `<input-boundary-dir>/<mission_name>/metadata-mission/<mission_name>_mission-metadata.gpkg`.  Example: drone/missions_03

*--s3-bucket-public* is the S3 bucket for public/final outputs (postprocessed, clipped products ready for distribution). Currently `ofo-public`.

*--s3-postprocessed-dir* **optional** argument for the S3 prefix (directory) within `--s3-bucket-public` where the postprocessed products will be stored. Defaults to `processed`. Products are organized as `{s3-postprocessed-dir}/{mission_name}/{photogrammetry-config-subfolder}/` when the subfolder is specified, or `{s3-postprocessed-dir}/{mission_name}/` when not specified. Example: drone/missions_03

*--output-max-dim* **optional** argument to specify the max dimensions of thumbnails. Defaults to 800 pixels.

*--working-dir* **optional** argument specifying the local directory within the container where the imagery products are downloaded to and postprocessed. Defaults to `/tmp/processing`, which means the data will be downloaded to the processing computer and postprocessed there. You have the ability to change the working directory to a persistent volume (PVC) if it's already mounted in the filesystem. **The entire working directory is deleted when the run finishes**, so point it at a dedicated directory.



<br/>
<br/>

## Outputs

```
S3:ofo-public/<s3-postprocessed-dir>/dataset1/photogrammetry_01/
├── full/
│   ├── mission_ortho-dtm-ptcloud.tif
│   ├── mission_dsm-ptcloud.tif
│   ├── mission_dtm-ptcloud.tif
│   ├── mission_chm-ptcloud.tif
│   ├── mission_points.copc.laz
│   ├── mission_camera-locations.gpkg
│   └── ...
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
docker run → Dockerfile ENTRYPOINT → entrypoint.py → postprocess.py
```

When the container starts, it follows this three-phase execution sequence:

1. **Phase 1**: Argument parsing and validation (`entrypoint.py`)
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
│ PHASE 1: entrypoint.py (parse_args, validate_environment)   │
├─────────────────────────────────────────────────────────────┤
│ 1. Parse command-line arguments (exit if required missing)  │
│    └─> Apply defaults for optional arguments                │
│                                                             │
│ 2. Print configuration                                      │
│                                                             │
│ 3. Validate required env vars (exit if missing):            │
│    ├─> S3_ENDPOINT                                          │
│    ├─> RCLONE_S3_ACCESS_KEY_ID                              │
│    └─> RCLONE_S3_SECRET_ACCESS_KEY                          │
│                                                             │
│ 4. Check rclone is installed (exit if missing)              │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2: entrypoint.py (main function)                      │
├─────────────────────────────────────────────────────────────┤
│ 1. Validate working directory exists and is writable        │
│    └─> Create directory if needed                           │
│                                                             │
│ 2. Create working directory structure                       │
│    ├─> $WORKING_DIR/input/                                  │
│    ├─> $WORKING_DIR/boundary/                               │
│    └─> $WORKING_DIR/output/                                 │
│                                                             │
│ 3. download_photogrammetry_products()                       │
│    ├─> Use rclone with S3 command-line flags                │
│    ├─> Download files matching {project_name}_* prefix      │
│    ├─> Save to $WORKING_DIR/input/                          │
│    └─> Return: project_name                                 │
│                                                             │
│ 4. download_boundary_polygons()                             │
│    ├─> Use rclone with S3 command-line flags                │
│    └─> Download .gpkg to $WORKING_DIR/boundary/             │
│                                                             │
│ 5. detect_and_match_missions()                              │
│    ├─> Match product files to boundary file                 │
│    └─> Return: mission_match dict                           │
│                                                             │
│ 6. Process the matched mission:                             │
│    ├─> postprocess_photogrammetry_containerized()           │
│    │   (calls Phase 3)                                      │
│    │                                                        │
│    ├─> upload_processed_products()                          │
│    │   └─> Upload $WORKING_DIR/output/ to                   │
│    │       S3:{mission_id}/{subfolder}/                     │
│    │       (subfolder skipped if empty)                     │
│    │                                                        │
│    └─> cleanup_working_directory()                          │
│        └─> Delete the entire $WORKING_DIR                   │
│            (also runs if processing fails)                  │
│                                                             │
│ 7. Print summary and exit                                   │
└────────────────┬────────────────────────────────────────────┘
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
│    ├─> $WORKING_DIR/output/full/                            │
│    └─> $WORKING_DIR/output/thumbnails/                      │
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
│    │                                                        │
│    └─> IF dsm-mesh AND dtm-ptcloud exist:                   │
│        └─> make_chm() → chm-mesh.tif                        │
│                                                             │
│    make_chm() logic:                                        │
│    ├─> Read DSM and DTM rasters                             │
│    ├─> Reproject DTM to match DSM CRS/resolution            │
│    └─> Calculate: CHM = DSM - DTM                           │
│    (the CHM is then written as a COG)                       │
│                                                             │
│ 7. FOR EACH .tif file in output/full/:                      │
│    └─> create_thumbnail()                                   │
│        ├─> Scale to fit --output-max-dim                    │
│        ├─> Read raster at reduced resolution                │
│        ├─> Render with matplotlib                           │
│        └─> Save PNG to output/thumbnails/                   │
│                                                             │
│ 8. IF cameras.xml AND dtm-ptcloud exist:                    │
│    └─> compute_height_above_ground()                        │
│        └─> Write camera-locations.gpkg to output/full/      │
│                                                             │
│ 9. FOR EACH non-raster file (.laz, .pdf, .xml, etc.):       │
│    └─> Copy directly to output/full/                        │
│                                                             │
│ 10. Print processing statistics                             │
│ 11. Return True (success)                                   │
└─────────────────────────────────────────────────────────────┘

```

---

<br/>

## Phase 1: Argument Parsing and Validation (entrypoint.py)

`parse_args()` and `validate_environment()` check the configuration before any data is transferred.

### Key Responsibilities:
- **Single Source of Truth for Defaults**: All defaults for optional arguments are set in `parse_args()`
- **Configuration Validation**: argparse exits if a required argument is missing; `validate_environment()` exits if an S3 credential is missing
- **Dependency Verification**: Confirms rclone is installed
- **Fail-Fast Behavior**: Exits immediately if validation fails, preventing wasted S3 bandwidth

### Required (container exits if missing):
Environment variables:
- `S3_ENDPOINT` - S3 service endpoint URL
- `RCLONE_S3_ACCESS_KEY_ID` - S3 access key
- `RCLONE_S3_SECRET_ACCESS_KEY` - S3 secret key

Arguments:
- `--project-name` - Specific project to process
- `--s3-bucket-internal` - Bucket containing raw Metashape outputs (internal/intermediate)
- `--s3-photogrammetry-dir` - Directory containing the Metashape outputs
- `--s3-bucket-input-boundary` - Bucket containing mission boundary files
- `--input-boundary-dir` - Directory containing mission boundary files
- `--s3-bucket-public` - Bucket for the final postprocessed outputs

### Optional (defaults applied):
- `S3_PROVIDER` → `Other`
- `--photogrammetry-config-subfolder` → `""` (empty string, skips subfolder)
- `--s3-postprocessed-dir` → `processed`
- `--working-dir` → `/tmp/processing`
- `--output-max-dim` → `800`

---

<br/>

## Phase 2: Python Orchestration (entrypoint.py)

The Python script orchestrates data movement between S3 and local filesystem, manages mission matching, and coordinates the processing pipeline.

### Key Functions:

#### `get_s3_flags()`
Builds rclone command-line flags for S3. Uses the **flag-based approach** (not config files) for consistency with Argo workflows. Credentials are not passed as flags; rclone reads `RCLONE_S3_ACCESS_KEY_ID` and `RCLONE_S3_SECRET_ACCESS_KEY` from the environment directly (every rclone flag can be set as an `RCLONE_*` env var), so they don't appear in the process list.

Returns: `['--s3-provider', ..., '--s3-endpoint', ...]`

#### `download_photogrammetry_products(project_name, input_bucket, s3_photogrammetry_dir, photogrammetry_config_subfolder, working_dir)`
Downloads Metashape outputs from flat S3 directory structure.

Process:
1. Builds the remote path `{s3-bucket-internal}/{s3-photogrammetry-dir}/{photogrammetry-config-subfolder}` (subfolder skipped if empty)
2. Uses rclone to copy files matching `{project_name}_*` pattern
3. Saves to `$WORKING_DIR/input/`
4. Exits if no matching files are found
5. Returns the project name

#### `download_boundary_polygons(mission_name, boundary_bucket, boundary_base_dir, working_dir)`
Downloads mission boundary polygon (`.gpkg` file) from nested S3 structure.

Process:
1. Constructs path: `{input-boundary-dir}/{mission_name}/metadata-mission/{mission_name}_mission-metadata.gpkg`
2. Downloads to `$WORKING_DIR/boundary/`
3. Returns True/False for success

#### `detect_and_match_missions(project_name, working_dir)`
Matches photogrammetry products to boundary files for the single mission being processed.

Returns dict:
```python
{
    'prefix': 'project_name',
    'boundary_file': '/path/to/boundary.gpkg',
    'product_files': [list of file paths]
}
```

#### `upload_processed_products(mission_id, output_bucket, s3_postprocessed_dir, photogrammetry_config_subfolder, working_dir)`
Uploads processed outputs to mission-specific S3 directories.

Process:
1. Constructs remote path: `{s3-bucket-public}/{s3-postprocessed-dir}/{mission_id}/{subfolder}/` (subfolder skipped if empty)
2. Uploads the whole `$WORKING_DIR/output/` directory (`full/` and `thumbnails/`)

Examples:
- `--photogrammetry-config-subfolder=` (empty) → `mission/`
- `--photogrammetry-config-subfolder=photogrammetry_01` → `mission/photogrammetry_01/`
- `--photogrammetry-config-subfolder=photogrammetry_02` → `mission/photogrammetry_02/`

#### `cleanup_working_directory(working_dir)`
Deletes the entire working directory. This runs after a successful upload and also when processing fails.

**Parallel processing:** in Argo, each project gets its own working directory (`{TEMP_WORKING_DIR}/{workflow-name}/{project-name}/postprocessing`), so parallel runs don't interfere. When running standalone, give each run its own `--working-dir`, and don't point it at a directory containing anything you want to keep.

#### `main()`
Primary execution function that coordinates the entire workflow:

1. Prints the configuration and validates the environment (Phase 1)
2. Validates the working directory exists and is writable
3. Downloads photogrammetry products
4. Downloads boundary polygon
5. Matches products to boundary
6. Calls `postprocess_photogrammetry_containerized()` (Phase 3)
7. Uploads processed products to S3
8. Deletes the working directory
9. Prints summary and exits

---

<br/>

## Phase 3: Geospatial Processing (postprocess.py)

The processing module performs raster operations, CHM generation, COG creation, and thumbnail rendering.

### Key Functions:

#### `crop_raster_save_cog(raster_filepath, output_filepath, mission_polygon)`
Crops a raster to mission boundary and saves as Cloud Optimized GeoTIFF.

Process:
1. Opens source raster with rasterio
2. Reprojects mission polygon to match raster CRS
3. Masks raster using polygon geometry (RGB orthomosaics get a 4-band output with an alpha mask)
4. Writes cropped raster as COG with compression

#### `make_chm(dsm_filepath, dtm_filepath)`
Generates a Canopy Height Model by subtracting DTM from DSM.

Process:
1. Opens DSM and DTM rasters
2. Reprojects DTM to match DSM CRS and resolution (if needed)
3. Calculates: `CHM = DSM - DTM` (pixel-wise subtraction; nodata in either input gives nodata)
4. Returns `(chm_array, profile)`; the caller writes it as a COG

**Important**: Two CHMs can be created independently:
- `chm-ptcloud` (if `dsm-ptcloud` and `dtm-ptcloud` exist)
- `chm-mesh` (if `dsm-mesh` and `dtm-ptcloud` exist)

#### `create_thumbnail(tif_filepath, output_path, max_dim=800)`
Generates PNG thumbnail from GeoTIFF.

Process:
1. Calculates scale factor to fit within `max_dim` pixels
2. Reads raster at reduced resolution (using `out_shape` parameter)
3. Renders based on band count:
   - Single-band (DSM, DTM, CHM) → `viridis` colormap, nodata transparent
   - 4-band uint8 (RGB + alpha) → RGBA, using the alpha band for transparency
   - 3+ bands → RGB from the first 3 bands
4. Saves as PNG with transparent background

#### `postprocess_photogrammetry_containerized(mission_id, boundary_file_path, product_file_paths, working_dir, output_max_dim=800)`
Main processing coordinator called from `entrypoint.py`.

Workflow:
1. **Validate inputs**: Check boundary file and product files exist
2. **Create output directories**: `output/full/` and `output/thumbnails/`
3. **Read boundary**: Load mission polygon from `.gpkg` file
4. **Build product catalog**: Parse filenames to identify product types
5. **Process rasters**: Crop each `.tif`/`.tiff` file and save as COG
6. **Generate CHMs**: Create `chm-ptcloud` and/or `chm-mesh` if DEMs available
7. **Create thumbnails**: Generate PNG thumbnails for all TIF files
8. **Compute camera heights**: If `cameras.xml` and `dtm-ptcloud` exist, write `camera-locations.gpkg` with each aligned camera's height above ground
9. **Copy non-rasters**: Copy `.laz`, `.pdf`, `.xml`, and other files directly
10. **Print statistics**: Report file counts
11. **Return success**: `True` if completed; any failed product raises an exception, so an incomplete product set is never uploaded

---

<br/>

## Working Directory Structure

During processing, the working directory (`--working-dir`, default: `/tmp/processing`) contains:

```
$WORKING_DIR/
├── input/                           # Downloaded Metashape products
│   ├── mission_dsm-ptcloud.tif
│   ├── mission_dtm-ptcloud.tif
│   └── ...
│
├── boundary/                        # Downloaded boundary file
│   └── mission_mission-metadata.gpkg
│
└── output/
    ├── full/                        # Processed COGs and copied files
    │   ├── mission_dsm-ptcloud.tif
    │   ├── mission_chm-ptcloud.tif
    │   └── ...
    │
    └── thumbnails/                  # PNG thumbnails
        ├── mission_dsm-ptcloud.png
        ├── mission_chm-ptcloud.png
        └── ...
```

The whole directory is deleted at the end of the run (see `cleanup_working_directory()` above).

---

<br/>

## S3 Output Structure

Processed products are uploaded to mission-specific directories:

```
S3:{s3-bucket-public}/{s3-postprocessed-dir}/
└── {mission_name}/
    ├── photogrammetry_00/
    │   ├── full/
    │   │   ├── mission_ortho-dtm-ptcloud.tif
    │   │   ├── mission_dsm-ptcloud.tif
    │   │   ├── mission_dtm-ptcloud.tif
    │   │   ├── mission_chm-ptcloud.tif
    │   │   ├── mission_chm-mesh.tif
    │   │   └── mission_points.copc.laz
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

The `photogrammetry_NN` subfolder is determined by the `--photogrammetry-config-subfolder` argument. If the parameter is empty or not set, products are stored directly under the mission name without a subfolder.

---

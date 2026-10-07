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
        ├── dataset1_points.copc.laz
        └── dataset1_report.pdf
        ├── dataset2_dsm-ptcloud.tif
        ├── dataset2_dtm-ptcloud.tif
        ├── dataset2_ortho-dtm-ptcloud.tif
        ├── dataset2_points.copc.laz
        └── dataset2_report.pdf
```


## Run Command

S3 credentials are passed as environment variables, and everything else is passed as command-line arguments.

```bash
docker run --rm \
  -e S3_ENDPOINT=https://js2.jetstream-cloud.org:8001 \
  -e S3_PROVIDER=Other \
  -e AWS_ACCESS_KEY_ID=<your_access_key> \
  -e AWS_SECRET_ACCESS_KEY=<your_secret_key> \
  ghcr.io/open-forest-observatory/photogrammetry-postprocessing:1.6 \
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

*AWS_ACCESS_KEY_ID* is the access key for OFOs S3 buckets

*AWS_SECRET_ACCESS_KEY* is the secret key for OFOs S3 buckets

### Arguments

*--project-name* is the name of the project you want to process. This docker container will only process one project name.

*--s3-bucket-internal* is the S3 bucket for internal/intermediate outputs where raw Metashape products (orthomosaics, point clouds, DEMs) reside. Currently `ofo-internal`.

*--s3-photogrammetry-dir* is the parent directory in S3 where existing Metashape products reside. When combined with `--photogrammetry-config-subfolder`, the full path becomes `{s3-photogrammetry-dir}/{photogrammetry-config-subfolder}/`.

*--photogrammetry-config-subfolder* **optional** argument specifying the photogrammetry configuration subfolder name (e.g., `photogrammetry_01`, `photogrammetry_02`). Used to construct the input path (`{s3-photogrammetry-dir}/{photogrammetry-config-subfolder}/`) and output directory (`{s3-postprocessed-dir}/{mission_name}/{photogrammetry-config-subfolder}/`). If not specified or set to empty string, products are read from and written to directories without the subfolder (e.g., `{s3-photogrammetry-dir}/` and `{s3-postprocessed-dir}/{mission_name}/`).

*--s3-bucket-input-boundary* is the bucket where the mission boundary polygons reside. These are used to clip imagery products. Currently in `ofo-public` (same as `--s3-bucket-public`).

*--input-boundary-dir* is the parent directory in `--s3-bucket-input-boundary` where the mission boundary polygons reside. Expected subdirectory structure: `<input-boundary-dir>/<mission_name>/metadata-mission/<mission_name>_mission-metadata.gpkg`.

*--s3-bucket-public* is the S3 bucket for public/final outputs (postprocessed, clipped products ready for distribution). Currently `ofo-public`.

*--s3-postprocessed-dir* **optional** argument for the parent directory where the postprocessed products will be stored. Defaults to `processed`. Products are organized as `{s3-postprocessed-dir}/{mission_name}/{photogrammetry-config-subfolder}/` when the subfolder is specified, or `{s3-postprocessed-dir}/{mission_name}/` when not specified.

*--output-max-dim* **optional** argument to specify the max dimensions of thumbnails. Defaults to 800 pixels.

*--working-dir* **optional** argument specifying the directory within the container where the imagery products are downloaded to and postprocessed. Defaults to `/tmp/processing`, which means the data will be downloaded to the processing computer and postprocessed there. You have the ability to change the working directory to a persistent volume (PVC).



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
│   └── mission_points.copc.laz
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
│ PHASE 1: entrypoint.py (parse_args, validate_environment)  │
├─────────────────────────────────────────────────────────────┤
│ 1. Parse command-line arguments (exit if required missing) │
│    └─> Apply defaults for optional arguments                │
│                                                             │
│ 2. Print configuration                                      │
│                                                             │
│ 3. Validate required env vars (exit if missing):            │
│    ├─> S3_ENDPOINT                                          │
│    ├─> AWS_ACCESS_KEY_ID                                    │
│    └─> AWS_SECRET_ACCESS_KEY                                │
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
│    ├─> $WORKING_DIR/input/              │
│    ├─> $WORKING_DIR/boundary/           │
│    └─> $WORKING_DIR/output/             │
│                                                             │
│ 3. download_photogrammetry_products()                       │
│    ├─> Use rclone with S3 command-line flags                │
│    ├─> Download files matching project name prefix          │
│    ├─> Save to $WORKING_DIR/input/{project_name}/ │
│    └─> Return: project_name                                 │
│                                                             │
│ 4. download_boundary_polygons(mission_name)                 │
│    ├─> Extract base mission name (strip numeric prefix)     │
│    ├─> Use rclone with S3 command-line flags                │
│    └─> Download .gpkg to $WORKING_DIR/boundary/{mission}/ │
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
│    │   ├─> Use photogrammetry config subfolder (may be empty) │ │
│    │   └─> Upload to S3:{mission_id}/{subfolder}/ (or skip subfolder if empty) │ │
│    │                                                      │ │
│    └─> cleanup_working_directory(mission_id)              │ │
│        ├─> Delete $WORKING_DIR/input/{mission_id}/ │ │
│        ├─> Delete $WORKING_DIR/boundary/{mission_id}/ │ │
│        ├─> Delete $WORKING_DIR/output/full/{mission_id}_* │ │
│        └─> Delete $WORKING_DIR/output/thumbnails/{mission_id}_* │ │
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
│    ├─> $WORKING_DIR/output/full/        │
│    └─> $WORKING_DIR/output/thumbnails/  │
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
│        ├─> Calculate scale factor (max dim = --output-max-dim)│
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
- `AWS_ACCESS_KEY_ID` - S3 access key
- `AWS_SECRET_ACCESS_KEY` - S3 secret key

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
Builds rclone command-line flags for S3. Uses the **flag-based approach** (not config files) for consistency with Argo workflows. Credentials are not passed as flags; `--s3-env-auth` makes rclone read `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` from the environment, so they don't appear in the process list.

Returns: `['--s3-provider', ..., '--s3-endpoint', ..., '--s3-env-auth']`

#### `download_photogrammetry_products()`
Downloads Metashape outputs from flat S3 directory structure.

Process:
1. Takes the project name from `--project-name`
2. Uses rclone to copy files matching `{project_name}_*` pattern
3. Saves to `$WORKING_DIR/input/{project_name}/`
4. Returns the project name

#### `download_boundary_polygons(mission_name)`
Downloads mission boundary polygon (`.gpkg` file) from nested S3 structure.

Process:
1. Constructs path: `{boundary_dir}/{mission_name}/metadata-mission/{mission_name}_mission-metadata.gpkg`
2. Downloads to `$WORKING_DIR/boundary/{mission_name}/`
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
1. Takes the photogrammetry config subfolder from `--photogrammetry-config-subfolder` (defaults to empty string)
2. Constructs remote path: `{mission_id}/{subfolder}/` (subfolder skipped if empty)
3. Uploads files from `$WORKING_DIR/output/full/` and `thumbnails/`
4. Only uploads files matching `{mission_id}_*` pattern

Examples:
- `--photogrammetry-config-subfolder=` (empty) → `mission/`
- `--photogrammetry-config-subfolder=photogrammetry_01` → `mission/photogrammetry_01/`
- `--photogrammetry-config-subfolder=photogrammetry_02` → `mission/photogrammetry_02/`

#### `cleanup_working_directory(mission_id)`
**Parallel-safe cleanup** that only deletes mission-specific files.

Deletes:
- `$WORKING_DIR/input/{mission_id}/` (entire directory)
- `$WORKING_DIR/boundary/{mission_id}/` (entire directory)
- `$WORKING_DIR/output/full/{mission_id}_*` (files only)
- `$WORKING_DIR/output/thumbnails/{mission_id}_*` (files only)

**Why mission-specific?** Multiple containers can safely share the same working directory (e.g., mounted PVC) during parallel Argo processing without interfering with each other.

#### `main()`
Primary execution function that coordinates the entire workflow:

1. Validates the working directory exists and is writable
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

#### `postprocess_photogrammetry_containerized(mission_id, boundary_file, product_files, working_dir, output_max_dim)`
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

During processing, the working directory (`--working-dir`, default: `/tmp/processing`) contains:

```
$WORKING_DIR/
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

**Parallel Processing Note**: Multiple containers can safely use the same working directory (e.g., mounted PVC) because cleanup is mission-specific. Each container only deletes its own mission's subdirectories and files.

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




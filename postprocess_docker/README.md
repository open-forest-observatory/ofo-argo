# Post-Processing Docker Image


## Overview

This Docker image provides automated post-processing of photogrammetry products from drone surveys. It downloads raw photogrammetry outputs (orthomosaics, DSMs, DTMs) and mission boundary polygons from S3 storage, crops rasters to mission boundaries, generates Canopy Height Models (CHMs), creates Cloud Optimized GeoTIFFs (COGs), produces PNG thumbnails, and uploads processed products back to S3 in organized mission-specific directories.

The image is based on GDAL (Geospatial Data Abstraction Library) and includes Python geospatial tools (rasterio, geopandas) and rclone for S3 operations.

The docker image is located at `ghcr.io/open-forest-observatory/photogrammetry-postprocess:1.2` and is attached as a package to this repo.

<br/>

## Input Requirements

For the standalone docker image to work, there needs to exist a directory in the `S3:ofo-internal` bucket that contains the metashape output imagery products (dsm, dtm, pointcloud, ortho). The directory structure must look like this:

```
/S3:ofo-internal/
├── <INPUT_DATA_DIRECTORY>/
    ├── 01_dataset1/
        ├── 01_dataset1_dsm-ptcloud.tif
        ├── 01_dataset1_dtm-ptcloud.tif
        ├── 01_dataset1_ortho-dtm-ptcloud.tif
        ├── 01_dataset1_points-copc.laz
        └── 01_dataset1_report.pdf
    ├── 02_dataset1/
        ├── 02_dataset1_dsm-ptcloud.tif
        ├── 02_dataset1_dtm-ptcloud.tif
        ├── 02_dataset1_ortho-dtm-ptcloud.tif
        ├── 02_dataset1_points-copc.laz
        └── 02_dataset1_report.pdf
    ├── 01_dataset2/
        ├── 01_dataset2_dsm-ptcloud.tif
        ├── 01_dataset2_dtm-ptcloud.tif
        ├── 01_dataset2_ortho-dtm-ptcloud.tif
        ├── 01_dataset2_points-copc.laz
        └── 01_dataset2_report.pdf
    ├── 02_dataset2/
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
  ghcr.io/open-forest-observatory/photogrammetry-postprocess:1.2
```

*S3_ENDPOINT* is the url of the Jetstream2s S3 storage

*S3_PROVIDER* keep as 'Other'

*S3_ACCESS_KEY* is the access key for OFOs S3 buckets

*S3_SECRET_KEY* is the secret key for OFOs S3 buckets

*S3_BUCKET_INPUT_DATA* is the S3 bucket where existing Metashape products reside. Currently on 'ofo-internal'

*INPUT_DATA_DIRECTORY* is the parent directory where existing Metashape products reside.

*S3_BUCKET_INPUT_BOUNDARY* is the bucket where the mission boundary polygons reside. These are used to clip imagery products.

*INPUT_BOUNDARY_DIRECTORY* is the parent directory where the mission boundary polygons reside.

*S3_BUCKET_OUTPUT* is the bucket where the postprocessed products will be stored. 'ofo-public'

*OUTPUT_DIRECTORY* is the parent directory where the postprocessed products will be stored

*DATASET_NAME* **optional** parameter if you want to postprocess a single config and dataset. If omitted, all datasets in the *INPUT_DATA_DIRECTORY* will be postprocessed. 

*OUTPUT_MAX_DIM* **optional** parameter to specify the max dimensions of thumbnails. Defaults to 800 pixels.

*WORKING_DIR* **optional** parameter specifying the directory within the container where the imagery products are downloaded to and postprocessed. The typical place is`/tmp/processing` which means the data will be downloaded to the processing computer and postprocessed there. You have the ability to change the WORKING_DIR to a persistent volume (PVC).



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
│    ├─> Discover missions with rclone lsd                    │
│    ├─> Download each mission to /tmp/processing/input/      │
│    └─> Return mission_dirs list                             │
│                                                             │
│ 5. download_boundary_polygons(mission_dirs)                 │
│    ├─> Extract base mission names                           │
│    ├─> Download .gpkg files to /tmp/processing/boundary/    │
│    └─> Return download count                                │
│                                                             │
│ 6. detect_and_match_missions()                              │
│    ├─> Match products to boundaries                         │
│    └─> Return list of mission match dicts                   │
│                                                             │
│ 7. FOR EACH mission in mission_matches:                     │
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
                 │
                 ▼
         Return to Phase 2
    (upload and continue loop)
```

---




<br/>
<br/>
<br/>

## Phase 1: docker-entrypoint.sh (Shell Validation Layer)

**File**: `docker-entrypoint.sh` (Lines 1-78)
**Language**: Bash
**Purpose**: Validate environment and dependencies before starting Python processing

### Step 1.1: Environment Variable Validation

The script first prints all configuration values and validates required environment variables:

```bash
Required variables checked:
- S3_ENDPOINT
- S3_ACCESS_KEY
- S3_SECRET_KEY
- S3_BUCKET_INPUT_DATA
- S3_BUCKET_INPUT_BOUNDARY
```

**Exit condition**: If any required variable is missing, the script exits with code 1 and prints missing variable names.

### Step 1.2: Set Default Values

Optional variables are set to defaults if not provided:

```bash
WORKING_DIR (default: /tmp/processing)
OUTPUT_MAX_DIM (default: 800)
S3_BUCKET_OUTPUT (default: same as S3_BUCKET_INPUT_DATA)
OUTPUT_DIRECTORY (default: processed)
```

### Step 1.3: Test rclone Installation

Verifies rclone is available and prints version:

```bash
command -v rclone
rclone version
```

**Exit condition**: Exits with code 1 if rclone is not found.

### Step 1.4: Test Python and Package Imports

Tests Python 3 availability and attempts to import all required packages:

```python
import rasterio
import geopandas
import numpy
import pandas
import matplotlib
```

**Exit condition**: Exits with code 1 if Python is missing or any package fails to import.

### Step 1.5: Hand Control to Python

If all validation passes, the script executes the Python entrypoint:

```bash
exec python3 /app/entrypoint.py "$@"
```

The `exec` command replaces the shell process with Python, making Python the main container process (PID 1).

---

<br/>
<br/>
<br/>

## Phase 2: entrypoint.py (Orchestration Layer)

**File**: `entrypoint.py` (Lines 1-447)
**Language**: Python
**Purpose**: Coordinate S3 operations, mission detection, and processing workflow

### Step 2.1: Environment Validation (Redundant Check)

The `main()` function validates required environment variables again (entrypoint.py:354-366):

```python
required_vars = [
    'S3_ENDPOINT',
    'S3_ACCESS_KEY',
    'S3_SECRET_KEY',
    'S3_BUCKET_INPUT_DATA',
    'S3_BUCKET_INPUT_BOUNDARY'
]
```

**Exit condition**: Exits with code 1 if any are missing.

### Step 2.2: Setup Working Directory

Creates the working directory structure (entrypoint.py:369-370):

```python
/tmp/processing/
├── input/
├── boundary/
├── output/
│   ├── full/
│   └── thumbnails/
└── temp/
```

### Step 2.3: Configure rclone

Calls `setup_rclone_config()` (entrypoint.py:64-88) to create `~/.config/rclone/rclone.conf`:

```ini
[s3remote]
type = s3
provider = <S3_PROVIDER>
access_key_id = <S3_ACCESS_KEY>
secret_access_key = <S3_SECRET_KEY>
endpoint = <S3_ENDPOINT>
```

This configuration allows rclone to connect to S3-compatible storage.

### Step 2.4: Download Photogrammetry Products

Calls `download_photogrammetry_products()` (entrypoint.py:91-162):

**Single-dataset mode** (if `DATASET_NAME` env var is set):
- Processes only the specified dataset
- Downloads from `s3remote:<bucket>/<input_dir>/<dataset_name>/` to `/tmp/processing/input/<dataset_name>/`

**Multi-dataset mode** (if `DATASET_NAME` is not set):
- Runs `rclone lsd` to discover all mission subdirectories in the input path
- Downloads each mission's products to separate subdirectories

**Downloads include**: DSMs, DTMs, orthomosaics, point clouds, cameras.xml, reports, logs

**Returns**: List of mission directory names (e.g., `['01_benchmarking-greasewood', '02_benchmarking-greasewood']`)

### Step 2.5: Download Boundary Polygons

Calls `download_boundary_polygons(mission_dirs)` (entrypoint.py:164-211):

For each mission:
1. Extracts base mission name using `extract_base_mission_name()` (removes numeric prefix like `01_`)
2. Constructs S3 path: `s3remote:<bucket>/<boundary_dir>/<base_name>/metadata-mission/<base_name>_mission-metadata.gpkg`
3. Downloads to `/tmp/processing/boundary/<mission_name>/<base_name>_mission-metadata.gpkg`

**Example**: For mission `01_benchmarking-greasewood`, downloads boundary file for base mission `benchmarking-greasewood`

**Returns**: Count of successfully downloaded boundary files

### Step 2.6: Detect and Match Missions

Calls `detect_and_match_missions()` (entrypoint.py:213-271):

1. Lists all directories in `/tmp/processing/input/`
2. For each mission directory:
   - Finds all product files
   - Matches to boundary file using base mission name
   - Validates both products and boundary exist
3. Creates mission match dictionary with keys:
   - `prefix`: Full mission name (e.g., `01_benchmarking-greasewood`)
   - `boundary_file`: Path to boundary polygon
   - `product_files`: List of product file paths

**Exit condition**: Exits with code 1 if no missions are matched

**Returns**: List of mission match dictionaries

### Step 2.7: Process Each Mission

Loops through mission matches (entrypoint.py:404-425):

For each mission:

```python
result = postprocess_photogrammetry_containerized(
    mission['prefix'],           # e.g., '01_benchmarking-greasewood'
    mission['boundary_file'],    # Path to boundary polygon
    mission['product_files']     # List of product files
)
```

This calls the main processing function from `postprocess.py` (Phase 3).

If processing succeeds:
- Calls `upload_processed_products(mission['prefix'])`
- Increments success counter
- Continues to next mission

If processing fails:
- Catches exception and prints error
- Continues to next mission (doesn't exit)

### Step 2.8: Upload Processed Products

For each successfully processed mission, calls `upload_processed_products(mission_prefix)` (entrypoint.py:273-333):

1. Extracts base mission name and numeric prefix
2. Constructs upload paths:
   - Full products: `s3remote:<output_bucket>/<output_dir>/<base_name>/processed_<NN>/full/`
   - Thumbnails: `s3remote:<output_bucket>/<output_dir>/<base_name>/processed_<NN>/thumbnails/`
3. Uploads files using `rclone copyto` for each file matching the mission prefix

**Example**: Mission `01_benchmarking-greasewood` uploads to `benchmarking-greasewood/processed_01/`

### Step 2.9: Cleanup Working Directory

Calls `cleanup_working_directory()` (entrypoint.py:335-343):

Removes entire `/tmp/processing/` directory to free disk space.

### Step 2.10: Print Summary and Exit

Prints summary statistics (entrypoint.py:428-442):
- Total missions found
- Successfully processed count
- Failed count

**Exit codes**:
- `0`: All missions processed successfully
- `1`: Partial success (some missions failed) or all missions failed

---

<br/>
<br/>
<br/>

## Phase 3: postprocess.py (Processing Layer)

**File**: `postprocess.py` (Lines 1-423)
**Language**: Python
**Purpose**: Perform geospatial transformations on photogrammetry products

This phase is triggered by the call to `postprocess_photogrammetry_containerized()` from entrypoint.py.

### Step 3.1: Validate Inputs

Function: `postprocess_photogrammetry_containerized()` (postprocess.py:227-422)

Validates:
- Boundary file exists
- All product files exist

**Exit condition**: Raises `FileNotFoundError` if validation fails

### Step 3.2: Create Output Directories

Creates directory structure:

```
/tmp/processing/output/
├── full/         # For full-resolution COGs
└── thumbnails/   # For PNG previews
```

### Step 3.3: Read Mission Boundary Polygon

Reads boundary polygon from GeoPackage (postprocess.py:263):

```python
mission_polygon = gpd.read_file(boundary_file_path)
```

This polygon will be used to crop all rasters.

### Step 3.4: Build Product DataFrame

Creates pandas DataFrame cataloging all products (postprocess.py:268-296):

For each product file:
- Extracts filename, extension, and product type
- Product type is extracted from filename pattern (e.g., `01_mission_ortho.tif` → type: `ortho`)
- Generates output filename: `<mission_prefix>_<type>.<extension>`

Example DataFrame:

| photogrammetry_output_filename | extension | type | postprocessed_filename |
|-------------------------------|-----------|------|----------------------|
| 01_mission_ortho-dtm-ptcloud.tif | tif | ortho-dtm-ptcloud | 01_benchmarking-greasewood_ortho-dtm-ptcloud.tif |
| 01_mission_dsm-ptcloud.tif | tif | dsm-ptcloud | 01_benchmarking-greasewood_dsm-ptcloud.tif |
| 01_mission_dtm-ptcloud.tif | tif | dtm-ptcloud | 01_benchmarking-greasewood_dtm-ptcloud.tif |

### Step 3.5: Crop Rasters and Save as COG

For each raster file (`.tif` or `.tiff`), calls `crop_raster_save_cog()` (postprocess.py:79-117):

**Process per raster**:
1. Opens raster with rasterio
2. Reprojects mission polygon to match raster CRS
3. Crops raster using `rasterio.mask.mask()` with polygon geometry
4. Updates metadata for COG format:
   ```python
   {
       'driver': 'COG',
       'compress': 'deflate',
       'tiled': True,
       'BIGTIFF': 'IF_SAFER'
   }
   ```
5. Writes cropped raster to `/tmp/processing/output/full/<mission_prefix>_<type>.tif`

**Error handling**: Prints warning and continues if a raster fails to process

### Step 3.6: Generate Canopy Height Models (CHMs)

Filters for DEM files (DSM and DTM variants) and attempts CHM creation (postprocess.py:319-376):

**CHM Creation Logic**:

Tries DSM/DTM combinations in this priority order:
1. `dsm-mesh` + `dtm-ptcloud`
2. `dsm-mesh` + `dtm`
3. `dsm-ptcloud` + `dtm-ptcloud`
4. `dsm-ptcloud` + `dtm`
5. `dsm` + `dtm-ptcloud`
6. `dsm` + `dtm`

For the first available combination, calls `make_chm()` (postprocess.py:120-165):

**CHM Generation Process**:
1. Reads DSM raster
2. Reads DTM raster
3. Reprojects DTM to match DSM CRS and resolution using bilinear resampling
4. Subtracts DTM from DSM: `CHM = DSM - DTM`
5. Writes CHM to `/tmp/processing/output/full/<mission_prefix>_chm.tif` as COG

**Exit condition**: If CHM creation fails for all combinations, prints warning and continues (CHM is optional)

### Step 3.7: Copy Non-Raster Files

For non-TIF files (e.g., `.laz` point clouds, `.xml` cameras, `.pdf` reports), copies directly to output (postprocess.py:378-393):

```python
shutil.copy(source, /tmp/processing/output/full/<mission_prefix>_<type>.<ext>)
```

**Error handling**: Prints warning and continues if a file fails to copy

### Step 3.8: Create Thumbnails

For all TIF files in `/tmp/processing/output/full/`, calls `create_thumbnail()` (postprocess.py:168-224):

**Thumbnail Generation Process**:
1. Opens raster with rasterio
2. Calculates scale factor to fit max dimension (default 800px)
3. Reads raster at reduced resolution (uses `out_shape` parameter)
4. Determines image type:
   - 1 band → Grayscale
   - 3+ bands → RGB (uses first 3 bands)
   - 2 bands → Grayscale (fallback)
5. Creates matplotlib figure with exact pixel dimensions
6. Saves as PNG to `/tmp/processing/output/thumbnails/<mission_prefix>_<type>.png`

**Error handling**: Prints warning and continues if thumbnail creation fails

### Step 3.9: Report Statistics

Counts output files and prints summary (postprocess.py:416-421):

```
Post-processing completed for mission: <mission_prefix>
Created <N> full-resolution products and <M> thumbnails
```

**Returns**: `True` on success (allows entrypoint.py to proceed to upload)

---


<br/>
<br/>
<br/>
<br/>

## Error Handling and Failure Modes

### Phase 1 Failures (Shell Validation)

**Failure Point**: Missing environment variables
**Behavior**: Print error message, exit with code 1
**Recovery**: None - container stops immediately

**Failure Point**: rclone not found
**Behavior**: Print error message, exit with code 1
**Recovery**: None - indicates broken Docker image

**Failure Point**: Python package import fails
**Behavior**: Print error message, exit with code 1
**Recovery**: None - indicates broken Docker image

### Phase 2 Failures (Orchestration)

**Failure Point**: rclone download fails
**Behavior**: Print warning, continue with other missions
**Recovery**: Partial - other missions can still succeed

**Failure Point**: No missions matched
**Behavior**: Print error, exit with code 1
**Recovery**: None - indicates data structure issue or missing boundaries

**Failure Point**: Processing exception (Phase 3)
**Behavior**: Catch exception, print traceback, continue with other missions
**Recovery**: Partial - other missions can still succeed

**Failure Point**: Upload failure
**Behavior**: Print warning, continue
**Recovery**: Partial - mission is processed but not uploaded

### Phase 3 Failures (Processing)

**Failure Point**: Boundary file missing
**Behavior**: Raise FileNotFoundError, caught by Phase 2
**Recovery**: Skip mission, continue with others

**Failure Point**: Raster cropping fails
**Behavior**: Print warning, continue with other rasters
**Recovery**: Partial - other products still processed

**Failure Point**: CHM generation fails
**Behavior**: Print warning, continue without CHM
**Recovery**: Full - CHM is optional

**Failure Point**: Thumbnail creation fails
**Behavior**: Print warning, continue with other thumbnails
**Recovery**: Partial - other thumbnails still created

### Exit Code Meanings

- **Exit 0**: All missions downloaded, processed, and uploaded successfully
- **Exit 1**: One of the following occurred:
  - Environment validation failed (Phase 1 or 2)
  - No missions matched (Phase 2)
  - All missions failed processing (Phase 2)
  - Some missions failed (partial success)

---

## Performance Characteristics

### Download Phase (2.4-2.5)

**Bottleneck**: Network I/O from S3
**Parallelization**: Sequential per mission (could be optimized with concurrent downloads)
**Typical Duration**: 2-10 minutes per mission depending on dataset size

### Processing Phase (3.5-3.8)

**Bottleneck**: Disk I/O and CPU for raster operations
**Parallelization**: Sequential per raster within each mission
**Typical Duration**: 5-20 minutes per mission depending on raster resolution

### Upload Phase (2.8)

**Bottleneck**: Network I/O to S3
**Parallelization**: Sequential per file
**Typical Duration**: 2-10 minutes per mission

### Total Runtime

**Single mission**: ~10-40 minutes
**Multiple missions**: Linear scaling (missions processed sequentially)

### Disk Space Requirements

**Peak usage**: 2-3x total input data size
**Working directory**: All inputs + outputs stored simultaneously until cleanup
**Cleanup**: Full cleanup after all missions processed


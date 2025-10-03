# Python Post-Processing Docker v2

## Changes from v1

This version adapts to a new nested directory structure for input data, boundary polygons, and output files.

### New Directory Structures

#### Input Data (Photogrammetry Products)
**v1 (flat):**
```
s3://bucket/run_folder/
  ├── mission-name_ortho.tif
  ├── mission-name_dsm.tif
  └── ...
```

**v2 (nested):**
```
s3://bucket/run_folder/
  └── mission-name/
      ├── mission-name_ortho.tif
      ├── mission-name_dsm.tif
      └── ...
```

#### Boundary Polygons
**v1 (flat):**
```
s3://bucket/boundaries/
  ├── mission-name_mission-metadata.gpkg
  └── ...
```

**v2 (nested):**
```
s3://bucket/boundaries/
  └── mission-name/
      └── metadata-mission/
          └── mission-name_mission-metadata.gpkg
```

#### Output Products
**v1 (flat):**
```
s3://bucket/output/
  ├── mission-name_ortho.tif
  ├── mission-name_chm.tif
  ├── mission-name_ortho.png
  └── ...
```

**v2 (mission-specific):**
```
s3://bucket/output/
  └── mission-name/
      └── processed_01/
          ├── full/
          │   ├── mission-name_ortho.tif
          │   ├── mission-name_chm.tif
          │   ├── mission-name.laz
          │   └── ... (all .tif, .laz, .pdf, .txt, .xml, .ply)
          └── thumbnails/
              ├── mission-name_ortho.png
              ├── mission-name_chm.png
              └── ... (all .png files)
```

### Code Changes

#### 1. `download_photogrammetry_products()` (lines 45-108)
- Uses `rclone lsd` to discover mission subdirectories
- Downloads each mission's products to `/tmp/processing/input/<mission_name>/`
- Returns list of mission directory names

#### 2. `download_boundary_polygons(mission_dirs)` (lines 111-154)
- Now accepts mission directory list as parameter
- Downloads from nested path: `<base>/<mission>/metadata-mission/<mission>_mission-metadata.gpkg`
- Stores locally in `/tmp/processing/boundary/<mission_name>/`

#### 3. `detect_and_match_missions()` (lines 157-211)
- Uses directory names directly as mission identifiers (no filename parsing)
- Matches each mission directory to its boundary file
- Collects all product files from mission's input directory

#### 4. `upload_processed_products(mission_prefix)` (lines 214-261)
- Uploads to mission-specific paths:
  - Thumbnails (.png): `<output_base>/<mission>/processed_01/thumbnails/`
  - Full products (all other): `<output_base>/<mission>/processed_01/full/`
- Assumes S3 directories already exist (does not create them)

### Environment Variables (Unchanged)

Same Docker run parameters as v1:
- `S3_ENDPOINT`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `S3_BUCKET_INPUT_DATA`
- `INPUT_DATA_DIRECTORY`
- `S3_BUCKET_INPUT_BOUNDARY`
- `INPUT_BOUNDARY_DIRECTORY`
- `S3_BUCKET_OUTPUT`
- `OUTPUT_DIRECTORY`
- `OUTPUT_MAX_DIM` (optional, default: 800)
- `WORKING_DIR` (optional, default: /tmp/processing)

### Build & Run

**Build:**
```bash
cd python-postprocessing-docker-v2
docker build -t ghcr.io/open-forest-observatory/photogrammetry-postprocess:v2 .
```

**Run:**
```bash
docker run --rm \
  -e S3_ENDPOINT=https://js2.jetstream-cloud.org:8001 \
  -e S3_PROVIDER=Other \
  -e S3_ACCESS_KEY=<key> \
  -e S3_SECRET_KEY=<secret> \
  -e S3_BUCKET_INPUT_DATA=ofo-internal \
  -e INPUT_DATA_DIRECTORY=gillan_oct3 \
  -e S3_BUCKET_INPUT_BOUNDARY=ofo-public \
  -e INPUT_BOUNDARY_DIRECTORY=jgillan_test \
  -e S3_BUCKET_OUTPUT=ofo-public \
  -e OUTPUT_DIRECTORY=jgillan_test \
  ghcr.io/open-forest-observatory/photogrammetry-postprocess:v2
```

### Preserved Functionality

- Same processing logic (crop, COG conversion, CHM generation, thumbnails)
- Same error handling and logging
- Same rclone retry/transfer settings
- Same file type detection and handling
- Same working directory cleanup

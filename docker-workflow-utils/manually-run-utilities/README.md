# Manually-Run Utilities

Scripts that are run manually (outside of Argo workflows) to prepare data or manage workflow state.

## Paired photogrammetry pipeline

These four scripts are run in sequence to set up a paired photogrammetry run, where high-nadir (hn) and low-oblique (lo) drone missions are processed together.

```
add_agl_summary_to_mission_metadata.py
            |
            v
    compile_metadata.py
            |
            v
      pair_missions.py
            |
            v
  upload_paired_metadata_by_project.py
```

### Dependencies
```
pip install boto3 numpy geopandas
```

### 1. `add_agl_summary_to_mission_metadata.py`

**Prerequisite for pairing.** For each mission, downloads the photogrammetry camera-locations file, computes per-mission AGL summary statistics (`agl_mean`, `agl_fidelity`), and backfills those columns onto the mission metadata GeoPackages on S3. These columns are required by `pair_missions.py` to classify missions as hn or lo.

- **Input:** Per-mission metadata files on S3 (`{missions_prefix}/{mission_id}/`)
- **Output:** Updated mission and image metadata GeoPackages re-uploaded to the same S3 paths
- **Auth:** boto3 (`S3_ENDPOINT`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)

### 2. `compile_metadata.py`

Iterates over all missions in S3, downloads their per-mission metadata GeoPackages, and concatenates them into two monolithic files covering all missions.

- **Input:** Per-mission metadata files on S3 (`{missions_prefix}/{mission_id}/metadata-mission/` and `metadata-images/`)
- **Output:** `metadata-missions-compiled.gpkg` and `metadata-images-compiled.gpkg` uploaded to `{missions_prefix}/` on S3
- **Auth:** rclone `js2s3` remote (`RCLONE_CONFIG_JS2S3_*`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)

### 3. `pair_missions.py`

Reads the compiled metadata and identifies valid hn/lo mission pairs based on spatial overlap, date proximity, altitude range, pitch range, and terrain-follow fidelity. Applies filters to prefer within-year pairings and drop redundant subset pairs. For each valid pair, produces cropped footprint polygons and selects the images that fall within them.

- **Input:** `metadata-missions-compiled.gpkg` and `metadata-images-compiled.gpkg` (from S3 or local)
- **Output:**
  - `selected-composites-polygons.gpkg` — one polygon per mission per pair (two rows per pair)
  - `selected-composites-images.gpkg` — images falling within each pair's footprint
- **Auth:** boto3 (`S3_ENDPOINT`, `AWS_ACCESS_KEY_ID` / `S3_ACCESS_KEY`, `AWS_SECRET_ACCESS_KEY` / `S3_SECRET_KEY`)

### 4. `create_paired_metadata.py`

Splits the monolithic composite outputs from `pair_missions.py` into per-composite metadata folders, mirroring the per-mission structure used for single-mission photogrammetry. Each composite's folder is uploaded to S3.

- **Input:** `selected-composites-images.gpkg` and `selected-composites-polygons.gpkg` (local files from step 3)
- **Output:** Per-composite metadata folders uploaded to `{S3_COMPOSITE_MISSIONS_PATH}/{composite_id}/metadata-images/` and `.../metadata-mission/`
- **Auth:** rclone `js2s3` remote (`RCLONE_CONFIG_JS2S3_*`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)

---

## Workflow management utilities

These scripts are independent of the paired photogrammetry pipeline and can be used with any photogrammetry run.

### `generate_retroactive_log.py`

One-time bootstrap utility. Scans S3 for completed-run sentinel files (PDF reports) and generates a JSONL completion log for projects that finished before the logging feature was implemented. The output log can be used by `generate_remaining_configs.py` and by Argo's skip-if-complete logic.

- **Input:** S3 prefixes for internal (metashape) and public (postprocessed) products
- **Output:** A JSONL completion log file

### `generate_remaining_configs.py`

Given a config list file and a completion log, outputs only the configs whose projects have not yet reached the specified completion phase (`metashape` or `postprocess`). Useful for restarting a partially-completed batch.

- **Input:** A config list file and a JSONL completion log
- **Output:** A filtered config list (stdout or file)

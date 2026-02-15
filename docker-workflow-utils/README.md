# OFO Argo Workflow Utilities

Docker container with utility scripts used by OFO Argo workflows.

## Container Image

**Image:** `ghcr.io/open-forest-observatory/argo-workflow-utils:latest`

Built automatically via GitHub Actions and published to GitHub Container Registry.

## Scripts

### `determine_datasets.py`

Preprocessing script for the step-based photogrammetry workflow. Reads mission config files and generates mission parameters with enabled step flags.

**Purpose:**
- Parse mission config files from config list
- Extract project names and configuration paths
- Validate project names are shell/filesystem-safe
- Determine which processing steps are enabled
- Determine GPU vs CPU node scheduling for GPU-capable steps
- Filter out already-completed projects based on completion log (skip-if-complete feature)
- Gate on required phases (e.g., only include projects with completed metashape phase)

**Usage:**
```bash
python3 /app/determine_datasets.py <config_list_path> [output_file] \
  [--completion-log LOG_PATH] \
  [--phase {metashape,postprocess}] \
  [--skip-if-complete {true,false}] \
  [--require-phase {metashape,postprocess}]
```

**Arguments:**
- `config_list_path`: Path to text file listing config files (relative to `/data`)
- `output_file`: Optional output file for full configs JSON. If omitted, no full configs are written.
- `--completion-log`: Path to config-specific completion log file (e.g., `completion-log-default.jsonl`)
- `--phase`: Which phase this workflow runs (`metashape` or `postprocess`). Required when `--skip-if-complete true`.
- `--skip-if-complete`: Skip projects that already completed the given `--phase` (default: `false`)
- `--require-phase`: Only include projects that have completed the given phase

**Output:**
- Always outputs minimal refs to stdout: `[{"project_name": "..."}]`
- If `output_file` provided: also writes full configs JSON to that file

**Example:**
```bash
# Metashape workflow: write full configs, skip completed
python3 /app/determine_datasets.py /data/config_list.txt /data/output/configs.json \
  --completion-log /data/completion-log-default.jsonl \
  --phase metashape --skip-if-complete true

# Postprocessing workflow: no output file, require metashape phase
python3 /app/determine_datasets.py /data/config_list.txt \
  --completion-log /data/completion-log-default.jsonl \
  --phase postprocess --skip-if-complete true \
  --require-phase metashape

# No skip, no output file
python3 /app/determine_datasets.py /data/config_list.txt
```

**Output Format (stdout):**
```json
[
  {"project_name": "mission_001"},
  {"project_name": "mission_002"}
]
```

**Full configs file format (when output_file provided):**
```json
{
  "mission_001": {
    "project_name": "mission_001",
    "config": "/data/argo-input/configs/mission_001.yml",
    "match_photos_enabled": true,
    "match_photos_use_gpu": true,
    "align_cameras_enabled": true,
    "build_depth_maps_enabled": true,
    "build_point_cloud_enabled": true,
    "build_mesh_enabled": false,
    "build_dem_orthomosaic_enabled": true,
    ...
  }
}
```

### `generate_remaining_configs.py`

Utility script to generate a new config list containing only projects that have not yet completed processing. Useful after a workflow is cancelled or fails partway through.

**Purpose:**
- Read original config list and completion log
- Filter out projects that are already complete
- Generate a new config list with only remaining projects

**Usage:**
```bash
python3 /app/generate_remaining_configs.py <config_list> <completion_log> \
  [--phase {metashape,postprocess}] \
  [--output OUTPUT_FILE]
```

**Arguments:**
- `config_list`: Original config list file path
- `completion_log`: Config-specific completion log file path (e.g., `completion-log-default.jsonl`)
- `--phase`: Completion phase to check (default: `postprocess`)
- `--output, -o`: Output file (default: stdout)

**Example:**
```bash
# Generate list of projects that haven't completed postprocessing
# Note: Use config-specific completion log file
python3 /app/generate_remaining_configs.py \
  /data/argo-input/configs/batch1.txt \
  /data/argo-input/config-lists/completion-log-default.jsonl \
  --phase postprocess \
  -o /data/argo-input/configs/batch1-remaining.txt
```

### `generate_retroactive_log.py`

Utility script to generate a completion log by scanning S3 buckets for existing products. Useful for bootstrapping completion tracking from projects processed before the feature existed.

**Purpose:**
- Scan S3 buckets for Metashape and postprocessed products
- Detect project completion based on sentinel files
- Generate a completion log compatible with skip-if-complete feature

**Requirements:**
- `boto3` Python package (see updated `requirements.txt`)
- S3 credentials configured (environment variables or AWS credentials file)

**Usage:**
```bash
python3 /app/generate_retroactive_log.py \
  --internal-bucket BUCKET \
  --internal-prefix PREFIX \
  [--public-bucket BUCKET] \
  [--public-prefix PREFIX] \
  [--phase {metashape,postprocess,both}] \
  --output OUTPUT_FILE \
  [--append] \
  [--dry-run]
```

**Arguments:**
- `--internal-bucket`: S3 bucket for internal/Metashape products (required)
- `--internal-prefix`: S3 prefix for Metashape products, including any config-specific subdirectories (required)
- `--public-bucket`: S3 bucket for public/postprocessed products
- `--public-prefix`: S3 prefix for postprocessed products
- `--phase`: Which phases to detect (default: `both`)
- `--output, -o`: Output file path (required). **Use config-specific names** (e.g., `completion-log-default.jsonl`)
- `--append`: Append to existing log instead of overwriting
- `--dry-run`: Preview output without writing

**Example:**
```bash
# Set S3 credentials (for non-AWS S3)
export S3_ENDPOINT=https://s3.example.com
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key

# Generate completion log from existing S3 products for default config
python3 /app/generate_retroactive_log.py \
  --internal-bucket ofo-internal \
  --internal-prefix photogrammetry/default-run \
  --public-bucket ofo-public \
  --public-prefix postprocessed \
  --output /data/argo-input/config-lists/completion-log-default.jsonl

# Metashape only
python3 /app/generate_retroactive_log.py \
  --internal-bucket ofo-internal \
  --internal-prefix photogrammetry/default-run \
  --phase metashape \
  --output /data/argo-input/config-lists/completion-log-default.jsonl
```

**Sentinel files for completion detection:**
- **Metashape complete**: `*_report.pdf`
- **Postprocess complete**: `*_report.pdf` (now uses same sentinel as metashape)

### `db_logger.py`

Database logging script for tracking Argo workflow status in PostGIS.

**Note:** Currently disabled - being migrated to hosted Supabase solution.

## Dependencies

See `requirements.txt`:
- `pyyaml>=6.0` - YAML parsing for config files
- `psycopg2-binary>=2.9.6` - PostgreSQL database connectivity
- `sqlalchemy>=2.0.0` - Database ORM
- `argparse>=1.4.0` - Command-line argument parsing
- `boto3>=1.26.0` - S3 access for retroactive log generation

## Development

### Building Locally

```bash
cd docker-workflow-utils
docker build -t argo-workflow-utils:local .
```

### Testing Locally

```bash
# Test determine_datasets.py
docker run --rm -v /path/to/data:/data argo-workflow-utils:local \
  python3 /app/determine_datasets.py argo-input/config-lists/missions.txt
```

### Container Build

The container is built automatically via GitHub Actions when changes are pushed to the repository.

**Workflow file:** `.github/workflows/docker-workflow-utils.yml` (if exists)

## Usage in Workflows

This container is used by:
- `metashape-workflow.yaml` - Preprocessing step for mission parameters
- `postprocessing-workflow.yaml` - Preprocessing step for project filtering

## File Structure

```
docker-workflow-utils/
├── Dockerfile                      # Container definition
├── requirements.txt                # Python dependencies
├── determine_datasets.py           # Config preprocessing script
├── download_imagery.py             # S3 imagery download script
├── transform_config.py             # Config path transformation script
├── db_logger.py                    # Database logging (disabled)
├── README.md                       # This file
└── manually-run-utilities/
    ├── generate_remaining_configs.py   # Generate list of uncompleted projects
    └── generate_retroactive_log.py     # Bootstrap completion log from S3
```

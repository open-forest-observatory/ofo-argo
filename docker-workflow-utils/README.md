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
- Generate unique iteration IDs for mission isolation
- Determine which processing steps are enabled
- Determine GPU vs CPU node scheduling for GPU-capable steps
- Filter out already-completed projects based on completion log (skip-if-complete feature)

**Usage:**
```bash
python3 /app/determine_datasets.py <config_list_path> [output_file] \
  [--completion-log LOG_PATH] \
  [--skip-if-complete {none,metashape,postprocess,both}] \
  [--config-id CONFIG_ID] \
  [--workflow-name WORKFLOW_NAME]
```

**Arguments:**
- `config_list_path`: Path to text file listing config files (relative to `/data`)
- `output_file`: Optional output file for configs (default: stdout)
- `--completion-log`: Path to completion log file for skip-if-complete feature
- `--skip-if-complete`: Skip mode (default: `none`)
- `--config-id`: Photogrammetry config ID (default: `default`)
- `--workflow-name`: Workflow name for logging

**Output:**
- JSON array of mission parameters to stdout or file

**Example:**
```bash
# Inside container
python3 /app/determine_datasets.py argo-input/config-lists/missions.txt

# In Argo workflow
container:
  image: ghcr.io/open-forest-observatory/argo-workflow-utils:latest
  volumeMounts:
    - name: data
      mountPath: /data
  command: ["python3"]
  args: ["/app/determine_datasets.py", "{{workflow.parameters.CONFIG_LIST}}"]
```

**Output Format:**
```json
[
  {
    "project_name": "mission_001",
    "project_name_sanitized": "mission-001",
    "config": "argo-input/configs/mission_001.yml",
    "iteration_id": "000_mission-001",
    "match_photos_enabled": "true",
    "match_photos_use_gpu": "true",
    "align_cameras_enabled": "true",
    "build_depth_maps_enabled": "true",
    "build_point_cloud_enabled": "true",
    "build_mesh_enabled": "false",
    "build_mesh_use_gpu": "true",
    "build_dem_orthomosaic_enabled": "true",
    "match_photos_secondary_enabled": "false",
    "match_photos_secondary_use_gpu": "true",
    "align_cameras_secondary_enabled": "false"
  }
]
```

**Note:** The `iteration_id` is a unique identifier (`{index}_{sanitized_project_name}`) used to isolate each mission's working directory and prevent collisions during parallel processing.

### `generate_remaining_configs.py`

Utility script to generate a new config list containing only projects that have not yet completed processing. Useful after a workflow is cancelled or fails partway through.

**Purpose:**
- Read original config list and completion log
- Filter out projects that are already complete
- Generate a new config list with only remaining projects

**Usage:**
```bash
python3 /app/generate_remaining_configs.py <config_list> <completion_log> \
  [--config-id CONFIG_ID] \
  [--level {metashape,postprocess}] \
  [--output OUTPUT_FILE]
```

**Arguments:**
- `config_list`: Original config list file path
- `completion_log`: Completion log file path
- `--config-id`: Config ID to check (default: `default`)
- `--level`: Completion level to check (default: `postprocess`)
- `--output, -o`: Output file (default: stdout)

**Example:**
```bash
# Generate list of projects that haven't completed postprocessing
python3 /app/generate_remaining_configs.py \
  /data/argo-input/configs/batch1.txt \
  /data/argo-input/config-lists/completion-log.jsonl \
  --level postprocess \
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
  [--config-subfolder SUBFOLDER] \
  [--public-bucket BUCKET] \
  [--public-prefix PREFIX] \
  [--config-id CONFIG_ID] \
  [--level {metashape,postprocess,both}] \
  --output OUTPUT_FILE \
  [--append] \
  [--dry-run]
```

**Arguments:**
- `--internal-bucket`: S3 bucket for internal/Metashape products (required)
- `--internal-prefix`: S3 prefix for Metashape products (required)
- `--config-subfolder`: Optional config subfolder (e.g., `photogrammetry_highres`)
- `--public-bucket`: S3 bucket for public/postprocessed products
- `--public-prefix`: S3 prefix for postprocessed products
- `--config-id`: Config ID for log entries (default: `default`)
- `--level`: Which levels to detect (default: `both`)
- `--output, -o`: Output file path (required)
- `--append`: Append to existing log instead of overwriting
- `--dry-run`: Preview output without writing

**Example:**
```bash
# Set S3 credentials (for non-AWS S3)
export S3_ENDPOINT=https://s3.example.com
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key

# Generate completion log from existing S3 products
python3 /app/generate_retroactive_log.py \
  --internal-bucket ofo-internal \
  --internal-prefix photogrammetry/default-run \
  --public-bucket ofo-public \
  --public-prefix postprocessed \
  --config-id default \
  --output /data/argo-input/config-lists/completion-log.jsonl

# Dry run to preview results
python3 /app/generate_retroactive_log.py \
  --internal-bucket ofo-internal \
  --internal-prefix photogrammetry/default-run \
  --public-bucket ofo-public \
  --public-prefix postprocessed \
  --dry-run \
  --output /tmp/completion-log.jsonl
```

**Sentinel files for completion detection:**
- **Metashape complete**: `*_ortho.tif`, `*_dsm-ptcloud.tif`, or `*_ptcloud.las/laz`
- **Postprocess complete**: `<project_name>_ortho.tif`

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
  python3 /app/determine_datasets.py argo-input/config-lists/test.txt
```

### Container Build

The container is built automatically via GitHub Actions when changes are pushed to the repository.

**Workflow file:** `.github/workflows/docker-workflow-utils.yml` (if exists)

## Usage in Workflows

This container is used by:
- `photogrammetry-workflow-stepbased.yaml` - Preprocessing step for mission parameters
- Future workflow utilities

## File Structure

```
docker-workflow-utils/
├── Dockerfile                      # Container definition
├── requirements.txt                # Python dependencies
├── determine_datasets.py           # Config preprocessing script
├── generate_remaining_configs.py   # Generate list of uncompleted projects
├── generate_retroactive_log.py     # Bootstrap completion log from S3
├── db_logger.py                    # Database logging (disabled)
└── README.md                       # This file
```

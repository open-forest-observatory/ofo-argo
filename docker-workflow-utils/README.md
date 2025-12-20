# OFO Argo Workflow Utilities

Docker container with utility scripts used by OFO Argo workflows.

## Container Image

**Image:** `ghcr.io/open-forest-observatory/ofo-argo-utils:latest`

Built automatically via GitHub Actions and published to GitHub Container Registry.

## Scripts

### `determine_datasets.py`

Preprocessing script for the step-based photogrammetry workflow. Reads mission config files and generates mission parameters with enabled step flags.

**Purpose:**
- Parse mission config files from config list
- Extract project names and configuration paths
- Determine which processing steps are enabled
- Determine GPU vs CPU node scheduling for GPU-capable steps

**Usage:**
```bash
python3 /app/determine_datasets.py <config_list_path>
```

**Arguments:**
- `config_list_path`: Path to text file listing config files (relative to `/data`)

**Output:**
- JSON array of mission parameters to stdout

**Example:**
```bash
# Inside container
python3 /app/determine_datasets.py argo-input/config-lists/missions.txt

# In Argo workflow
container:
  image: ghcr.io/open-forest-observatory/ofo-argo-utils:latest
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
    "config": "argo-input/configs/mission_001.yml",
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

### `db_logger.py`

Database logging script for tracking Argo workflow status in PostGIS.

**Note:** Currently disabled - being migrated to hosted Supabase solution.

## Dependencies

See `requirements.txt`:
- `pyyaml>=6.0` - YAML parsing for config files
- `psycopg2-binary>=2.9.6` - PostgreSQL database connectivity
- `sqlalchemy>=2.0.0` - Database ORM
- `argparse>=1.4.0` - Command-line argument parsing

## Development

### Building Locally

```bash
cd docker-workflow-utils
docker build -t ofo-argo-utils:local .
```

### Testing Locally

```bash
# Test determine_datasets.py
docker run --rm -v /path/to/data:/data ofo-argo-utils:local \
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
├── Dockerfile              # Container definition
├── requirements.txt        # Python dependencies
├── determine_datasets.py   # Config preprocessing script
├── db_logger.py           # Database logging (disabled)
└── README.md              # This file
```

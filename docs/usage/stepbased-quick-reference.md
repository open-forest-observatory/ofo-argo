---
title: Step-based workflow quick reference
weight: 22
---

# Step-Based Workflow Quick Reference

Quick command reference for common step-based workflow operations. See the [complete guide](stepbased-workflow.md) for detailed explanations.

## Submit Workflow

### Basic Submission
```bash
argo submit photogrammetry-workflow-stepbased.yaml \
  --name "my-run-name" \
  -p CONFIG_LIST="argo-input/config-lists/my_missions.txt" \
  -p RUN_FOLDER="2024-12-19-run" \
  -p S3_BUCKET_PHOTOGRAMMETRY_OUTPUTS="ofo-photogrammetry-outputs"
```

### Full Submission with All Parameters
```bash
argo submit photogrammetry-workflow-stepbased.yaml \
  --name "production-run-2024-12-19" \
  -p CONFIG_LIST="argo-input/config-lists/december_missions.txt" \
  -p RUN_FOLDER="2024-12-19-production" \
  -p PHOTOGRAMMETRY_CONFIG_ID="v2" \
  -p S3_BUCKET_PHOTOGRAMMETRY_OUTPUTS="ofo-photogrammetry-outputs" \
  -p S3_BUCKET_POSTPROCESSED_OUTPUTS="ofo-public" \
  -p OUTPUT_DIRECTORY="processed-outputs/december-2024" \
  -p BOUNDARY_DIRECTORY="boundaries" \
  -p POSTPROCESSING_IMAGE_TAG="latest" \
  -p AUTOMATE_METASHAPE_IMAGE_TAG="latest"
```

## Monitor Workflows

### Watch Workflow Progress
```bash
# Watch a specific workflow
argo watch <workflow-name>

# List all running workflows
argo list

# List all workflows (including completed)
argo list --all

# Get detailed workflow info
argo get <workflow-name>
```

### View Logs
```bash
# View logs for preprocessing step
argo logs <workflow-name> -c determine-datasets

# View logs for a specific mission's step
# Format: process-datasets-<N>.<step-name>
# where N is the mission index (0-based)
argo logs <workflow-name> -c process-datasets-0.setup
argo logs <workflow-name> -c process-datasets-0.match-photos-gpu
argo logs <workflow-name> -c process-datasets-1.build-depth-maps

# Follow logs in real-time
argo logs <workflow-name> -c process-datasets-0.setup -f
```

### Delete/Stop Workflows
```bash
# Stop a running workflow
argo stop <workflow-name>

# Delete a workflow
argo delete <workflow-name>

# Delete all completed workflows
argo delete --completed
```

## Config File Setup

### Minimal Config Example
```yaml
project:
  project_name: "mission_001"
  photo_path: "/data/drone-imagery/mission_001"
  project_crs: "EPSG::32610"

add_photos:
  enabled: true

match_photos:
  enabled: true
  gpu_enabled: true  # Use GPU node

align_cameras:
  enabled: true

build_depth_maps:
  enabled: true

build_point_cloud:
  enabled: true

build_dem:
  enabled: true

build_orthomosaic:
  enabled: true
```

### GPU Configuration
```yaml
# Use GPU for match_photos
match_photos:
  enabled: true
  gpu_enabled: true  # GPU node

# Use CPU for match_photos (cheaper)
match_photos:
  enabled: true
  gpu_enabled: false  # CPU node

# Build mesh on GPU (default)
build_mesh:
  enabled: true
  gpu_enabled: true  # GPU node

# Build mesh on CPU (cheaper, slower)
build_mesh:
  enabled: true
  gpu_enabled: false  # CPU node
```

## Troubleshooting Commands

### Check Preprocessing Output
```bash
# See which steps are enabled for each mission
argo logs <workflow-name> -c determine-datasets
```

### Check Failed Steps
```bash
# Get workflow status
argo get <workflow-name>

# View logs of failed step
argo logs <workflow-name> -c process-datasets-0.<failed-step-name>

# Get node info where step ran
argo get <workflow-name> -o json | jq '.status.nodes'
```

### Verify Config Files
```bash
# On the cluster, check config file exists
ls -l /data/argo-input/configs/

# Check config list file
cat /data/argo-input/config-lists/my_missions.txt

# Validate YAML syntax
python3 -c "import yaml; yaml.safe_load(open('/data/argo-input/configs/mission_001.yml'))"
```

## Controlling Parallelism

The max number of concurrent projects is controlled by the `parallelism` field in the workflow file
(around line 79). Edit this value directly before submitting. Default is `10`.

```yaml
# In photogrammetry-workflow-stepbased.yaml
- name: main
  parallelism: 10  # Change this value as needed
  steps:
    ...
```

See the [complete guide](stepbased-workflow.md#determine-the-maximum-number-of-projects-to-process-in-parallel) for details on why this can't be a command-line parameter.

## Common Workflow Patterns

### Test with Single Mission
```bash
# Create test config list
echo "argo-input/configs/test_mission.yml" > /data/argo-input/config-lists/test-single.txt

# Submit test run
argo submit photogrammetry-workflow-stepbased.yaml \
  --name "test-single-mission" \
  -p CONFIG_LIST="argo-input/config-lists/test-single.txt" \
  -p RUN_FOLDER="test-$(date +%Y%m%d-%H%M%S)"
```

### Process Multiple Missions
```bash
# Create config list with multiple missions
cat > /data/argo-input/config-lists/batch.txt <<EOF
argo-input/configs/mission_001.yml
argo-input/configs/mission_002.yml
argo-input/configs/mission_003.yml
EOF

# Submit batch run
argo submit photogrammetry-workflow-stepbased.yaml \
  --name "batch-run-$(date +%Y%m%d)" \
  -p CONFIG_LIST="argo-input/config-lists/batch.txt" \
  -p RUN_FOLDER="batch-$(date +%Y%m%d)"
```

## Step Names Reference

### All Available Steps
1. `setup` - Initialize project, add photos
2. `match_photos` - Generate tie points (GPU/CPU)
3. `align_cameras` - Align cameras, post-processing
4. `build_depth_maps` - Create depth maps (GPU only)
5. `build_point_cloud` - Generate dense point cloud
6. `build_mesh` - Build 3D mesh (GPU/CPU)
7. `build_dem_orthomosaic` - Create DEMs/orthomosaics
8. `match_photos_secondary` - Match secondary photos (GPU/CPU)
9. `align_cameras_secondary` - Align secondary cameras
10. `finalize` - Cleanup and reports

### Task Names in Argo UI

Mission N (0-indexed) tasks appear as:
- `process-datasets-N.setup`
- `process-datasets-N.match-photos-gpu` (or `-cpu`)
- `process-datasets-N.align-cameras`
- `process-datasets-N.build-depth-maps`
- `process-datasets-N.build-point-cloud`
- `process-datasets-N.build-mesh-gpu` (or `-cpu`)
- `process-datasets-N.build-dem-orthomosaic`
- `process-datasets-N.match-photos-secondary-gpu` (or `-cpu`)
- `process-datasets-N.align-cameras-secondary`
- `process-datasets-N.finalize`
- `process-datasets-N.rclone-upload-task`
- `process-datasets-N.postprocessing-task`

## Useful Argo CLI Options

```bash
# Submit and watch immediately
argo submit <workflow.yaml> --watch

# Submit with custom service account
argo submit <workflow.yaml> --serviceaccount my-sa

# Get workflow output parameters
argo get <workflow-name> -o json | jq '.status.outputs.parameters'

# Resubmit a workflow with same parameters
argo resubmit <workflow-name>

# Retry a failed workflow
argo retry <workflow-name>
```

## Performance Tips

### For Small Datasets (<100 images)
```yaml
match_photos:
  enabled: true
  gpu_enabled: false  # CPU is sufficient

build_mesh:
  enabled: false  # Skip if not needed
```

### For Large Datasets (>500 images)
```yaml
match_photos:
  enabled: true
  gpu_enabled: true  # GPU recommended

build_depth_maps:
  enabled: true  # Always uses GPU

build_mesh:
  enabled: true
  gpu_enabled: true  # GPU recommended for large meshes
```

### Cost Optimization
```yaml
# Minimize GPU usage
match_photos:
  gpu_enabled: false  # Use CPU

build_mesh:
  enabled: false  # Skip mesh generation if not needed

# Remove point cloud after DEM/ortho generation
build_point_cloud:
  enabled: true
  remove_after_export: true  # Cleanup in finalize step
```

## Getting Help

- **Full Guide**: See [MULTINODE-WORKFLOW-GUIDE.md](MULTINODE-WORKFLOW-GUIDE.md)
- **Implementation Details**: See `implementation-plans/step-workflow-implementation-plan.md`
- **Argo Docs**: https://argoproj.github.io/argo-workflows/
- **automate-metashape**: https://github.com/open-forest-observatory/automate-metashape

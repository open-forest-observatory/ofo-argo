---
title: Running the step-based photogrammetry workflow
weight: 21
---

# Running the step-based photogrammetry workflow

!!! success "Recommended Workflow"
    This is the **recommended workflow** for photogrammetry processing. It provides optimized resource allocation, cost savings, and better monitoring compared to the [original monolithic workflow](photogrammetry-workflow.md).

This guide describes how to run the OFO **step-based photogrammetry workflow**, which splits Metashape processing into 10 individual steps with optimized CPU/GPU node allocation. The workflow uses [automate-metashape](https://github.com/open-forest-observatory/automate-metashape) and performs post-processing steps.

## Key Benefits

- 🎯 **GPU steps** (match_photos, build_depth_maps, build_mesh) run on expensive GPU nodes only when needed
- 💻 **CPU steps** (align_cameras, build_point_cloud, build_dem_orthomosaic, etc.) run on cheaper CPU nodes
- ⚡ **Disabled steps** are completely skipped (no pod creation, no resource allocation)
- 📊 **Fine-grained monitoring** - Track progress of each individual step in the Argo UI
- 🔧 **Flexible GPU usage** - Configure whether GPU-capable steps use GPU or CPU nodes
- 💰 **Cost optimization** - Reduce GPU usage by 60-80% compared to monolithic workflow

## Prerequisites

Before running the workflow, ensure you have:

1. [Installed and set up](cluster-access-and-resizing.md) the `openstack` and `kubectl` utilities
1. [Installed](argo-usage.md) the Argo CLI
1. [Added](cluster-access-and-resizing.md#cluster-resizing) the appropriate type and number of nodes to the cluster
1. Set up your `kubectl` authentication env var (part of instructions for adding nodes). Quick reference:

```
source ~/venv/openstack/bin/activate
source ~/.ofocluster/app-cred-ofocluster-openrc.sh
export KUBECONFIG=~/.ofocluster/ofocluster.kubeconfig
```

## Workflow overview

The step-based workflow executes **10 separate Metashape processing steps** as individual containerized tasks, followed by upload and post-processing. Each mission processes sequentially through these steps:

### Metashape Processing Steps

1. **setup** (CPU) - Initialize project, add photos, calibrate reflectance
2. **match_photos** (GPU/CPU configurable) - Generate tie points for camera alignment
3. **align_cameras** (CPU) - Align cameras, add GCPs, optimize, filter sparse points
4. **build_depth_maps** (GPU) - Create depth maps for dense reconstruction
5. **build_point_cloud** (CPU) - Generate dense point cloud from depth maps
6. **build_mesh** (GPU/CPU configurable) - Build 3D mesh model
7. **build_dem_orthomosaic** (CPU) - Create DEMs and orthomosaic products
8. **match_photos_secondary** (GPU/CPU configurable, optional) - Match secondary photos if provided
9. **align_cameras_secondary** (CPU, optional) - Align secondary cameras if provided
10. **finalize** (CPU) - Cleanup, generate reports

### Post-Processing Steps

11. **rclone-upload** - Upload Metashape outputs to S3
12. **postprocessing** - Generate CHMs, clip to boundaries, create COGs and thumbnails, upload to S3

!!! info "Sequential Execution"
    Steps execute **sequentially within each mission** to prevent conflicts with shared Metashape project files. However, **multiple missions process in parallel**, each with its own step sequence.

!!! tip "Conditional Execution"
    Steps disabled in your config file are **completely skipped** - no container is created and no resources are allocated. This is more efficient than the original workflow where disabled operations still ran inside a single long-running container.

## Setup

### Prepare inputs

Before running the workflow, you need to prepare three types of inputs on the cluster's shared storage:

1. Drone imagery datasets (JPEG images)
2. Metashape configuration files
3. A config list file specifying which configs to process

All inputs must be placed in `/ofo-share/argo-data/`.

#### Add drone imagery datasets

To add new drone imagery datasets to be processed using Argo, transfer files from your local machine (or the cloud) to the `/ofo-share` volume. Put the drone imagery datasets to be processed in their own directory in `/ofo-share/argo-data/argo-input/datasets` (or another folder within `argo-input`).

One data transfer method is the `scp` command-line tool:

```bash
scp -r <local/directory/drone_image_dataset/> exouser@<vm.ip.address>:/ofo-share/argo-data/argo-input/datasets
```

Replace `<vm.ip.address>` with the IP address of a cluster node that has the share mounted.

#### Specify Metashape parameters

!!! warning "Config Structure Requirement"
    The step-based workflow requires an updated config structure with:

    - Global settings under `project:` section
    - Each operation as a top-level config section with `enabled` flag
    - Separate `match_photos` and `align_cameras` sections (not combined `alignPhotos`)
    - Separate `build_dem` and `build_orthomosaic` sections

    See the [updated config example](https://github.com/open-forest-observatory/automate-metashape/blob/main/config/config-example.yml) for the full structure.

Metashape processing parameters are specified in configuration YAML files which should be placed somewhere within `/ofo-share/argo-data/argo-input`.

Every project to be processed needs to have its own standalone configuration file.

**Setting the `photo_path`:** Within the `project:` section of the config YAML, you must specify `photo_path` which is
the location of the drone imagery dataset. When running via Argo workflows, this path refers to the
location **inside the docker container**. The `/ofo-share/argo-data` directory gets mounted at `/data` inside the container, so for example, if your drone images are at
`/ofo-share/argo-data/argo-input/datasets/dataset_1`, then the `photo_path` should be written as:

```yaml
project:
  photo_path: /data/argo-input/datasets/dataset_1
```

## Resource Configuration

All Argo workflow resource parameters (GPU, CPU, memory) are configured in the top-level `argo` section of your config file. This section is optional -- if omitted, sensible defaults will be used. The defaults assume one or more m3.large CPU nodes and one or more `mig1` (7-slice MIG) GPU nodes (see [cluster access and resizing](cluster-access-and-resizing.md)).

### GPU Scheduling

Three steps support configurable GPU usage via `argo.<step>.gpu_enabled` parameters:

- `argo.match_photos.gpu_enabled` - If `true`, runs on GPU node; if `false`, runs on CPU node (default: `true`)
- `argo.build_mesh.gpu_enabled` - If `true`, runs on GPU node; if `false`, runs on CPU node (default: `true`)
- `argo.match_photos_secondary.gpu_enabled` - Inherits from `match_photos` unless explicitly set

The `build_depth_maps` step always runs on GPU nodes (no config option) as it always benefits from GPU acceleration.

### GPU Resource Selection (MIG Support)

For GPU steps, you can specify which GPU resource to request using `gpu_resource` and `gpu_count` in the `argo` section. This allows using MIG (Multi-Instance GPU) partitions instead of full GPUs:

```yaml
argo:
  match_photos:
    gpu_enabled: true
    gpu_resource: "nvidia.com/mig-1g.5gb"  # Use smallest MIG partition
    gpu_count: 2                           # Request 2 MIG slices for more parallelism

  build_depth_maps:
    gpu_resource: "nvidia.com/gpu"         # Explicitly request full GPU (this is the default)
    # gpu_count defaults to 1 if omitted

  build_mesh:
    gpu_enabled: true
    gpu_resource: "nvidia.com/mig-3g.20gb" # Larger MIG partition for mesh building
    gpu_count: 1
```

Available GPU resources:

| Resource | Description | Pods per GPU |
|----------|-------------|--------------|
| `nvidia.com/gpu` | Full GPU (default if `gpu_resource` omitted) | 1 |
| `nvidia.com/mig-1g.5gb` | 1/7 compute, 5GB VRAM | 7 |
| `nvidia.com/mig-2g.10gb` | 2/7 compute, 10GB VRAM | 3 |
| `nvidia.com/mig-3g.20gb` | 3/7 compute, 20GB VRAM | 2 |

Use `gpu_count` to request multiple MIG slices (e.g., `gpu_count: 2` with `mig-1g.5gb` to get 2/7 compute power).

!!! tip "When to use MIG"
    Use MIG partitions when your GPU steps have low utilization. This allows multiple workflow steps to share a single physical GPU, reducing costs. In extensive benchmarking, we have found that we get the greatest efficiency with mig-1g.5gb nodes, potentially providing more than one slice to GPU-intensive pods.

!!! note "Nodegroup requirement"
    MIG resources are only available on MIG-enabled nodegroups. Create a MIG nodegroup with a name containing `mig1-`, `mig2-`, or `mig3-` (see [MIG nodegroups](cluster-access-and-resizing.md#mig-nodegroups)).

### CPU and Memory Configuration

You can configure CPU and memory requests for all workflow steps (both CPU and GPU steps) using `cpu_request` and `memory_request` parameters in the `argo` section:

```yaml
argo:
  # Optional: Set global defaults that apply to all steps
  defaults:
    cpu_request: "10"        # Default CPU cores for all steps
    memory_request: "50Gi"   # Default memory for all steps

  # Override for specific steps
  match_photos:
    cpu_request: "8"         # Override default CPU request for this step
    memory_request: "32Gi"   # Override default memory request for this step

  build_depth_maps:
    cpu_request: "6"
    memory_request: "24Gi"

  align_cameras:
    cpu_request: "15"        # CPU-heavy step
    memory_request: "50Gi"
```

Default values (if not specified) are hard-coded into the workflow YAML under the CPU and GPU step templates.

**Fallback order:**

1. Step-specific value (e.g., `argo.match_photos.cpu_request`)
2. User default from `argo.defaults` (if specified)
3. Hardcoded default (based on step type and GPU mode)

!!! tip "Using defaults as a template"
    You can leave step-level parameters blank/empty to use the defaults, which serves as a visual template:

    ```yaml
    argo:
      defaults:
        cpu_request: "8"
        memory_request: "40Gi"

      match_photos:
        cpu_request:      # Blank = uses defaults.cpu_request → 8
        memory_request:   # Blank = uses defaults.memory_request → 40Gi

      build_depth_maps:
        cpu_request: "12" # Override: uses 12 instead of defaults
        memory_request:   # Blank = uses defaults.memory_request → 40Gi
    ```

### Secondary Photo Processing

The `match_photos_secondary` and `align_cameras_secondary` steps **inherit resource configuration** from their primary steps unless explicitly overridden:

```yaml
argo:
  match_photos:
    gpu_resource: "nvidia.com/mig-2g.10gb"
    cpu_request: "6"
    memory_request: "24Gi"

  # match_photos_secondary automatically inherits the above settings
  # unless you override them:
  match_photos_secondary:
    gpu_resource: "nvidia.com/mig-1g.5gb"  # Override: use smaller GPU
    # cpu_request and memory_request still inherited from match_photos
```

This 4-level fallback applies: Secondary-specific → Primary step → User defaults → Hardcoded defaults

**Parameters handled by Argo:** The `project_path`, `output_path`, and `project_name` configuration parameters are handled automatically by the Argo workflow:

- `project_path` and `output_path` are determined via CLI arguments passed to the automate-metashape container, derived from the `TEMP_WORKING_DIR` Argo workflow parameter (passed by the user on the command line when invoking `argo submit`)
- `project_name` is extracted from `project.project_name` in the config file (or from the filename
  of the config file if missing in the config) and passed by Argo via CLI to each step to ensure consistent project names per mission

Any values specified for `project_path` and `output_path` in the config.yml will be overridden by Argo CLI arguments.

#### Create a config list file

We use a text file, for example `config_list.txt`, to tell the Argo workflow which config files
should be processed in the current run. This text file should list the paths to each config.yml file
you want to process within the container (for example, use `/data/XYZ` to specity the path `/ofo-share/argo-data/XYZ`), one config file path per line.

For example:

```
/data/argo-input/configs/01_benchmarking-greasewood.yml
/data/argo-input/configs/02_benchmarking-greasewood.yml
/data/argo-input/configs/01_benchmarking-emerald-subset.yml
/data/argo-input/configs/02_benchmarking-emerald-subset.yml
```

This allows you to organize your config files in subdirectories or different locations. The project name will be automatically derived from the config filename (e.g., `/data/argo-input/configs/project-name.yml` becomes project `project-name`), unless it is explicity set in the config file at `project.project_name` (which takes priority).

You can create your own config list file and name it whatever you want, placing it anywhere within `/ofo-share/argo-data/`. Then specify the path to it within the container (using `/data/XYZ` to refer to `/ofo-share/argo-data/XYZ`) using the `CONFIG_LIST` parameter when submitting the workflow.

### Determine the maximum number of projects to process in parallel

When tasked with parallelizing across multiple multi-step DAGs, Argo prioritizes breadth first. So
when it has a choice, it will start on a new DAG (metashape project) rather than starting the next
step of an existing one. This is unfortunately not customizable, and it is undesirable because the
workflow involves storing in-process files (including raw imagery, metashape project, outputs)
locally during processing. Our shared storage does not have the space to store all files locally at
the same time. In addition, we have a limited number of Metashape licenses. So we need to restrict
the number of parallel DAGs (metashape projects) it will attempt to run.

The workflow controls this via the `parallelism` field in the `main` template (around line 79 in
`photogrammetry-workflow-stepbased.yaml`). **To change the max parallel projects, edit this value
directly in the workflow file before submitting.** The default is set to `10`.

!!! note "Why not a command-line parameter?"
    Argo Workflows doesn't support parameter substitution for integer fields like `parallelism`,
    so this value must be hardcoded in the workflow file. This is an [known issue](https://github.com/argoproj/argo-workflows/issues/1780) with Argo and we
    should look for it to be resovled so we can implement it as a command line parameter.

### Adjusting parallelism on a running workflow

If you need to increase or decrease parallelism while a workflow is already running, you can patch
the workflow in place. First, find your workflow name:

```bash
argo list -n argo
```

Then patch the `main` template's parallelism (index 0):

```bash
kubectl patch workflow <workflow-name> -n argo --type='json' \
  -p='[{"op": "replace", "path": "/spec/templates/0/parallelism", "value": 20}]'
```

The change takes effect immediately for any new pods that haven't started yet. Already-running pods
are not affected.

!!! note
    This only affects the running workflow instance. Future submissions will still use the value
    from the YAML file.


## Submit the workflow

Once your cluster authentication is set up and your inputs are prepared, run:

```bash
argo submit -n argo photogrammetry-workflow-stepbased.yaml \
  --name "my-run-$(date +%Y%m%d)" \
  -p CONFIG_LIST=/data/argo-input/config-lists/config_list.txt \
  -p TEMP_WORKING_DIR=/data/argo-output/temp-runs/gillan_june27 \
  -p S3_PHOTOGRAMMETRY_DIR=gillan_june27 \
  -p PHOTOGRAMMETRY_CONFIG_ID=01 \
  -p S3_BUCKET_PHOTOGRAMMETRY_OUTPUTS=ofo-internal \
  -p S3_POSTPROCESSED_DIR=jgillan_test \
  -p S3_BUCKET_POSTPROCESSED_OUTPUTS=ofo-public \
  -p BOUNDARY_DIRECTORY=jgillan_test \
  -p POSTPROCESSING_IMAGE_TAG=latest \
  -p UTILS_IMAGE_TAG=latest \
  -p AUTOMATE_METASHAPE_IMAGE_TAG=latest
```

!!! note "Workflow File"
    Note the different workflow file: `photogrammetry-workflow-stepbased.yaml` instead of `photogrammetry-workflow.yaml`

Database parameters (not currently functional):
```bash
-p DB_PASSWORD=<password> \
-p DB_HOST=<vm_ip_address> \
-p DB_NAME=<db_name> \
-p DB_USER=<user_name>
```


### Workflow parameters

| Parameter | Description |
|-----------|-------------|
| `CONFIG_LIST` | **Absolute path** to text file listing metashape config file paths (each line should be an absolute path starting with `/data/`). Example: `/data/argo-input/config-lists/config_list.txt` |
| `TEMP_WORKING_DIR` | **Absolute path** for temporary workflow files (both photogrammetry and postprocessing). Workflow creates `photogrammetry/` and `postprocessing/` subdirectories automatically. All files are deleted after successful S3 upload. Example: `/data/argo-output/temp-runs/gillan_june27` |
| `S3_PHOTOGRAMMETRY_DIR` | S3 directory name for raw Metashape outputs. When `PHOTOGRAMMETRY_CONFIG_ID` is set, products upload to `{bucket}/{S3_PHOTOGRAMMETRY_DIR}/photogrammetry_{PHOTOGRAMMETRY_CONFIG_ID}/`. When not set, products go to `{bucket}/{S3_PHOTOGRAMMETRY_DIR}/`. Example: `gillan_june27` |
| `PHOTOGRAMMETRY_CONFIG_ID` | Two-digit configuration ID (e.g., `01`, `02`) used to organize outputs into `photogrammetry_NN` subdirectories in S3 for both raw and postprocessed products. If not specified or set to `NONE`, both raw and postprocessed products are stored without the `photogrammetry_NN` subfolder. |
| `S3_BUCKET_PHOTOGRAMMETRY_OUTPUTS` | S3 bucket where raw Metashape products (orthomosaics, point clouds, etc.) are uploaded (typically `ofo-internal`). |
| `S3_POSTPROCESSED_DIR` | S3 directory name for postprocessed outputs. When `PHOTOGRAMMETRY_CONFIG_ID` is set, products are organized as `{S3_POSTPROCESSED_DIR}/{mission_name}/photogrammetry_{PHOTOGRAMMETRY_CONFIG_ID}/`. When not set, products go to `{S3_POSTPROCESSED_DIR}/{mission_name}/`. Example: `jgillan_test` |
| `S3_BUCKET_POSTPROCESSED_OUTPUTS` | S3 bucket for final postprocessed outputs and where boundary files are stored (typically `ofo-public`) |
| `BOUNDARY_DIRECTORY` | Parent directory in S3 where mission boundary polygons reside (used to clip imagery). Example: `jgillan_test` |
| `POSTPROCESSING_IMAGE_TAG` | Docker image tag for the postprocessing container (default: `latest`). Use a specific branch name or tag to test development versions (e.g., `dy-manila`) |
| `UTILS_IMAGE_TAG` | Docker image tag for the argo-workflow-utils container (default: `latest`). Use a specific branch name or tag to test development versions (e.g., `dy-manila`) |
| `AUTOMATE_METASHAPE_IMAGE_TAG` | Docker image tag for the automate-metashape container (default: `latest`). Use a specific branch name or tag to test development versions |
| `DB_*` | Database parameters for logging Argo status (not currently functional; credentials in [OFO credentials document](https://docs.google.com/document/d/155AP0P3jkVa-yT53a-QLp7vBAfjRa78gdST1Dfb4fls/edit?tab=t.0)) |

**Secrets configuration:**

- **S3 credentials**: S3 access credentials, provider type, and endpoint URL are configured via the `s3-credentials` Kubernetes secret
- **Agisoft license**: Metashape floating license server address is configured via the
  `agisoft-license` Kubernetes secret

These secrets should have been created (within the `argo` namespace) during [cluster creation](../admin/cluster-creation-and-resizing.md).

## Monitor the workflow

### Using the Argo UI

The Argo UI is great for troubleshooting and checking individual step progress. Access it at [argo.focal-lab.org](https://argo.focal-lab.org), using the credentials from [Vaultwarden](https://vault.focal-lab.org) under the record "Argo UI token".

#### Navigating the Argo UI

The **Workflows** tab on the left side menu shows all running workflows. Click a workflow to see a detailed DAG (directed acyclic graph) showing:

- **Preprocessing task**: The `determine-datasets` step that reads config files
- **Per-mission columns**: Each mission shows as a separate column with all its processing steps
- **Individual step status**: Each of the 10+ steps shown with color-coded status

**Step status colors:**

- 🟢 **Green (Succeeded)**: Step completed successfully
- 🔵 **Blue (Running)**: Step currently executing
- ⚪ **Gray (Skipped)**: Step was disabled in config or conditionally skipped
- 🔴 **Red (Failed)**: Step encountered an error
- 🟡 **Yellow (Pending)**: Step waiting for dependencies

Click on a specific step to see detailed information including:

- Which VM/node it's running on (CPU vs GPU node)
- Duration of the step
- Real-time logs
- Resource usage
- Input/output parameters

!!! tip "Viewing Step Logs"
    To view logs for a specific step:

    1. Click the workflow in Argo UI
    2. Click on the individual step node (e.g., `match-photos-gpu`, `build-depth-maps`)
    3. Click the "Logs" tab
    4. Logs will stream in real-time if the step is running

#### Multi-Mission View

When processing multiple missions, the Argo UI shows all missions side-by-side. This makes it easy to:

- See which missions are at which step
- Identify if one mission is failing while others succeed
- Compare processing times across missions
- Monitor overall workflow progress

#### Understanding Step Names

Task names in the Argo UI follow the pattern `process-datasets-N.<step-name>`:

- `process-datasets-0.setup` - Setup step for first mission (index 0)
- `process-datasets-0.match-photos-gpu` - Match photos on GPU for first mission
- `process-datasets-1.build-depth-maps` - Build depth maps for second mission (index 1)

!!! tip "Finding Your Mission"
    To identify which mission corresponds to which index:

    1. Check the `determine-datasets` step logs to see the order of missions in the JSON output
    2. Click on any task (e.g., `process-datasets-0.setup`) and view the parameters to see the `project-name` value
    3. The project name appears in all file paths, logs, and processing outputs

GPU-capable steps show either `-gpu` or `-cpu` suffix depending on config.

### Using the CLI

View workflow status from the command line:

```bash
# Watch overall workflow progress
argo watch <workflow-name>

# List all workflows
argo list

# Get logs for preprocessing step
argo logs <workflow-name> -c determine-datasets

# Get logs for a specific mission's step
# Format: process-datasets-<N>.<step-name>
argo logs <workflow-name> -c process-datasets-0.setup
argo logs <workflow-name> -c process-datasets-0.match-photos-gpu
argo logs <workflow-name> -c process-datasets-1.build-depth-maps

# Follow logs in real-time
argo logs <workflow-name> -c process-datasets-0.setup -f
```

## Workflow outputs

The final outputs will be written to `S3:ofo-public` in the following directory structure:

```bash
/S3:ofo-public/
├── <OUTPUT_DIRECTORY>/
    ├── dataset1/
         ├── images/
         ├── metadata-images/
         ├── metadata-mission/
            └── dataset1_mission-metadata.gpkg
         ├──photogrammetry_01/
            ├── full/
               ├── dataset1_cameras.xml
               ├── dataset1_chm-ptcloud.tif
               ├── dataset1_dsm-ptcloud.tif
               ├── dataset1_dtm-ptcloud.tif
               ├── dataset1_log.txt
               ├── dataset1_ortho-dtm-ptcloud.tif
               ├── dataset1_points-copc.laz
               └── dataset1_report.pdf
            ├── thumbnails/
               ├── dataset1_chm-ptcloud.png
               ├── dataset1_dsm-ptcloud.png
               ├── dataset1_dtm-ptcloud.png
               └── dataset1-ortho-dtm-ptcloud.png
         ├──photogrammetry_02/
            ├── full/
               ├── dataset1_cameras.xml
               ├── dataset1_chm-ptcloud.tif
               ├── dataset1_dsm-ptcloud.tif
               ├── dataset1_dtm-ptcloud.tif
               ├── dataset1_log.txt
               ├── dataset1_ortho-dtm-ptcloud.tif
               ├── dataset1_points-copc.laz
               └── dataset1_report.pdf
            ├── thumbnails/
               ├── dataset1_chm-ptcloud.png
               ├── dataset1_dsm-ptcloud.png
               ├── dataset1_dtm-ptcloud.png
               └── dataset1-ortho-dtm-ptcloud.png
    ├── dataset2/
```

This directory structure should already exist prior to running the Argo workflow.

<!-- Commenting out the AI-generated troubleshooting section since it may be misleading or not current.
## Troubleshooting

### Steps are skipped even though they should run

**Check:**

1. Verify the step's `enabled` flag is `true` in the config file
2. For `build_dem_orthomosaic`, verify either `build_dem.enabled` OR `build_orthomosaic.enabled` is `true`
3. For secondary photo steps, verify `project.photo_path_secondary` is set to a non-empty path
4. Check preprocessing logs to see what parameters were extracted:

```bash
argo logs <workflow-name> -c determine-datasets
```

### Step fails with "Prerequisites not met"

**Cause:** A required previous step was skipped or failed.

**Solution:**

1. Check the error message to see which prerequisite is missing
2. Verify the previous step's config is enabled
3. Check previous step logs for failures

**Common prerequisites:**

- `align_cameras` requires `match_photos` to have created tie points
- `build_depth_maps` requires `align_cameras` to have aligned cameras
- `build_point_cloud` requires `build_depth_maps` to have created depth maps
- `build_dem_orthomosaic` requires either `build_point_cloud` or `build_mesh` to have run

### GPU steps running on CPU nodes (or vice versa)

**Check:**

1. Verify `argo.<step>.gpu_enabled` parameter in config is a boolean (`true` or `false`), not a string
2. Check preprocessing output to confirm correct `use_gpu` parameter was extracted:
   ```bash
   argo logs <workflow-name> -c determine-datasets
   ```
3. Verify cluster has GPU nodes available and properly labeled (`nvidia.com/gpu.present=true`)
4. Verify the GPU step template has the correct GPU resource request

### MIG pods not scheduling

**Check:**

1. Verify nodegroup name includes `mig1-`, `mig2-`, or `mig3-`
2. Verify the MIG NodeFeatureRule is applied: `kubectl get nodefeaturerule mig-nodegroup-labels`
3. Check node has correct MIG label: `kubectl get node <name> -o yaml | grep mig.config`
4. Check MIG resources are available: `kubectl describe node <name> | grep mig`
5. Verify workflow requests correct MIG resource type (e.g., `nvidia.com/mig-2g.10gb`)

### Project file not found in later steps

**Cause:** The `setup` step failed or project file was not saved correctly.

**Solution:**

1. Check `setup` step logs for errors
2. Verify `project_path` is correctly set
3. Ensure shared storage (`/ofo-share`) is mounted correctly
4. Verify `project.project_name` is set in config file

### Config file parsing errors in preprocessing

**Common issues:**

- YAML syntax errors (indentation, missing colons)
- Config file path in `CONFIG_LIST` is incorrect
- Config file doesn't exist at specified path
- Missing required fields (`project.project_name`, `project.photo_path`)

**Debug:**

```bash
# Check preprocessing logs
argo logs <workflow-name> -c determine-datasets

# Manually validate config YAML
python3 -c "import yaml; yaml.safe_load(open('/ofo-share/argo-data/argo-input/configs/mission.yml'))"
```

### Out of memory errors

**Solutions:**

1. Reduce dataset size or processing quality settings
2. Increase memory limits in workflow templates
3. For large datasets, ensure you're using GPU for `match_photos` and `build_depth_maps`
4. Check cluster node resources and ensure sufficient memory per node

### Performance optimization tips

**For small datasets (<100 images):**

```yaml
match_photos:
  enabled: true
  # ... match_photos parameters

argo:
  match_photos:
    gpu_enabled: false  # CPU is sufficient, saves cost
    cpu_request: "18"
    memory_request: "100Gi"

  build_mesh:
    # Skip mesh generation if not needed (set enabled: false in build_mesh section)
```

**For large datasets (>500 images):**

```yaml
match_photos:
  enabled: true
  # ... match_photos parameters

build_depth_maps:
  enabled: true
  # ... depth maps parameters

build_mesh:
  enabled: true
  # ... mesh parameters

argo:
  match_photos:
    gpu_enabled: true  # GPU recommended
    gpu_resource: "nvidia.com/mig-2g.10gb"
    cpu_request: "4"
    memory_request: "16Gi"

  build_depth_maps:
    # Always uses GPU
    gpu_resource: "nvidia.com/gpu"  # Use full GPU for large datasets
    cpu_request: "4"
    memory_request: "16Gi"

  build_mesh:
    gpu_enabled: true  # GPU recommended for large meshes
    gpu_resource: "nvidia.com/mig-2g.10gb"
```

**Cost optimization:**

```yaml
# Minimize GPU usage where possible
argo:
  defaults:
    gpu_resource: "nvidia.com/mig-1g.5gb"  # Use smallest MIG by default

  match_photos:
    gpu_enabled: false  # Use CPU for small datasets
    cpu_request: "18"
    memory_request: "100Gi"

  build_depth_maps:
    gpu_resource: "nvidia.com/mig-2g.10gb"  # Smaller GPU for depth maps
    cpu_request: "4"
    memory_request: "16Gi"

# In step sections:
build_mesh:
  enabled: false  # Skip mesh generation if not needed

build_point_cloud:
  enabled: true
  remove_after_export: true  # Cleanup happens in finalize step
```
-->

<!--

## Argo Workflow Logging in PostGIS Database

**THE DB LOGGING IS CURRENTLY DISABLED AND IS BEING MIGRATED TO A HOSTED SOLUTION THROUGH SUPABASE**

Argo run status is logged into a PostGIS DB. This is done through an additional docker container (hosted on GitHub Container Registry `ghcr.io/open-forest-observatory/argo-workflow-utils:latest`) that is included in the argo workflow. The files to make the docker image are in the folder `argo-workflow-utils`.

### Info on the PostGIS DB

There is a JS2 VM called `ofo-postgis` that hosts a PostGIS DB for storing metadata of argo workflows.

You can access the `ofo-postgis` VM through Webshell in Exosphere. Another access option is to SSH into `ofo-postgis` with the command `ssh exouser@<ip_address>`. This is not public and will require a password.

The DB is running in a docker container (`postgis/postgis`). The DB storage is a 10 GB volume at `/media/volume/ofo-postgis` on the VM.

### Steps to View the Logged Results

Enter the Docker container running the PostGIS server:
```bash
sudo docker exec -ti ofo-postgis bash
```

Launch the PostgreSQL CLI as the intended user (grab from DB credentials):
```bash
psql -U postgres
```

List all tables in the database:
```
\dt
```

Show the structure of a specific table (column names & data types):
```
\d automate_metashape
```

Currently, the PostGIS server stores the following keys in the `automate_metashape` table:

| **Column**   | **Type** | **Description**  |
|  --- | ----  | --- |
|id | integer | unique identifier for each call of automate-metashape (not run) |
|dataset_name | character varying(100) | project running for the individual call of automate-metashape (column name is legacy) |
| workflow_id | character varying(100) | identifier for run of ofo-argo |
| status | character varying(50)  | either queued, processing, failed or completed, based on current and final status of automate-metashape |
| start_time | timestamp without time zone | start time of automate-metashape run |
| finish_time  | timestamp without time zone | end time of automate-metashape run (if it was able to finish) |
| created_at | timestamp without time zone | creation time of entry in database |

View all data records for a specific table:
```sql
select * from automate_metashape ORDER BY id DESC;
```

![SQL query results](https://github.com/user-attachments/assets/cba4532a-21de-4c35-8b2d-635eec326ef7)

Exit out of psql command-line:
```
\q
```

Exit out of container:
```bash
exit
```

### Other useful commands

View all running and stopped containers:
```bash
docker ps -a
```

Stop a running container:
```bash
docker stop <container_id>
```

Remove container:
```bash
docker rm <container_id>
```

Run the docker container DB:
```bash
sudo docker run --name ofo-postgis   -e POSTGRES_PASSWORD=ujJ1tsY9OizN0IpOgl1mY1cQGvgja3SI   -p 5432:5432   -v /media/volume/ofo-postgis/data:/var/lib/postgresql/data  -d postgis/postgis
```

### Github action to rebuild DB logging docker image

There is a GitHub action workflow that rebuilds the logging docker image if any changes have been made at all in the repo. This workflow is in the directory `.github/workflows`. **The workflow is currently disabled in the 'Actions' section of the repository.**

-->

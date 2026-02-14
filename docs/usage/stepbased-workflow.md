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

The step-based workflow executes **10 separate Metashape processing steps** as individual containerized tasks, followed by upload, post-processing, and cleanup. Each mission processes sequentially through these steps:

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

11. **rclone-upload-task** - Upload Metashape outputs to S3
12. **postprocessing-task** - Generate CHMs, clip to boundaries, create COGs and thumbnails, upload to S3
13. **cleanup-iteration** - Remove temporary iteration directories after successful postprocessing

!!! info "Sequential Execution"
    Steps execute **sequentially within each mission** to prevent conflicts with shared Metashape project files. However, **multiple missions process in parallel**, each with its own step sequence.
    
    **Automatic Cleanup:** After postprocessing completes successfully, the workflow automatically removes the temporary iteration directory (`{TEMP_WORKING_DIR}/{workflow-name}/{iteration-id}/`) to free disk space, keeping only the final products uploaded to S3.

!!! tip "Conditional Execution"
    Steps disabled in your config file are **completely skipped** - no container is created and no resources are allocated. This is more efficient than the original workflow where disabled operations still ran inside a single long-running container.

### Iteration ID

Each mission in the workflow is assigned a unique **iteration ID** for isolation and tracking. The iteration ID is automatically generated as `{index}_{project-name}` where:

- `{index}` is a zero-padded 3-digit number (000, 001, 002, etc.) representing the mission's position in the config list
- `{project-name}` is the sanitized project name from the config file (DNS-compliant: lowercase, alphanumeric with hyphens)

**Example:** If processing "Mission_001" as the first mission, the iteration ID would be `000_mission-001`.

The iteration ID is used to:

- Create isolated working directories: `{TEMP_WORKING_DIR}/{workflow-name}/{iteration-id}/`
- Prevent collisions between parallel mission processing
- Enable unique identification even when multiple missions have the same project name
- Organize downloaded imagery and intermediate files

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

## Downloading imagery from S3 (optional)

Instead of pre-staging imagery on the shared PVC, you can have the workflow automatically download and extract imagery zip files from S3 at runtime. This is useful for:

- **Cloud-native workflows**: Process imagery stored in S3 without manual uploads
- **One-time processing**: Imagery that doesn't need to persist after the workflow
- **Remote collaboration**: Team members can trigger workflows without PVC access

### When to use S3 imagery download

Use this feature when:

- Your imagery is already stored as zip files in S3
- You want to avoid manual file transfers to the cluster
- You're processing imagery that won't be reused

**Don't use this feature when:**

- Your imagery is already on the PVC (use direct paths instead)
- You need to reprocess the same imagery multiple times (pre-staging is more efficient)
- Your zip files are very large and bandwidth is a concern

### Configuration

Add the following to the `argo:` section of your config file:

```yaml
argo:
  # List of S3 zip files to download (can also be a single string)
  s3_imagery_zip_download:
    - ofo-public/drone/missions_01/000558/images/000558_images.zip
    - ofo-public/drone/missions_01/000559/images/000559_images.zip

  # Whether to delete downloaded imagery after workflow completes (default: true)
  cleanup_downloaded_imagery: true
```

| Parameter | Description | Default |
|-----------|-------------|---------|
| `s3_imagery_zip_download` | S3 path(s) of zip files to download. Can be a single string or a list. Format: `bucket/path/file.zip`. The S3 endpoint and credentials are configured in the cluster's `s3-credentials` Kubernetes secret. | (none) |
| `cleanup_downloaded_imagery` | If `true`, downloaded imagery is deleted after photogrammetry completes to free disk space | `true` |

### Path syntax: The `__DOWNLOADED__` prefix

When using S3 imagery download, reference downloaded files in `photo_path` using the `__DOWNLOADED__` prefix:

```yaml
project:
  project_name: my_forest_plot
  photo_path:
    - __DOWNLOADED__/000558_images/000558-01
    - __DOWNLOADED__/000558_images/000558-02
    - __DOWNLOADED__/000559_images/000559-01
```

The workflow automatically replaces `__DOWNLOADED__` with the actual download location before photogrammetry begins.

### Zip file structure requirements

The zip filename (without `.zip` extension) becomes the extraction folder name. Plan your `photo_path` entries accordingly:

**Example:** Downloading `000558_images.zip` containing:
```
000558_images.zip
├── 000558-01/
│   ├── IMG_0001.jpg
│   └── IMG_0002.jpg
└── 000558-02/
    ├── IMG_0001.jpg
    └── IMG_0002.jpg
```

Results in this structure after extraction:
```
{download_dir}/
└── 000558_images/          ← folder name from zip filename
    ├── 000558-01/
    │   ├── IMG_0001.jpg
    │   └── IMG_0002.jpg
    └── 000558-02/
        ├── IMG_0001.jpg
        └── IMG_0002.jpg
```

Reference these paths as:
```yaml
photo_path:
  - __DOWNLOADED__/000558_images/000558-01
  - __DOWNLOADED__/000558_images/000558-02
```

### Complete example configuration

```yaml
argo:
  # S3 imagery download settings
  s3_imagery_zip_download:
    - ofo-public/drone/missions_01/000558/images/000558_images.zip
  cleanup_downloaded_imagery: true

  # Standard workflow settings
  match_photos:
    gpu_enabled: true
    gpu_resource: "nvidia.com/mig-1g.5gb"
    cpu_request: "4"
    memory_request: "16Gi"

  build_depth_maps:
    gpu_resource: "nvidia.com/mig-2g.10gb"

project:
  project_name: mission_000558
  # Reference downloaded imagery with __DOWNLOADED__ prefix
  photo_path:
    - __DOWNLOADED__/000558_images/000558-01
    - __DOWNLOADED__/000558_images/000558-02

# ... rest of Metashape config sections ...
match_photos:
  enabled: true
  # ...
```

### How it works

When `s3_imagery_zip_download` is specified, the workflow adds these steps before photogrammetry:

1. **download-imagery**: Downloads each zip file from S3 using rclone and extracts it
2. **transform-config**: Replaces `__DOWNLOADED__` in `photo_path` with the actual download location

After all processing completes (including upload and postprocessing):

3. **cleanup-imagery** (if enabled): Deletes the downloaded imagery to free disk space

Each project gets its own isolated download directory to prevent collisions when processing multiple projects in parallel.

### Troubleshooting S3 imagery download

#### "Config validation failed: __DOWNLOADED__ prefix used but no downloads specified"

**Cause:** Your `photo_path` contains `__DOWNLOADED__` but `s3_imagery_zip_download` is empty or missing.

**Solution:** Either add `s3_imagery_zip_download` entries, or change `photo_path` to use direct paths (e.g., `/data/...`).

#### "Config validation failed: Downloads specified but no __DOWNLOADED__ paths found"

**Cause:** You specified `s3_imagery_zip_download` but your `photo_path` entries don't use the `__DOWNLOADED__` prefix.

**Solution:** Update `photo_path` to use `__DOWNLOADED__/...` paths that reference your downloaded zip contents.

#### Download fails with "Failed to copy" or timeout errors

**Possible causes:**

- Incorrect S3 path format (should be `bucket/path/file.zip` without a remote prefix)
- S3 credentials not configured in the cluster's `s3-credentials` secret
- Network issues or S3 endpoint unavailable
- Zip file doesn't exist at the specified path

**Debug steps:**

1. Check the `download-imagery` step logs in Argo UI
2. Verify the S3 path is correct by listing files (requires rclone configured with the same credentials):
   ```bash
   rclone ls :s3:ofo-public/drone/missions_01/000558/images/ --s3-provider=Ceph --s3-endpoint=<endpoint>
   ```

#### "Photo path not found" errors in setup step

**Cause:** The extracted zip structure doesn't match your `photo_path` entries.

**Solution:**

1. Check what's actually inside your zip file
2. Ensure `photo_path` matches the extracted folder structure
3. Remember: zip filename (minus `.zip`) becomes the top-level folder

#### Disk space issues

**Cause:** Downloaded imagery fills up the shared storage.

**Solutions:**

- Ensure `cleanup_downloaded_imagery: true` (default) to auto-delete after completion
- Process fewer projects in parallel to reduce concurrent disk usage
- Monitor disk usage during workflow execution

## Resource request configuration

All Argo workflow resource requests (GPU, CPU, memory) are configured in the top-level `argo` section of your automate-metashape config file. The defaults assume one or more JS2 `m3.large` CPU nodes and one or more `mig1` (7-slice MIG `g3.xl`) GPU nodes (see [cluster access and resizing](cluster-access-and-resizing.md)).

Importantly, using well-selected resource requests may allow more than one workflow step to schedule simultaneously on the same compute node, without substantially extending the compute time of either, thus greatly increasing compute efficiency by requiring fewer compute nodes. The example config YAML includes suggested resource requests we have developed through extensive benchmarking.

### GPU scheduling

Three steps support configurable GPU usage via `argo.<step>.gpu_enabled` parameters:

- `argo.match_photos.gpu_enabled` - If `true`, runs on GPU node; if `false`, runs on CPU node (default: `true`)
- `argo.build_mesh.gpu_enabled` - If `true`, runs on GPU node; if `false`, runs on CPU node (default: `true`)
- `argo.match_photos_secondary.gpu_enabled` - Inherits from `match_photos` unless explicitly set

The `build_depth_maps` step always runs on GPU nodes (`gpu_enabled` cannot be disabled) as it always benefits from GPU acceleration. However, you can configure the GPU resource type and count using `gpu_resource` and `gpu_count`.

### GPU resource selection (MIG Support)

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

### CPU and memory configuration

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

### Secondary photo processing

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

We use a text file, for example `config-list.txt`, to tell the Argo workflow which config files
should be processed in the current run. Place this file in the **same directory as your config files**, then list just the **filenames** (not full paths), one per line.

**Example:** If your configs are in `/ofo-share/argo-data/argo-input/configs/`, create a file at `/ofo-share/argo-data/argo-input/configs/config-list.txt`:

```
# Benchmarking missions
01_benchmarking-greasewood.yml
02_benchmarking-greasewood.yml

# Skipping emerald for now
# 01_benchmarking-emerald-subset.yml
# 02_benchmarking-emerald-subset.yml

03_production-run.yml  # high priority
```

**Features:**

- **Filenames only**: List just the config filename; the directory is inferred from the config list's location
- **Comments**: Lines starting with `#` (after whitespace) are skipped
- **Inline comments**: Text after `#` on any line is ignored (e.g., `config.yml # note`)
- **Blank lines**: Empty lines are ignored for readability
- **Backward compatibility**: Absolute paths (starting with `/`) still work if needed

The project name will be automatically derived from the config filename (e.g., `project-name.yml` becomes project `project-name`), unless explicitly set in the config file at `project.project_name` (which takes priority).

You can create your own config list file and name it whatever you want, placing it anywhere within `/ofo-share/argo-data/`. Then specify the path to it within the container (using `/data/XYZ` to refer to `/ofo-share/argo-data/XYZ`) using the `CONFIG_LIST` parameter when submitting the workflow.

### Determine the maximum number of projects to process in parallel

When tasked with parallelizing across multiple multi-step DAGs, Argo prioritizes breadth first. So
when it has a choice, it will start on a new DAG (metashape project) rather than starting the next
step of an existing one. This is unfortunately not customizable, and it is undesirable because the
workflow involves storing in-process files (including raw imagery, metashape project, outputs)
locally during processing. Our shared storage does not have the space to store all files locally at
the same time. In addition, we have a limited number of Metashape licenses. So we need to restrict
the number of parallel DAGs (metashape projects) it will attempt to run.

The workflow controls this via the `parallelism` field in the `main` template (line 66 in
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
  -p CONFIG_LIST=/data/argo-input/configs/config-list.txt \
  -p TEMP_WORKING_DIR=/data/argo-output/tmp/derek-0202 \
  -p S3_BUCKET_INTERNAL=ofo-internal \
  -p S3_PHOTOGRAMMETRY_DIR=photogrammetry-outputs_dytest02 \
  -p PHOTOGRAMMETRY_CONFIG_ID=03 \
  -p S3_BUCKET_PUBLIC=ofo-public \
  -p S3_POSTPROCESSED_DIR=drone_dytest02 \
  -p S3_BOUNDARY_DIR=drone_dytest02 \
  -p OFO_ARGO_IMAGES_TAG=latest \
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
| `CONFIG_LIST` | **Absolute path** to text file listing metashape config files. Each line should be a config filename (resolved relative to the config list's directory) or an absolute path. Lines starting with `#` are comments. Example: `/data/argo-input/configs/config-list.txt` |
| `TEMP_WORKING_DIR` | **Absolute path** for temporary workflow files (both photogrammetry and postprocessing). Workflow creates `{workflow-name}/{iteration-id}/` subdirectories automatically for each mission. Iteration directories are automatically deleted after successful postprocessing to free disk space. Example: `/data/argo-output/temp-runs/gillan_june27` |
| `PHOTOGRAMMETRY_CONFIG_ID` | Two-digit configuration ID (e.g., `01`, `02`) used to organize outputs into `photogrammetry_NN` subdirectories in S3 for both raw and postprocessed products. If not specified or set to `NONE`, both raw and postprocessed products are stored without the `photogrammetry_NN` subfolder. |
| `S3_BUCKET_INTERNAL` | S3 bucket for internal/intermediate outputs where raw Metashape products (orthomosaics, point clouds, DEMs) are uploaded (typically `ofo-internal`). |
| `S3_PHOTOGRAMMETRY_DIR` | S3 directory name for raw Metashape outputs. When `PHOTOGRAMMETRY_CONFIG_ID` is set, products upload to `{S3_BUCKET_INTERNAL}/{S3_PHOTOGRAMMETRY_DIR}/photogrammetry_{PHOTOGRAMMETRY_CONFIG_ID}/`. When `PHOTOGRAMMETRY_CONFIG_ID` is not set, products go to `{bucket}/{S3_PHOTOGRAMMETRY_DIR}/`. Example: `photogrammetry-outputs` |
| `S3_BUCKET_PUBLIC` | S3 bucket for public/final outputs (postprocessed, clipped products ready for distribution) and where boundary files are stored (typically `ofo-public`). |
| `S3_POSTPROCESSED_DIR` | S3 directory name for postprocessed outputs. When `PHOTOGRAMMETRY_CONFIG_ID` is set, products are organized as `{S3_POSTPROCESSED_DIR}/{mission_name}/photogrammetry_{PHOTOGRAMMETRY_CONFIG_ID}/`. When not set, products go to `{S3_POSTPROCESSED_DIR}/{mission_name}/`. Example: `drone/missions_03` |
| `S3_BOUNDARY_DIR` | Parent directory in `S3_BUCKET_PUBLIC` where mission boundary polygons reside (used to clip imagery). The structure beneath this directory is assumed to be: `<S3_BOUNDARY_DIR>/<mission_name>/metadata-mission/<mission_name>_mission-metadata.gpkg`. Example: `drone/missions_03` |
| `OFO_ARGO_IMAGES_TAG` | Docker image tag for OFO Argo containers (postprocessing and argo-workflow-utils) (default: `latest`). Use a specific branch name or tag to test development versions (e.g., `dy-manila`) |
| `AUTOMATE_METASHAPE_IMAGE_TAG` | Docker image tag for the automate-metashape container (default: `latest`). Use a specific branch name or tag to test development versions |
| `LICENSE_RETRY_INTERVAL` | Seconds to wait between license acquisition retries (default: `300` = 5 minutes). See [License Retry Behavior](#license-retry-behavior) |
| `LICENSE_MAX_RETRIES` | Maximum license retry attempts. `0` = no retries (fail immediately, default), `-1` = unlimited retries, `>0` = that many retries. See [License Retry Behavior](#license-retry-behavior) |
| `LOG_HEARTBEAT_INTERVAL` | Seconds between heartbeat status lines during Metashape processing (default: `60`). Set to `0` to disable filtering and print all Metashape output (original behavior). See [Heartbeat Logger and Progress Monitoring](#heartbeat-logger-and-progress-monitoring) |
| `LOG_BUFFER_SIZE` | Number of recent output lines kept in memory for error context (default: `100`). On failure, these lines are dumped to console for immediate debugging. See [Heartbeat Logger and Progress Monitoring](#heartbeat-logger-and-progress-monitoring) |
| `PROGRESS_INTERVAL_PCT` | Percentage interval for progress reporting during Metashape API calls (default: `1`). Prints structured `[progress]` lines at each threshold (e.g., 1%, 2%, 3%). See [Heartbeat Logger and Progress Monitoring](#heartbeat-logger-and-progress-monitoring) |
| `COMPLETION_LOG_PATH` | Path to completion log file for tracking finished projects (default: `""`). When set, the workflow logs completed projects and can skip already-completed work. See [Completion Tracking and Skip-If-Complete](#completion-tracking-and-skip-if-complete) |
| `SKIP_IF_COMPLETE` | Skip projects based on completion status (default: `"none"`). Options: `none` (never skip), `metashape` (skip if metashape or postprocess complete), `postprocess` (skip only if postprocess complete), `both` (granular: skip metashape if done, run postprocessing). See [Completion Tracking and Skip-If-Complete](#completion-tracking-and-skip-if-complete) |
| `DB_*` | Database parameters for logging Argo status (not currently functional; credentials in [OFO credentials document](https://docs.google.com/document/d/155AP0P3jkVa-yT53a-QLp7vBAfjRa78gdST1Dfb4fls/edit?tab=t.0)) |

**Secrets configuration:**

- **S3 credentials**: S3 access credentials, provider type, and endpoint URL are configured via the `s3-credentials` Kubernetes secret
- **Agisoft license**: Metashape floating license server address is configured via the
  `agisoft-license` Kubernetes secret

These secrets should have been created (within the `argo` namespace) during [cluster creation](../admin/cluster-creation-and-resizing.md).

### License Retry Behavior

Metashape requires a floating license from the Agisoft license server. When multiple workflows compete for limited licenses, some pods may fail to acquire a license at startup. The workflow includes optional retry logic to handle this.

**By default, retries are disabled** (`LICENSE_MAX_RETRIES=0`). If no license is available, the step fails immediately. To enable retries, set `LICENSE_MAX_RETRIES` to a positive number or `-1` for unlimited.

**How it works (when retries are enabled):**

1. When a Metashape step starts, it checks for license availability in the first 20 lines of output
2. If "license not found" is detected, the process terminates immediately (avoiding wasted compute)
3. After waiting `LICENSE_RETRY_INTERVAL` seconds (default: 300 = 5 minutes), the step retries
4. This continues until either a license is acquired or `LICENSE_MAX_RETRIES` is reached

**`LICENSE_MAX_RETRIES` values:**

| Value | Behavior |
|-------|----------|
| `0` (default) | No retries - fail immediately if no license |
| `-1` | Unlimited retries |
| `>0` | Retry up to that many times |

**Example output when retries are disabled (default):**
```
[license-wrapper] Starting Metashape workflow (attempt 1)...
No nodelocked license found
License server 149.165.171.237:5842: License not found
[license-wrapper] No license available and retries disabled (LICENSE_MAX_RETRIES=0)
```

**Example output when retries are enabled:**
```
[license-wrapper] Starting Metashape workflow (attempt 1)...
No nodelocked license found
License server 149.165.171.237:5842: License not found
[license-wrapper] No license available. Waiting 300s before retry...
[license-wrapper] Starting Metashape workflow (attempt 2)...
```

**Example output when license is acquired:**
```
[license-wrapper] Starting Metashape workflow (attempt 1)...
No nodelocked license found
License server 149.165.171.237:5842: OK
[license-wrapper] License check passed, proceeding with workflow...
```

!!! tip "When to enable retries"
    - **High contention (many parallel workflows)**: Set `LICENSE_MAX_RETRIES=-1` for unlimited retries, or a reasonable limit like `288` (24 hours at 5-minute intervals)
    - **Low contention**: Keep the default (`0`) - if a license isn't available, something is likely wrong

## Heartbeat Logger and Progress Monitoring

Metashape produces extremely verbose stdout during processing. With many projects running in parallel, this volume of logs taxes the Argo artifact store and k8s control plane. The heartbeat logger reduces console output to ~50-100 lines per multi-hour job while preserving full debugging context on errors.

### How It Works

The system has two layers:

1. **Progress callbacks**: Metashape API calls report structured `[progress] step: X%` messages at configurable intervals (e.g., every 10%)
2. **Output monitor**: The license retry wrapper filters subprocess output, writing the full log to a file on the shared volume while only passing through important lines to the console

### Operating Modes

The behavior is controlled by `LOG_HEARTBEAT_INTERVAL`:

**Sparse mode (default, `LOG_HEARTBEAT_INTERVAL > 0`):**

- Console shows only `[progress]`, `[license-wrapper]`, and `[monitor]` lines, plus periodic heartbeats
- Heartbeat includes timestamp, line count, elapsed time, and the most recent Metashape output line
- Full log file written to disk with every line (no timestamps added, zero overhead)
- On failure, the last `LOG_BUFFER_SIZE` lines are dumped to console for immediate debugging

**Full output mode (`LOG_HEARTBEAT_INTERVAL=0`):**

- Every line printed to console (original behavior)
- `[progress]` milestones still appear at configured intervals
- Full log file still written to disk
- Error buffer still dumped on failure

### Console Output Examples

**Normal operation (sparse mode):**
```
[license-wrapper] Starting Metashape workflow (attempt 1)...
No nodelocked license found
License server 149.165.171.237:5842: OK
[license-wrapper] License check passed, proceeding with workflow...
[monitor] Full log: /data/.../photogrammetry/metashape-build_depth_maps.log
[progress] buildDepthMaps: 10%
[heartbeat] 14:32:15 | lines: 247 | elapsed: 60s | last: Processing depth map for camera 145...
[progress] buildDepthMaps: 20%
[progress] buildDepthMaps: 30%
[heartbeat] 14:33:15 | lines: 512 | elapsed: 120s | last: Building point cloud from depth maps... chunk 3/12
[progress] buildDepthMaps: 40%
...
[progress] buildDepthMaps: 100%
[monitor] SUCCESS | total lines: 5247 | elapsed: 3847s
[monitor] Full log saved to: /data/.../photogrammetry/metashape-build_depth_maps.log
```

**Error with buffer dump (sparse mode):**
```
[progress] buildDepthMaps: 60%

[monitor] === Last 100 lines before error ===
2024-02-08 15:47:15 Processing depth map for camera 3180...
...
2024-02-08 15:47:45 Error: Insufficient memory for depth map computation
RuntimeError: Not enough memory
[monitor] === End error context ===

[monitor] FAILED (exit code 1) | total lines: 3247 | elapsed: 7215s
[monitor] Full log saved to: /data/.../photogrammetry/metashape-build_depth_maps.log
```

### Full Log Files

Complete Metashape output is saved to the shared volume at:

```
{TEMP_WORKING_DIR}/{workflow-name}/{project-name}/photogrammetry/metashape-<step>.log
```

These files contain every line of output as-is (no timestamps added) and are available for download from the Argo UI artifacts or via direct filesystem access. They are automatically cleaned up by the existing cleanup step after workflow completion.

### Configuration

All three parameters have sensible defaults and require no configuration for normal use:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `LOG_HEARTBEAT_INTERVAL` | `60` | Seconds between heartbeat lines. `0` = full output mode |
| `LOG_BUFFER_SIZE` | `100` | Lines kept in memory for error context dump |
| `PROGRESS_INTERVAL_PCT` | `1` | Progress reporting interval (%) |

To use full output mode (e.g., for debugging or initial validation):

```bash
argo submit -n argo photogrammetry-workflow-stepbased.yaml \
  -p LOG_HEARTBEAT_INTERVAL=0 \
  # ... other parameters ...
```

!!! tip "Migration path"
    Start with `LOG_HEARTBEAT_INTERVAL=0` (full output mode) to validate that progress callbacks and log files work correctly. Then switch to the default sparse mode (`60`) once you're comfortable with the reduced console output. You can always set it back to `0` without any code changes.

## Completion Tracking and Skip-If-Complete

The workflow includes a completion tracking system that logs finished projects and can automatically skip already-completed work. This is useful for:

- **Resuming cancelled workflows**: Resubmit a workflow and automatically skip projects that already completed
- **Iterative processing**: Re-run with different postprocessing settings without redoing Metashape processing
- **Cost optimization**: Avoid wasting compute resources on already-completed projects
- **Partial reruns**: Selectively reprocess only Metashape or only postprocessing steps

### How It Works

When `COMPLETION_LOG_PATH` is set, the workflow:

1. **Reads the completion log** at workflow start to determine which projects are already complete
2. **Filters projects** based on `SKIP_IF_COMPLETE` setting before creating processing tasks
3. **Logs completion** after successful Metashape processing and after successful postprocessing
4. **Enables granular skipping** (with `SKIP_IF_COMPLETE=both`): Skip only Metashape if it's done, still run postprocessing

### Completion Log Format

The completion log is a JSON Lines file (`.jsonl`) where each line represents a completed project stage:

```jsonl
{"project_name":"mission_001","completion_level":"postprocess","timestamp":"2024-01-15T10:30:00Z","workflow_name":"automate-metashape-workflow-abc123"}
{"project_name":"mission_002","completion_level":"metashape","timestamp":"2024-01-15T11:45:00Z","workflow_name":"automate-metashape-workflow-def456"}
```

**Fields:**

| Field | Description |
|-------|-------------|
| `project_name` | Project identifier from config file |
| `completion_level` | Either `"metashape"` (Metashape processing complete) or `"postprocess"` (postprocessing complete) |
| `timestamp` | ISO 8601 UTC timestamp when the stage completed |
| `workflow_name` | Argo workflow name for traceability |

**Key behavior:**

- **Use separate log files for different configs** (e.g., `completion-log-default.jsonl`, `completion-log-highres.jsonl`)
- Each project can have at most two entries in a log file: one for `metashape` and one for `postprocess`
- If multiple entries exist for the same project, the highest completion level is used (`postprocess` > `metashape`)
- The log file is created automatically if it doesn't exist
- Concurrent writes from parallel projects are handled safely with file locking

### Skip Modes

The `SKIP_IF_COMPLETE` parameter controls which projects are skipped:

| Mode | Behavior | Use Case |
|------|----------|----------|
| `none` (default) | Never skip any projects | Fresh processing run |
| `metashape` | Skip entire project if metashape OR postprocess is complete | Resume after cancellation, avoiding all completed work |
| `postprocess` | Skip entire project only if postprocess is complete | Conservative: only skip fully finished projects |
| `both` | **Granular skipping**: Skip entire project if postprocess complete; skip only Metashape steps if metashape complete (still run postprocessing) | Re-run postprocessing with different settings |

**Granular skipping with `both` mode:**

When a project has `metashape` completion but not `postprocess` completion:

- All 10 Metashape processing steps are skipped
- Postprocessing still runs, using the previously uploaded Metashape outputs from S3
- Useful for tweaking postprocessing parameters without rerunning expensive Metashape steps

### Usage Examples

#### Resume a cancelled workflow

If a workflow was cancelled or failed partway through, resubmit with the same completion log to skip already-finished projects:

```bash
argo submit -n argo photogrammetry-workflow-stepbased.yaml \
  -p CONFIG_LIST=/data/argo-input/configs/batch1.txt \
  -p COMPLETION_LOG_PATH=/data/argo-input/config-lists/completion-log-default.jsonl \
  -p SKIP_IF_COMPLETE=postprocess \
  -p TEMP_WORKING_DIR=/data/argo-output/tmp/batch1 \
  # ... other parameters ...
```

Only projects that haven't completed postprocessing will run.

#### Re-run postprocessing only

If you want to adjust postprocessing parameters (e.g., clipping boundaries, COG settings) without redoing Metashape processing:

```bash
argo submit -n argo photogrammetry-workflow-stepbased.yaml \
  -p CONFIG_LIST=/data/argo-input/configs/batch1.txt \
  -p COMPLETION_LOG_PATH=/data/argo-input/config-lists/completion-log-default.jsonl \
  -p SKIP_IF_COMPLETE=both \
  -p TEMP_WORKING_DIR=/data/argo-output/tmp/batch1-reprocess \
  # ... other parameters ...
```

Projects with completed Metashape will skip all Metashape steps but run postprocessing.

#### Force complete reprocessing

To reprocess everything regardless of completion log (useful for testing or when products need to be regenerated):

```bash
argo submit -n argo photogrammetry-workflow-stepbased.yaml \
  -p CONFIG_LIST=/data/argo-input/configs/batch1.txt \
  -p COMPLETION_LOG_PATH=/data/argo-input/config-lists/completion-log-default.jsonl \
  -p SKIP_IF_COMPLETE=none \
  # ... other parameters ...
```

All projects will run, but completion will still be logged for future use.

#### First-time processing with completion tracking

Enable completion tracking from the start to make future reruns easier:

```bash
argo submit -n argo photogrammetry-workflow-stepbased.yaml \
  -p CONFIG_LIST=/data/argo-input/configs/batch1.txt \
  -p COMPLETION_LOG_PATH=/data/argo-input/config-lists/completion-log-default.jsonl \
  -p SKIP_IF_COMPLETE=none \
  # ... other parameters ...
```

The log will be created and populated as projects complete.

### Bootstrapping from Existing Products

If you have projects that were processed before completion tracking was implemented, you can generate a retroactive completion log by scanning S3 buckets for existing products.

Use the `generate_retroactive_log.py` utility script (requires `boto3` Python package):

```bash
# Install dependency
pip install boto3

# Set S3 credentials (for non-AWS S3 like Ceph/MinIO)
export S3_ENDPOINT=https://s3.example.com
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key

# Generate log from existing S3 products for default config
python docker-workflow-utils/manually-run-utilities/generate_retroactive_log.py \
  --internal-bucket ofo-internal \
  --internal-prefix photogrammetry/default-run \
  --public-bucket ofo-public \
  --public-prefix postprocessed \
  --output /data/argo-input/config-lists/completion-log-default.jsonl

# For a specific config (e.g., highres), use config-specific prefix and output file
python docker-workflow-utils/manually-run-utilities/generate_retroactive_log.py \
  --internal-bucket ofo-internal \
  --internal-prefix photogrammetry/default-run/photogrammetry_highres \
  --public-bucket ofo-public \
  --public-prefix postprocessed \
  --output /data/argo-input/config-lists/completion-log-highres.jsonl
```

**Script options:**

| Option | Description |
|--------|-------------|
| `--internal-bucket` | S3 bucket for internal/Metashape products |
| `--internal-prefix` | S3 prefix for Metashape products, including any config-specific subdirectories (e.g., `photogrammetry/default-run` for default config, or `photogrammetry/default-run/photogrammetry_highres` for highres config) |
| `--public-bucket` | S3 bucket for public/postprocessed products |
| `--public-prefix` | S3 prefix for postprocessed products |
| `--level` | Which completion levels to detect: `metashape`, `postprocess`, or `both` (default: `both`) |
| `--output` | Output file path for completion log. **Use config-specific names** (e.g., `completion-log-default.jsonl`, `completion-log-highres.jsonl`) |
| `--append` | Append to existing log instead of overwriting |
| `--dry-run` | Preview what would be written without actually writing |

**Example dry run to preview results:**

```bash
python docker-workflow-utils/manually-run-utilities/generate_retroactive_log.py \
  --internal-bucket ofo-internal \
  --internal-prefix photogrammetry/default-run \
  --public-bucket ofo-public \
  --public-prefix postprocessed \
  --dry-run \
  --output /tmp/completion-log-default.jsonl
```

The script detects completed projects by looking for sentinel files:

- **Metashape complete**: `*_report.pdf` in the project folder
- **Postprocess complete**: `<project_name>_ortho.tif` in the public bucket

### Generating Remaining Configs After Cancellation

If you need to create a new config list containing only uncompleted projects (useful for manual workflow management):

```bash
python docker-workflow-utils/manually-run-utilities/generate_remaining_configs.py \
  /data/argo-input/configs/batch1.txt \
  /data/argo-input/config-lists/completion-log-default.jsonl \
  --level postprocess \
  -o /data/argo-input/configs/batch1-remaining.txt
```

This reads the original config list, filters out completed projects, and outputs a new config list with only remaining projects. **Note:** Use the config-specific completion log file (e.g., `completion-log-default.jsonl`).

### Troubleshooting Completion Tracking

#### Projects not being skipped when they should be

**Possible causes:**

1. **Wrong completion log file**: Using the wrong config-specific log file
   - **Solution**: Ensure `COMPLETION_LOG_PATH` points to the correct config-specific log (e.g., `completion-log-default.jsonl` for default config, `completion-log-highres.jsonl` for highres config)

2. **Project name mismatch**: The project name in the log doesn't match the config file's project name
   - **Debug**: Check the `determine-projects` step logs to see extracted project names
   - **Solution**: Ensure `project.project_name` in config matches the log entry

3. **Wrong skip mode**: `SKIP_IF_COMPLETE` is set to `none` or a mode that doesn't match completion level
   - **Solution**: Use `postprocess` for conservative skipping, or `both` for granular control

4. **Completion log path incorrect**: The log file isn't where the workflow expects
   - **Debug**: Check workflow logs for "completion log not found" messages
   - **Solution**: Verify `COMPLETION_LOG_PATH` is correct and accessible from containers

#### Projects being skipped when they shouldn't be

**Possible causes:**

1. **Stale log entries**: The log contains entries from previous runs that should be removed
   - **Solution**: Manually edit the `.jsonl` file to remove unwanted entries, or start with a fresh log

2. **Wrong log file**: Using a log file from a different configuration
   - **Solution**: Verify you're using the correct config-specific log file (e.g., `completion-log-default.jsonl` for default config, not a log from highres config)

#### Completion log corruption or malformed entries

**Symptoms:** Warnings in `determine-projects` logs about "malformed line" or "skipping line"

**Causes:**

- Manual editing introduced invalid JSON
- Concurrent writes without proper locking (shouldn't happen with the workflow, but possible with external tools)

**Solutions:**

1. **Validate the JSON Lines file:**
   ```bash
   python3 -c "
   import json, sys
   for i, line in enumerate(open('/path/to/completion-log.jsonl'), 1):
       if line.strip():
           try:
               json.loads(line)
           except json.JSONDecodeError as e:
               print(f'Line {i}: {e}')
   "
   ```

2. **Regenerate from S3** using `generate_retroactive_log.py`

3. **Manual fix**: Edit the `.jsonl` file with a text editor, ensuring each line is valid JSON

#### Disk space issues with completion log

**Unlikely scenario**, but if the log grows very large (thousands of projects over many months):

- **Solution**: Archive or split old log entries by date/config_id
- **Note**: The log file size is minimal (~150 bytes per entry), so this is rarely a concern

## Monitor the workflow

### Using the Argo UI

The Argo UI is great for troubleshooting and checking individual step progress. Access it at [argo.focal-lab.org](https://argo.focal-lab.org), using the credentials from [Vaultwarden](https://vault.focal-lab.org) under the record "Argo UI token".

#### Navigating the Argo UI

The **Workflows** tab on the left side menu shows all running workflows. Click a workflow to see a detailed DAG (directed acyclic graph) showing:

- **Preprocessing task**: The `determine-projects` step that reads config files
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

#### Multi-mission miew

When processing multiple missions, the Argo UI shows all missions side-by-side. This makes it easy to:

- See which missions are at which step
- Identify if one mission is failing while others succeed
- Compare processing times across missions
- Monitor overall workflow progress

#### Understanding step names

Task names in the Argo UI follow the pattern `process-projects-N.<step-name>`:

- `process-projects-0.setup` - Setup step for first mission (index 0)
- `process-projects-0.match-photos-gpu` - Match photos on GPU for first mission
- `process-projects-1.build-depth-maps` - Build depth maps for second mission (index 1)

!!! tip "Finding Your Mission"
    To identify which mission corresponds to which index:

    1. Check the `determine-projects` step logs to see the order of missions in the JSON output
    2. Click on any task (e.g., `process-projects-0.setup`) and view the parameters to see the `project-name` value
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
argo logs <workflow-name> -c determine-projects

# Get logs for a specific mission's step
# Format: process-projects-<N>.<step-name>
argo logs <workflow-name> -c process-projects-0.setup
argo logs <workflow-name> -c process-projects-0.match-photos-gpu
argo logs <workflow-name> -c process-projects-1.build-depth-maps

# Follow logs in real-time
argo logs <workflow-name> -c process-projects-0.setup -f
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
               ├── dataset1_points.copc.laz
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
               ├── dataset1_points.copc.laz
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

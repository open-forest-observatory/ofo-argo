# Implementation Plan: S3 Imagery Zip Download Feature

## Context

The OFO step-based photogrammetry workflow currently requires imagery to already exist on the shared PVC at `/data/`. Users must manually upload imagery before running workflows, which is time-consuming and requires separate coordination.

The workflow processes multiple projects in parallel using Argo's `withParam` mechanism. Each project has its own configuration file that specifies, among other things, the `photo_path` where imagery is located.

## Problem Statement

Users need the ability to have the workflow automatically download imagery from S3 (via rclone) at runtime, rather than requiring imagery to be pre-staged on the PVC. This is especially useful for:
- Running workflows on imagery stored in cloud object storage
- Avoiding manual pre-upload steps
- Processing imagery that doesn't need to persist after the workflow

## Goals

1. Allow users to specify S3 zip file(s) to download in the `argo:` section of their config
2. Automatically download and unzip imagery before photogrammetry begins
3. Provide a simple path prefix (`__DOWNLOADED__`) for users to reference downloaded imagery
4. Isolate downloads per-project to prevent collisions in parallel execution
5. Clean up downloaded imagery after workflow completion (configurable)
6. Fail gracefully: individual project failures should not stop other projects

## Non-Goals (Future Possibilities)

- Sharing downloaded imagery between projects (would save bandwidth but adds complexity with timing and storage management)
- Downloading non-zip formats (tarballs, raw folders)
- Incremental/resumable downloads
- Per-project folder reorganization (see Future Enhancements section)

---

## User Experience

### Config File Example

```yaml
argo:
  # New: List of S3 zip files to download (can also be a single string)
  # Format: bucket/path/file.zip (no remote prefix needed)
  # S3 credentials come from the cluster's s3-credentials Kubernetes secret
  s3_imagery_zip_download:
    - ofo-public/drone/missions_01/000558/images/000558_images.zip
    - ofo-public/drone/missions_01/000559/images/000559_images.zip

  # New: Whether to delete downloaded imagery after workflow (default: true)
  cleanup_downloaded_imagery: true

  # Existing settings...
  match_photos:
    gpu_enabled: true

project:
  project_name: my_forest_plot
  # Use __DOWNLOADED__ prefix to reference downloaded imagery
  photo_path:
    - __DOWNLOADED__/000558_images/000558-01
    - __DOWNLOADED__/000558_images/000558-02
    - __DOWNLOADED__/000559_images/000559-01
```

### Expected Behavior

1. Workflow downloads `000558_images.zip` and `000559_images.zip`
2. Each zip is extracted to a folder named after the zip (sans `.zip` extension)
3. The `__DOWNLOADED__` prefix is replaced with the actual download path
4. Photogrammetry runs with the resolved paths
5. After photogrammetry completes, downloaded imagery is deleted (if cleanup enabled)

---

## Architecture Overview

### Download Location

```
{TEMP_WORKING_DIR}/downloaded_imagery/{iteration_id}/
├── 000558_images/
│   ├── 000558-01/
│   │   └── *.jpg
│   └── 000558-02/
│       └── *.jpg
└── 000559_images/
    └── 000559-01/
        └── *.jpg
```

- `TEMP_WORKING_DIR` = `/ofo-share/argo-working/{workflow-name}` (already exists)
- `iteration_id` = `{index}_{project_name_sanitized}` with 3-digit zero-padded index
  - Examples: `000_mission_001`, `001_mission_001`, `002_other_project`
  - Includes project name for easy identification during manual intervention
  - Index ensures uniqueness even with duplicate project names in the same config list

### Workflow DAG Changes

Current flow:
```
setup-photogrammetry → match-photos → align-cameras → ...
```

New flow:
```
download-imagery (conditional) → setup-photogrammetry → ... → cleanup-imagery (conditional)
```

---

## Implementation Steps

### Step 1: Update Config Parsing in `determine_datasets.py`

**File:** `docker-workflow-utils/determine_datasets.py`

**Changes needed:**

1. **Add iteration ID generation**: When building the list of mission parameters, generate a unique `iteration_id` combining the zero-padded index (3 digits) and the sanitized project name, separated by underscore.

2. **Extract new argo attributes**: Parse `s3_imagery_zip_download` and `cleanup_downloaded_imagery` from the `argo:` section.

3. **Normalize to list**: Handle both single string and list inputs for `s3_imagery_zip_download`.

4. **Add new output parameters**: Include in the JSON output for each mission:
   - `iteration_id`: Format `{index:03d}_{project_name_sanitized}` (e.g., `000_mission_001`)
   - `imagery_zip_downloads`: JSON array of S3 URLs (empty array if not specified)
   - `imagery_download_enabled`: Boolean flag for conditional step execution
   - `cleanup_downloaded_imagery`: Boolean (default `true`)

**Example of parameter extraction logic:**

```python
# In process_config_file() function, after loading argo_config:
# Note: index is the enumeration index passed to this function

# Generate unique iteration ID: 3-digit zero-padded index + underscore + sanitized project name
# Example: "000_mission_001", "001_mission_001" (for duplicates), "002_other_project"
iteration_id = f"{index:03d}_{project_name_sanitized}"

# Extract imagery download settings
imagery_downloads = argo_config.get('s3_imagery_zip_download', [])
if isinstance(imagery_downloads, str):
    imagery_downloads = [imagery_downloads] if imagery_downloads.strip() else []

cleanup_imagery = argo_config.get('cleanup_downloaded_imagery', True)
```

**Add to mission_params dict:**
```python
mission_params['iteration_id'] = iteration_id
mission_params['imagery_zip_downloads'] = json.dumps(imagery_downloads)
mission_params['imagery_download_enabled'] = str(len(imagery_downloads) > 0).lower()
mission_params['cleanup_downloaded_imagery'] = str(cleanup_imagery).lower()
```

**Add comment for future enhancement:**
```python
# FUTURE: Could implement download sharing between projects to save bandwidth.
# Would require: (1) download coordination/locking, (2) reference counting for cleanup,
# (3) handling projects that start days apart. Current approach downloads per-project
# to avoid these complexities and prevent storage issues from long-running workflows.
```

---

### Step 2: Create Download Script

**File:** `docker-workflow-utils/download_imagery.py` (new file)

**Purpose:** Download and extract zip files from S3, preparing imagery for photogrammetry.

**Inputs (via environment variables or arguments):**
- `IMAGERY_ZIP_URLS`: JSON array of S3 paths (format: `bucket/path/file.zip`, no remote prefix)
- `DOWNLOAD_BASE_DIR`: Base directory for downloads (e.g., `{TEMP_WORKING_DIR}/downloaded_imagery`)
- `ITERATION_ID`: Unique ID for this project iteration
- S3 credentials: `S3_PROVIDER`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`

**Logic:**

1. Parse the JSON array of URLs
2. Create project-specific download directory: `{DOWNLOAD_BASE_DIR}/{ITERATION_ID}/`
3. For each URL:
   a. Extract filename from URL (e.g., `000558_images.zip`)
   b. Download using rclone: `rclone copyto {url} {download_dir}/{filename}`
   c. Determine extraction folder name (filename sans `.zip`)
   d. Create extraction directory
   e. Unzip: `unzip {download_dir}/{filename} -d {download_dir}/{folder_name}`
   f. Delete zip file to save space
4. Output the download path for use by subsequent steps

**Error handling:**
- If any download or extraction fails, exit with non-zero status
- Log clear error messages identifying which URL failed
- Do not attempt partial cleanup on failure (let workflow handle)

**Example rclone command construction:**

Use the existing `get_s3_flags()` pattern from `docker-photogrammetry-postprocessing/entrypoint.py` for consistency:

```python
def get_s3_flags():
    """Build common S3 authentication flags for rclone commands."""
    return [
        "--s3-provider", os.environ.get("S3_PROVIDER"),
        "--s3-endpoint", os.environ.get("S3_ENDPOINT"),
        "--s3-access-key-id", os.environ.get("S3_ACCESS_KEY"),
        "--s3-secret-access-key", os.environ.get("S3_SECRET_KEY"),
    ]

# Download command using rclone's on-the-fly backend syntax (:s3:)
# This avoids needing a pre-configured remote - credentials come from flags
# User specifies just "bucket/path/file.zip", we prepend ":s3:"
rclone_url = f":s3:{s3_path}"
rclone_cmd = [
    "rclone", "copyto",
    rclone_url,
    f"{download_dir}/{filename}",
    "--progress",
    "--transfers", "8",
    "--checkers", "8",
    "--retries", "5",
    "--retries-sleep", "15s",
    "--stats", "30s",
] + get_s3_flags()
```

---

### Step 3: Create Config Transform Script

**File:** `docker-workflow-utils/transform_config.py` (new file)

**Purpose:** Replace `__DOWNLOADED__` prefix in config's `photo_path` with actual download path.

**Inputs:**
- `CONFIG_FILE`: Path to original config file
- `OUTPUT_CONFIG_FILE`: Path to write transformed config
- `DOWNLOADED_IMAGERY_PATH`: Actual path to downloaded imagery

**Logic:**

1. Load YAML config file
2. Get `photo_path` from `project` section
3. If `photo_path` is a string, convert to single-item list for uniform handling
4. Replace `__DOWNLOADED__` prefix with actual path in each photo_path entry
5. Write modified config to output path
6. Preserve all other config settings unchanged

**Example transformation:**
```python
# Input photo_path: __DOWNLOADED__/000558_images/000558-01
# DOWNLOADED_IMAGERY_PATH: /ofo-share/argo-working/wf-abc123/downloaded_imagery/000_my_project
# Output photo_path: /ofo-share/argo-working/wf-abc123/downloaded_imagery/000_my_project/000558_images/000558-01
```

**Validation (exit non-zero on failure):**
- **FAIL** if `__DOWNLOADED__` prefix is used in `photo_path` but no downloads were specified in config
- **FAIL** if downloads were specified but no `__DOWNLOADED__` paths found in `photo_path`
- These are configuration errors that should be caught early rather than causing cryptic failures later

---

### Step 4: Create Cleanup Script

**File:** `docker-workflow-utils/cleanup_imagery.py` (new file)

**Purpose:** Delete downloaded imagery after photogrammetry completes.

**Inputs:**
- `DOWNLOAD_DIR`: Directory to delete (e.g., `{TEMP_WORKING_DIR}/downloaded_imagery/{ITERATION_ID}`)

**Logic:**

1. Verify directory exists and is within expected base path (safety check)
2. Remove directory recursively
3. Log success/failure

**Safety checks (exit non-zero on failure):**
- **FAIL** if path doesn't contain expected components (`downloaded_imagery`, `argo-working`)
- **FAIL** if path appears to be outside the expected temp working directory structure
- This prevents accidental deletion of important data if paths are misconfigured
- A failed safety check indicates a bug or misconfiguration that needs investigation

---

### Step 5: Update Workflow YAML

**File:** `photogrammetry-workflow-stepbased.yaml`

**Changes needed:**

#### 5.1: Add New Parameters to Workflow

In the `process-project-workflow` template's `inputs.parameters` section, add:

```yaml
- name: iteration-id
- name: imagery-zip-downloads
  default: "[]"
- name: imagery-download-enabled
  default: "false"
- name: cleanup-downloaded-imagery
  default: "true"
```

#### 5.2: Add Download Step Template

Create new template `download-imagery`:

```yaml
- name: download-imagery
  inputs:
    parameters:
      - name: imagery-zip-downloads
      - name: iteration-id
  container:
    image: ghcr.io/open-forest-observatory/docker-workflow-utils:latest
    command: ["python3", "/app/download_imagery.py"]
    env:
      - name: IMAGERY_ZIP_URLS
        value: "{{inputs.parameters.imagery-zip-downloads}}"
      - name: DOWNLOAD_BASE_DIR
        value: "{{workflow.parameters.TEMP_WORKING_DIR}}/downloaded_imagery"
      - name: ITERATION_ID
        value: "{{inputs.parameters.iteration-id}}"
      # S3 credentials from existing secret references
```

#### 5.3: Add Config Transform Step Template

Create new template `transform-config`:

```yaml
- name: transform-config
  inputs:
    parameters:
      - name: config-file
      - name: iteration-id
      - name: project-name
  container:
    image: ghcr.io/open-forest-observatory/docker-workflow-utils:latest
    command: ["python3", "/app/transform_config.py"]
    env:
      - name: CONFIG_FILE
        value: "{{inputs.parameters.config-file}}"
      - name: OUTPUT_CONFIG_FILE
        value: "{{workflow.parameters.TEMP_WORKING_DIR}}/configs/{{inputs.parameters.project-name}}-transformed.yml"
      - name: DOWNLOADED_IMAGERY_PATH
        value: "{{workflow.parameters.TEMP_WORKING_DIR}}/downloaded_imagery/{{inputs.parameters.iteration-id}}"
  outputs:
    parameters:
      - name: transformed-config-path
        value: "{{workflow.parameters.TEMP_WORKING_DIR}}/configs/{{inputs.parameters.project-name}}-transformed.yml"
```

#### 5.4: Add Cleanup Step Template

Create new template `cleanup-imagery`:

```yaml
- name: cleanup-imagery
  inputs:
    parameters:
      - name: iteration-id
  container:
    image: ghcr.io/open-forest-observatory/docker-workflow-utils:latest
    command: ["python3", "/app/cleanup_imagery.py"]
    env:
      - name: DOWNLOAD_DIR
        value: "{{workflow.parameters.TEMP_WORKING_DIR}}/downloaded_imagery/{{inputs.parameters.iteration-id}}"
```

#### 5.5: Update DAG Structure

Modify the `process-project-workflow` DAG to include new steps:

**Add download step (conditional):**
```yaml
- name: download-imagery
  template: download-imagery
  when: "{{inputs.parameters.imagery-download-enabled}} == 'true'"
  arguments:
    parameters:
      - name: imagery-zip-downloads
        value: "{{inputs.parameters.imagery-zip-downloads}}"
      - name: iteration-id
        value: "{{inputs.parameters.iteration-id}}"
```

**Add transform step (conditional, depends on download):**
```yaml
- name: transform-config
  template: transform-config
  when: "{{inputs.parameters.imagery-download-enabled}} == 'true'"
  depends: "download-imagery"
  arguments:
    parameters:
      - name: config-file
        value: "{{inputs.parameters.config-file}}"
      - name: iteration-id
        value: "{{inputs.parameters.iteration-id}}"
      - name: project-name
        value: "{{inputs.parameters.project-name}}"
```

**Update setup-photogrammetry dependency:**
- If downloads enabled: depends on `transform-config`
- Use transformed config path instead of original

**Add cleanup step at end (conditional):**
```yaml
- name: cleanup-imagery
  template: cleanup-imagery
  when: "{{inputs.parameters.imagery-download-enabled}} == 'true' && {{inputs.parameters.cleanup-downloaded-imagery}} == 'true'"
  depends: "upload-outputs"  # After all photogrammetry and upload complete
  arguments:
    parameters:
      - name: iteration-id
        value: "{{inputs.parameters.iteration-id}}"
```

#### 5.6: Handle Config Path Switching

The tricky part: subsequent steps need to use either the original config or transformed config.

Use Argo's conditional expression syntax to select the appropriate config path:

```yaml
- name: setup-photogrammetry
  arguments:
    parameters:
      - name: config-file
        # Conditional config path selection:
        # - If imagery download is enabled, use the transformed config (with __DOWNLOADED__ paths resolved)
        # - Otherwise, use the original config file path unchanged
        # This allows the same workflow DAG structure to handle both download and non-download cases
        value: "{{=inputs.parameters['imagery-download-enabled'] == 'true' ? steps['transform-config'].outputs.parameters['transformed-config-path'] : inputs.parameters['config-file']}}"
```

This conditional expression uses Argo's expression syntax (`{{= ... }}`) to evaluate at runtime which config path to pass to downstream steps.

**Alternative considered (rejected):** Always run the transform step and transform the config even if no downloads are specified, outputting to a consistent location. This was rejected because it adds unnecessary processing overhead for the common case where no downloads are needed, and the conditional approach is cleaner.

---

### Step 6: Update Docker Image Build

**File:** `docker-workflow-utils/Dockerfile`

**Changes:**
- Ensure `rclone` is installed (follow pattern from `docker-photogrammetry-postprocessing/Dockerfile`)
- Ensure `unzip` package is installed
- Include new Python scripts: `download_imagery.py`, `transform_config.py`, `cleanup_imagery.py`
- Ensure PyYAML is available for config parsing

---

### Step 7: Update Parameter Passing in Main Template

**File:** `photogrammetry-workflow-stepbased.yaml`

In the `main` template where `withParam` iterates, add the new parameters to the arguments:

```yaml
- name: process-projects
  template: process-project-workflow
  arguments:
    parameters:
      # Existing parameters...
      - name: iteration-id
        value: "{{item.iteration_id}}"
      - name: imagery-zip-downloads
        value: "{{item.imagery_zip_downloads}}"
      - name: imagery-download-enabled
        value: "{{item.imagery_download_enabled}}"
      - name: cleanup-downloaded-imagery
        value: "{{item.cleanup_downloaded_imagery}}"
```

---

### Step 8: Update Documentation

**File:** `docs/usage/stepbased-workflow.md`

Add new section documenting:

1. **When to use S3 imagery download** - Use cases and benefits
2. **Configuration options** - Document `s3_imagery_zip_download` and `cleanup_downloaded_imagery`
3. **Path syntax** - Explain `__DOWNLOADED__` prefix usage
4. **Zip file structure requirements** - Explain that zip filename becomes folder name
5. **Example configurations** - Show complete config examples
6. **Troubleshooting** - Common issues (wrong paths, download failures)

---

## Testing Plan

### Unit Tests

1. Test `determine_datasets.py` correctly parses new attributes
2. Test normalization of single string to list
3. Test default values when attributes not present
4. Test iteration_id format is correct (`{index:03d}_{project_name_sanitized}`)

### Integration Tests

1. **Happy path:** Config with downloads specified, verify:
   - Download step runs
   - Files are extracted correctly
   - Config is transformed
   - Photogrammetry receives correct paths
   - Cleanup removes files

2. **No downloads:** Config without `s3_imagery_zip_download`, verify:
   - Download step is skipped
   - Config is passed through unchanged

3. **Cleanup disabled:** Set `cleanup_downloaded_imagery: false`, verify files persist

4. **Download failure:** Use invalid S3 path, verify:
   - That specific project fails
   - Other projects continue
   - Workflow reports partial failure

5. **Parallel projects:** Two projects downloading same-named zips simultaneously, verify:
   - No collisions due to iteration_id isolation
   - Both complete successfully

6. **Validation failures:** Verify workflow fails early when:
   - `__DOWNLOADED__` prefix used but no downloads specified
   - Downloads specified but no `__DOWNLOADED__` paths in config

---

## Rollback Plan

If issues arise after deployment:

1. Users can simply not use `s3_imagery_zip_download` attribute (feature is additive)
2. Revert workflow YAML to previous version
3. Revert docker-workflow-utils image to previous tag

---

## Future Enhancements

Document these as comments in relevant code files:

1. **Download sharing between projects** - Would save bandwidth when multiple projects need the same imagery. Would require: download coordination/locking, reference counting for cleanup, handling projects that start days apart. Current approach downloads per-project to avoid these complexities and prevent storage issues from long-running workflows.

2. **Per-project folder reorganization** - Currently, workflow intermediates are organized as:
   ```
   {TEMP_WORKING_DIR}/
   ├── photogrammetry/{project-name}/
   ├── postprocessing/
   └── downloaded_imagery/{iteration_id}/
   ```
   A future enhancement could reorganize to per-project folders:
   ```
   {TEMP_WORKING_DIR}/
   └── {iteration_id}/
       ├── photogrammetry/
       ├── postprocessing/
       └── downloaded_imagery/
   ```
   This would make per-project cleanup trivial (delete one folder) and simplify debugging failed iterations. However, this is a larger refactor affecting existing workflow code and should be implemented separately.

3. **Support for tarballs** - Different extraction command (`tar -xzf`)

4. **Direct folder download** - `rclone copy` instead of `copyto` + unzip for uncompressed imagery

5. **Parallel zip downloads within a project** - Currently downloads are sequential within a project

6. **Download progress reporting** - Surface download progress to Argo UI

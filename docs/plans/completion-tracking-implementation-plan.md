# Completion Tracking & Skip-If-Complete Implementation Plan

## Overview

This plan adds two features:
1. **Completion logging**: Persist a log of completed projects across workflow runs
2. **Skip-if-complete**: Filter out already-completed projects at workflow start

## Design Summary

- **Single JSON Lines log file** stored on shared volume (near config list)
- **Filtering in `determine_datasets.py`**: Completed projects don't appear in Argo UI
- **Configurable skip level**: `none`, `metashape`, `postprocess`, `both`
- **Granular skipping** (`both`): Skip only Metashape if it's done, still run postprocessing

---

## Component 1: Completion Log Format

**Location**: User-specified via `COMPLETION_LOG_PATH` parameter (e.g., `/data/argo-input/config-lists/completion-log.jsonl`)

**Format**: JSON Lines (one JSON object per line)

```jsonl
{"project_name":"mission_001","config_id":"default","completion_level":"postprocess","timestamp":"2024-01-15T10:30:00Z","workflow_name":"automate-metashape-workflow-abc123"}
{"project_name":"mission_002","config_id":"highres","completion_level":"metashape","timestamp":"2024-01-15T11:45:00Z","workflow_name":"automate-metashape-workflow-def456"}
```

**Fields**:
| Field | Type | Description |
|-------|------|-------------|
| `project_name` | string | Project identifier from config |
| `config_id` | string | Photogrammetry config ID (or `"default"` if none) |
| `completion_level` | string | `"metashape"` or `"postprocess"` |
| `timestamp` | string | ISO 8601 UTC timestamp |
| `workflow_name` | string | Argo workflow name for traceability |

**Key**: `(project_name, config_id)` - a project can have one entry per config_id

---

## Component 2: Workflow Parameters

Add to `spec.arguments.parameters` in workflow YAML:

```yaml
# Completion tracking and skip behavior
- name: COMPLETION_LOG_PATH
  value: ""  # Path to completion log file (empty = disable skip/logging)
- name: SKIP_IF_COMPLETE
  value: "none"  # "none", "metashape", "postprocess", "both"
```

**`SKIP_IF_COMPLETE` behavior**:

| Value | Skip entire project if... | Partial skip behavior |
|-------|---------------------------|----------------------|
| `none` | Never skip | N/A |
| `metashape` | Metashape OR postprocess complete | No partial skip |
| `postprocess` | Postprocess complete | No partial skip |
| `both` | Postprocess complete | If only metashape complete: skip metashape steps, run postprocessing |

---

## Component 3: Changes to `determine_datasets.py`

### 3.1 New Command-Line Arguments

```python
# In main() or argparse setup:
parser.add_argument("--completion-log", help="Path to completion log file")
parser.add_argument("--skip-if-complete", choices=["none", "metashape", "postprocess", "both"], default="none")
parser.add_argument("--config-id", default="default", help="Photogrammetry config ID for this run")
parser.add_argument("--workflow-name", help="Argo workflow name for logging")
```

### 3.2 New Function: `load_completion_log()`

```python
def load_completion_log(log_path: str) -> Dict[Tuple[str, str], str]:
    """
    Load completion log and return lookup table.

    Args:
        log_path: Path to JSON Lines completion log

    Returns:
        Dict mapping (project_name, config_id) -> completion_level
        If duplicate entries exist, keeps the highest level (postprocess > metashape)
    """
    completions = {}
    if not os.path.exists(log_path):
        return completions

    level_priority = {"metashape": 1, "postprocess": 2}

    with open(log_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                key = (entry["project_name"], entry["config_id"])
                level = entry["completion_level"]
                # Keep highest completion level
                if key not in completions or level_priority.get(level, 0) > level_priority.get(completions[key], 0):
                    completions[key] = level
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Warning: Skipping malformed line {line_num} in completion log: {e}", file=sys.stderr)

    return completions
```

### 3.3 New Function: `should_skip_project()`

```python
def should_skip_project(
    project_name: str,
    config_id: str,
    completions: Dict[Tuple[str, str], str],
    skip_mode: str
) -> Tuple[bool, bool]:
    """
    Determine if project should be skipped based on completion status.

    Args:
        project_name: Project identifier
        config_id: Photogrammetry config ID
        completions: Completion lookup from load_completion_log()
        skip_mode: One of "none", "metashape", "postprocess", "both"

    Returns:
        Tuple of (skip_entirely, skip_metashape_only)
        - skip_entirely: Don't include project in output at all
        - skip_metashape_only: Include project but set skip_metashape=True (for "both" mode)
    """
    if skip_mode == "none":
        return (False, False)

    key = (project_name, config_id)
    completion_level = completions.get(key)

    if completion_level is None:
        # Not in log, don't skip
        return (False, False)

    if skip_mode == "metashape":
        # Skip if metashape OR postprocess complete
        return (True, False)

    if skip_mode == "postprocess":
        # Skip only if postprocess complete
        if completion_level == "postprocess":
            return (True, False)
        return (False, False)

    if skip_mode == "both":
        # Skip entirely if postprocess complete
        # Skip metashape only if metashape complete (but postprocess not)
        if completion_level == "postprocess":
            return (True, False)
        if completion_level == "metashape":
            return (False, True)  # Partial skip
        return (False, False)

    return (False, False)
```

### 3.4 Modified `main()` Function

```python
def main(config_list_path: str, output_file_path: Optional[str] = None,
         completion_log: Optional[str] = None, skip_if_complete: str = "none",
         config_id: str = "default", workflow_name: str = "") -> None:
    """Main entry point with completion tracking support."""

    # Load completion log if provided
    completions = {}
    if completion_log and skip_if_complete != "none":
        completions = load_completion_log(completion_log)
        print(f"Loaded {len(completions)} entries from completion log", file=sys.stderr)

    # Create completion log file if it doesn't exist (for later appending)
    if completion_log and not os.path.exists(completion_log):
        os.makedirs(os.path.dirname(completion_log), exist_ok=True)
        Path(completion_log).touch()
        print(f"Created completion log file: {completion_log}", file=sys.stderr)

    missions: List[Dict[str, Any]] = []
    skipped_count = 0

    # ... existing config path resolution code ...

    for index, config_path in enumerate(config_paths):
        try:
            mission = process_config_file(config_path, index)

            # Check if should skip
            skip_entirely, skip_metashape = should_skip_project(
                mission["project_name"], config_id, completions, skip_if_complete
            )

            if skip_entirely:
                level = completions.get((mission["project_name"], config_id), "unknown")
                print(f"Skipping {mission['project_name']} (config_id={config_id}): "
                      f"already complete at level '{level}'", file=sys.stderr)
                skipped_count += 1
                continue

            # Add skip_metashape flag for "both" mode partial skipping
            mission["skip_metashape"] = skip_metashape

            missions.append(mission)

        except Exception as e:
            print(f"Error processing config {config_path}: {e}", file=sys.stderr)
            raise

    print(f"Processing {len(missions)} projects, skipped {skipped_count} as already complete",
          file=sys.stderr)

    # ... rest of existing output code ...
```

### 3.5 Updated Argument Handling

```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Preprocess config files for Argo workflow")
    parser.add_argument("config_list_path", help="Path to config list file")
    parser.add_argument("output_file_path", nargs="?", help="Optional output file for configs")
    parser.add_argument("--completion-log", help="Path to completion log file")
    parser.add_argument("--skip-if-complete", choices=["none", "metashape", "postprocess", "both"],
                        default="none", help="Skip projects based on completion status")
    parser.add_argument("--config-id", default="default", help="Photogrammetry config ID")
    parser.add_argument("--workflow-name", default="", help="Workflow name for logging")

    args = parser.parse_args()

    main(
        config_list_path=args.config_list_path,
        output_file_path=args.output_file_path,
        completion_log=args.completion_log,
        skip_if_complete=args.skip_if_complete,
        config_id=args.config_id,
        workflow_name=args.workflow_name
    )
```

---

## Component 4: New Workflow Template for Logging Completion

### 4.1 Template Definition

Add after the `cleanup-iteration-template`:

```yaml
#--------- LOG COMPLETION ---------
# Appends completion entry to the shared completion log file
# Uses file locking to handle concurrent writes from parallel projects
- name: log-completion-template
  inputs:
    parameters:
      - name: project-name
      - name: config-id
      - name: completion-level  # "metashape" or "postprocess"
      - name: completion-log-path
  nodeSelector:
    feature.node.kubernetes.io/workload-type: cpu
  script:
    image: python:3.9-slim
    volumeMounts:
      - name: data
        mountPath: /data
    command: ["python3"]
    source: |
      import json
      import fcntl
      import os
      from datetime import datetime, timezone

      log_path = "{{inputs.parameters.completion-log-path}}"

      # Skip if no log path configured
      if not log_path:
          print("No completion log path configured, skipping")
          exit(0)

      entry = {
          "project_name": "{{inputs.parameters.project-name}}",
          "config_id": "{{inputs.parameters.config-id}}",
          "completion_level": "{{inputs.parameters.completion-level}}",
          "timestamp": datetime.now(timezone.utc).isoformat(),
          "workflow_name": "{{workflow.name}}"
      }

      line = json.dumps(entry) + "\n"

      # Ensure directory exists
      os.makedirs(os.path.dirname(log_path), exist_ok=True)

      # Append with exclusive lock for concurrency safety
      with open(log_path, "a") as f:
          fcntl.flock(f.fileno(), fcntl.LOCK_EX)
          f.write(line)
          f.flush()

      print(f"Logged completion: {entry['project_name']} at level {entry['completion_level']}")
    resources:
      requests:
        cpu: "100m"
        memory: "64Mi"
```

---

## Component 5: Workflow YAML Changes

### 5.1 Add New Parameters

In `spec.arguments.parameters`, add:

```yaml
# Completion tracking and skip behavior
- name: COMPLETION_LOG_PATH
  value: ""  # Path to completion log file (empty = disable skip/logging)
- name: SKIP_IF_COMPLETE
  value: "none"  # "none", "metashape", "postprocess", "both"
```

### 5.2 Update `determine-projects` Template

Change the container args to pass new parameters:

```yaml
- name: determine-projects
  nodeSelector:
    feature.node.kubernetes.io/workload-type: cpu
  container:
    image: ghcr.io/open-forest-observatory/argo-workflow-utils:{{workflow.parameters.OFO_ARGO_IMAGES_TAG}}
    volumeMounts:
      - name: data
        mountPath: /data
    command: ["python3"]
    args:
      - "/app/determine_datasets.py"
      - "{{workflow.parameters.CONFIG_LIST}}"
      - "{{workflow.parameters.TEMP_WORKING_DIR}}/{{workflow.name}}/project-configs.json"
      - "--completion-log"
      - "{{workflow.parameters.COMPLETION_LOG_PATH}}"
      - "--skip-if-complete"
      - "{{workflow.parameters.SKIP_IF_COMPLETE}}"
      - "--config-id"
      - "{{workflow.parameters.PHOTOGRAMMETRY_CONFIG_ID}}"
      - "--workflow-name"
      - "{{workflow.name}}"
  outputs:
    parameters:
      - name: configs-file
        value: "{{workflow.parameters.TEMP_WORKING_DIR}}/{{workflow.name}}/project-configs.json"
```

### 5.3 Add Logging Tasks to DAG

In the `process-project-workflow` template DAG, add two new tasks:

```yaml
# Log metashape completion (after rclone upload succeeds)
- name: log-metashape-complete
  depends: "rclone-upload-task.Succeeded"
  when: "{{workflow.parameters.COMPLETION_LOG_PATH}} != ''"
  template: log-completion-template
  arguments:
    parameters:
      - name: project-name
        value: "{{inputs.parameters.project-name}}"
      - name: config-id
        value: "{{=workflow.parameters.PHOTOGRAMMETRY_CONFIG_ID != 'NONE' ? workflow.parameters.PHOTOGRAMMETRY_CONFIG_ID : 'default'}}"
      - name: completion-level
        value: "metashape"
      - name: completion-log-path
        value: "{{workflow.parameters.COMPLETION_LOG_PATH}}"

# Log postprocess completion (after postprocessing succeeds)
- name: log-postprocess-complete
  depends: "postprocessing-task.Succeeded"
  when: "{{workflow.parameters.COMPLETION_LOG_PATH}} != ''"
  template: log-completion-template
  arguments:
    parameters:
      - name: project-name
        value: "{{inputs.parameters.project-name}}"
      - name: config-id
        value: "{{=workflow.parameters.PHOTOGRAMMETRY_CONFIG_ID != 'NONE' ? workflow.parameters.PHOTOGRAMMETRY_CONFIG_ID : 'default'}}"
      - name: completion-level
        value: "postprocess"
      - name: completion-log-path
        value: "{{workflow.parameters.COMPLETION_LOG_PATH}}"
```

### 5.4 Update Dependencies for Logging Tasks

Modify `cleanup-iteration` to depend on logging completion:

```yaml
- name: cleanup-iteration
  depends: "(postprocessing-task.Succeeded || postprocessing-task.Skipped) && (log-postprocess-complete.Succeeded || log-postprocess-complete.Skipped)"
  template: cleanup-iteration-template
  arguments:
    parameters:
      - name: iteration-id
        value: "{{=sprig.fromJson(tasks['load-config'].outputs.result).iteration_id}}"
```

### 5.5 Add `when` Conditions for `SKIP_IF_COMPLETE=both` Mode

For the "both" mode to work, we need to conditionally skip metashape steps when `skip_metashape=true`.

**Add `when` to tasks that currently always run:**

```yaml
# setup task - add when clause
- name: setup
  template: metashape-cpu-step
  depends: "load-config.Succeeded && (transform-config.Succeeded || transform-config.Skipped)"
  when: "{{=sprig.fromJson(tasks['load-config'].outputs.result).skip_metashape != true}}"
  arguments:
    # ... existing arguments ...
```

```yaml
# finalize task - add when clause
- name: finalize
  depends: "(build-dem-orthomosaic.Succeeded || build-dem-orthomosaic.Skipped) && (align-cameras-secondary.Succeeded || align-cameras-secondary.Skipped)"
  when: "{{=sprig.fromJson(tasks['load-config'].outputs.result).skip_metashape != true}}"
  template: metashape-cpu-step
  arguments:
    # ... existing arguments ...
```

```yaml
# rclone-upload-task - add when clause
- name: rclone-upload-task
  depends: "finalize.Succeeded || finalize.Skipped"
  when: "{{=sprig.fromJson(tasks['load-config'].outputs.result).skip_metashape != true}}"
  template: rclone-upload-template
  arguments:
    # ... existing arguments ...
```

**Extend `when` for tasks that already have conditions:**

For each metashape step that already has a `when` clause, add `&& sprig.fromJson(tasks['load-config'].outputs.result).skip_metashape != true`.

Example for `match-photos-gpu`:

```yaml
# Before:
when: "{{=sprig.fromJson(tasks['load-config'].outputs.result).match_photos_enabled == true && sprig.fromJson(tasks['load-config'].outputs.result).match_photos_use_gpu == true}}"

# After:
when: "{{=sprig.fromJson(tasks['load-config'].outputs.result).skip_metashape != true && sprig.fromJson(tasks['load-config'].outputs.result).match_photos_enabled == true && sprig.fromJson(tasks['load-config'].outputs.result).match_photos_use_gpu == true}}"
```

Apply this pattern to all 11 metashape tasks with existing `when` clauses:
- `match-photos-gpu`
- `match-photos-cpu`
- `align-cameras`
- `build-depth-maps`
- `build-point-cloud`
- `build-mesh-gpu`
- `build-mesh-cpu`
- `build-dem-orthomosaic`
- `match-photos-secondary-gpu`
- `match-photos-secondary-cpu`
- `align-cameras-secondary`

### 5.6 Update `depends` for Downstream Tasks

Update tasks that depend on potentially-skipped tasks:

```yaml
# postprocessing-task - handle skipped rclone
- name: postprocessing-task
  depends: "rclone-upload-task.Succeeded || rclone-upload-task.Skipped"
  template: postprocessing-template
  arguments:
    # ... existing arguments ...

# log-metashape-complete - handle skipped rclone
- name: log-metashape-complete
  depends: "rclone-upload-task.Succeeded"  # Only log if actually ran
  when: "{{workflow.parameters.COMPLETION_LOG_PATH}} != '' && {{=sprig.fromJson(tasks['load-config'].outputs.result).skip_metashape != true}}"
  # ... rest of task ...
```

---

## Component 6: Utility Script (Optional)

Create a utility script to generate remaining config list after a cancelled run:

**File**: `docker-workflow-utils/generate_remaining_configs.py`

```python
#!/usr/bin/env python3
"""
Generate a config list of projects not yet completed.

Usage:
    python generate_remaining_configs.py <config_list> <completion_log> [--config-id ID] [--level LEVEL]

Example:
    python generate_remaining_configs.py /data/config_list.txt /data/completion-log.jsonl --level postprocess
"""

import argparse
import json
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="Generate remaining config list")
    parser.add_argument("config_list", help="Original config list file")
    parser.add_argument("completion_log", help="Completion log file")
    parser.add_argument("--config-id", default="default", help="Config ID to check")
    parser.add_argument("--level", choices=["metashape", "postprocess"], default="postprocess",
                        help="Completion level to check")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")

    args = parser.parse_args()

    # Load completion log
    completed = set()
    if os.path.exists(args.completion_log):
        with open(args.completion_log) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry["config_id"] == args.config_id:
                        if args.level == "metashape" or entry["completion_level"] == "postprocess":
                            completed.add(entry["project_name"])
                        elif args.level == "postprocess" and entry["completion_level"] == "postprocess":
                            completed.add(entry["project_name"])
                except (json.JSONDecodeError, KeyError):
                    continue

    # Read config list and filter
    config_list_dir = os.path.dirname(args.config_list)
    remaining = []

    with open(args.config_list) as f:
        for line in f:
            original_line = line
            line = line.split("#")[0].strip()
            if not line:
                continue

            # Resolve path
            if line.startswith("/"):
                config_path = line
            else:
                config_path = os.path.join(config_list_dir, line)

            # Extract project name from config (simplified - just use filename)
            project_name = os.path.splitext(os.path.basename(config_path))[0]

            if project_name not in completed:
                remaining.append(original_line.rstrip())

    # Output
    output = "\n".join(remaining) + "\n" if remaining else ""

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Wrote {len(remaining)} remaining configs to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(output)
        print(f"# {len(remaining)} remaining, {len(completed)} completed", file=sys.stderr)


if __name__ == "__main__":
    main()
```

---

## Summary of Changes

| File | Type | Description |
|------|------|-------------|
| `docker-workflow-utils/determine_datasets.py` | Modify | Add completion log reading, skip logic, new CLI args |
| `photogrammetry-workflow-stepbased.yaml` | Modify | Add parameters, logging template, DAG tasks, when conditions |
| `docker-workflow-utils/generate_remaining_configs.py` | New | Utility to generate remaining config list |

**Line count estimates:**
- `determine_datasets.py`: +80-100 lines
- `photogrammetry-workflow-stepbased.yaml`: +60-80 lines
- `generate_remaining_configs.py`: +70 lines (new file, optional)

---

## Testing Plan

1. **Unit test `determine_datasets.py`**:
   - Test `load_completion_log()` with valid, empty, and malformed log files
   - Test `should_skip_project()` with all skip modes
   - Test main() filtering behavior

2. **Integration test workflow**:
   - Run workflow with empty completion log, verify all projects process
   - Run again, verify projects are skipped based on log
   - Test `SKIP_IF_COMPLETE=both` partial skip behavior
   - Test concurrent project completion logging (no corruption)

3. **Edge cases**:
   - Empty completion log path (feature disabled)
   - Missing completion log file (should be created)
   - Duplicate entries in log (highest level wins)
   - Config ID mismatch (should not skip)

---

## Usage Examples

### Basic usage with postprocess skip:
```bash
argo submit photogrammetry-workflow-stepbased.yaml \
  -p CONFIG_LIST=/data/argo-input/config-lists/batch1.txt \
  -p COMPLETION_LOG_PATH=/data/argo-input/config-lists/completion-log.jsonl \
  -p SKIP_IF_COMPLETE=postprocess
```

### Re-run postprocessing only (both mode):
```bash
argo submit photogrammetry-workflow-stepbased.yaml \
  -p CONFIG_LIST=/data/argo-input/config-lists/batch1.txt \
  -p COMPLETION_LOG_PATH=/data/argo-input/config-lists/completion-log.jsonl \
  -p SKIP_IF_COMPLETE=both
```

### Force full reprocessing:
```bash
argo submit photogrammetry-workflow-stepbased.yaml \
  -p CONFIG_LIST=/data/argo-input/config-lists/batch1.txt \
  -p COMPLETION_LOG_PATH=/data/argo-input/config-lists/completion-log.jsonl \
  -p SKIP_IF_COMPLETE=none
```

### Generate remaining configs after cancellation:
```bash
python generate_remaining_configs.py \
  /data/argo-input/config-lists/batch1.txt \
  /data/argo-input/config-lists/completion-log.jsonl \
  --level postprocess \
  -o /data/argo-input/config-lists/batch1-remaining.txt
```

---

## Component 7: Retroactive Log Generation (Bootstrap Tool)

This utility scans S3 for existing products from runs completed before the logging feature existed, and generates a completion log that can be used for skip-if-complete functionality.

### 7.1 Design Overview

**Input sources for detecting completion:**

| Completion Level | Location | Detection Method |
|-----------------|----------|------------------|
| `metashape` | `s3://S3_BUCKET_INTERNAL/S3_PHOTOGRAMMETRY_DIR/` (may include config-specific subdirectories in prefix) | Project folder exists with expected products |
| `postprocess` | `s3://S3_BUCKET_PUBLIC/S3_POSTPROCESSED_DIR/` | `<project_name>_ortho.tif` exists (or other sentinel file) |

**Key design decisions:**

1. **Run locally or in container**: Can run anywhere with S3 credentials and rclone/boto3
2. **Sentinel files**: Define minimal files that indicate completion (avoid listing entire buckets)
3. **Project name extraction**: Parse from S3 object keys (e.g., `mission_001_ortho.tif` → `mission_001`)
4. **Timestamp**: Use S3 object `LastModified` or fall back to "unknown"
5. **Workflow name**: Set to `"retroactive-bootstrap"` to distinguish from real workflow entries

### 7.2 Sentinel Files for Completion Detection

**Metashape complete** (any ONE of these in project folder):
- `*_ortho.tif` (orthomosaic)
- `*_dsm-ptcloud.tif` (DSM from point cloud)
- `*_ptcloud.las` or `*_ptcloud.laz` (point cloud)

**Postprocess complete** (in public bucket):
- `<project_name>_ortho.tif` (COG orthomosaic)

### 7.3 Script: `generate_retroactive_log.py`

**File**: `docker-workflow-utils/generate_retroactive_log.py`

```python
#!/usr/bin/env python3
"""
Generate a completion log from existing S3 products.

Scans S3 buckets for products from workflow runs that completed before
the logging feature was implemented, and generates a compatible completion log.

Usage:
    python generate_retroactive_log.py \
        --internal-bucket ofo-internal \
        --internal-prefix photogrammetry/default-run \
        --public-bucket ofo-public \
        --public-prefix postprocessed \
        --config-id default \
        --output completion-log.jsonl

Requirements:
    - boto3 (pip install boto3)
    - S3 credentials configured (env vars, ~/.aws/credentials, or IAM role)

Environment variables for S3:
    S3_ENDPOINT: S3 endpoint URL (for non-AWS S3)
    AWS_ACCESS_KEY_ID: Access key
    AWS_SECRET_ACCESS_KEY: Secret key
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

try:
    import boto3
    from botocore.config import Config
except ImportError:
    print("Error: boto3 required. Install with: pip install boto3", file=sys.stderr)
    sys.exit(1)


def get_s3_client():
    """Create S3 client with optional custom endpoint."""
    endpoint = os.environ.get("S3_ENDPOINT")

    if endpoint:
        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("S3_ACCESS_KEY"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY") or os.environ.get("S3_SECRET_KEY"),
            config=Config(signature_version="s3v4"),
        )
    else:
        return boto3.client("s3")


def list_s3_objects(client, bucket: str, prefix: str, max_keys: int = 10000) -> List[dict]:
    """
    List objects in S3 bucket with prefix.

    Returns list of dicts with 'Key' and 'LastModified' fields.
    """
    objects = []
    paginator = client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, MaxKeys=max_keys):
        if "Contents" in page:
            objects.extend(page["Contents"])

    return objects


def extract_project_name_from_key(key: str, prefix: str) -> Optional[str]:
    """
    Extract project name from S3 object key.

    For internal bucket (metashape products):
        prefix/project_name/project_name_product.tif -> project_name

    For public bucket (postprocessed):
        prefix/project_name_product.tif -> project_name
    """
    # Remove prefix
    relative = key[len(prefix):].lstrip("/")

    # Check if it's in a subdirectory (internal bucket structure)
    parts = relative.split("/")
    if len(parts) >= 2:
        # Structure: project_name/filename
        return parts[0]
    elif len(parts) == 1:
        # Structure: project_name_product.ext (flat, postprocessed)
        filename = parts[0]
        # Extract project name by removing _product.ext suffix
        # Pattern: project_name_ortho.tif, project_name_dsm-ptcloud.tif, etc.
        match = re.match(r"^(.+?)_(ortho|dsm-ptcloud|dsm-mesh|dtm-ptcloud|chm-ptcloud|chm-mesh|ptcloud)\.", filename)
        if match:
            return match.group(1)

    return None


def detect_metashape_complete(
    client, bucket: str, prefix: str
) -> Dict[str, datetime]:
    """
    Detect projects with completed metashape products.

    Returns dict mapping project_name -> latest LastModified timestamp.
    """
    print(f"Scanning s3://{bucket}/{prefix} for metashape products...", file=sys.stderr)

    objects = list_s3_objects(client, bucket, prefix)
    print(f"  Found {len(objects)} objects", file=sys.stderr)

    # Sentinel patterns that indicate completion
    sentinel_patterns = [
        r"_ortho\.tif$",
        r"_dsm-ptcloud\.tif$",
        r"_ptcloud\.(las|laz)$",
    ]

    projects: Dict[str, datetime] = {}

    for obj in objects:
        key = obj["Key"]

        # Check if this is a sentinel file
        is_sentinel = any(re.search(pattern, key) for pattern in sentinel_patterns)
        if not is_sentinel:
            continue

        project_name = extract_project_name_from_key(key, prefix)
        if project_name:
            timestamp = obj["LastModified"]
            if project_name not in projects or timestamp > projects[project_name]:
                projects[project_name] = timestamp

    print(f"  Detected {len(projects)} completed metashape projects", file=sys.stderr)
    return projects


def detect_postprocess_complete(
    client, bucket: str, prefix: str
) -> Dict[str, datetime]:
    """
    Detect projects with completed postprocessed products.

    Returns dict mapping project_name -> latest LastModified timestamp.
    """
    print(f"Scanning s3://{bucket}/{prefix} for postprocessed products...", file=sys.stderr)

    objects = list_s3_objects(client, bucket, prefix)
    print(f"  Found {len(objects)} objects", file=sys.stderr)

    # Look for ortho COGs as sentinel (always produced by postprocessing)
    projects: Dict[str, datetime] = {}

    for obj in objects:
        key = obj["Key"]

        # Only consider ortho files as sentinel for postprocess completion
        if not re.search(r"_ortho\.tif$", key):
            continue

        project_name = extract_project_name_from_key(key, prefix)
        if project_name:
            timestamp = obj["LastModified"]
            if project_name not in projects or timestamp > projects[project_name]:
                projects[project_name] = timestamp

    print(f"  Detected {len(projects)} completed postprocess projects", file=sys.stderr)
    return projects


def generate_log_entries(
    metashape_projects: Dict[str, datetime],
    postprocess_projects: Dict[str, datetime],
    config_id: str,
) -> List[dict]:
    """
    Generate completion log entries from detected projects.

    A project gets:
    - 'postprocess' level if found in postprocess_projects
    - 'metashape' level if found only in metashape_projects
    """
    entries = []
    all_projects = set(metashape_projects.keys()) | set(postprocess_projects.keys())

    for project_name in sorted(all_projects):
        # Determine completion level (postprocess > metashape)
        if project_name in postprocess_projects:
            level = "postprocess"
            timestamp = postprocess_projects[project_name]
        else:
            level = "metashape"
            timestamp = metashape_projects[project_name]

        entry = {
            "project_name": project_name,
            "config_id": config_id,
            "completion_level": level,
            "timestamp": timestamp.isoformat(),
            "workflow_name": "retroactive-bootstrap",
        }
        entries.append(entry)

    return entries


def main():
    parser = argparse.ArgumentParser(
        description="Generate completion log from existing S3 products",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Scan default locations
    python generate_retroactive_log.py \\
        --internal-bucket ofo-internal \\
        --internal-prefix photogrammetry/default-run \\
        --public-bucket ofo-public \\
        --public-prefix postprocessed \\
        --output completion-log.jsonl

    # With specific config (include in prefix)
    python generate_retroactive_log.py \\
        --internal-bucket ofo-internal \\
        --internal-prefix photogrammetry/default-run/photogrammetry_highres \\
        --public-bucket ofo-public \\
        --public-prefix postprocessed \\
        --config-id highres \\
        --output completion-log.jsonl

    # Metashape only (no postprocess check)
    python generate_retroactive_log.py \\
        --internal-bucket ofo-internal \\
        --internal-prefix photogrammetry/default-run \\
        --level metashape \\
        --output completion-log.jsonl
        """,
    )

    parser.add_argument("--internal-bucket", required=True,
                        help="S3 bucket for internal/metashape products")
    parser.add_argument("--internal-prefix", required=True,
                        help="S3 prefix for metashape products (e.g., photogrammetry/default-run or photogrammetry/default-run/photogrammetry_highres)")
    parser.add_argument("--public-bucket", default="",
                        help="S3 bucket for public/postprocessed products (optional)")
    parser.add_argument("--public-prefix", default="",
                        help="S3 prefix for postprocessed products (optional)")
    parser.add_argument("--config-id", default="default",
                        help="Config ID to use in log entries")
    parser.add_argument("--level", choices=["metashape", "postprocess", "both"], default="both",
                        help="Which completion levels to detect")
    parser.add_argument("--output", "-o", required=True,
                        help="Output file path for completion log")
    parser.add_argument("--append", action="store_true",
                        help="Append to existing log instead of overwriting")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written without writing")

    args = parser.parse_args()

    # Validate args
    if args.level in ["postprocess", "both"] and (not args.public_bucket or not args.public_prefix):
        parser.error("--public-bucket and --public-prefix required when checking postprocess level")

    # Create S3 client
    client = get_s3_client()

    # Detect completed projects
    metashape_projects: Dict[str, datetime] = {}
    postprocess_projects: Dict[str, datetime] = {}

    if args.level in ["metashape", "both"]:
        metashape_projects = detect_metashape_complete(
            client, args.internal_bucket, args.internal_prefix
        )

    if args.level in ["postprocess", "both"]:
        postprocess_projects = detect_postprocess_complete(
            client, args.public_bucket, args.public_prefix
        )

    # Generate log entries
    entries = generate_log_entries(metashape_projects, postprocess_projects, args.config_id)

    print(f"\nGenerated {len(entries)} log entries:", file=sys.stderr)
    metashape_only = sum(1 for e in entries if e["completion_level"] == "metashape")
    postprocess_count = sum(1 for e in entries if e["completion_level"] == "postprocess")
    print(f"  - metashape level: {metashape_only}", file=sys.stderr)
    print(f"  - postprocess level: {postprocess_count}", file=sys.stderr)

    if args.dry_run:
        print("\n[DRY RUN] Would write:", file=sys.stderr)
        for entry in entries:
            print(json.dumps(entry))
        return

    # Write output
    mode = "a" if args.append else "w"
    with open(args.output, mode) as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    print(f"\nWrote {len(entries)} entries to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

### 7.4 Usage Examples

**Basic scan (both levels):**
```bash
python generate_retroactive_log.py \
    --internal-bucket ofo-internal \
    --internal-prefix photogrammetry/default-run \
    --public-bucket ofo-public \
    --public-prefix postprocessed \
    --output /data/argo-input/config-lists/completion-log.jsonl
```

**With specific config (include in prefix):**
```bash
python generate_retroactive_log.py \
    --internal-bucket ofo-internal \
    --internal-prefix photogrammetry/default-run/photogrammetry_highres \
    --public-bucket ofo-public \
    --public-prefix postprocessed \
    --config-id highres \
    --output /data/argo-input/config-lists/completion-log-highres.jsonl
```

**Metashape only (skip postprocess check):**
```bash
python generate_retroactive_log.py \
    --internal-bucket ofo-internal \
    --internal-prefix photogrammetry/default-run \
    --level metashape \
    --config-id default \
    --output /data/argo-input/config-lists/completion-log.jsonl
```

**Dry run (preview without writing):**
```bash
python generate_retroactive_log.py \
    --internal-bucket ofo-internal \
    --internal-prefix photogrammetry/default-run \
    --public-bucket ofo-public \
    --public-prefix postprocessed \
    --dry-run \
    --output /data/argo-input/config-lists/completion-log.jsonl
```

**Append to existing log (combine multiple config IDs):**
```bash
# First, generate for default config
python generate_retroactive_log.py \
    --internal-bucket ofo-internal \
    --internal-prefix photogrammetry/default-run \
    --public-bucket ofo-public \
    --public-prefix postprocessed \
    --config-id default \
    --output completion-log.jsonl

# Then append highres config
python generate_retroactive_log.py \
    --internal-bucket ofo-internal \
    --internal-prefix photogrammetry/default-run/photogrammetry_highres \
    --public-bucket ofo-public \
    --public-prefix postprocessed \
    --config-id highres \
    --append \
    --output completion-log.jsonl
```

### 7.5 Running the Tool

**Option A: Locally with Python**
```bash
# Install dependency
pip install boto3

# Set S3 credentials (for non-AWS S3 like Ceph/MinIO)
export S3_ENDPOINT=https://s3.example.com
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key

# Run
python generate_retroactive_log.py --internal-bucket ... --output ...
```

**Option B: In a container/pod with access to shared volume**
```bash
# From a pod with S3 credentials already configured
kubectl exec -it <pod-name> -- python /app/generate_retroactive_log.py \
    --internal-bucket ofo-internal \
    --internal-prefix photogrammetry/default-run \
    --public-bucket ofo-public \
    --public-prefix postprocessed \
    --output /data/argo-input/config-lists/completion-log.jsonl
```

### 7.6 Customizing Sentinel Files

The script uses sentinel files to detect completion. To customize:

1. **Metashape sentinels** (in `detect_metashape_complete()`):
   ```python
   sentinel_patterns = [
       r"_ortho\.tif$",
       r"_dsm-ptcloud\.tif$",
       r"_ptcloud\.(las|laz)$",
   ]
   ```

2. **Postprocess sentinels** (in `detect_postprocess_complete()`):
   - Currently uses `_ortho.tif` only
   - Modify regex if your postprocess outputs differ

### 7.7 Notes and Limitations

1. **Project name extraction**: Assumes standard naming conventions:
   - Internal: `prefix/project_name/project_name_product.tif`
   - Public: `prefix/project_name_product.tif`

2. **Timestamp accuracy**: Uses S3 object `LastModified`, which is upload time, not processing completion time

3. **Duplicate handling**: If a project appears multiple times (shouldn't happen), latest timestamp wins

4. **Large buckets**: Uses pagination, but may be slow for buckets with millions of objects. Consider using `--level metashape` or `--level postprocess` separately if needed

5. **Idempotent**: Running multiple times produces same output (can safely re-run)

---

## Implementation Steps

### Phase 1: Core Infrastructure

**Step 1.1: Update `determine_datasets.py` with completion log support**
- [ ] Add argparse-based CLI argument handling (replace positional args)
- [ ] Add `--completion-log`, `--skip-if-complete`, `--config-id`, `--workflow-name` arguments
- [ ] Implement `load_completion_log()` function
- [ ] Implement `should_skip_project()` function
- [ ] Modify `main()` to filter projects based on completion status
- [ ] Add `skip_metashape` field to project output for "both" mode
- [ ] Test locally with sample completion log

**Step 1.2: Add workflow parameters**
- [ ] Add `COMPLETION_LOG_PATH` parameter to workflow YAML
- [ ] Add `SKIP_IF_COMPLETE` parameter to workflow YAML
- [ ] Update `determine-projects` template to pass new args

### Phase 2: Completion Logging

**Step 2.1: Create log-completion template**
- [ ] Add `log-completion-template` to workflow YAML
- [ ] Template should accept: project-name, config-id, completion-level, completion-log-path
- [ ] Include file locking for concurrent safety

**Step 2.2: Add logging tasks to DAG**
- [ ] Add `log-metashape-complete` task after `rclone-upload-task`
- [ ] Add `log-postprocess-complete` task after `postprocessing-task`
- [ ] Update `cleanup-iteration` depends to include logging tasks

### Phase 3: Skip-If-Complete "both" Mode

**Step 3.1: Add conditional skipping for metashape steps**
- [ ] Add `when` clause to `setup` task
- [ ] Add `when` clause to `finalize` task
- [ ] Add `when` clause to `rclone-upload-task` task
- [ ] Extend `when` clauses on all 11 existing metashape tasks (match-photos-gpu/cpu, align-cameras, etc.)

**Step 3.2: Update downstream dependencies**
- [ ] Update `postprocessing-task` depends to handle skipped rclone
- [ ] Update `log-metashape-complete` when clause to skip if metashape was skipped

### Phase 4: Utility Scripts ✓

**Step 4.1: Create `generate_remaining_configs.py`**
- [x] Implement script to diff config list against completion log
- [x] Add to `docker-workflow-utils/`
- [x] Test with sample data

**Step 4.2: Create `generate_retroactive_log.py`**
- [x] Implement S3 scanning for existing products
- [x] Implement project name extraction from S3 keys
- [x] Add `--dry-run` and `--append` options
- [x] Test against actual S3 buckets (verified syntax and logic, requires boto3 for full S3 testing)

### Phase 5: Docker Image Updates

**Step 5.1: Update argo-workflow-utils image**
- [ ] Ensure `determine_datasets.py` changes are included
- [ ] Add `generate_remaining_configs.py` to image
- [ ] Add `generate_retroactive_log.py` to image (optional, can run locally)
- [ ] Add `boto3` to requirements if including retroactive script
- [ ] Build and push updated image

### Phase 6: Testing

**Step 6.1: Unit tests**
- [ ] Test `load_completion_log()` with valid, empty, malformed logs
- [ ] Test `should_skip_project()` with all skip modes
- [ ] Test project filtering in `main()`

**Step 6.2: Integration tests**
- [ ] Run workflow with `SKIP_IF_COMPLETE=none`, verify all projects process
- [ ] Run workflow with `SKIP_IF_COMPLETE=postprocess`, verify completed projects skip
- [ ] Test `SKIP_IF_COMPLETE=both` partial skip behavior
- [ ] Verify completion log entries are written correctly
- [ ] Test concurrent project completion (check for log corruption)

**Step 6.3: Edge case tests**
- [ ] Empty `COMPLETION_LOG_PATH` (feature disabled)
- [ ] Missing completion log file (should be created)
- [ ] Config ID mismatch (should not skip)
- [ ] Duplicate entries in log (highest level wins)

### Phase 7: Documentation

- [x] Update `docs/usage/stepbased-workflow.md` with new parameters
- [x] Add usage examples for skip-if-complete feature
- [x] Document completion log format
- [x] Add troubleshooting section for common issues

---

## Implementation Order Recommendation

For incremental delivery, implement in this order:

1. **Minimum viable feature** (Steps 1.1, 1.2, 2.1, 2.2):
   - Completion logging works
   - `SKIP_IF_COMPLETE=postprocess` works
   - ~2-3 hours of work

2. **Full skip modes** (Steps 3.1, 3.2):
   - `SKIP_IF_COMPLETE=both` works
   - ~1-2 hours of work

3. **Utility scripts** (Steps 4.1, 4.2):
   - Generate remaining configs after cancellation
   - Bootstrap log from existing S3 products
   - ~1-2 hours of work

4. **Polish** (Steps 5, 6, 7):
   - Docker image updates
   - Testing
   - Documentation
   - ~2-3 hours of work

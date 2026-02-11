# Implementation Plan: Heartbeat Logger with Error Context for Metashape Pipeline

> **Status: Planning** - This plan describes adding progress callbacks, heartbeat logging, error context buffering, and full log file output to reduce console log volume while maintaining visibility and debuggability.

## Overview

Metashape produces extremely verbose stdout during processing. With many projects running in parallel, this volume of logs taxes the Argo artifact store and k8s control plane. This implementation reduces console output to ~50-100 lines per multi-hour job while preserving full debugging context on errors.

**Two-layer approach:**

1. **Progress callbacks** (in-process): Metashape API calls accept `progress=callback` parameter. Add a callback that prints structured `[progress] step: X%` messages at configurable intervals (e.g., every 10%)

2. **Output monitor wrapper** (out-of-process): `license_retry_wrapper.py` already intercepts all subprocess output line-by-line. Enhance it to:
   - Write full log to file on shared volume
   - Pass through important lines (`[progress]`, `[license-wrapper]`, etc.)
   - Print periodic heartbeats to prove liveness
   - Buffer last N lines for error context dump

**Key insight:** Progress callbacks provide meaningful structured updates, eliminating the need for random line sampling. The wrapper adds heartbeat, buffering, and full logging without needing to understand what the lines mean.

---

## Part 1: automate-metashape Repository Changes

### File 1: `python/metashape_workflow_functions.py`

#### Change 1.1: Add progress callback factory method

Add this method to the `MetashapeWorkflow` class (suggested location: after `__init__`, around line 180):

```python
def _make_progress_callback(self, operation_name):
    """
    Create a progress callback for Metashape API calls.

    Prints progress updates to stderr at configurable percentage intervals.
    The callback is called frequently by Metashape but only prints when
    crossing threshold boundaries (e.g., 10%, 20%, 30%).

    Args:
        operation_name: Name of the operation (e.g., "matchPhotos", "buildDepthMaps")

    Returns:
        Callable[[float], None]: Callback function for Metashape progress parameter
    """
    import os
    import sys

    last_report = [0]  # Use list for closure mutability
    interval = int(os.environ.get("PROGRESS_INTERVAL_PCT", 1))

    def callback(progress):
        """Progress callback: receives 0-100 float from Metashape."""
        pct = int(progress)
        # Print when crossing interval threshold or reaching 100%
        if pct >= last_report[0] + interval or pct >= 100:
            print(f"[progress] {operation_name}: {pct}%", file=sys.stderr, flush=True)
            last_report[0] = pct

    return callback
```

**Notes:**
- Uses closure to maintain state (`last_report`)
- `flush=True` ensures immediate output (important for subprocess buffering)
- Prints to `sys.stderr` (because `metashape_workflow.py` redirects stdout to stderr anyway)

#### Change 1.2: Add progress callbacks to API calls

Add `progress=self._make_progress_callback("operationName")` parameter to each Metashape API call. The call sites (approximate line numbers, verify in actual file):

**Match Photos operations:**
```python
# Line ~521: Primary match photos
self.doc.chunk.matchPhotos(
    downscale=cfg.matchPhotos.downscale,
    # ... other parameters ...
    progress=self._make_progress_callback("matchPhotos")
)

# Line ~610: Secondary match photos (if enabled)
self.doc.chunk.matchPhotos(
    downscale=cfg.matchPhotos_secondary.downscale,
    # ... other parameters ...
    progress=self._make_progress_callback("matchPhotos_secondary")
)
```

**Align Cameras operations:**
```python
# Line ~552: Primary align cameras
self.doc.chunk.alignCameras(
    adaptive_fitting=cfg.alignCameras.adaptive_fitting,
    # ... other parameters ...
    progress=self._make_progress_callback("alignCameras")
)

# Line ~638: Secondary align cameras (if enabled)
self.doc.chunk.alignCameras(
    adaptive_fitting=cfg.alignCameras_secondary.adaptive_fitting,
    # ... other parameters ...
    progress=self._make_progress_callback("alignCameras_secondary")
)
```

**Depth Maps, Point Cloud, Model:**
```python
# Line ~1346: Build depth maps
self.doc.chunk.buildDepthMaps(
    downscale=cfg.buildDepthMaps.downscale,
    # ... other parameters ...
    progress=self._make_progress_callback("buildDepthMaps")
)

# Line ~1369: Build point cloud
self.doc.chunk.buildPointCloud(
    source_data=source,
    # ... other parameters ...
    progress=self._make_progress_callback("buildPointCloud")
)

# Line ~1441: Build model
self.doc.chunk.buildModel(
    surface_type=cfg.buildModel.surface_type,
    # ... other parameters ...
    progress=self._make_progress_callback("buildModel")
)
```

**DEM operations (multiple surface types):**
```python
# Line ~1513: Build DEM (point cloud surface)
self.doc.chunk.buildDem(
    source_data=Metashape.DataSource.PointCloudData,
    # ... other parameters ...
    progress=self._make_progress_callback("buildDem_pointcloud")
)

# Line ~1541: Build DEM (mesh surface)
self.doc.chunk.buildDem(
    source_data=Metashape.DataSource.ModelData,
    # ... other parameters ...
    progress=self._make_progress_callback("buildDem_mesh")
)

# Line ~1567: Build DEM (tie points surface)
self.doc.chunk.buildDem(
    source_data=Metashape.DataSource.TiePointsData,
    # ... other parameters ...
    progress=self._make_progress_callback("buildDem_tiepoints")
)
```

**Orthomosaic:**
```python
# Line ~1640: Build orthomosaic
self.doc.chunk.buildOrthomosaic(
    surface_data=surface_source,
    # ... other parameters ...
    progress=self._make_progress_callback("buildOrthomosaic")
)
```

**Export operations (if they support progress callbacks - verify in API docs):**
```python
# Lines ~1402, 1415: Export point cloud (check if progress param supported)
# Lines ~1471: Export model
# Lines ~1528, 1557, 1581, 1669: Export rasters

# Only add progress callbacks if the Metashape API supports them for these exports
# Check metashape_python_api_2_2_1.pdf to confirm
```

**Total: ~10-15 one-line additions** (exact count depends on whether export methods support progress callbacks).

---

### File 2: `python/license_retry_wrapper.py`

#### Change 2.1: Add OutputMonitor class

Add this class at module level (after imports, before `_signal_handler`):

```python
import collections
import time
import os
from pathlib import Path


class OutputMonitor:
    """
    Monitor subprocess output with heartbeat, selective pass-through, buffering, and full logging.

    Features:
    - Circular buffer: Keeps last N lines in memory for error context dump
    - Full log file: Writes every line to disk (on shared volume, no timestamps added)
    - Heartbeat: Periodic status messages proving process liveness (with recent line sample)
    - Selective pass-through: Only prints important lines to console (progress, license, monitor messages)
    - Full output mode: When LOG_HEARTBEAT_INTERVAL=0, prints all lines like original behavior
    """

    def __init__(self, log_file_path=None):
        """
        Initialize the output monitor.

        Args:
            log_file_path: Path to full log file (optional). If None, no file logging.
        """
        # Configuration from environment variables
        self.buffer_size = int(os.environ.get("LOG_BUFFER_SIZE", 100))
        self.heartbeat_interval = int(os.environ.get("LOG_HEARTBEAT_INTERVAL", 60))

        # If heartbeat interval is 0, enable full output mode (print all lines)
        self.full_output_mode = (self.heartbeat_interval == 0)

        # State
        self.buffer = collections.deque(maxlen=self.buffer_size)
        self.line_count = 0
        self.start_time = time.time()
        self.last_heartbeat = self.start_time
        self.last_content_line = ""  # Track most recent Metashape output line
        self.log_file = None

        # Important line prefixes to always pass through to console (in sparse mode)
        self.important_prefixes = (
            "[progress]",
            "[license-wrapper]",
            "[monitor]",
            "[heartbeat]",
        )

        # Open full log file if path provided
        if log_file_path:
            log_dir = os.path.dirname(log_file_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            self.log_file = open(log_file_path, "w", buffering=1)  # Line buffered
            print(f"[monitor] Full log: {log_file_path}")

        if self.full_output_mode:
            print("[monitor] Full output mode enabled (LOG_HEARTBEAT_INTERVAL=0)")

    def process_line(self, line):
        """
        Process a single line of subprocess output.

        - Adds to circular buffer
        - Writes to full log file (as-is, no timestamps added)
        - In full mode: prints every line to console
        - In sparse mode: only prints important lines + heartbeat with recent line sample

        Args:
            line: Line of output from subprocess (includes newline)

        Returns:
            str: The line unchanged (for compatibility with license checking)
        """
        self.line_count += 1
        self.buffer.append(line)

        # Write every line to full log file (no timestamp overhead)
        if self.log_file:
            self.log_file.write(line)

        if self.full_output_mode:
            # Full output mode: print every line (original behavior)
            print(line, end="")
        else:
            # Sparse mode: selective pass-through with heartbeat

            # Track last interesting line (not our own system messages) for heartbeat display
            if not any(line.startswith(prefix) for prefix in self.important_prefixes):
                self.last_content_line = line.strip()[:100]  # Truncate to 100 chars

            # Pass through important lines to console
            if any(line.startswith(prefix) for prefix in self.important_prefixes):
                print(line, end="")

            # Check if it's time for a heartbeat
            now = time.time()
            if now - self.last_heartbeat >= self.heartbeat_interval:
                elapsed = now - self.start_time
                last_line_display = f" | last: {self.last_content_line}" if self.last_content_line else ""
                print(f"[heartbeat] {time.strftime('%H:%M:%S')} | "
                      f"lines: {self.line_count} | "
                      f"elapsed: {elapsed:.0f}s{last_line_display}")
                self.last_heartbeat = now

        return line

    def dump_buffer(self):
        """Dump circular buffer contents to console (for error context)."""
        print(f"\n[monitor] === Last {len(self.buffer)} lines before error ===")
        for line in self.buffer:
            print(line, end="")
        print(f"[monitor] === End error context ===\n")

    def print_summary(self, exit_code):
        """Print final summary of processing."""
        elapsed = time.time() - self.start_time
        status = "SUCCESS" if exit_code == 0 else f"FAILED (exit code {exit_code})"
        print(f"[monitor] {status} | "
              f"total lines: {self.line_count} | "
              f"elapsed: {elapsed:.0f}s")
        if self.log_file:
            print(f"[monitor] Full log saved to: {self.log_file.name}")

    def close(self):
        """Clean up resources."""
        if self.log_file:
            self.log_file.close()

    def reset(self):
        """Reset state for a new retry attempt."""
        self.buffer.clear()
        self.line_count = 0
        self.start_time = time.time()
        self.last_heartbeat = self.start_time
        if self.log_file:
            # Truncate log file for new attempt
            self.log_file.seek(0)
            self.log_file.truncate()
```

#### Change 2.2: Add log path computation helper

Add this function after the `OutputMonitor` class:

```python
def _compute_log_path(args):
    """
    Derive log file path from CLI arguments (--output-path and --step).

    Places log file on shared volume as a sibling to the output directory:
    /data/.../photogrammetry/metashape-<step>.log

    Args:
        args: Command-line arguments list (sys.argv[1:])

    Returns:
        str: Computed log file path, or fallback to /tmp if args not found
    """
    # Allow explicit override via environment variable
    override = os.environ.get("LOG_OUTPUT_DIR")

    output_path = None
    step = "unknown"
    i = 0
    while i < len(args):
        if args[i] == "--output-path" and i + 1 < len(args):
            output_path = args[i + 1]
        elif args[i] == "--step" and i + 1 < len(args):
            step = args[i + 1]
        i += 1

    if override:
        return os.path.join(override, f"metashape-{step}.log")
    elif output_path:
        # Place log as sibling to output dir
        # output_path is like: /data/.../photogrammetry/output
        # log path should be:   /data/.../photogrammetry/metashape-<step>.log
        parent = os.path.dirname(output_path.rstrip("/"))
        return os.path.join(parent, f"metashape-{step}.log")
    else:
        # Fallback to /tmp if we can't determine path from args
        return f"/tmp/metashape-{step}.log"
```

#### Change 2.3: Modify main retry loop

Replace the `run_with_license_retry()` function with this updated version:

```python
def run_with_license_retry():
    global _child_process

    max_retries = int(os.environ.get("LICENSE_MAX_RETRIES", 0))
    retry_interval = int(os.environ.get("LICENSE_RETRY_INTERVAL", 300))
    license_check_lines = int(os.environ.get("LICENSE_CHECK_LINES", 4))

    # Find metashape_workflow.py relative to this script
    script_dir = Path(__file__).parent
    workflow_script = script_dir / "metashape_workflow.py"

    # Pass through all command-line arguments
    cmd = [sys.executable, str(workflow_script)] + sys.argv[1:]

    # Compute log file path from arguments
    log_file_path = _compute_log_path(sys.argv[1:])

    # Create output monitor (persists across retry attempts)
    monitor = OutputMonitor(log_file_path)

    # Set up signal handlers to forward termination signals to child
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    attempt = 0
    while True:
        attempt += 1
        monitor.reset()
        print(f"[license-wrapper] Starting Metashape workflow (attempt {attempt})...")

        _child_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        license_error = False
        line_count = 0

        for line in _child_process.stdout:
            # License check phase: first N lines are always printed directly
            # (needed for license error detection to work)
            if line_count < license_check_lines:
                print(line, end="")

                # Also track in monitor (buffer + full log, but skip duplicate console print)
                monitor.buffer.append(line)
                monitor.line_count += 1
                if monitor.log_file:
                    monitor.log_file.write(line)

                # Check for license error
                line_lower = line.lower()
                if "license not found" in line_lower or "no license found" in line_lower:
                    license_error = True
                    _child_process.terminate()
                    _child_process.wait()
                    break

                line_count += 1
                if line_count >= license_check_lines:
                    print("[license-wrapper] License check passed, proceeding with workflow...")
            else:
                # Post-license-check: use monitor for selective output
                monitor.process_line(line)

        _child_process.wait()

        if license_error:
            # License error detected - retry if configured
            if max_retries == 0:
                print("[license-wrapper] No license available and retries disabled (LICENSE_MAX_RETRIES=0)")
                monitor.close()
                sys.exit(1)
            if max_retries > 0 and attempt > max_retries:
                print(f"[license-wrapper] Max retries ({max_retries}) exceeded")
                monitor.close()
                sys.exit(1)
            print(f"[license-wrapper] No license available. Waiting {retry_interval}s before retry...")
            time.sleep(retry_interval)
            continue

        # Process completed (not a license error)
        if _child_process.returncode != 0:
            # Non-zero exit: dump error context buffer
            monitor.dump_buffer()

        monitor.print_summary(_child_process.returncode)
        monitor.close()
        sys.exit(_child_process.returncode)
```

**Key changes:**
- Create `OutputMonitor` instance with computed log path
- During license check phase: print directly + track in monitor
- After license check: route all lines through `monitor.process_line()`
- On error: call `monitor.dump_buffer()`
- On completion: call `monitor.print_summary()`

---

## Part 2: ofo-argo Repository Changes

### File: `photogrammetry-workflow-stepbased.yaml`

#### Change 2.1: Add workflow parameters

Add these parameters under `spec.arguments.parameters` (around line 30-50):

```yaml
  # Heartbeat logger and progress callback configuration
  - name: LOG_HEARTBEAT_INTERVAL
    value: "60"  # Seconds between heartbeat status lines
  - name: LOG_BUFFER_SIZE
    value: "100"  # Number of lines to keep in error context buffer
  - name: PROGRESS_INTERVAL_PCT
    value: "10"  # Print progress every N percent (e.g., 10 = print at 10%, 20%, 30%...)
```

#### Change 2.2: Update CPU template environment variables

In the `metashape-cpu-step` template (around line 633-642), add to the existing `env:` section:

```yaml
        env:
          - name: AGISOFT_FLS
            valueFrom:
              secretKeyRef:
                name: agisoft-license
                key: license_server
          - name: LICENSE_RETRY_INTERVAL
            value: "{{workflow.parameters.LICENSE_RETRY_INTERVAL}}"
          - name: LICENSE_MAX_RETRIES
            value: "{{workflow.parameters.LICENSE_MAX_RETRIES}}"
          # Add these three new env vars:
          - name: LOG_HEARTBEAT_INTERVAL
            value: "{{workflow.parameters.LOG_HEARTBEAT_INTERVAL}}"
          - name: LOG_BUFFER_SIZE
            value: "{{workflow.parameters.LOG_BUFFER_SIZE}}"
          - name: PROGRESS_INTERVAL_PCT
            value: "{{workflow.parameters.PROGRESS_INTERVAL_PCT}}"
```

#### Change 2.3: Update GPU template environment variables

In the `metashape-gpu-step` template (around line 680-689), add the same three env vars:

```yaml
        env:
          - name: AGISOFT_FLS
            valueFrom:
              secretKeyRef:
                name: agisoft-license
                key: license_server
          - name: LICENSE_RETRY_INTERVAL
            value: "{{workflow.parameters.LICENSE_RETRY_INTERVAL}}"
          - name: LICENSE_MAX_RETRIES
            value: "{{workflow.parameters.LICENSE_MAX_RETRIES}}"
          # Add these three new env vars:
          - name: LOG_HEARTBEAT_INTERVAL
            value: "{{workflow.parameters.LOG_HEARTBEAT_INTERVAL}}"
          - name: LOG_BUFFER_SIZE
            value: "{{workflow.parameters.LOG_BUFFER_SIZE}}"
          - name: PROGRESS_INTERVAL_PCT
            value: "{{workflow.parameters.PROGRESS_INTERVAL_PCT}}"
```

---

## Configuration Summary

### Environment Variables

| Variable | Default | Purpose | Configured In |
|----------|---------|---------|---------------|
| `LOG_HEARTBEAT_INTERVAL` | `60` | Seconds between heartbeat status lines. **Special value `0` = full output mode** (print all lines, no filtering). | ofo-argo workflow YAML |
| `LOG_BUFFER_SIZE` | `100` | Number of lines kept in circular buffer for error context dump on failure. | ofo-argo workflow YAML |
| `PROGRESS_INTERVAL_PCT` | `10` | Progress reporting interval (%) - prints at 10%, 20%, 30%... Applies in both sparse and full modes. | ofo-argo workflow YAML |
| `LOG_OUTPUT_DIR` | (not set) | Optional override for log file directory. If not set, path is computed from `--output-path` argument. | Manual override only |

### Operating Modes

The behavior changes based on `LOG_HEARTBEAT_INTERVAL`:

**Sparse Mode (default):** `LOG_HEARTBEAT_INTERVAL > 0` (e.g., `60`)
- Console: Only `[progress]`, `[license-wrapper]`, `[monitor]` lines, plus periodic heartbeats
- Heartbeat includes: timestamp, line count, elapsed time, **most recent Metashape output line** (random sampling)
- Full log file: Every line written to disk (no timestamps added, zero overhead)
- Error buffer: Last 100 lines dumped on failure

**Full Output Mode:** `LOG_HEARTBEAT_INTERVAL=0`
- Console: **Every line printed** (original behavior) + `[progress]` lines from callbacks
- No heartbeat messages (not needed since you see all output)
- Full log file: Still written
- Error buffer: Still dumped on failure (though less useful since you already saw everything)

### Key Design Decisions

**1. No timestamp overhead**
- Full log file writes lines as-is via `self.log_file.write(line)` with no string formatting
- Even at 100+ lines/sec, zero computational overhead
- Metashape's output already includes timestamps where relevant

**2. Heartbeat shows recent activity**
- The `last:` field in heartbeat displays the most recent Metashape output line (truncated to 100 chars)
- Provides random sampling of actual processing activity for human visibility
- Example: `[heartbeat] 14:32:15 | lines: 247 | elapsed: 60s | last: Processing depth map for camera 145...`

**3. Full output mode for migration/debugging**
- Setting `LOG_HEARTBEAT_INTERVAL=0` disables all filtering
- Prints every line to console (original behavior) while still getting:
  - Progress callbacks showing X% completion
  - Full log file on disk
  - Error buffer dump on failures
- Easy migration path for teams that want incremental adoption

### Log File Paths

Full logs are written to the shared volume at:
```
/data/argo-output/temp-dir/<workflow-name>/<project-name-sanitized>/photogrammetry/metashape-<step>.log
```

Example:
```
/data/argo-output/temp-dir/wf-abc123/my-project/photogrammetry/metashape-build_depth_maps.log
```

These are automatically cleaned up by the existing `cleanup-project-template` after workflow completion.

---

## Output Examples

### Console Output: Normal Operation (Sparse Mode)

```
[license-wrapper] Starting Metashape workflow (attempt 1)...
No nodelocked license found
License server 149.165.171.237:5842: OK
[license-wrapper] License check passed, proceeding with workflow...
[monitor] Full log: /data/argo-output/temp-dir/wf-abc123/my-project/photogrammetry/metashape-build_depth_maps.log
[progress] buildDepthMaps: 10%
[heartbeat] 14:32:15 | lines: 247 | elapsed: 60s | last: Processing depth map for camera 145...
[progress] buildDepthMaps: 20%
[progress] buildDepthMaps: 30%
[heartbeat] 14:33:15 | lines: 512 | elapsed: 120s | last: Building point cloud from depth maps... chunk 3/12
[progress] buildDepthMaps: 40%
[progress] buildDepthMaps: 50%
[progress] buildDepthMaps: 60%
[heartbeat] 14:34:15 | lines: 841 | elapsed: 180s | last: Filtering depth values, threshold=0.5
[progress] buildDepthMaps: 70%
[progress] buildDepthMaps: 80%
[progress] buildDepthMaps: 90%
[progress] buildDepthMaps: 100%
[monitor] SUCCESS | total lines: 5247 | elapsed: 3847s
[monitor] Full log saved to: /data/argo-output/temp-dir/wf-abc123/my-project/photogrammetry/metashape-build_depth_maps.log
{"point_cloud_all_classes": "/data/argo-output/temp-dir/wf-abc123/my-project/photogrammetry/output/project_points.copc.laz"}
```

**Total console lines: ~20-30** (versus thousands without this implementation)

**Note:** The `last:` field in heartbeat shows a random sample of what Metashape is actually doing, giving human visibility into the process without overwhelming the logs.

### Console Output: Full Mode (LOG_HEARTBEAT_INTERVAL=0)

```
[license-wrapper] Starting Metashape workflow (attempt 1)...
No nodelocked license found
License server 149.165.171.237:5842: OK
[license-wrapper] License check passed, proceeding with workflow...
[monitor] Full log: /data/argo-output/temp-dir/wf-abc123/my-project/photogrammetry/metashape-build_depth_maps.log
[monitor] Full output mode enabled (LOG_HEARTBEAT_INTERVAL=0)
2024-02-08 14:30:15 Metashape Version: 2.1.0
2024-02-08 14:30:16 Building depth maps...
2024-02-08 14:30:17 Downscale: 4
[progress] buildDepthMaps: 10%
2024-02-08 14:30:18 Processing depth map for camera 0...
2024-02-08 14:30:19 Camera 0: depth map complete
2024-02-08 14:30:20 Processing depth map for camera 1...
... (every single line printed)
[progress] buildDepthMaps: 20%
... (thousands more lines)
[progress] buildDepthMaps: 100%
[monitor] SUCCESS | total lines: 5247 | elapsed: 3847s
[monitor] Full log saved to: /data/argo-output/temp-dir/wf-abc123/my-project/photogrammetry/metashape-build_depth_maps.log
{"point_cloud_all_classes": "/data/argo-output/temp-dir/wf-abc123/my-project/photogrammetry/output/project_points.copc.laz"}
```

**Total console lines: Same as today (thousands)** but now with `[progress]` milestones and full log file + error buffer

### Console Output: Error with Buffer Dump (Sparse Mode)

```
[license-wrapper] Starting Metashape workflow (attempt 1)...
No nodelocked license found
License server 149.165.171.237:5842: OK
[license-wrapper] License check passed, proceeding with workflow...
[monitor] Full log: /data/argo-output/temp-dir/wf-xyz789/failing-project/photogrammetry/metashape-build_depth_maps.log
[progress] buildDepthMaps: 10%
[progress] buildDepthMaps: 20%
[heartbeat] 15:44:22 | lines: 1523 | elapsed: 120s | last: Depth map filter: processing camera group 2/8
[progress] buildDepthMaps: 30%
[progress] buildDepthMaps: 40%
[progress] buildDepthMaps: 50%
[heartbeat] 15:46:22 | lines: 3200 | elapsed: 240s | last: Allocating memory for depth computation (12.4 GB required)
[progress] buildDepthMaps: 60%

[monitor] === Last 100 lines before error ===
2024-02-08 15:47:15 Processing depth map for camera 3180...
2024-02-08 15:47:16 Processing depth map for camera 3181...
2024-02-08 15:47:17 Processing depth map for camera 3182...
... (97 more lines of context)
2024-02-08 15:47:45 Error: Insufficient memory for depth map computation
Traceback (most recent call last):
  File "/app/python/metashape_workflow.py", line 245, in main
    workflow.run()
  File "/app/python/metashape_workflow_functions.py", line 1350, in run
    self.build_depth_maps()
RuntimeError: Not enough memory
Metashape errored while processing...
[monitor] === End error context ===

[monitor] FAILED (exit code 1) | total lines: 3247 | elapsed: 7215s
[monitor] Full log saved to: /data/argo-output/temp-dir/wf-xyz789/failing-project/photogrammetry/metashape-build_depth_maps.log
{"report": "/data/argo-output/temp-dir/wf-xyz789/failing-project/photogrammetry/output/project_report.pdf"}
```

**Result:** You see the last 100 lines leading up to the error, including the full traceback, without needing to download the full log file. The heartbeat's `last:` field gives clues about what was happening before the crash (in this case, memory allocation).

### Full Log File Contents

The full log file contains **every single line** of Metashape output **as-is (no timestamps added)**, including all the verbose processing details.

**Note on overhead:** Lines are written directly via `self.log_file.write(line)` with no timestamp prepending, so there's **zero computational overhead** even at 100+ lines per second. Metashape's own output often includes timestamps where relevant.

Example excerpt:

```
2024-02-08 15:45:10 Metashape Version: 2.1.0
2024-02-08 15:45:11 Loading project from /data/.../project/project.psx
2024-02-08 15:45:12 Project loaded: 5247 photos, 1 chunk
2024-02-08 15:45:13 Building depth maps...
2024-02-08 15:45:14 Depth map downscale: 4
2024-02-08 15:45:14 Filter mode: Mild
2024-02-08 15:45:15 Processing depth map for camera 0...
2024-02-08 15:45:16 Camera 0: depth map complete (1024x768 pixels)
2024-02-08 15:45:17 Processing depth map for camera 1...
2024-02-08 15:45:18 Camera 1: depth map complete (1024x768 pixels)
... (thousands more lines)
```

This file is available for download from the Argo UI artifacts or via direct filesystem access for deep debugging.

---

## Testing Plan

### 1. Unit Test: Progress Callback (automate-metashape)

**Test script:** `test_progress_callback.py`

```python
import sys
from io import StringIO
from python.metashape_workflow_functions import MetashapeWorkflow

# Mock minimal workflow instance
class MockWorkflow:
    def _make_progress_callback(self, operation_name):
        # Copy implementation from MetashapeWorkflow
        pass

# Capture stderr
old_stderr = sys.stderr
sys.stderr = StringIO()

workflow = MockWorkflow()
callback = workflow._make_progress_callback("testOperation")

# Simulate Metashape calling callback with various progress values
for pct in [0, 5, 10, 15, 20, 25, 50, 75, 95, 100]:
    callback(float(pct))

output = sys.stderr.getvalue()
sys.stderr = old_stderr

# Verify output
assert "[progress] testOperation: 10%" in output
assert "[progress] testOperation: 20%" in output
assert "[progress] testOperation: 100%" in output
assert "[progress] testOperation: 5%" not in output  # Should not print intermediate values
```

### 2. Unit Test: OutputMonitor (automate-metashape)

**Test script:** `test_output_monitor.py`

```python
import tempfile
import os
from python.license_retry_wrapper import OutputMonitor

# Test file logging
with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
    log_path = f.name

monitor = OutputMonitor(log_file_path=log_path)

# Process some lines
monitor.process_line("[progress] test: 10%\n")
monitor.process_line("verbose metashape line 1\n")
monitor.process_line("verbose metashape line 2\n")
monitor.process_line("[progress] test: 20%\n")

# Verify buffer contains all lines
assert len(monitor.buffer) == 4

# Verify full log file contains all lines
monitor.close()
with open(log_path) as f:
    log_contents = f.read()
assert "[progress] test: 10%" in log_contents
assert "verbose metashape line 1" in log_contents

os.unlink(log_path)
print("OutputMonitor tests passed")
```

### 3. Integration Test: Small Metashape Run (automate-metashape)

**Prerequisites:** Access to Metashape license, small test dataset

**Test 3a: Sparse mode**
1. Build Docker image with changes: `docker build -t automate-metashape:test .`
2. Run a single step (e.g., match photos) with a tiny dataset (~10 photos)
3. Set env vars: `LOG_HEARTBEAT_INTERVAL=10`, `PROGRESS_INTERVAL_PCT=10`
4. Monitor console output: should see `[progress]` lines, heartbeats with `last:` field
5. Check full log file: should contain all verbose Metashape output
6. Verify JSON output line appears at end of console output

**Expected result:**
- Console: ~10-20 lines total including heartbeats with recent line samples
- Heartbeat shows actual Metashape activity in `last:` field
- Log file: Hundreds of lines with full Metashape details
- Processing completes successfully

**Test 3b: Full output mode**
1. Same setup, but set `LOG_HEARTBEAT_INTERVAL=0`
2. Verify console shows: "[monitor] Full output mode enabled" message
3. Verify every line is printed to console (like original behavior)
4. Verify `[progress]` lines still appear at 10%, 20%, etc.
5. Verify NO heartbeat messages (since all lines are visible)

**Expected result:**
- Console: Hundreds of lines (every Metashape line) + progress milestones
- Log file: Same content as console
- Processing completes successfully

### 4. Integration Test: Error Case (automate-metashape)

**Steps:**
1. Force an error (e.g., insufficient memory, invalid parameter)
2. Run the workflow step
3. Verify buffer dump appears in console with last 100 lines
4. Verify full log file contains complete error context

### 5. Deployment Test: Argo Workflow (ofo-argo)

**Prerequisites:** Kubernetes cluster access, small test dataset configured

**Steps:**
1. Update workflow YAML with env var additions
2. Deploy workflow: `argo submit photogrammetry-workflow-stepbased.yaml --parameters-file test-params.yaml`
3. Monitor live logs: `argo logs <workflow-name> -f`
4. Verify:
   - `[progress]` lines appear during processing
   - Heartbeats appear every 60s
   - Console output remains sparse (~20-30 lines per step)
5. After completion, check pod logs in Argo UI
6. Verify full log files exist on shared volume at computed paths

**Expected result:**
- Workflow completes successfully
- Console logs are sparse but informative
- Full log files available for debugging if needed

---

## Files Changed

### automate-metashape Repository

| File | Lines Changed | Description |
|------|---------------|-------------|
| `python/metashape_workflow_functions.py` | +20 lines, ~10-15 one-line additions | Add `_make_progress_callback()` method, add `progress=` param to API calls |
| `python/license_retry_wrapper.py` | +160 lines, ~35 lines modified | Add `OutputMonitor` class with full/sparse modes, `_compute_log_path()` helper, modify main loop |

### ofo-argo Repository

| File | Lines Changed | Description |
|------|---------------|-------------|
| `photogrammetry-workflow-stepbased.yaml` | +9 lines | Add 3 workflow parameters, 3 env vars to CPU template, 3 env vars to GPU template |

### Summary of Improvements

✅ **Progress visibility:** Real percentage completion via Metashape API callbacks
✅ **Heartbeat with context:** Shows timestamp, line count, elapsed time, and most recent Metashape output
✅ **Zero overhead:** No timestamps added to log files, direct write-through
✅ **Full output mode:** Set `LOG_HEARTBEAT_INTERVAL=0` for original behavior + progress callbacks
✅ **Error context:** Last 100 lines always dumped on failure for immediate debugging
✅ **Full logs preserved:** Complete Metashape output saved to shared volume for deep analysis

---

## Migration Path

For teams wanting to adopt this incrementally or validate behavior before full deployment:

### Phase 1: Full output mode with progress callbacks
- Deploy automate-metashape changes + ofo-argo YAML changes
- Set `LOG_HEARTBEAT_INTERVAL=0` (full output mode)
- Benefit: Get progress % milestones + full log files + error buffer, with no change to console verbosity
- Validate: Progress callbacks work, full logs written correctly

### Phase 2: Sparse mode on a subset of projects
- For a few test projects, set `LOG_HEARTBEAT_INTERVAL=60`
- Monitor Argo logs to verify heartbeat + progress output is sufficient
- Compare sparse console logs vs full log files for debugging workflow
- Adjust `PROGRESS_INTERVAL_PCT` if needed (smaller = more frequent updates)

### Phase 3: Sparse mode globally
- Update default `LOG_HEARTBEAT_INTERVAL` to `60` for all workflows
- Monitor k8s control plane and artifact store resource usage (should decrease)
- Keep full log files for post-mortem debugging if needed

### Emergency fallback
- If sparse mode causes issues, immediately set `LOG_HEARTBEAT_INTERVAL=0` to restore full output
- No code changes needed, just update workflow parameter

---

## Rollback Plan

If issues occur in production:

1. **automate-metashape:** Revert to previous container image tag via `AUTOMATE_METASHAPE_IMAGE_TAG` workflow parameter
2. **ofo-argo:** Remove the 9 added lines from workflow YAML (env vars are optional, so old containers ignore them)
3. No data migration needed - changes are purely runtime behavior

---

## Future Enhancements (Out of Scope)

1. **Time-based progress throttling:** Print progress at most once every N seconds (in addition to percentage intervals)
2. **Progress callback for export operations:** Check if Metashape export APIs support progress callbacks (currently assumed they don't)
3. **Log file upload to S3:** Optionally copy full log files to S3 artifacts alongside outputs (currently they're cleaned up with temp files)
4. **Configurable important prefixes:** Allow workflow to specify which line prefixes to pass through (currently hardcoded)
5. **Metrics extraction from logs:** Parse full log files post-processing to extract timing/resource metrics

---

## References

- Original specification: User request for heartbeat logger with error context
- Metashape Python API: `/home/derek/repos/ofo-argo/ref/metashape_python_api_2_2_1.pdf`
- License retry implementation: `/home/derek/repos/ofo-argo/docs/plans/metashape-license-retry-implementation-plan.md`
- automate-metashape repository: `https://github.com/open-forest-observatory/automate-metashape`
- ofo-argo repository: `https://github.com/open-forest-observatory/ofo-argo`
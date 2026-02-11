# Implementation Plan: Metashape License Retry Wrapper

> **Status: Implemented** - See [automate-metashape PR](https://github.com/open-forest-observatory/automate-metashape) for wrapper script and [ofo-argo workflow changes](../photogrammetry-workflow-stepbased.yaml) for Argo integration.

## Overview

Add a Python wrapper script to the automate-metashape repository that monitors subprocess output for license failures and retries with configurable delays.

---

## 1. New File: `python/license_retry_wrapper.py`

```python
#!/usr/bin/env python3
"""
Wrapper script that runs metashape_workflow.py with license retry logic.

Monitors the first N lines of output for "license not found" errors.
If detected, terminates the subprocess immediately and retries after a delay.
This prevents wasting hours of compute on jobs that will fail at save time.

Environment variables:
  LICENSE_MAX_RETRIES: Maximum retry attempts (0 = no retries/fail immediately, -1 = unlimited, >0 = that many retries). Default: 0
  LICENSE_RETRY_INTERVAL: Seconds between retries (default: 300)
  LICENSE_CHECK_LINES: Number of lines to monitor for license errors (default: 20)
"""

import subprocess
import sys
import time
import os
from pathlib import Path


def run_with_license_retry():
    max_retries = int(os.environ.get("LICENSE_MAX_RETRIES", 0))
    retry_interval = int(os.environ.get("LICENSE_RETRY_INTERVAL", 300))
    license_check_lines = int(os.environ.get("LICENSE_CHECK_LINES", 20))

    # Find metashape_workflow.py relative to this script
    script_dir = Path(__file__).parent
    workflow_script = script_dir / "metashape_workflow.py"

    # Pass through all command-line arguments
    cmd = ["python3", str(workflow_script)] + sys.argv[1:]

    attempt = 0
    while True:
        attempt += 1
        print(f"[license-wrapper] Starting Metashape workflow (attempt {attempt})...")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        license_error = False
        line_count = 0

        for line in proc.stdout:
            print(line, end='')

            # Only check first N lines for license error
            if line_count < license_check_lines:
                line_lower = line.lower()
                if "license not found" in line_lower or "no license found" in line_lower:
                    license_error = True
                    proc.terminate()
                    proc.wait()
                    break
                line_count += 1
                if line_count >= license_check_lines:
                    print("[license-wrapper] License check passed, proceeding with workflow...")

        proc.wait()

        if license_error:
            if max_retries > 0 and attempt >= max_retries:
                print(f"[license-wrapper] Max retries ({max_retries}) exceeded")
                sys.exit(1)
            print(f"[license-wrapper] No license available. Waiting {retry_interval}s before retry...")
            time.sleep(retry_interval)
            continue

        # Not a license error - exit with subprocess exit code
        sys.exit(proc.returncode)


if __name__ == "__main__":
    run_with_license_retry()
```

---

## 2. Changes to ofo-argo Workflow YAML

### 2a. Add workflow parameters (optional, for override flexibility)

```yaml
# In spec.arguments.parameters:
- name: LICENSE_RETRY_INTERVAL
  value: "300"
- name: LICENSE_MAX_RETRIES
  value: "0"
```

### 2b. Update `metashape-cpu-step` template

Change command from:
```yaml
python3 /app/python/metashape_workflow.py \
```

To:
```yaml
python3 /app/python/license_retry_wrapper.py \
```

Add environment variables:
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
```

### 2c. Update `metashape-gpu-step` template

Same changes as CPU template.

---

## 3. Behavior Summary

| Scenario | Behavior |
|----------|----------|
| License available | Wrapper prints "License check passed", workflow runs normally |
| License unavailable, `LICENSE_MAX_RETRIES=0` (default) | Wrapper detects error, exits immediately with code 1 |
| License unavailable, `LICENSE_MAX_RETRIES>0` or `-1` | Wrapper detects error, waits `LICENSE_RETRY_INTERVAL`, retries |
| License unavailable after max retries exceeded | Wrapper exits with code 1 |
| Non-license error | Wrapper exits with subprocess exit code |

---

## 4. Output Examples

### License found:
```
[license-wrapper] Starting Metashape workflow (attempt 1)...
No nodelocked license found
License server 149.165.171.237:5842: OK
[license-wrapper] License check passed, proceeding with workflow...
<normal workflow output>
```

### License not found, retry:
```
[license-wrapper] Starting Metashape workflow (attempt 1)...
No nodelocked license found
License server 149.165.171.237:5842: License not found
[license-wrapper] No license available. Waiting 300s before retry...
[license-wrapper] Starting Metashape workflow (attempt 2)...
...
```

---

## 5. Testing

1. **Local test without license**: Temporarily misconfigure `AGISOFT_FLS`, verify wrapper detects and retries
2. **Local test with license**: Verify wrapper passes through and workflow completes
3. **Docker test**: Build image, run container, verify behavior matches local
4. **Argo test**: Deploy workflow, verify env vars passed correctly

---

## 6. Files Changed

| Repository | File | Change | Status |
|------------|------|--------|--------|
| automate-metashape | `python/license_retry_wrapper.py` | New file | ✅ Done |
| ofo-argo | `photogrammetry-workflow-stepbased.yaml` | Update command + add env vars | ✅ Done |

---

## 7. Background

### Why this approach?

- **License acquired at import**: Metashape checks/acquires license when `import Metashape` runs
- **No reload possible**: `importlib.reload(Metashape)` doesn't work due to module structure
- **Operations run without license**: Metashape lets you run matching, alignment, etc. without a license
- **Save fails**: Only `doc.save()` fails with "No license found"
- **Early detection**: License failure messages appear in first few lines of output
- **Subprocess restart**: Each retry spawns a fresh Python process with fresh `import Metashape`

### License error patterns detected:

- `"License not found"` (from license server check)
- `"No license found"` (from nodelocked check and save errors)

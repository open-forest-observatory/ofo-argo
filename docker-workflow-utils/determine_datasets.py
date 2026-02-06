#!/usr/bin/env python3
"""
Preprocessing script for step-based photogrammetry workflow.

Reads mission config files and generates mission parameters with enabled flags.
This determines which processing steps are enabled and whether GPU or CPU nodes
should be used for GPU-capable steps.

Usage:
    python determine_datasets.py <config_list_path> [output_file_path] [options]

Arguments:
    config_list_path: Path to text file listing config files
    output_file_path: Optional path to write full configs JSON (for artifact-based workflow).
                      If provided, stdout will contain only minimal references.
                      If not provided, stdout will contain full configs (legacy behavior).

Options:
    --completion-log PATH     Path to completion log file (JSON Lines format)
                              Use separate log files per config (e.g., completion-log-default.jsonl)
    --skip-if-complete MODE   Skip projects based on completion status:
                              none (default), metashape, postprocess, both
    --workflow-name NAME      Argo workflow name for logging

Output:
    - If output_file_path provided: Writes full configs to file, outputs minimal refs to stdout
    - If output_file_path not provided: Outputs full configs to stdout (legacy)
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


def get_nested(d: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    """
    Safely get nested dictionary value.

    Args:
        d: Dictionary to traverse
        keys: List of keys to traverse (e.g., ['project', 'project_name'])
        default: Default value if key path doesn't exist

    Returns:
        Value at the nested key path, or default if not found
    """
    for key in keys:
        if isinstance(d, dict):
            d = d.get(key, default)
        else:
            return default
    return d


def str_to_bool(val: Any) -> bool:
    """
    Convert string value to boolean.

    Args:
        val: Value to convert (bool, str, or other)

    Returns:
        Boolean representation of the value
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


def sanitize_dns1123(name: str) -> str:
    """
    Sanitize a name to be DNS-1123 compliant for Kubernetes.

    DNS-1123 requirements:
    - Lowercase alphanumeric characters, hyphens, and dots only
    - Must start and end with an alphanumeric character (a-z, 0-9)
    - Must not start or end with a hyphen or dot
    - Max length of 253 characters

    Args:
        name: Original name to sanitize

    Returns:
        DNS-1123 compliant name
    """
    # Convert to lowercase
    sanitized = name.lower()

    # Replace invalid characters (anything not alphanumeric, hyphen, or dot) with hyphen
    sanitized = re.sub(r"[^a-z0-9.-]", "-", sanitized)

    # Collapse multiple consecutive hyphens into one
    sanitized = re.sub(r"-+", "-", sanitized)

    # Remove leading/trailing hyphens or dots
    sanitized = sanitized.strip("-.")

    # Truncate to max 253 characters
    sanitized = sanitized[:253]

    # Ensure we didn't create a trailing hyphen/dot after truncation
    sanitized = sanitized.rstrip("-.")

    return sanitized


def load_completion_log(log_path: str) -> Dict[str, str]:
    """
    Load completion log and return lookup table.

    Args:
        log_path: Path to JSON Lines completion log

    Returns:
        Dict mapping project_name -> completion_level
        If duplicate entries exist, keeps the highest level (postprocess > metashape)
    """
    completions: Dict[str, str] = {}
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
                project_name = entry["project_name"]
                level = entry["completion_level"]
                # Keep highest completion level
                if project_name not in completions or level_priority.get(
                    level, 0
                ) > level_priority.get(completions[project_name], 0):
                    completions[project_name] = level
            except (json.JSONDecodeError, KeyError) as e:
                print(
                    f"Warning: Skipping malformed line {line_num} in completion log: {e}",
                    file=sys.stderr,
                )

    return completions


def should_skip_project(
    project_name: str,
    completions: Dict[str, str],
    skip_mode: str,
) -> Tuple[bool, bool]:
    """
    Determine if project should be skipped based on completion status.

    Args:
        project_name: Project identifier
        completions: Completion lookup from load_completion_log()
        skip_mode: One of "none", "metashape", "postprocess", "both"

    Returns:
        Tuple of (skip_entirely, skip_metashape_only)
        - skip_entirely: Don't include project in output at all
        - skip_metashape_only: Include project but set skip_metashape=True (for "both" mode)
    """
    if skip_mode == "none":
        return (False, False)

    completion_level = completions.get(project_name)

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


def process_config_file(config_path: str, index: int) -> Dict[str, Any]:
    """
    Process a single mission config file and extract mission parameters.

    Args:
        config_path: Absolute path to config file
        index: Zero-based index of this config in the processing list (used for iteration_id)

    Returns:
        Dictionary of mission parameters with enabled flags

    Raises:
        ValueError: If config file uses Phase 1 format (not compatible with step-based workflow)
    """
    # Load config file (expecting absolute path)
    with open(config_path, "r") as cf:
        config = yaml.safe_load(cf)

    # Validate that this is a Phase 2 config
    # Phase 1 configs have 'alignPhotos' section, Phase 2 has separate 'match_photos' and 'align_cameras'
    if "alignPhotos" in config:
        raise ValueError(
            f"Config file '{config_path}' uses Phase 1 format which is not compatible with the step-based workflow.\n"
            f"The step-based workflow requires Phase 2 config structure with:\n"
            f"  - Separate 'match_photos' and 'align_cameras' sections (not combined 'alignPhotos')\n"
            f"  - Each operation as a top-level section with 'enabled' flag\n"
            f"  - Global settings under 'project:' section\n"
            f"Please update your config to Phase 2 format.\n"
            f"See example: https://github.com/open-forest-observatory/automate-metashape/blob/main/config/config-example.yml\n"
            f"Or use the original monolithic workflow (photogrammetry-workflow.yaml) for Phase 1 configs."
        )

    # Extract project name (used as mission identifier)
    project_name = get_nested(config, ["project", "project_name"])
    if not project_name:
        # Fallback: extract from config file path
        base_with_ext = os.path.basename(config_path)
        project_name = os.path.splitext(base_with_ext)[0]

    # Create DNS-1123 compliant name for Kubernetes task names (Argo UI display only)
    # The original project_name is preserved for file paths and processing
    project_name_sanitized = sanitize_dns1123(project_name)

    # Generate unique iteration ID: 3-digit zero-padded index + underscore + sanitized project name
    # Example: "000_mission_001", "001_mission_001" (for duplicates), "002_other_project"
    # This provides uniqueness even with duplicate project names and easy identification
    iteration_id = f"{index:03d}_{project_name_sanitized}"

    # Extract argo config section for easy access
    argo_config = config.get("argo", {})

    # Extract imagery download settings from argo section
    # FUTURE: Could implement download sharing between projects to save bandwidth.
    # Would require: (1) download coordination/locking, (2) reference counting for cleanup,
    # (3) handling projects that start days apart. Current approach downloads per-project
    # to avoid these complexities and prevent storage issues from long-running workflows.
    imagery_downloads = argo_config.get("s3_imagery_zip_download", [])
    # Normalize single string to list
    if isinstance(imagery_downloads, str):
        imagery_downloads = [imagery_downloads] if imagery_downloads.strip() else []
    # Ensure it's a list (handle None case)
    if imagery_downloads is None:
        imagery_downloads = []

    # Default GPU resource (full GPU). Can be overridden per-step with MIG resources like:
    # "nvidia.com/mig-1g.5gb", "nvidia.com/mig-2g.10gb", "nvidia.com/mig-3g.20gb"
    DEFAULT_GPU_RESOURCE = "nvidia.com/gpu"
    DEFAULT_GPU_COUNT = 1

    # Hardcoded defaults for CPU/memory requests
    DEFAULT_CPU_REQUEST_CPU_MODE = "18"
    DEFAULT_MEMORY_REQUEST_CPU_MODE = "100Gi"
    DEFAULT_CPU_REQUEST_GPU_MODE = "4"
    DEFAULT_MEMORY_REQUEST_GPU_MODE = "16Gi"

    # Extract user-specified defaults from argo.defaults section (if present)
    # These sit between step-specific values and hardcoded defaults in the fallback chain
    user_cpu_default = get_nested(config, ["argo", "defaults", "cpu_request"])
    user_memory_default = get_nested(config, ["argo", "defaults", "memory_request"])
    user_gpu_resource_default = get_nested(config, ["argo", "defaults", "gpu_resource"])
    user_gpu_count_default = get_nested(config, ["argo", "defaults", "gpu_count"])

    # Apply translation logic from implementation plan
    mission = {
        "project_name": project_name,
        "project_name_sanitized": project_name_sanitized,
        "config": config_path,
        # Iteration ID for unique per-project isolation (used in download paths, etc.)
        "iteration_id": iteration_id,
        # S3 imagery download settings
        # imagery_zip_downloads is a list that Argo will serialize to JSON when needed
        "imagery_zip_downloads": imagery_downloads,
        # Boolean flags as lowercase strings for Argo workflow conditionals
        "imagery_download_enabled": str(len(imagery_downloads) > 0).lower(),
        # Setup step resources
        "setup_cpu_request": (
            get_nested(config, ["argo", "setup", "cpu_request"])
            or user_cpu_default
            or DEFAULT_CPU_REQUEST_CPU_MODE
        ),
        "setup_memory_request": (
            get_nested(config, ["argo", "setup", "memory_request"])
            or user_memory_default
            or DEFAULT_MEMORY_REQUEST_CPU_MODE
        ),
        # Step enabled flags (setup and finalize always run, so not included)
        # Use actual Python booleans (not strings) so they serialize to JSON true/false
        "match_photos_enabled": str_to_bool(
            get_nested(config, ["match_photos", "enabled"], False)
        ),
        "match_photos_use_gpu": str_to_bool(
            get_nested(config, ["argo", "match_photos", "gpu_enabled"], True)
        ),
        "match_photos_gpu_resource": (
            get_nested(config, ["argo", "match_photos", "gpu_resource"])
            or user_gpu_resource_default
            or DEFAULT_GPU_RESOURCE
        ),
        "match_photos_gpu_count": (
            get_nested(config, ["argo", "match_photos", "gpu_count"])
            or user_gpu_count_default
            or DEFAULT_GPU_COUNT
        ),
        "match_photos_cpu_request": (
            get_nested(config, ["argo", "match_photos", "cpu_request"])
            or user_cpu_default
            or (
                DEFAULT_CPU_REQUEST_GPU_MODE
                if str_to_bool(
                    get_nested(config, ["argo", "match_photos", "gpu_enabled"], True)
                )
                else DEFAULT_CPU_REQUEST_CPU_MODE
            )
        ),
        "match_photos_memory_request": (
            get_nested(config, ["argo", "match_photos", "memory_request"])
            or user_memory_default
            or (
                DEFAULT_MEMORY_REQUEST_GPU_MODE
                if str_to_bool(
                    get_nested(config, ["argo", "match_photos", "gpu_enabled"], True)
                )
                else DEFAULT_MEMORY_REQUEST_CPU_MODE
            )
        ),
        "align_cameras_enabled": str_to_bool(
            get_nested(config, ["align_cameras", "enabled"], False)
        ),
        "align_cameras_cpu_request": (
            get_nested(config, ["argo", "align_cameras", "cpu_request"])
            or user_cpu_default
            or DEFAULT_CPU_REQUEST_CPU_MODE
        ),
        "align_cameras_memory_request": (
            get_nested(config, ["argo", "align_cameras", "memory_request"])
            or user_memory_default
            or DEFAULT_MEMORY_REQUEST_CPU_MODE
        ),
        "build_depth_maps_enabled": str_to_bool(
            get_nested(config, ["build_depth_maps", "enabled"], False)
        ),
        "build_depth_maps_gpu_resource": (
            get_nested(config, ["argo", "build_depth_maps", "gpu_resource"])
            or user_gpu_resource_default
            or DEFAULT_GPU_RESOURCE
        ),
        "build_depth_maps_gpu_count": (
            get_nested(config, ["argo", "build_depth_maps", "gpu_count"])
            or user_gpu_count_default
            or DEFAULT_GPU_COUNT
        ),
        "build_depth_maps_cpu_request": (
            get_nested(config, ["argo", "build_depth_maps", "cpu_request"])
            or user_cpu_default
            or DEFAULT_CPU_REQUEST_GPU_MODE
        ),
        "build_depth_maps_memory_request": (
            get_nested(config, ["argo", "build_depth_maps", "memory_request"])
            or user_memory_default
            or DEFAULT_MEMORY_REQUEST_GPU_MODE
        ),
        "build_point_cloud_enabled": str_to_bool(
            get_nested(config, ["build_point_cloud", "enabled"], False)
        ),
        "build_point_cloud_cpu_request": (
            get_nested(config, ["argo", "build_point_cloud", "cpu_request"])
            or user_cpu_default
            or DEFAULT_CPU_REQUEST_CPU_MODE
        ),
        "build_point_cloud_memory_request": (
            get_nested(config, ["argo", "build_point_cloud", "memory_request"])
            or user_memory_default
            or DEFAULT_MEMORY_REQUEST_CPU_MODE
        ),
        "build_mesh_enabled": str_to_bool(
            get_nested(config, ["build_mesh", "enabled"], False)
        ),
        "build_mesh_use_gpu": str_to_bool(
            get_nested(config, ["argo", "build_mesh", "gpu_enabled"], True)
        ),
        "build_mesh_gpu_resource": (
            get_nested(config, ["argo", "build_mesh", "gpu_resource"])
            or user_gpu_resource_default
            or DEFAULT_GPU_RESOURCE
        ),
        "build_mesh_gpu_count": (
            get_nested(config, ["argo", "build_mesh", "gpu_count"])
            or user_gpu_count_default
            or DEFAULT_GPU_COUNT
        ),
        "build_mesh_cpu_request": (
            get_nested(config, ["argo", "build_mesh", "cpu_request"])
            or user_cpu_default
            or (
                DEFAULT_CPU_REQUEST_GPU_MODE
                if str_to_bool(
                    get_nested(config, ["argo", "build_mesh", "gpu_enabled"], True)
                )
                else DEFAULT_CPU_REQUEST_CPU_MODE
            )
        ),
        "build_mesh_memory_request": (
            get_nested(config, ["argo", "build_mesh", "memory_request"])
            or user_memory_default
            or (
                DEFAULT_MEMORY_REQUEST_GPU_MODE
                if str_to_bool(
                    get_nested(config, ["argo", "build_mesh", "gpu_enabled"], True)
                )
                else DEFAULT_MEMORY_REQUEST_CPU_MODE
            )
        ),
        # build_dem_orthomosaic runs if either DEM or orthomosaic is enabled
        "build_dem_orthomosaic_enabled": (
            str_to_bool(get_nested(config, ["build_dem", "enabled"], False))
            or str_to_bool(get_nested(config, ["build_orthomosaic", "enabled"], False))
        ),
        "build_dem_orthomosaic_cpu_request": (
            get_nested(config, ["argo", "build_dem_orthomosaic", "cpu_request"])
            or user_cpu_default
            or DEFAULT_CPU_REQUEST_CPU_MODE
        ),
        "build_dem_orthomosaic_memory_request": (
            get_nested(config, ["argo", "build_dem_orthomosaic", "memory_request"])
            or user_memory_default
            or DEFAULT_MEMORY_REQUEST_CPU_MODE
        ),
        # Secondary photo processing runs if photo_path_secondary is non-empty
        "match_photos_secondary_enabled": bool(
            get_nested(config, ["project", "photo_path_secondary"], "")
        ),
        # Secondary inherits from primary unless explicitly overridden (4-level fallback)
        "match_photos_secondary_use_gpu": str_to_bool(
            get_nested(config, ["argo", "match_photos_secondary", "gpu_enabled"])
            or get_nested(config, ["argo", "match_photos", "gpu_enabled"], True)
        ),
        "match_photos_secondary_gpu_resource": (
            get_nested(config, ["argo", "match_photos_secondary", "gpu_resource"])
            or get_nested(config, ["argo", "match_photos", "gpu_resource"])
            or user_gpu_resource_default
            or DEFAULT_GPU_RESOURCE
        ),
        "match_photos_secondary_gpu_count": (
            get_nested(config, ["argo", "match_photos_secondary", "gpu_count"])
            or get_nested(config, ["argo", "match_photos", "gpu_count"])
            or user_gpu_count_default
            or DEFAULT_GPU_COUNT
        ),
        "match_photos_secondary_cpu_request": (
            get_nested(config, ["argo", "match_photos_secondary", "cpu_request"])
            or get_nested(config, ["argo", "match_photos", "cpu_request"])
            or user_cpu_default
            or (
                DEFAULT_CPU_REQUEST_GPU_MODE
                if str_to_bool(
                    get_nested(
                        config, ["argo", "match_photos_secondary", "gpu_enabled"]
                    )
                    or get_nested(config, ["argo", "match_photos", "gpu_enabled"], True)
                )
                else DEFAULT_CPU_REQUEST_CPU_MODE
            )
        ),
        "match_photos_secondary_memory_request": (
            get_nested(config, ["argo", "match_photos_secondary", "memory_request"])
            or get_nested(config, ["argo", "match_photos", "memory_request"])
            or user_memory_default
            or (
                DEFAULT_MEMORY_REQUEST_GPU_MODE
                if str_to_bool(
                    get_nested(
                        config, ["argo", "match_photos_secondary", "gpu_enabled"]
                    )
                    or get_nested(config, ["argo", "match_photos", "gpu_enabled"], True)
                )
                else DEFAULT_MEMORY_REQUEST_CPU_MODE
            )
        ),
        "align_cameras_secondary_enabled": bool(
            get_nested(config, ["project", "photo_path_secondary"], "")
        ),
        "align_cameras_secondary_cpu_request": (
            get_nested(config, ["argo", "align_cameras_secondary", "cpu_request"])
            or get_nested(config, ["argo", "align_cameras", "cpu_request"])
            or user_cpu_default
            or DEFAULT_CPU_REQUEST_CPU_MODE
        ),
        "align_cameras_secondary_memory_request": (
            get_nested(config, ["argo", "align_cameras_secondary", "memory_request"])
            or get_nested(config, ["argo", "align_cameras", "memory_request"])
            or user_memory_default
            or DEFAULT_MEMORY_REQUEST_CPU_MODE
        ),
        # Finalize step resources
        "finalize_cpu_request": (
            get_nested(config, ["argo", "finalize", "cpu_request"])
            or user_cpu_default
            or DEFAULT_CPU_REQUEST_CPU_MODE
        ),
        "finalize_memory_request": (
            get_nested(config, ["argo", "finalize", "memory_request"])
            or user_memory_default
            or DEFAULT_MEMORY_REQUEST_CPU_MODE
        ),
    }

    return mission


def main(
    config_list_path: str,
    output_file_path: Optional[str] = None,
    completion_log: Optional[str] = None,
    skip_if_complete: str = "none",
    workflow_name: str = "",
) -> None:
    """
    Main entry point for preprocessing script.

    Args:
        config_list_path: Absolute path to text file listing config files.
            Each line can be either a filename (resolved relative to the config list's directory)
            or an absolute path (starting with /). Lines starting with # are comments.
            Inline comments (# after filename) are also supported.
        output_file_path: Optional path to write full configs JSON. If provided,
            stdout will contain only minimal references (to avoid Argo parameter size limits).
        completion_log: Optional path to completion log file (JSON Lines format).
            Should be config-specific (e.g., completion-log-default.jsonl).
        skip_if_complete: Skip mode - "none", "metashape", "postprocess", or "both".
        workflow_name: Argo workflow name for logging (unused in filtering, passed for reference).
    """
    # Load completion log if provided
    completions: Dict[str, str] = {}
    if completion_log and skip_if_complete != "none":
        completions = load_completion_log(completion_log)
        print(f"Loaded {len(completions)} entries from completion log", file=sys.stderr)

    # Create completion log file if it doesn't exist (for later appending by workflow)
    if completion_log and not os.path.exists(completion_log):
        os.makedirs(os.path.dirname(completion_log), exist_ok=True)
        Path(completion_log).touch()
        print(f"Created completion log file: {completion_log}", file=sys.stderr)

    missions: List[Dict[str, Any]] = []
    skipped_count = 0

    # Get directory containing the config list for resolving relative filenames
    config_list_dir = os.path.dirname(config_list_path)

    # Read config list file and resolve paths
    # Supports: comments (#), inline comments, filenames, and absolute paths
    config_paths = []
    with open(config_list_path, "r") as f:
        for line in f:
            line = line.split("#")[0].strip()  # Remove inline comments and whitespace
            if not line:  # Skip empty lines and comment-only lines
                continue
            # Resolve path: absolute paths used as-is, filenames joined with config list dir
            if line.startswith("/"):
                config_paths.append(line)
            else:
                config_paths.append(os.path.join(config_list_dir, line))

    for index, config_path in enumerate(config_paths):
        try:
            mission = process_config_file(config_path, index)

            # Check if should skip based on completion status
            skip_entirely, skip_metashape = should_skip_project(
                mission["project_name"], completions, skip_if_complete
            )

            if skip_entirely:
                level = completions.get(mission["project_name"], "unknown")
                print(
                    f"Skipping {mission['project_name']}: "
                    f"already complete at level '{level}'",
                    file=sys.stderr,
                )
                skipped_count += 1
                continue

            # Add skip_metashape flag for "both" mode partial skipping
            mission["skip_metashape"] = skip_metashape

            missions.append(mission)
        except Exception as e:
            print(f"Error processing config {config_path}: {e}", file=sys.stderr)
            raise

    print(
        f"Processing {len(missions)} projects, skipped {skipped_count} as already complete",
        file=sys.stderr,
    )

    if output_file_path:
        # Artifact-based mode: write full configs to file, output minimal refs to stdout
        # This avoids Argo's parameter size limit (default 256KB) for large batch runs

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

        # Write full configs to file
        with open(output_file_path, "w") as f:
            json.dump(missions, f)

        print(
            f"Wrote {len(missions)} project configs to {output_file_path}",
            file=sys.stderr,
        )

        # Output minimal references to stdout (just index and project_name)
        # These are small enough to pass via withParam without hitting size limits
        refs = [
            {"index": i, "project_name": m["project_name"]}
            for i, m in enumerate(missions)
        ]
        json.dump(refs, sys.stdout)
    else:
        # Legacy mode: output full configs to stdout
        json.dump(missions, sys.stdout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Preprocess config files for Argo workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic usage (legacy mode)
    python determine_datasets.py /data/config_list.txt

    # Artifact mode (avoids Argo parameter size limits)
    python determine_datasets.py /data/config_list.txt /data/output/configs.json

    # With completion tracking (use config-specific log file)
    python determine_datasets.py /data/config_list.txt /data/output/configs.json \\
        --completion-log /data/completion-log-default.jsonl \\
        --skip-if-complete postprocess
        """,
    )
    parser.add_argument(
        "config_list_path",
        help="Path to text file listing config files. Each line can be a filename "
        "(resolved relative to config list dir) or an absolute path. "
        "Lines starting with # are comments.",
    )
    parser.add_argument(
        "output_file_path",
        nargs="?",
        default=None,
        help="Optional output file for configs JSON. If provided, full configs are "
        "written to this file and only minimal refs are output to stdout (artifact mode).",
    )
    parser.add_argument(
        "--completion-log",
        help="Path to completion log file (JSON Lines format)",
    )
    parser.add_argument(
        "--skip-if-complete",
        choices=["none", "metashape", "postprocess", "both"],
        default="none",
        help="Skip projects based on completion status: "
        "none (default), metashape, postprocess, both",
    )
    parser.add_argument(
        "--workflow-name",
        default="",
        help="Argo workflow name for logging",
    )

    args = parser.parse_args()

    main(
        config_list_path=args.config_list_path,
        output_file_path=args.output_file_path,
        completion_log=args.completion_log,
        skip_if_complete=args.skip_if_complete,
        workflow_name=args.workflow_name,
    )

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
                      If omitted, no full configs file is written.

Options:
    --completion-log PATH       Path to completion log file (JSON Lines format)
                                Use separate log files per config (e.g., completion-log-default.jsonl)
    --skip-if-complete MODE     Skip projects based on completion status:
                                none (default), metashape, postprocess
    --require-phase PHASE       Only include projects that have completed the given phase

Output:
    - Always outputs minimal refs to stdout: [{"project_name": "..."}]
    - If output_file_path provided: also writes full configs to that file
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

# Regex for valid project names: must start and end with alphanumeric,
# internal characters can be alphanumeric, dots, hyphens, or underscores
VALID_PROJECT_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*[a-zA-Z0-9]$|^[a-zA-Z0-9]$")


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


def validate_project_name(name: str) -> None:
    """
    Validate that a project name is safe for shell and filesystem use.

    Must start and end with alphanumeric characters, and contain only
    alphanumeric characters, dots, hyphens, and underscores.

    Args:
        name: Project name to validate

    Raises:
        ValueError: If name contains invalid characters
    """
    if not VALID_PROJECT_NAME_RE.match(name):
        raise ValueError(
            f"Invalid project name '{name}'. "
            f"Project names must start and end with alphanumeric characters "
            f"and contain only alphanumeric characters, dots, hyphens, and underscores. "
            f"Pattern: {VALID_PROJECT_NAME_RE.pattern}"
        )


def load_completion_log(log_path: str) -> Dict[str, Set[str]]:
    """
    Load completion log and return lookup table.

    Supports both the current 'phase' field and the legacy 'completion_level' field
    for backward compatibility with existing logs.

    Args:
        log_path: Path to JSON Lines completion log

    Returns:
        Dict mapping project_name -> set of completed phases
        (e.g., {"project-A": {"metashape", "postprocess"}})
    """
    completions: Dict[str, Set[str]] = {}
    if not os.path.exists(log_path):
        return completions

    with open(log_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                project_name = entry["project_name"]
                # Support both 'phase' (current) and 'completion_level' (legacy)
                phase = entry.get("phase") or entry.get("completion_level")
                if phase is None:
                    raise KeyError("Missing 'phase' or 'completion_level' field")
                # Add phase to set of completed phases
                if project_name not in completions:
                    completions[project_name] = set()
                completions[project_name].add(phase)
            except (json.JSONDecodeError, KeyError) as e:
                print(
                    f"Warning: Skipping malformed line {line_num} in completion log: {e}",
                    file=sys.stderr,
                )

    return completions


def should_skip_project(
    project_name: str,
    completions: Dict[str, Set[str]],
    skip_mode: str,
) -> bool:
    """
    Determine if project should be skipped based on completion status.

    Args:
        project_name: Project identifier
        completions: Completion lookup from load_completion_log()
        skip_mode: One of "none", "metashape", "postprocess"

    Returns:
        True if the project should be skipped entirely
    """
    if skip_mode == "none":
        return False

    completed_phases = completions.get(project_name, set())
    return skip_mode in completed_phases


def should_include_project(
    project_name: str,
    completions: Dict[str, Set[str]],
    require_phase: Optional[str],
) -> bool:
    """
    Determine if project meets the required phase gate.

    Args:
        project_name: Project identifier
        completions: Completion lookup from load_completion_log()
        require_phase: Required phase (e.g., "metashape"). None means no requirement.

    Returns:
        True if the project should be included
    """
    if require_phase is None:
        return True

    completed_phases = completions.get(project_name, set())
    return require_phase in completed_phases


def process_config_file(config_path: str) -> Dict[str, Any]:
    """
    Process a single mission config file and extract mission parameters.

    Args:
        config_path: Absolute path to config file

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

    # Validate project name is safe for shell/filesystem use
    validate_project_name(project_name)

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
        "config": config_path,
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
    require_phase: Optional[str] = None,
) -> None:
    """
    Main entry point for preprocessing script.

    Args:
        config_list_path: Absolute path to text file listing config files.
            Each line can be either a filename (resolved relative to the config list's directory)
            or an absolute path (starting with /). Lines starting with # are comments.
            Inline comments (# after filename) are also supported.
        output_file_path: Optional path to write full configs JSON. If provided,
            full configs are written to this file. Stdout always contains minimal refs.
        completion_log: Optional path to completion log file (JSON Lines format).
            Should be config-specific (e.g., completion-log-default.jsonl).
        skip_if_complete: Skip mode - "none", "metashape", or "postprocess".
        require_phase: Only include projects that have completed this phase.
    """
    # Load completion log if needed for skip or require-phase logic
    completions: Dict[str, Set[str]] = {}
    if completion_log and (skip_if_complete != "none" or require_phase is not None):
        completions = load_completion_log(completion_log)
        print(f"Loaded {len(completions)} project completion records from log", file=sys.stderr)

    # Create completion log file if it doesn't exist (for later appending by workflow)
    if completion_log and not os.path.exists(completion_log):
        os.makedirs(os.path.dirname(completion_log), exist_ok=True)
        Path(completion_log).touch()
        print(f"Created completion log file: {completion_log}", file=sys.stderr)

    missions: List[Dict[str, Any]] = []
    skipped_count = 0
    excluded_count = 0

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

    seen_names = set()

    for config_path in config_paths:
        try:
            mission = process_config_file(config_path)

            # Check for duplicate project names
            name = mission["project_name"]
            if name in seen_names:
                print(
                    f"Warning: Dropping duplicate project '{name}' "
                    f"from config '{config_path}'",
                    file=sys.stderr,
                )
                continue
            seen_names.add(name)

            # Check if should skip based on completion status
            if should_skip_project(name, completions, skip_if_complete):
                phases = completions.get(name, set())
                phases_str = ", ".join(sorted(phases)) if phases else "unknown"
                print(
                    f"Skipping {name}: already complete (phases: {phases_str})",
                    file=sys.stderr,
                )
                skipped_count += 1
                continue

            # Check require-phase gate
            if not should_include_project(name, completions, require_phase):
                print(
                    f"Excluding {name}: required phase '{require_phase}' not met",
                    file=sys.stderr,
                )
                excluded_count += 1
                continue

            missions.append(mission)
        except Exception as e:
            print(f"Error processing config {config_path}: {e}", file=sys.stderr)
            raise

    print(
        f"Processing {len(missions)} projects, "
        f"skipped {skipped_count} as already complete, "
        f"excluded {excluded_count} for unmet phase requirement",
        file=sys.stderr,
    )

    if output_file_path:
        # Write full configs to file as dict keyed by project_name
        # This avoids Argo's parameter size limit (default 256KB) for large batch runs
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

        configs_dict = {m["project_name"]: m for m in missions}
        with open(output_file_path, "w") as f:
            json.dump(configs_dict, f)

        print(
            f"Wrote {len(missions)} project configs to {output_file_path}",
            file=sys.stderr,
        )

    # Always output minimal references to stdout (just project_name)
    refs = [{"project_name": m["project_name"]} for m in missions]
    json.dump(refs, sys.stdout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Preprocess config files for Argo workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Metashape workflow
    python determine_datasets.py /data/config_list.txt /data/output/configs.json \\
        --completion-log /data/completion-log-default.jsonl \\
        --skip-if-complete metashape

    # Postprocessing workflow (no output file, require metashape phase)
    python determine_datasets.py /data/config_list.txt \\
        --completion-log /data/completion-log-default.jsonl \\
        --require-phase metashape \\
        --skip-if-complete postprocess

    # No skip, no output file
    python determine_datasets.py /data/config_list.txt
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
        "written to this file. Stdout always contains minimal refs.",
    )
    parser.add_argument(
        "--completion-log",
        help="Path to completion log file (JSON Lines format)",
    )
    parser.add_argument(
        "--skip-if-complete",
        choices=["none", "metashape", "postprocess"],
        default="none",
        help="Skip projects based on completion status: "
        "none (default), metashape, postprocess",
    )
    parser.add_argument(
        "--require-phase",
        choices=["metashape", "postprocess"],
        default=None,
        help="Only include projects that have completed the given phase",
    )

    args = parser.parse_args()

    main(
        config_list_path=args.config_list_path,
        output_file_path=args.output_file_path,
        completion_log=args.completion_log,
        skip_if_complete=args.skip_if_complete,
        require_phase=args.require_phase,
    )

#!/usr/bin/env python3
"""
Preprocessing script for step-based photogrammetry workflow.

Reads mission config files and generates mission parameters with enabled flags.
This determines which processing steps are enabled and whether GPU or CPU nodes
should be used for GPU-capable steps.

Usage:
    python determine_datasets.py <config_list_path>

Output:
    JSON array of mission parameters to stdout
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

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

    # Create DNS-1123 compliant name for Kubernetes task names (Argo UI display only)
    # The original project_name is preserved for file paths and processing
    project_name_sanitized = sanitize_dns1123(project_name)

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


def main(config_list_path: str) -> None:
    """
    Main entry point for preprocessing script.

    Args:
        config_list_path: Absolute path to text file listing config files (each line should be an absolute path)
    """
    missions: List[Dict[str, Any]] = []

    # Read config list file (expecting absolute path)
    with open(config_list_path, "r") as f:
        for line in f:
            config_path = line.strip()
            if not config_path:
                continue

            try:
                mission = process_config_file(config_path)
                missions.append(mission)
            except Exception as e:
                print(f"Error processing config {config_path}: {e}", file=sys.stderr)
                raise

    # Output as JSON list to stdout
    json.dump(missions, sys.stdout)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: determine_datasets.py <config_list_path>", file=sys.stderr)
        print(
            "  config_list_path: Absolute path to text file listing config files (each line should be an absolute path)",
            file=sys.stderr,
        )
        sys.exit(1)

    config_list_path = sys.argv[1]
    main(config_list_path)

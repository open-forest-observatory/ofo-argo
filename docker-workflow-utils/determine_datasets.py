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
        return val.lower() in ('true', '1', 'yes')
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
    sanitized = re.sub(r'[^a-z0-9.-]', '-', sanitized)

    # Collapse multiple consecutive hyphens into one
    sanitized = re.sub(r'-+', '-', sanitized)

    # Remove leading/trailing hyphens or dots
    sanitized = sanitized.strip('-.')

    # Truncate to max 253 characters
    sanitized = sanitized[:253]

    # Ensure we didn't create a trailing hyphen/dot after truncation
    sanitized = sanitized.rstrip('-.')

    return sanitized


def process_config_file(config_path: str, data_root: str = "/data") -> Dict[str, Any]:
    """
    Process a single mission config file and extract mission parameters.

    Args:
        config_path: Path to config file (relative to data_root)
        data_root: Root directory where data is mounted (default: /data)

    Returns:
        Dictionary of mission parameters with enabled flags

    Raises:
        ValueError: If config file uses Phase 1 format (not compatible with step-based workflow)
    """
    # Load config file
    full_config_path = Path(data_root) / config_path
    with open(full_config_path, "r") as cf:
        config = yaml.safe_load(cf)

    # Validate that this is a Phase 2 config
    # Phase 1 configs have 'alignPhotos' section, Phase 2 has separate 'match_photos' and 'align_cameras'
    if 'alignPhotos' in config:
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
    project_name = get_nested(config, ['project', 'project_name'])
    if not project_name:
        # Fallback: extract from config file path
        base_with_ext = os.path.basename(config_path)
        project_name = os.path.splitext(base_with_ext)[0]

    # Create DNS-1123 compliant name for Kubernetes task names (Argo UI display only)
    # The original project_name is preserved for file paths and processing
    project_name_sanitized = sanitize_dns1123(project_name)

    # Apply translation logic from implementation plan
    mission = {
        "project_name": project_name,
        "project_name_sanitized": project_name_sanitized,
        "config": config_path,

        # Step enabled flags (setup and finalize always run, so not included)
        # Use actual Python booleans (not strings) so they serialize to JSON true/false
        "match_photos_enabled": str_to_bool(get_nested(config, ['match_photos', 'enabled'], False)),
        "match_photos_use_gpu": str_to_bool(get_nested(config, ['match_photos', 'gpu_enabled'], True)),

        "align_cameras_enabled": str_to_bool(get_nested(config, ['align_cameras', 'enabled'], False)),

        "build_depth_maps_enabled": str_to_bool(get_nested(config, ['build_depth_maps', 'enabled'], False)),

        "build_point_cloud_enabled": str_to_bool(get_nested(config, ['build_point_cloud', 'enabled'], False)),

        "build_mesh_enabled": str_to_bool(get_nested(config, ['build_mesh', 'enabled'], False)),
        "build_mesh_use_gpu": str_to_bool(get_nested(config, ['build_mesh', 'gpu_enabled'], True)),

        # build_dem_orthomosaic runs if either DEM or orthomosaic is enabled
        "build_dem_orthomosaic_enabled": (
            str_to_bool(get_nested(config, ['build_dem', 'enabled'], False)) or
            str_to_bool(get_nested(config, ['build_orthomosaic', 'enabled'], False))
        ),

        # Secondary photo processing runs if photo_path_secondary is non-empty
        "match_photos_secondary_enabled": bool(get_nested(config, ['project', 'photo_path_secondary'], "")),
        "match_photos_secondary_use_gpu": str_to_bool(get_nested(config, ['match_photos', 'gpu_enabled'], True)),

        "align_cameras_secondary_enabled": bool(get_nested(config, ['project', 'photo_path_secondary'], "")),
    }

    return mission


def main(config_list_path: str, data_root: str = "/data") -> None:
    """
    Main entry point for preprocessing script.

    Args:
        config_list_path: Path to text file listing config files (relative to data_root)
        data_root: Root directory where data is mounted (default: /data)
    """
    missions: List[Dict[str, Any]] = []

    # Read config list file
    full_list_path = Path(data_root) / config_list_path
    with open(full_list_path, "r") as f:
        for line in f:
            config_path = line.strip()
            if not config_path:
                continue

            try:
                mission = process_config_file(config_path, data_root)
                missions.append(mission)
            except Exception as e:
                print(f"Error processing config {config_path}: {e}", file=sys.stderr)
                raise

    # Output as JSON list to stdout
    json.dump(missions, sys.stdout)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: determine_datasets.py <config_list_path>", file=sys.stderr)
        print("  config_list_path: Path to text file listing config files (relative to /data)", file=sys.stderr)
        sys.exit(1)

    config_list_path = sys.argv[1]
    main(config_list_path)

#!/usr/bin/env python3
"""
Transform config file by replacing __DOWNLOADED__ prefix with actual download path.

This script is used when imagery is downloaded from S3 at runtime. It replaces
the __DOWNLOADED__ placeholder in photo_path entries with the actual path where
imagery was downloaded.

Usage:
    python transform_config.py

Environment Variables:
    CONFIG_FILE: Path to the original config file
    OUTPUT_CONFIG_FILE: Path to write the transformed config (e.g., '{TEMP_WORKING_DIR}/{workflow_name}/configs/{iteration_id}-transformed.yml')
    DOWNLOADED_IMAGERY_PATH: Actual path to downloaded imagery directory (e.g., '{TEMP_WORKING_DIR}/{workflow_name}/{iteration_id}/photogrammetry/downloaded-raw-imagery')

Output:
    Writes transformed config to OUTPUT_CONFIG_FILE.
    Exits with non-zero status on failure.

Validation:
    - Fails if __DOWNLOADED__ prefix is used but DOWNLOADED_IMAGERY_PATH is not set
    - Fails if this script is called but no __DOWNLOADED__ paths found in photo_path
      (indicates configuration mismatch - downloads specified but paths not using them)
"""

import os
import sys
from typing import Any, Dict, List, Union

import yaml


# Placeholder prefix that users put in their config to reference downloaded imagery
DOWNLOAD_PREFIX = "__DOWNLOADED__"


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load a YAML config file.

    Args:
        config_path: Path to the config file

    Returns:
        Parsed config dictionary

    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If config file is invalid YAML
    """
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def save_config(config: Dict[str, Any], output_path: str) -> None:
    """
    Save a config dictionary to a YAML file.

    Args:
        config: Config dictionary to save
        output_path: Path to write the config file
    """
    # Ensure output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(output_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def normalize_photo_path(photo_path: Union[str, List[str], None]) -> List[str]:
    """
    Normalize photo_path to a list of strings.

    Args:
        photo_path: Either a single path string, list of paths, or None

    Returns:
        List of path strings (empty list if None)
    """
    if photo_path is None:
        return []
    if isinstance(photo_path, str):
        return [photo_path]
    if isinstance(photo_path, list):
        return photo_path
    # Fallback for unexpected types
    return [str(photo_path)]


def transform_path(path: str, download_path: str) -> str:
    """
    Transform a single path by replacing __DOWNLOADED__ prefix.

    Args:
        path: Original path (may or may not have __DOWNLOADED__ prefix)
        download_path: Actual path to downloaded imagery

    Returns:
        Transformed path with __DOWNLOADED__ replaced, or original path if no prefix
    """
    if path.startswith(DOWNLOAD_PREFIX):
        # Replace prefix with actual download path
        # Handle both "__DOWNLOADED__/subpath" and "__DOWNLOADED__" alone
        suffix = path[len(DOWNLOAD_PREFIX):]
        if suffix.startswith("/"):
            suffix = suffix[1:]  # Remove leading slash for clean join
        if suffix:
            return os.path.join(download_path, suffix)
        else:
            return download_path
    return path


def has_download_prefix(paths: List[str]) -> bool:
    """
    Check if any path in the list uses the __DOWNLOADED__ prefix.

    Args:
        paths: List of paths to check

    Returns:
        True if any path starts with __DOWNLOADED__
    """
    return any(path.startswith(DOWNLOAD_PREFIX) for path in paths)


def transform_config(config: Dict[str, Any], download_path: str) -> Dict[str, Any]:
    """
    Transform config by replacing __DOWNLOADED__ prefix in photo_path entries.

    Args:
        config: Original config dictionary
        download_path: Actual path to downloaded imagery

    Returns:
        Transformed config dictionary (original is not modified)
    """
    # Deep copy to avoid modifying original
    import copy
    transformed = copy.deepcopy(config)

    # Get project section
    project = transformed.get("project", {})

    # Transform photo_path
    photo_path = project.get("photo_path")
    if photo_path is not None:
        paths = normalize_photo_path(photo_path)
        transformed_paths = [transform_path(p, download_path) for p in paths]

        # Preserve original format (string vs list)
        if isinstance(photo_path, str):
            project["photo_path"] = transformed_paths[0] if transformed_paths else ""
        else:
            project["photo_path"] = transformed_paths

    # Also transform photo_path_secondary if it exists and uses the prefix
    photo_path_secondary = project.get("photo_path_secondary")
    if photo_path_secondary is not None:
        paths = normalize_photo_path(photo_path_secondary)
        if has_download_prefix(paths):
            transformed_paths = [transform_path(p, download_path) for p in paths]

            # Preserve original format
            if isinstance(photo_path_secondary, str):
                project["photo_path_secondary"] = transformed_paths[0] if transformed_paths else ""
            else:
                project["photo_path_secondary"] = transformed_paths

    transformed["project"] = project
    return transformed


def main() -> None:
    """Main entry point for config transform script."""
    print("=" * 60)
    print("Transforming config file")
    print("=" * 60)

    # Get environment variables
    config_file = os.environ.get("CONFIG_FILE", "")
    output_config_file = os.environ.get("OUTPUT_CONFIG_FILE", "")
    download_path = os.environ.get("DOWNLOADED_IMAGERY_PATH", "")

    # Validate required environment variables
    if not config_file:
        print("ERROR: CONFIG_FILE environment variable is required")
        sys.exit(1)

    if not output_config_file:
        print("ERROR: OUTPUT_CONFIG_FILE environment variable is required")
        sys.exit(1)

    if not download_path:
        print("ERROR: DOWNLOADED_IMAGERY_PATH environment variable is required")
        sys.exit(1)

    print(f"Input config: {config_file}")
    print(f"Output config: {output_config_file}")
    print(f"Download path: {download_path}")

    # Load config
    try:
        config = load_config(config_file)
    except FileNotFoundError:
        print(f"ERROR: Config file not found: {config_file}")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"ERROR: Invalid YAML in config file: {e}")
        sys.exit(1)

    # Get photo paths for validation
    project = config.get("project", {})
    photo_path = project.get("photo_path")
    photo_path_secondary = project.get("photo_path_secondary")

    # Normalize paths for checking
    all_paths = normalize_photo_path(photo_path) + normalize_photo_path(photo_path_secondary)

    # Validation: This script should only be called when downloads are configured,
    # so at least one path should use __DOWNLOADED__ prefix
    if not has_download_prefix(all_paths):
        print("ERROR: Configuration mismatch detected")
        print("  This script was called (implying S3 imagery downloads are configured),")
        print("  but no photo_path entries use the __DOWNLOADED__ prefix.")
        print("  Either:")
        print("    1. Add __DOWNLOADED__ prefix to photo_path entries that should use downloaded imagery")
        print("    2. Remove s3_imagery_zip_download from argo config if not using downloaded imagery")
        print(f"  Current photo_path: {photo_path}")
        if photo_path_secondary:
            print(f"  Current photo_path_secondary: {photo_path_secondary}")
        sys.exit(1)

    # Transform config
    transformed_config = transform_config(config, download_path)

    # Save transformed config
    try:
        save_config(transformed_config, output_config_file)
        print(f"Transformed config saved to: {output_config_file}")
    except Exception as e:
        print(f"ERROR: Failed to save transformed config: {e}")
        sys.exit(1)

    # Log the transformation for debugging
    transformed_project = transformed_config.get("project", {})
    transformed_photo_path = transformed_project.get("photo_path")
    print("\nTransformation complete:")
    print(f"  Original photo_path: {photo_path}")
    print(f"  Transformed photo_path: {transformed_photo_path}")

    if photo_path_secondary and has_download_prefix(normalize_photo_path(photo_path_secondary)):
        transformed_secondary = transformed_project.get("photo_path_secondary")
        print(f"  Original photo_path_secondary: {photo_path_secondary}")
        print(f"  Transformed photo_path_secondary: {transformed_secondary}")

    print("\n" + "=" * 60)
    print("SUCCESS: Config transformation complete")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()

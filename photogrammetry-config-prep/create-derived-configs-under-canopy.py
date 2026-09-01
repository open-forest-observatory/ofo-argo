#!/usr/bin/env python3
"""
Generate derived Metashape configuration files from a base config and drone mission metadata.

For each mission in the input GeoPackage, creates a YAML config file that overrides
the base config with mission-specific values (photo paths, CRS, S3 download path).

Dependencies: geopandas, pyyaml
"""

import argparse
import copy
from pathlib import Path
import yaml

import pandas as pd

# =============================================================================
# Configuration Defaults (used when no values are provided via command-line arguments)
# =============================================================================

# Path to the GeoPackage containing drone mission polygons and metadata
MISSIONS_LIST_PATH_DEFAULT = "/home/derek/repos/ofo-argo/photogrammetry-config-prep/config-prep-runs/run-03/input/ofo-all-missions-metadata-curated.gpkg"

# Path to the base automate-metashape configuration YAML
BASE_CONFIG_PATH_DEFAULT = "/home/derek/repos/ofo-argo/photogrammetry-config-prep/config-prep-runs/run-03/input/config-base.yml"

# Output directory for derived config files
OUTPUT_DIR_DEFAULT = "/home/derek/repos/ofo-argo/photogrammetry-config-prep/config-prep-runs/run-03/derived-configs"

# S3 path prefix for drone mission imagery downloads.
# The full path will be: {S3_DRONE_MISSIONS_PATH}/{mission_id}/images/{mission_id}_images.zip
# This assumes the standard OFO directory structure where each mission has an 'images' subfolder
# containing a zip file named {mission_id}_images.zip
# Note: No remote prefix needed - just bucket/path format. The S3 credentials come from the
# cluster's s3-credentials Kubernetes secret.
S3_DRONE_MISSIONS_PATH_DEFAULT = "ofo-public/gopro"


# =============================================================================
# Helper Functions
# =============================================================================


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "missions_list_path",
        type=Path,
        default=Path(MISSIONS_LIST_PATH_DEFAULT),
        help="Path to the csv file with mission_id and crs columns.",
    )
    parser.add_argument(
        "base_config_path",
        type=Path,
        default=Path(BASE_CONFIG_PATH_DEFAULT),
        help="Path to the base automate-metashape configuration YAML.",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        default=Path(OUTPUT_DIR_DEFAULT),
        help="Output directory for derived config files.",
    )
    parser.add_argument(
        "--s3-drone-missions-path",
        type=str,
        default=S3_DRONE_MISSIONS_PATH_DEFAULT,
        help="S3 path prefix for drone mission imagery downloads.",
    )

    return parser.parse_args()


def create_derived_config_dict(
    base_config: dict,
    photo_paths: list[str],
    project_crs: str,
    s3_download_path: str,
) -> dict:
    """
    Create a derived config dict by applying mission-specific overrides to the base config dict.

    Args:
        base_config: The base configuration dictionary
        mission_id: Mission identifier
        photo_paths: List of photo directory paths
        project_crs: UTM EPSG code string
        s3_download_path: S3 rclone path for imagery download

    Returns:
        New config dictionary with overrides applied
    """
    config = copy.deepcopy(base_config)
    config["project"]["photo_path"] = photo_paths
    config["project"]["project_crs"] = project_crs
    config["argo"]["s3_imagery_zip_download"] = s3_download_path
    return config


# =============================================================================
# Main Script
# =============================================================================


def main(
    missions_list_path: Path,
    base_config_path: Path,
    output_dir: Path,
    s3_drone_missions_path: str,
):
    missions_df = pd.read_csv(missions_list_path, skipinitialspace=True)

    # Load base configuration
    print(f"Loading base config from: {base_config_path}")
    with open(base_config_path) as f:
        base_config = yaml.safe_load(f)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Process each mission
    config_filenames = []

    for _, row in missions_df.iterrows():
        mission_id = f"{int(row['mission_id']):06}"
        project_crs = str(row["crs"])

        # Generate S3 download path
        s3_download_path = (
            f"{s3_drone_missions_path}/{mission_id}/images/{mission_id}_images.zip"
        )

        photo_paths = [f"__DOWNLOADED__/{mission_id}_images"]

        # Create derived config
        derived_config = create_derived_config_dict(
            base_config,
            photo_paths,
            project_crs,
            s3_download_path,
        )

        # Write to output file
        output_filename = f"{mission_id}.yml"
        output_path = output_dir / output_filename
        with open(output_path, "w") as f:
            yaml.dump(derived_config, f, default_flow_style=False, sort_keys=False)

        config_filenames.append(output_filename)

    # Write config list file with priority and standard sections
    config_list_path = output_dir / "config-list.txt"
    with open(config_list_path, "w") as f:
        for filename in config_filenames:
            f.write(f"{filename}\n")

    print(
        f"Successfully created {len(config_filenames)} derived config files in: {output_dir}"
    )
    print(f"Config list written to: {config_list_path}")


if __name__ == "__main__":
    args = parse_args()

    main(**args.__dict__)

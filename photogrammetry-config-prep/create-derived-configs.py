#!/usr/bin/env python3
"""
Generate derived Metashape configuration files from a base config and drone mission metadata.

For each mission in the input GeoPackage, creates a YAML config file that overrides
the base config with mission-specific values (photo paths, CRS, S3 download path).

Dependencies: geopandas, pyyaml
"""

import copy
import math
from pathlib import Path

import geopandas as gpd
import yaml


# =============================================================================
# Configuration Constants
# =============================================================================

# Path to the GeoPackage containing drone mission polygons and metadata
MISSIONS_GPKG_PATH = "/home/derek/repos/ofo-argo/photogrammetry-config-prep/config-prep-runs/run-03/input/ofo-all-missions-metadata-curated.gpkg"

# Path to the base automate-metashape configuration YAML
BASE_CONFIG_PATH = "/home/derek/repos/ofo-argo/photogrammetry-config-prep/config-prep-runs/run-03/input/config-base.yml"

# Output directory for derived config files
OUTPUT_DIR = "/home/derek/repos/ofo-argo/photogrammetry-config-prep/config-prep-runs/run-03/derived-configs"

# S3 path prefix for drone mission imagery downloads.
# The full path will be: {S3_DRONE_MISSIONS_PATH}/{mission_id}/images/{mission_id}_images.zip
# This assumes the standard OFO directory structure where each mission has an 'images' subfolder
# containing a zip file named {mission_id}_images.zip
# Note: No remote prefix needed - just bucket/path format. The S3 credentials come from the
# cluster's s3-credentials Kubernetes secret.
S3_DRONE_MISSIONS_PATH = "ofo-public/drone/missions_03"


# =============================================================================
# Helper Functions
# =============================================================================

def compute_utm_epsg(longitude: float, latitude: float) -> str:
    """
    Compute the UTM EPSG code for a given longitude/latitude.

    Args:
        longitude: Longitude in degrees (-180 to 180)
        latitude: Latitude in degrees (used to determine hemisphere)

    Returns:
        EPSG code string in format "EPSG::32XXX" (northern) or "EPSG::327XX" (southern)
    """
    zone = int(math.floor((longitude + 180) / 6)) + 1
    if latitude >= 0:
        epsg_code = 32600 + zone  # Northern hemisphere
    else:
        epsg_code = 32700 + zone  # Southern hemisphere
    return f"EPSG::{epsg_code}"


def parse_sub_mission_ids(sub_mission_ids_str: str, mission_id: str) -> list[str]:
    """
    Parse comma-separated sub-mission IDs and generate photo paths.

    Args:
        sub_mission_ids_str: Comma-separated string like "000002-01, 000002-02"
        mission_id: The parent mission ID (e.g., "000002")

    Returns:
        List of photo paths like ["__DOWNLOADED__/000002_images/000002-01", ...]
    """
    sub_ids = [s.strip() for s in sub_mission_ids_str.split(",")]
    return [f"__DOWNLOADED__/{mission_id}_images/{sub_id}" for sub_id in sub_ids]


def create_derived_config(
    base_config: dict,
    mission_id: str,
    photo_paths: list[str],
    project_crs: str,
    s3_download_path: str,
) -> dict:
    """
    Create a derived config by applying mission-specific overrides to the base config.

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

def main():
    gpkg_path = Path(MISSIONS_GPKG_PATH)
    base_config_path = Path(BASE_CONFIG_PATH)
    output_dir = Path(OUTPUT_DIR)

    # Load mission metadata
    print(f"Loading missions from: {gpkg_path}")
    missions_gdf = gpd.read_file(gpkg_path)
    print(f"Found {len(missions_gdf)} missions")

    # Load base configuration
    print(f"Loading base config from: {base_config_path}")
    with open(base_config_path) as f:
        base_config = yaml.safe_load(f)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Process each mission
    success_count = 0
    config_filenames = []
    for idx, row in missions_gdf.iterrows():
        mission_id = row["mission_id"]
        sub_mission_ids_str = row["sub_mission_ids"]

        # Validate sub_mission_ids
        if not sub_mission_ids_str or (isinstance(sub_mission_ids_str, float) and math.isnan(sub_mission_ids_str)):
            raise ValueError(f"Mission {mission_id} has empty or null sub_mission_ids")

        # Compute centroid for UTM zone calculation
        centroid = row.geometry.centroid
        project_crs = compute_utm_epsg(centroid.x, centroid.y)

        # Generate photo paths from sub-mission IDs
        photo_paths = parse_sub_mission_ids(str(sub_mission_ids_str), str(mission_id))

        # Generate S3 download path
        s3_download_path = f"{S3_DRONE_MISSIONS_PATH}/{mission_id}/images/{mission_id}_images.zip"

        # Create derived config
        derived_config = create_derived_config(
            base_config,
            mission_id,
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
        success_count += 1

    # Write config list file
    config_list_path = output_dir / "config-list.txt"
    with open(config_list_path, "w") as f:
        for filename in config_filenames:
            f.write(f"{filename}\n")
        f.write("\n")

    print(f"Successfully created {success_count} derived config files in: {output_dir}")
    print(f"Config list written to: {config_list_path}")


if __name__ == "__main__":
    main()

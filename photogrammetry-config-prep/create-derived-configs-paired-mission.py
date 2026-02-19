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

# Path to the GeoPackage containing which images were selected
COMPOSITE_IMAGES_GPKG_PATH = Path(
    "/ofo-share/repos/david/ofo-argo/scratch/paired-photogrammetry/selected-composites-images.gpkg"
)
MISSION_METADATA_GPKG_PATH = Path(
    "/ofo-share/repos/david/ofo-argo/scratch/paired-photogrammetry/metadata-missions-compiled.gpkg"
)

# Path to the base automate-metashape configuration YAML
BASE_CONFIG_PATH = Path(
    "/ofo-share/repos/david/ofo-argo/photogrammetry-config-prep/config-prep-runs/run-03/input/config-base.yml"
)

# Output directory for derived config files
OUTPUT_DIR_CONFIGS = Path(
    "/ofo-share/repos/david/ofo-argo/photogrammetry-config-prep/config-prep-runs/run-03/derived-configs"
)
OUTPUT_DIR_SUBSETS = Path(
    "/ofo-share/repos/david/ofo-argo/photogrammetry-config-prep/config-prep-runs/run-03/derived-subsets"
)
# Once everything is mounted in Argo, where will the subset files be
# TODO, figure out a way to make this more flexible
SUBSETS_FOLDER_IN_ARGO = "/data/argo-input/david-photogrammetry-0218/subsets"

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
    altitude_offset: float,
    lower_offset_folders: list[str],
    upper_offset_folders: list[str],
    images_subset_file: str,
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

    # Altitude adjustment parameters
    config["add_photos"]["apply_paired_altitude_offset"] = True
    config["add_photos"]["paired_altitude_offset"] = altitude_offset
    config["add_photos"]["lower_offset_folders"] = lower_offset_folders
    config["add_photos"]["upper_offset_folders"] = upper_offset_folders

    # Argo
    config["argo"]["s3_imagery_zip_download"] = s3_download_path
    config["argo"]["images_subset_file"] = images_subset_file

    return config


# =============================================================================
# Main Script
# =============================================================================


def main():
    images_metadata_gdf = gpd.read_file(COMPOSITE_IMAGES_GPKG_PATH)
    mission_metadata_gdf = gpd.read_file(MISSION_METADATA_GPKG_PATH)

    images_by_pair = images_metadata_gdf.groupby("composite_id")

    # Load base configuration
    print(f"Loading base config from: {BASE_CONFIG_PATH}")
    with open(BASE_CONFIG_PATH) as f:
        base_config = yaml.safe_load(f)

    # Create output directories
    OUTPUT_DIR_CONFIGS.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR_SUBSETS.mkdir(parents=True, exist_ok=True)

    # Process each mission
    success_count = 0
    standard_config_filenames = []

    for paired_missions_id, included_images in images_by_pair:
        # TODO determine if this needs to be a nanmean
        mean_altitudes = (
            included_images[["altitude_agl", "mission_type"]]
            .groupby("mission_type")
            .mean()
        )

        altitude_difference = float(
            mean_altitudes.loc["hn", "altitude_agl"]
            - mean_altitudes.loc["lo", "altitude_agl"]
        )

        # The paired_mission_id is just the two mission IDs concatenated
        mission_id_hn, mission_id_lo = paired_missions_id.split("_")

        # TODO either load these from the metadata-missions-compiled file or add them to the
        # composites metadata.
        sub_mission_ids_lo = mission_metadata_gdf.query("mission_id == @mission_id_lo")[
            "sub_mission_ids"
        ].values[0]
        sub_mission_ids_hn = mission_metadata_gdf.query("mission_id == @mission_id_hn")[
            "sub_mission_ids"
        ].values[0]

        # Compute centroid for UTM zone calculation
        centroid = included_images.dissolve().centroid
        project_crs = compute_utm_epsg(centroid.x.values[0], centroid.y.values[0])

        # Generate photo paths from sub-mission IDs
        # This needs to be updated to handle the fact that this is paired. So we'll compute one
        # set of LO and HN photo paths and then this will be the concatanation of them.
        photo_paths_lo = parse_sub_mission_ids(
            str(sub_mission_ids_lo), str(mission_id_lo)
        )
        photo_paths_hn = parse_sub_mission_ids(
            str(sub_mission_ids_hn), str(mission_id_hn)
        )
        photo_paths = photo_paths_lo + photo_paths_hn

        # Generate S3 download path
        s3_download_paths = [
            f"{S3_DRONE_MISSIONS_PATH}/{mission_id}/images/{mission_id}_images.zip"
            for mission_id in [mission_id_lo, mission_id_hn]
        ]

        # Get image paths
        images_subset = included_images["image_id"].tolist()

        # TODO figure out this pathing
        images_subsets_file = f"{SUBSETS_FOLDER_IN_ARGO}/{paired_missions_id}.txt"

        # Create derived config
        derived_config = create_derived_config(
            base_config,
            paired_missions_id,  # unused
            photo_paths,
            project_crs,
            s3_download_paths,
            altitude_offset=altitude_difference,
            lower_offset_folders=photo_paths_lo,
            upper_offset_folders=photo_paths_hn,
            images_subset_file=images_subsets_file,
        )

        # Write to output file
        output_config_filename = f"{paired_missions_id}.yml"
        output_config_path = OUTPUT_DIR_CONFIGS / output_config_filename
        with open(output_config_path, "w") as f:
            yaml.dump(derived_config, f, default_flow_style=False, sort_keys=False)

        standard_config_filenames.append(output_config_filename)

        # Output subset
        output_subset_path = OUTPUT_DIR_SUBSETS / f"{paired_missions_id}.txt"
        with open(output_subset_path, "w") as f:
            for image_id in images_subset:
                f.write(f"{image_id}\n")

        success_count += 1

    # Write config list file with priority and standard sections
    config_list_path = OUTPUT_DIR_CONFIGS / "config-list.txt"
    with open(config_list_path, "w") as f:
        f.write("# Standard-priority missions\n")
        for filename in standard_config_filenames:
            f.write(f"{filename}\n")
        f.write("\n")

    print(
        f"Successfully created {success_count} derived config files in: {OUTPUT_DIR_CONFIGS}"
    )
    print(f"  - Standard: {len(standard_config_filenames)}")
    print(f"Config list written to: {config_list_path}")


if __name__ == "__main__":
    main()

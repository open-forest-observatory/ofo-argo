#!/usr/bin/env python3
"""
Generate derived Metashape configuration files from a base config and drone mission metadata from
two paired drone mssions.

For each pair of mission in the input GeoPackage, creates a YAML config file that overrides
the base config with mission-specific values. These include attributes which are the same as the
single mission case (photo paths, CRS, S3 download path) as well as attributes which correct for
variation in recorded altitudes between the two missions in the pair (apply_paired_altitude_offset,
paired_altitude_offset, lower_offset_folders, upper_offset_folders). This script also creates a file
listing all the images which should be used for this photogrammetry run, and uploads this file to S3.
The path of this file is included as the "s3_imagery_subset_path" attribute.

Dependencies: geopandas, pyyaml

Note that the following credentials must be configured to access S3:
* S3_PROVIDER: S3 provider for rclone (e.g., 'Ceph', 'AWS')
* S3_ENDPOINT: S3 endpoint URL
* S3_ACCESS_KEY: S3 access key ID
* S3_SECRET_KEY: S3 secret access key
"""

import os
import copy
import math
from pathlib import Path
import tempfile
from typing import List
import subprocess

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
# The path, starting at the bucket, for the subsets file that will be referenced in the config
S3_COMPOSITE_MISSIONS_PATH = "ofo-public/drone/mission-composites_01"

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
def get_s3_flags() -> List[str]:
    """Build common S3 authentication flags for rclone commands."""
    return [
        "--s3-provider",
        os.environ.get("S3_PROVIDER", ""),
        "--s3-endpoint",
        os.environ.get("S3_ENDPOINT", ""),
        "--s3-access-key-id",
        os.environ.get("S3_ACCESS_KEY", ""),
        "--s3-secret-access-key",
        os.environ.get("S3_SECRET_KEY", ""),
    ]


def upload_subset_file(image_ids: list[str], s3_path: str) -> None:
    """
    Write a list of image IDs to a temporary file and upload it to S3.

    Args:
        image_ids: List of image IDs to include in the subset file
        s3_path: S3 destination path (format: 'bucket/path/to/file.txt')

    Raises:
        subprocess.CalledProcessError: If upload fails
    """
    # Use rclone's on-the-fly backend syntax (:s3:) which configures the
    # S3 backend using command-line flags rather than a config file.
    # This avoids needing a pre-configured remote like "js2s3:".
    rclone_url = f":s3:{s3_path}"

    with tempfile.NamedTemporaryFile(mode="w") as tmp_subset_file:
        for image_id in image_ids:
            tmp_subset_file.write(f"{image_id}\n")
        tmp_subset_file.flush()

        print(f"Uploading: {tmp_subset_file.name}")
        print(f"  -> {s3_path}")

        # Note that this will create containing folders if needed
        cmd = [
            "rclone",
            "copyto",
            tmp_subset_file.name,
            rclone_url,
            "--progress",
            "--transfers",
            "1",
            "--checkers",
            "1",
            "--retries",
            "5",
            "--retries-sleep",
            "15s",
            "--stats",
            "30s",
        ] + get_s3_flags()
        subprocess.run(cmd, check=True)


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
    s3_imagery_subset_path: str,
) -> dict:
    """
    Create a derived config by applying mission-specific overrides to the base config.

    Args:
        base_config: The base configuration dictionary
        mission_id: Mission identifier
        photo_paths: List of photo directory paths
        project_crs: UTM EPSG code string
        s3_download_path: S3 rclone path for imagery download
        altitude_offset: The difference in meters requested between the upper and lower image sets
        lower_offset_folders: Include the images in this list of folders in the lower offset group
        upper_offset_folders: Include the images in this list of folders in the upper offset group
        s3_imagery_subset_path: Path to a file on S3 which contains a subset of images to include

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
    config["argo"]["s3_imagery_subset_path"] = s3_imagery_subset_path

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

    # Process each mission
    success_count = 0
    standard_config_filenames = []

    for paired_missions_id, included_images in images_by_pair:
        ## Subset file generation steps

        # The path on S3 where the file defining which images to use will be uploaded to
        s3_imagery_subset_path = f"{S3_COMPOSITE_MISSIONS_PATH}/{paired_missions_id}/{paired_missions_id}_images_subset.txt"

        # Get image IDs which are included
        images_subset = included_images["image_id"].tolist()

        # Create the subset file and upload to S3
        upload_subset_file(images_subset, s3_imagery_subset_path)

        ## Config file generation steps

        # Determine the mean altitude for the high and low mission sets. Note that Groupby.mean
        # works similarly to nanmean in that it excludes missing values. It is highly unlikely that
        # all values would be NaN, since that only occurs when all cameras for that gorup are not
        # aligned or do not have a valid DTM. In practice, ~1% are missing altitide.
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

        # Determine the sub-mission IDs
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
        # Compute independent LO and HN photo paths for use in the altitude offset step.
        photo_paths_lo = parse_sub_mission_ids(
            str(sub_mission_ids_lo), str(mission_id_lo)
        )
        photo_paths_hn = parse_sub_mission_ids(
            str(sub_mission_ids_hn), str(mission_id_hn)
        )
        # The total photo paths is just the concatenation of the LO and HN ones
        photo_paths = photo_paths_lo + photo_paths_hn

        # Generate S3 download path
        s3_download_paths = [
            f"{S3_DRONE_MISSIONS_PATH}/{mission_id}/images/{mission_id}_images.zip"
            for mission_id in [mission_id_lo, mission_id_hn]
        ]

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
            s3_imagery_subset_path=s3_imagery_subset_path,
        )

        # Write the config file
        output_config_filename = f"{paired_missions_id}.yml"
        output_config_path = OUTPUT_DIR_CONFIGS / output_config_filename
        with open(output_config_path, "w") as f:
            yaml.dump(derived_config, f, default_flow_style=False, sort_keys=False)

        standard_config_filenames.append(output_config_filename)

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

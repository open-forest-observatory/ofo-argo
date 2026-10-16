"""
Split the composite outputs of pair_missions.py into per-composite metadata folders
and upload each folder to S3.

Outputs (per composite, locally under OUTPUT_FOLDER and on S3 under
S3_COMPOSITE_MISSIONS_PATH):
  - {composite_id}/metadata-images/{composite_id}_image-metadata.gpkg
  - {composite_id}/metadata-mission/{composite_id}_mission-metadata.gpkg

Usage:
    # Edit the path constants below, then process and upload all composites:
    python upload_paired_metadata_by_project.py

    # Skip composites whose image and mission metadata files already exist on S3:
    python upload_paired_metadata_by_project.py --skip-existing

Requirements:
    - geopandas
    - rclone with a configured js2s3 remote (RCLONE_CONFIG_JS2S3_* env vars)
"""

import argparse
import subprocess
import sys
from pathlib import Path

import geopandas as gpd

IMAGERY_METADATA_FILE = (
    "/ofo-share/scratch/derek/tmp_pairing/selected-composites-images.gpkg"
)
BOUNDARY_METADATA_FILE = (
    "/ofo-share/scratch/derek/tmp_pairing/selected-composites-polygons.gpkg"
)
OUTPUT_FOLDER = "/ofo-share/scratch/derek/tmp_pairing/per-mission-metadata"

RCLONE_REMOTE = "js2s3"
S3_COMPOSITE_MISSIONS_PATH = "ofo-public/drone/mission-composites_01"


def rclone_copy(src, dst):
    """Run an rclone copy command."""
    cmd = ["rclone", "copy", src, dst, "--transfers", "8", "--checkers", "8"]
    print(f"  rclone copy {src} -> {dst}", file=sys.stderr)
    subprocess.run(cmd, check=True)


def list_existing_composites():
    """Return the composite IDs that already have both metadata files on S3."""
    remote = f"{RCLONE_REMOTE}:{S3_COMPOSITE_MISSIONS_PATH}"
    cmd = [
        "rclone",
        "lsf",
        remote,
        "--recursive",
        "--files-only",
        "--max-depth",
        "3",
        "--include",
        "*/metadata-images/*_image-metadata.gpkg",
        "--include",
        "*/metadata-mission/*_mission-metadata.gpkg",
    ]
    print(f"Listing existing composites in {remote}", file=sys.stderr)
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)

    # Paths look like {composite_id}/metadata-images/{composite_id}_image-metadata.gpkg
    found = {}
    for path in result.stdout.splitlines():
        composite_id, subfolder, _ = path.split("/")
        found.setdefault(composite_id, set()).add(subfolder)

    return {
        composite_id
        for composite_id, subfolders in found.items()
        if subfolders == {"metadata-images", "metadata-mission"}
    }


parser = argparse.ArgumentParser(
    description="Split composite metadata into per-composite folders and upload to S3."
)
parser.add_argument(
    "--skip-existing",
    action="store_true",
    help="Skip composites whose image and mission metadata files already exist on S3.",
)
args = parser.parse_args()

imagery_metadata = gpd.read_file(IMAGERY_METADATA_FILE)
boundary_metadata = gpd.read_file(BOUNDARY_METADATA_FILE)

existing_composites = list_existing_composites() if args.skip_existing else set()

# Iterate over the unique mission IDs
# Subset the images and boundaries for each mission
for composite_id in boundary_metadata["composite_id"].unique():

    if composite_id in existing_composites:
        print(f"Skipping composite {composite_id}: already exists on S3")
        continue

    mission_images = imagery_metadata[imagery_metadata["composite_id"] == composite_id]
    mission_boundaries = boundary_metadata[
        boundary_metadata["composite_id"] == composite_id
    ]

    # Save the subsetted images and boundaries to new GeoPackages
    output_images_file = Path(
        OUTPUT_FOLDER,
        composite_id,
        "metadata-images",
        f"{composite_id}_image-metadata.gpkg",
    )
    output_boundaries_file = Path(
        OUTPUT_FOLDER,
        composite_id,
        "metadata-mission",
        f"{composite_id}_mission-metadata.gpkg",
    )

    output_images_file.parent.mkdir(parents=True, exist_ok=True)
    output_boundaries_file.parent.mkdir(parents=True, exist_ok=True)

    mission_images.to_file(output_images_file, driver="GPKG")
    mission_boundaries.to_file(output_boundaries_file, driver="GPKG")

    print(
        f"Saved {len(mission_images)} images and {len(mission_boundaries)} boundaries for composite {composite_id}"
    )

    # Upload the composite's metadata folder to S3
    local_composite_dir = str(Path(OUTPUT_FOLDER, composite_id))
    remote_composite_path = (
        f"{RCLONE_REMOTE}:{S3_COMPOSITE_MISSIONS_PATH}/{composite_id}"
    )
    rclone_copy(local_composite_dir, remote_composite_path)

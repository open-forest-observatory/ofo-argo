import subprocess
import sys
from pathlib import Path

import geopandas as gpd

IMAGERY_METADATA_FILE = "/ofo-share/repos/david/ofo-argo/scratch/paired-photogrammetry/selected-composites-images.gpkg"
BOUNDARY_METADATA_FILE = "/ofo-share/repos/david/ofo-argo/scratch/paired-photogrammetry/selected-composites-polygons.gpkg"
OUTPUT_FOLDER = (
    "/ofo-share/repos/david/ofo-argo/scratch/paired-photogrammetry/per-mission-metadata"
)

RCLONE_REMOTE = "js2s3"
S3_COMPOSITE_MISSIONS_PATH = "ofo-public/drone/mission-composites_01"


def rclone_copy(src, dst):
    """Run an rclone copy command."""
    cmd = ["rclone", "copy", src, dst, "--transfers", "8", "--checkers", "8"]
    print(f"  rclone copy {src} -> {dst}", file=sys.stderr)
    subprocess.run(cmd, check=True)


imagery_metadata = gpd.read_file(IMAGERY_METADATA_FILE)
boundary_metadata = gpd.read_file(BOUNDARY_METADATA_FILE)

# Iterate over the unique mission IDs
# Subset the images and boundaries for each mission
for composite_id in boundary_metadata["composite_id"].unique():

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

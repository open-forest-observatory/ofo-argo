import geopandas as gpd
from pathlib import Path

IMAGERY_METADATA_FILE = "/ofo-share/repos/david/ofo-argo/scratch/paired-photogrammetry/selected-composites-images.gpkg"
BOUNDARY_METADATA_FILE = "/ofo-share/repos/david/ofo-argo/scratch/paired-photogrammetry/selected-composites-polygons.gpkg"
OUTPUT_FOLDER = (
    "/ofo-share/repos/david/ofo-argo/scratch/paired-photogrammetry/per-mission-metadata"
)

imagery_metadata = gpd.read_file(IMAGERY_METADATA_FILE)
boundary_metadata = gpd.read_file(BOUNDARY_METADATA_FILE)

# Iterate over the unique mission IDs
# Subset the images and boundaries for each mission
# * Extract the hn polygon for the boundary
for composite_id in boundary_metadata["composite_id"].unique():

    mission_images = imagery_metadata[imagery_metadata["composite_id"] == composite_id]
    mission_boundaries = boundary_metadata[
        boundary_metadata["composite_id"] == composite_id
    ]

    # Extract the hn polygon for the boundary
    hn_boundaries = mission_boundaries[mission_boundaries["mission_type"] == "hn"]

    # Save the subsetted images and boundaries to new GeoPackages
    # ofo-public/drone/missions_03/000001/metadata-images/000001_image-metadata.gpkg
    output_images_file = Path(
        OUTPUT_FOLDER,
        composite_id,
        "metadata-images",
        f"{composite_id}_image-metadata.gpkg",
    )
    # js2s3:ofo-public/drone/missions_03/000001/metadata-mission/000001_mission-metadata.gpkg
    output_boundaries_file = Path(
        OUTPUT_FOLDER,
        composite_id,
        "metadata-mission",
        f"{composite_id}_mission-metadata.gpkg",
    )

    if len(hn_boundaries) == 0 or len(mission_images) == 0:
        breakpoint()

    output_images_file.parent.mkdir(parents=True, exist_ok=True)
    output_boundaries_file.parent.mkdir(parents=True, exist_ok=True)

    mission_images.to_file(output_images_file, driver="GPKG")
    hn_boundaries.to_file(output_boundaries_file, driver="GPKG")

    print(
        f"Saved {len(mission_images)} images and {len(hn_boundaries)} boundaries for composite {composite_id}"
    )

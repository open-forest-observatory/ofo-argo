import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

import geopandas as gpd
import pandas as pd
import numpy as np
import rasterio as rio
import shapely


def make_4x4_transform(rotation_str: str, translation_str: str, scale_str: str = "1"):
    """Convenience function to make a 4x4 matrix from the string format used by Metashape

    Args:
        rotation_str (str): Row major with 9 entries
        translation_str (str): 3 entries
        scale_str (str, optional): single value. Defaults to "1".

    Returns:
        np.ndarray: (4, 4) A homogenous transform mapping from cam to world
    """
    rotation_np = np.fromstring(rotation_str, sep=" ")
    rotation_np = np.reshape(rotation_np, (3, 3))

    if not np.isclose(np.linalg.det(rotation_np), 1.0, atol=1e-8, rtol=0):
        raise ValueError(
            f"Inproper rotation matrix with determinant {np.linalg.det(rotation_np)}"
        )

    translation_np = np.fromstring(translation_str, sep=" ")
    scale = float(scale_str)
    transform = np.eye(4)
    transform[:3, :3] = rotation_np * scale
    transform[:3, 3] = translation_np
    return transform


def parse_transform_metashape(camera_file: str):
    """
    Return the transform from local coordinates to the earth centered, earth fixed frame, EPSG:4978.
    This is encoded in the XML file exported from Metashape.

    Args:
        camera_file (str): Path to the Metashape .xml export file.

    Returns:
        np.ndarray: (4, 4) Transform matrix from local coordinates to EPSG:4978.
    """
    tree = ET.parse(camera_file)
    root = tree.getroot()
    # first level
    components = root.find("chunk").find("components")

    assert len(components) == 1
    transform = components.find("component").find("transform")
    if transform is None:
        raise ValueError("Could not find transform")

    rotation = transform.find("rotation").text
    translation = transform.find("translation").text
    scale = transform.find("scale").text

    local_to_epgs_4978_transform = make_4x4_transform(rotation, translation, scale)

    return local_to_epgs_4978_transform


def get_camera_locations(camera_file):
    """
    Parse camera locations from a Metashape XML file into a GeoDataFrame.

    Args:
        camera_file (str): Path to the Metashape .xml export file.

    Returns:
        gpd.GeoDataFrame: GeoDataFrame with camera locations as Point geometries in EPSG:4978 (ECEF),
                          with a 'label' column for camera labels.
        List[str]: The labels of un-aligned cameras
    """
    # Load and parse the XML file
    tree = ET.parse(camera_file)
    cameras = tree.getroot().find("chunk").find("cameras")

    # Some cameras are stored in groups, so we need to flatten the structure
    ungrouped_cameras = []
    for cam_or_group in cameras:
        if cam_or_group.tag == "group":
            for cam in cam_or_group:
                ungrouped_cameras.append(cam)
        else:
            ungrouped_cameras.append(cam_or_group)

    # Collect camera-to-world transforms
    camera_locations_local = []
    camera_labels = []

    # Record the labels of cameras which did not align
    unaligned_cameras = []

    # Extract the locations of each camera from the 4x4 transform matrix representing both the
    # rotation and translation of the camera, in local chunk coordinates.
    for cam in ungrouped_cameras:
        transform = cam.find("transform")
        label = cam.get("label")
        # Skip un-aligned cameras
        if transform is None:
            unaligned_cameras.append(label)
            continue

        # Convert the string representation into a 4x4 numpy array and extract the translation column
        location = np.fromstring(transform.text, sep=" ").reshape(4, 4)[:, 3:]

        camera_labels.append(label)
        camera_locations_local.append(location)

    camera_locations_local = np.concatenate(camera_locations_local, axis=1)

    # Get the transform from chunk to EPSG:4978
    chunk_to_epsg4978 = parse_transform_metashape(camera_file)

    if chunk_to_epsg4978 is None:
        raise ValueError("Chunk is not georeferenced")

    # Convert the locations from the local chunk frame to EPSG:4978
    camera_locations_epsg4978 = chunk_to_epsg4978 @ camera_locations_local

    # Create GeoDataFrame with point geometries using the first three rows as x, y, z coordinates
    points = shapely.points(
        camera_locations_epsg4978[0, :],
        camera_locations_epsg4978[1, :],
        camera_locations_epsg4978[2, :],
    )
    points_gdf = gpd.GeoDataFrame(
        {"label": camera_labels}, geometry=points, crs="EPSG:4978"
    )

    return points_gdf, unaligned_cameras


def compute_height_above_ground(camera_file: str, dtm_file: str) -> gpd.GeoDataFrame:
    """
    Take the camera locations and DTM from Metashape and produce a height above ground for each camera
    that is aligned and has a valid DTM entry for the corresponding location.

    Args
        camera_file (str):
            Path to the Metashape camera file (.xml)
        dtm_file (str):
            Path to the Metashape DTM (.tif)
    Returns:
        gpd.GeoDataFrame:
            GeoDataFrame with camera locations as Point geometries in EPSG:4326.
            * 'label' the image path
            * 'altitude' the image altitude above ground level in meters
            * 'valid_dtm' was the camera above a valid DTM pixel
            * 'camera_aligned' was the camera aligned by photogrammetry
            * 'ground_elevation' the height of the ground in meters
            * 'image_id' the image filename

    """
    # Parse aligned cameras as geodataframe and record labels of unaligned ones
    cameras_gdf, unaligned_cameras = get_camera_locations(camera_file=camera_file)

    with rio.open(dtm_file) as dtm:
        # Project to the CRS of the DTM
        # Note that any reasonable CRS for a raster (not ECEF) will have a meters-based altitude
        # above ground as the z dimension.
        cameras_gdf = cameras_gdf.to_crs(dtm.crs)

        # Step 3: Extract X, Y from projected points
        sample_coords = [(pt.x, pt.y) for pt in cameras_gdf.geometry]
        # Sort for performance
        sample_coords = rio.sample.sort_xy(sample_coords)

        # Step 4: Sample DTM at these coordinates with masking
        elevations = list(dtm.sample(sample_coords, masked=True))

    # Record which cameras had a corresponding non-null DTM value
    cameras_gdf["valid_dtm"] = [not elev.mask[0] for elev in elevations]
    # Record sampled ground elevation
    cameras_gdf["ground_elevation"] = [elev.data[0] for elev in elevations]
    # Set all ground elevations to nan if the corresponding dtm was not valid
    cameras_gdf.loc[~cameras_gdf.valid_dtm, "ground_elevation"] = np.nan

    # Compute the difference between the ground elevation and the camera elevation.
    cameras_gdf["altitude"] = cameras_gdf.geometry.z - cameras_gdf["ground_elevation"]

    # Note that these cameras aligned properly
    cameras_gdf["camera_aligned"] = True

    # Create a geodataframe with the label and marking that the cameras are unaligned. All other
    # fields are set to the default null value.
    n_unaligned_cameras = len(unaligned_cameras)
    unaligned_cameras_gdf = gpd.GeoDataFrame(
        {
            "label": unaligned_cameras,
            "camera_aligned": [False] * n_unaligned_cameras,
            "valid_dtm": [False] * n_unaligned_cameras,
            "ground_elevation": [np.nan] * n_unaligned_cameras,
            "altitude": [np.nan] * n_unaligned_cameras,
            "geometry": [None] * n_unaligned_cameras,
        },
        crs=cameras_gdf.crs,
    )

    # Add the un-aligned cameras to the geodataframe
    cameras_gdf = gpd.GeoDataFrame(
        pd.concat((cameras_gdf, unaligned_cameras_gdf)), crs=cameras_gdf.crs
    )
    # Add an image_id field representing the filename (without path) to correspond with the OFO
    # convention
    cameras_gdf["image_id"] = cameras_gdf.label.str.split("/").str[-1]
    # Convert to lat lon
    cameras_gdf.to_crs(4326, inplace=True)

    return cameras_gdf


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compute altitude above ground for camera locations using a DTM"
    )
    parser.add_argument(
        "camera_file", type=str, help="Path to the Metashape .xml camera export file"
    )
    parser.add_argument(
        "dtm_file", type=str, help="Path to the DTM (Digital Terrain Model) raster file"
    )
    parser.add_argument(
        "output_file",
        type=Path,
        help="Path to write out camera metadata. Should be a geospatial vector file format.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    # Main processing
    heights_above_ground = compute_height_above_ground(
        camera_file=args.camera_file, dtm_file=args.dtm_file
    )
    # Make the output directory and save
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    heights_above_ground.to_file(args.output_file)

import xml.etree.ElementTree as ET

import geopandas as gpd
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
        return None

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

    # Extract the locations of each camera from the 4x4 transform matrix representing both the
    # rotation and translation of the camera, in local chunk coordinates.
    for cam in ungrouped_cameras:
        transform = cam.find("transform")
        # Skip un-aligned cameras
        if transform is None:
            continue

        # Convert the string representation into a 4x4 numpy array and extract the translation column
        location = np.fromstring(transform.text, sep=" ").reshape(4, 4)[:, 3:]

        camera_labels.append(cam.get("label"))
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

    return points_gdf


def compute_height_above_ground(camera_file, dtm_file):
    cam_locations = get_camera_locations(camera_file=camera_file)

    with rio.open(dtm_file) as dtm:
        dtm_crs = dtm.crs
        # Project to the CRS of the DTM
        DTM_crs_cam_locations = cam_locations.to_crs(dtm_crs)

        # Step 3: Extract X, Y from projected points
        sample_coords = [(pt.x, pt.y) for pt in DTM_crs_cam_locations.geometry]

        # Step 4: Sample DTM at these coordinates with masking
        elevations = list(dtm.sample(sample_coords, masked=True))

    camera_elevations = DTM_crs_cam_locations.copy()
    camera_elevations["ground_elevation"] = [
        elev.data[0] if not elev.mask[0] else np.nan for elev in elevations
    ]
    camera_elevations["valid"] = [not elev.mask[0] for elev in elevations]
    camera_elevations["altitude_agl"] = (
        camera_elevations.geometry.z - camera_elevations["ground_elevation"]
    )

    return camera_elevations

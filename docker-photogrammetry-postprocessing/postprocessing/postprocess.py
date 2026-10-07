"""
Photogrammetry post-processing functions.
Converts raw photogrammetry products into deliverable versions (COGs, CHMs, thumbnails).
Python conversion of 20_postprocess-photogrammetry-products.R
Also computes the height above ground for each camera which was aligned by photogrammetry
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_window
from rasterio.warp import Resampling, calculate_default_transform, reproject
from shapely.geometry import Point

from .compute_derived_altitude import compute_height_above_ground

matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt

# Utility functions


def create_dir(path):
    """Create a directory if it doesn't exist."""
    Path(path).mkdir(parents=True, exist_ok=True)


def lonlat_to_utm_epsg(lon, lat):
    """
    Calculate UTM zone EPSG code from lon/lat coordinates.

    Args:
        lon: Longitude
        lat: Latitude

    Returns:
        EPSG code (int) for the UTM zone
    """
    utm_zone = int((np.floor((lon + 180) / 6) % 60) + 1)

    # Northern hemisphere: 32600 + zone, Southern: 32700 + zone
    if lat >= 0:
        epsg_code = 32600 + utm_zone
    else:
        epsg_code = 32700 + utm_zone

    return epsg_code


def transform_to_local_utm(gdf):
    """
    Reproject a GeoDataFrame to its local UTM zone.

    Args:
        gdf: GeoDataFrame to reproject

    Returns:
        GeoDataFrame reprojected to local UTM zone
    """
    # Convert to WGS84 to get centroid coordinates
    gdf_wgs84 = gdf.to_crs(4326)

    # Get centroid
    centroid = gdf_wgs84.geometry.centroid.iloc[0]
    lon, lat = centroid.x, centroid.y

    # Calculate UTM EPSG
    utm_epsg = lonlat_to_utm_epsg(lon, lat)

    # Reproject to UTM
    gdf_utm = gdf.to_crs(utm_epsg)

    return gdf_utm


# Core processing functions


def _is_rgb_orthomosaic(src):
    """
    Check if a raster is an RGB orthomosaic (3 or 4 band uint8).

    Args:
        src: Open rasterio dataset

    Returns:
        True if this appears to be an RGB orthomosaic
    """
    return src.dtypes[0] == "uint8" and src.count in (3, 4)


def crop_raster_save_cog(
    raster_filepath: str | Path,
    output_filepath: str | Path,
    mission_polygon: gpd.GeoDataFrame,
):
    """
    Crop raster to mission polygon boundary and save as Cloud Optimized GeoTIFF (COG).

    For RGB orthomosaics (3 or 4 band uint8), outputs 4-band uint8 with alpha mask.
    For other rasters, uses standard nodata value handling.

    Cropping is done with gdalwarp, which processes the raster in blocks so memory use
    stays bounded regardless of raster size. The output grid is pinned to the source
    grid (same CRS, resolution, and pixel-aligned bounds) with nearest-neighbor sampling
    and an exact transform, so pixel values are copied without resampling.

    Args:
        raster_filepath: Path to input raster file
        output_filepath: Path to output COG file
        mission_polygon: GeoDataFrame containing mission boundary polygon
    """
    # Ensure output_filepath is a Path object
    output_filepath = Path(output_filepath)

    with rasterio.open(raster_filepath) as src:
        # Reproject mission polygon to match raster CRS
        mission_polygon_matched = mission_polygon.to_crs(src.crs)

        # Note, if there are multiple rows in the boundaries geodataframe, this takes only the area
        # in the interesction of all of them.
        geometry = mission_polygon_matched.geometry.intersection_all()

        # Pixel-aligned bounds of the crop, matching what rasterio.mask(crop=True) would produce
        window = geometry_window(src, [geometry])
        left, bottom, right, top = rasterio.windows.bounds(window, src.transform)
        x_res, y_res = src.res

        # Why the gdalwarp CLI rather than rasterio.mask or the GDAL Python bindings (gdal.Warp):
        # - rasterio.mask reads the whole cropped area into memory (~23 GiB per copy for a
        #   75k x 82k RGBA orthomosaic), which exceeded the pod memory limit. gdalwarp works in
        #   blocks and peaked at ~3 GiB on that file.
        # - The base image (osgeo/gdal ubuntu-small-3.8.4) ships GDAL Python bindings compiled
        #   against NumPy 1.x, but requirements.txt installs NumPy 2.x, which breaks osgeo.gdal_array
        #   (and gdal.UseExceptions(), which imports it). The CLI has no Python dependency.
        #
        # To switch to the Python bindings (gdal.Warp with the same options), upgrade the base
        # image. Tested with ubuntu-small-3.13.3 (Ubuntu 26.04, Python 3.14, NumPy 2.3), where the
        # bindings work. That upgrade requires:
        # - Dockerfile: replace `RUN pip3 install --upgrade pip` with
        #   `ENV PIP_BREAK_SYSTEM_PACKAGES=1` (or use a venv); Ubuntu 26.04 blocks system pip
        #   installs (PEP 668) and the build fails otherwise.
        # - Writing COGs directly from the warp (-of COG / format="COG") is ~1.7x slower in
        #   GDAL 3.13 than 3.8 for large orthomosaics. Warp to a temporary tiled GTiff and then
        #   gdal.Translate / gdal_translate to COG instead, which is as fast as before.
        # - Expect these output differences (cropped and CHM pixel values were identical):
        #   GDAL 3.13 builds one fewer COG overview level, so thumbnails (read from overviews)
        #   differ slightly, and pandas 3 makes photogrammetry_ground_elevation in
        #   camera-locations.gpkg float64 instead of float32.
        cmd = [
            "gdalwarp",
            "-of", "COG",
            "-te", repr(left), repr(bottom), repr(right), repr(top),
            "-tr", repr(x_res), repr(y_res),
            "-r", "near",
            "-et", "0",
            "-wm", "2048",
            "-multi",
            # Bound the block cache so memory use doesn't scale with raster size
            "--config", "GDAL_CACHEMAX", "2048",
            # Parallel compression; parallel warping (-wo NUM_THREADS) is ~4x slower with a cutline
            "-co", "NUM_THREADS=ALL_CPUS",
            "-co", "COMPRESS=DEFLATE",
            "-co", "BIGTIFF=IF_SAFER",
            "-overwrite",
        ]  # fmt: skip

        if _is_rgb_orthomosaic(src):
            # An existing alpha band (4-band input) is used as the source mask; -dstalpha
            # writes an alpha band that is 0 outside the polygon or where the source was masked
            if src.count == 4:
                print(
                    f"  {output_filepath.name}: 4-band uint8 with alpha detected, preserving format"
                )
            else:
                print(
                    f"  {output_filepath.name}: 3-band uint8 detected, adding alpha band"
                )
            cmd += ["-dstalpha"]
        else:
            # Standard handling for non-RGB rasters (elevation data, etc.)
            # Determine nodata value and output dtype
            output_dtype = None
            if src.nodata is not None:
                nodata_value = src.nodata
                cmd += ["-srcnodata", repr(src.nodata)]
            elif src.dtypes[0] == "uint8":
                # Single-band uint8 without nodata: promote to int16
                nodata_value = -32767
                output_dtype = "Int16"
                print(
                    f"  Warning: {output_filepath.name} has no nodata defined. "
                    "Promoting uint8 to int16 to enable nodata masking."
                )
            else:
                nodata_value = -9999

            # Convert float64 to float32 to save space
            if src.dtypes[0] == "float64":
                output_dtype = "Float32"

            cmd += ["-dstnodata", repr(nodata_value)]
            if output_dtype is not None:
                cmd += ["-ot", output_dtype]

        with tempfile.TemporaryDirectory(dir=output_filepath.parent) as tmp_dir:
            cutline_path = os.path.join(tmp_dir, "cutline.gpkg")
            gpd.GeoDataFrame(geometry=[geometry], crs=src.crs).to_file(cutline_path)
            cmd += [
                "-cutline",
                cutline_path,
                str(raster_filepath),
                str(output_filepath),
            ]
            subprocess.run(cmd, check=True)

    print(f"  Saved COG: {output_filepath}")


def make_chm(dsm_filepath, dtm_filepath):
    """
    Create a Canopy Height Model (CHM) from DSM and DTM.

    Only pixels with valid data in both DSM and DTM will have values in the CHM.
    Pixels where either input has nodata will be set to nodata in the output.

    Args:
        dsm_filepath: Path to Digital Surface Model
        dtm_filepath: Path to Digital Terrain Model

    Returns:
        Tuple of (chm_array, profile) for writing
    """
    # Read DSM with masked array to handle nodata
    with rasterio.open(dsm_filepath) as dsm_src:
        dsm_data = dsm_src.read(1, masked=True)
        dsm_profile = dsm_src.profile.copy()
        dsm_transform = dsm_src.transform
        dsm_crs = dsm_src.crs
        dsm_shape = dsm_data.shape
        dsm_nodata = dsm_src.nodata

    # Read DTM and reproject to match DSM
    with rasterio.open(dtm_filepath) as dtm_src:
        dtm_nodata = dtm_src.nodata

        # Calculate transform for reprojection
        transform, width, height = calculate_default_transform(
            dtm_src.crs, dsm_crs, dtm_src.width, dtm_src.height, *dtm_src.bounds
        )

        # Initialize array with nodata value (instead of empty/uninitialized)
        dtm_fill_value = dtm_nodata if dtm_nodata is not None else -9999
        dtm_reprojected = np.full(dsm_shape, dtm_fill_value, dtype=dtm_src.dtypes[0])

        # Reproject DTM to match DSM, with explicit nodata handling
        reproject(
            source=rasterio.band(dtm_src, 1),
            destination=dtm_reprojected,
            src_transform=dtm_src.transform,
            src_crs=dtm_src.crs,
            dst_transform=dsm_transform,
            dst_crs=dsm_crs,
            src_nodata=dtm_nodata,
            dst_nodata=dtm_fill_value,
            resampling=Resampling.bilinear,
        )

    # Convert reprojected DTM to masked array
    dtm_reprojected = np.ma.masked_equal(dtm_reprojected, dtm_fill_value)

    # Calculate CHM - mask propagates automatically (nodata in either input = nodata in output)
    chm_data = dsm_data - dtm_reprojected

    # Convert back to regular array, filling masked values with nodata
    chm_nodata = dsm_nodata if dsm_nodata is not None else -9999
    chm_filled = chm_data.filled(chm_nodata)

    # Update profile with nodata value
    dsm_profile.update({"nodata": chm_nodata})

    return chm_filled, dsm_profile


def create_thumbnail(tif_filepath, output_path, max_dim=800):
    """
    Create a PNG thumbnail from a GeoTIFF.

    For 4-band uint8 images (RGB + alpha), uses the alpha band for transparency.

    Args:
        tif_filepath: Path to input TIF file
        output_path: Path to output PNG file
        max_dim: Maximum dimension (width or height) in pixels
    """
    with rasterio.open(tif_filepath) as src:
        # Get dimensions
        n_row = src.height
        n_col = src.width
        n_bands = src.count

        # Calculate scale factor
        max_dimension = max(n_row, n_col)
        scale_factor = max_dim / max_dimension
        new_n_row = int(n_row * scale_factor)
        new_n_col = int(n_col * scale_factor)

        # Create figure with exact pixel dimensions
        dpi = 100
        fig_width = new_n_col / dpi
        fig_height = new_n_row / dpi

        fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=dpi)

        if n_bands == 1:
            # Single-band (elevation data, CHM, etc.)
            # Read as masked array to handle nodata (renders as transparent)
            data = src.read(1, out_shape=(new_n_row, new_n_col), masked=True)
            ax.imshow(data, cmap="viridis")
        elif n_bands == 4 and src.dtypes[0] == "uint8":
            # RGBA (4-band uint8 with alpha)
            rgba = np.dstack(
                [src.read(i, out_shape=(new_n_row, new_n_col)) for i in [1, 2, 3, 4]]
            )
            ax.imshow(rgba)
        elif n_bands >= 3:
            # RGB (use first 3 bands)
            rgb = np.dstack(
                [src.read(i, out_shape=(new_n_row, new_n_col)) for i in [1, 2, 3]]
            )
            # Normalize to 0-255 if needed
            if rgb.max() > 255:
                rgb = ((rgb - rgb.min()) / (rgb.max() - rgb.min()) * 255).astype(
                    np.uint8
                )
            ax.imshow(rgb)
        else:
            # Fallback for 2-band images
            data = src.read(1, out_shape=(new_n_row, new_n_col))
            ax.imshow(data, cmap="viridis")

        # Remove axes and margins
        ax.axis("off")
        ax.set_position([0, 0, 1, 1])

        # Save with transparent background
        plt.savefig(
            output_path, bbox_inches="tight", pad_inches=0, transparent=True, dpi=dpi
        )
        plt.close(fig)

    print(f"  Created thumbnail: {os.path.basename(output_path)}")


def postprocess_photogrammetry_containerized(
    mission_id, boundary_file_path, product_file_paths, working_dir, output_max_dim=800
):
    """
    Main post-processing function for a single mission.

    Processes photogrammetry products:
    - Crops rasters to mission boundary
    - Saves as Cloud Optimized GeoTIFFs (COGs)
    - Generates Canopy Height Models (CHMs) from DSM/DTM
    - Creates PNG thumbnails
    - Copies non-raster files

    Output is written directly to output/full/ and output/thumbnails/ directories
    (no mission subdirectory since each iteration has its own isolated postprocessing folder).

    Args:
        mission_id: Mission identifier (used for naming output files, not directory structure)
        boundary_file_path: Path to mission boundary polygon file
        product_file_paths: List of paths to photogrammetry product files
        working_dir: Local working directory; outputs are written to working_dir/output
        output_max_dim: Maximum dimension in pixels of the generated thumbnails

    Returns:
        True on success, raises exception on failure. Any failed product raises
        immediately, so an incomplete product set is never uploaded.
    """
    print(f"Starting post-processing for mission: {mission_id}")

    # Validate inputs
    if not os.path.exists(boundary_file_path):
        raise FileNotFoundError(f"Boundary file not found: {boundary_file_path}")

    missing_products = [p for p in product_file_paths if not os.path.exists(p)]
    if missing_products:
        raise FileNotFoundError(
            f"Product files not found: {', '.join(missing_products)}"
        )

    # Create output directories (no mission subdirectory)
    postprocessed_path = f"{working_dir}/output"
    create_dir(os.path.join(postprocessed_path, "full"))
    create_dir(os.path.join(postprocessed_path, "thumbnails"))

    # Read mission polygon
    print(f"Reading boundary polygon from: {boundary_file_path}")
    mission_polygon = gpd.read_file(boundary_file_path)

    # Build product DataFrame
    product_filenames = [os.path.basename(p) for p in product_file_paths]

    photogrammetry_output_files = pd.DataFrame(
        {
            "photogrammetry_output_filename": product_filenames,
            "full_path": product_file_paths,
        }
    )

    # Extract file extensions
    photogrammetry_output_files["extension"] = photogrammetry_output_files[
        "photogrammetry_output_filename"
    ].apply(
        lambda x: os.path.splitext(x)[1][1:].lower()  # Remove leading dot
    )

    # Extract product type from filename
    def extract_product_type(filename):
        base_name = os.path.splitext(filename)[0]
        parts = base_name.split("_")
        if len(parts) > 1:
            return parts[-1]  # Last part is product type
        return "unknown"

    photogrammetry_output_files["type"] = photogrammetry_output_files[
        "photogrammetry_output_filename"
    ].apply(extract_product_type)

    # Create output filenames
    photogrammetry_output_files["postprocessed_filename"] = (
        photogrammetry_output_files.apply(
            lambda row: f"{mission_id}_{row['type']}.{row['extension']}", axis=1
        )
    )

    print(f"Found {len(photogrammetry_output_files)} product files:")
    print(
        photogrammetry_output_files[
            ["photogrammetry_output_filename", "type", "extension"]
        ]
    )

    ## Crop rasters and save as COG

    raster_files = photogrammetry_output_files[
        photogrammetry_output_files["extension"].isin(["tif", "tiff"])
    ]

    if len(raster_files) > 0:
        print(f"Processing {len(raster_files)} raster files")

        for _, row in raster_files.iterrows():
            print(f"  Cropping {row['photogrammetry_output_filename']}")
            crop_raster_save_cog(
                raster_filepath=row["full_path"],
                output_filepath=os.path.join(
                    postprocessed_path, "full", row["postprocessed_filename"]
                ),
                mission_polygon=mission_polygon,
            )

    ## Create CHMs

    # Filter for DEM files
    dem_files = photogrammetry_output_files[
        (photogrammetry_output_files["extension"].isin(["tif", "tiff"]))
        & (
            photogrammetry_output_files["type"].isin(
                ["dsm-ptcloud", "dsm-mesh", "dtm-ptcloud"]
            )
        )
    ].copy()

    # Add postprocessed file paths
    dem_files["postprocessed_filepath"] = dem_files["postprocessed_filename"].apply(
        lambda x: os.path.join(postprocessed_path, "full", x)
    )

    available_types = dem_files["type"].tolist()

    # Try to create chm-ptcloud
    if "dsm-ptcloud" in available_types and "dtm-ptcloud" in available_types:
        print("Creating chm-ptcloud from dsm-ptcloud and dtm-ptcloud")
        dsm_filepath = dem_files[dem_files["type"] == "dsm-ptcloud"][
            "postprocessed_filepath"
        ].iloc[0]
        dtm_filepath = dem_files[dem_files["type"] == "dtm-ptcloud"][
            "postprocessed_filepath"
        ].iloc[0]

        chm_data, chm_profile = make_chm(dsm_filepath, dtm_filepath)

        # Update profile for COG
        chm_profile.update(
            {
                "driver": "COG",
                "compress": "deflate",
                "tiled": True,
                "BIGTIFF": "IF_SAFER",
            }
        )

        # Write CHM
        chm_filename = f"{mission_id}_chm-ptcloud.tif"
        chm_filepath = os.path.join(postprocessed_path, "full", chm_filename)

        with rasterio.open(chm_filepath, "w", **chm_profile) as dst:
            dst.write(chm_data, 1)

        print(f"Successfully created CHM: {chm_filename}")

    # Try to create chm-mesh
    if "dsm-mesh" in available_types and "dtm-ptcloud" in available_types:
        print("Creating chm-mesh from dsm-mesh and dtm-ptcloud")
        dsm_filepath = dem_files[dem_files["type"] == "dsm-mesh"][
            "postprocessed_filepath"
        ].iloc[0]
        dtm_filepath = dem_files[dem_files["type"] == "dtm-ptcloud"][
            "postprocessed_filepath"
        ].iloc[0]

        chm_data, chm_profile = make_chm(dsm_filepath, dtm_filepath)

        # Update profile for COG
        chm_profile.update(
            {
                "driver": "COG",
                "compress": "deflate",
                "tiled": True,
                "BIGTIFF": "IF_SAFER",
            }
        )

        # Write CHM
        chm_filename = f"{mission_id}_chm-mesh.tif"
        chm_filepath = os.path.join(postprocessed_path, "full", chm_filename)

        with rasterio.open(chm_filepath, "w", **chm_profile) as dst:
            dst.write(chm_data, 1)

        print(f"Successfully created CHM: {chm_filename}")

    ## Create thumbnails

    # List all TIF files in output folder
    full_output_dir = os.path.join(postprocessed_path, "full")
    tif_files = [f for f in os.listdir(full_output_dir) if f.lower().endswith(".tif")]

    print(f"Creating thumbnails for {len(tif_files)} raster files")

    for tif_file in tif_files:
        tif_file_path = os.path.join(full_output_dir, tif_file)
        thumbnail_filename = os.path.splitext(tif_file)[0] + ".png"
        thumbnail_filepath = os.path.join(
            postprocessed_path, "thumbnails", thumbnail_filename
        )

        create_thumbnail(tif_file_path, thumbnail_filepath, max_dim=output_max_dim)

    # Create the height above ground file
    # Check if both input files exist
    if (
        f"{mission_id}_cameras.xml" in product_filenames
        and f"{mission_id}_dtm-ptcloud.tif" in product_filenames
    ):
        print("Computing height above ground for aligned cameras")
        # Find the matching full file paths in the dataframe of photogrammetry outputs
        cameras_file = Path(
            photogrammetry_output_files[
                photogrammetry_output_files["photogrammetry_output_filename"]
                == f"{mission_id}_cameras.xml"
            ]["full_path"].iloc[0]
        )
        DTM_file = Path(
            photogrammetry_output_files[
                photogrammetry_output_files["photogrammetry_output_filename"]
                == f"{mission_id}_dtm-ptcloud.tif"
            ]["full_path"].iloc[0]
        )
        output_file = Path(
            postprocessed_path, "full", f"{mission_id}_camera-locations.gpkg"
        )

        height_above_ground = compute_height_above_ground(
            camera_file=cameras_file, dtm_file=DTM_file
        )
        height_above_ground.to_file(output_file)
        print(f"Successfully created height above ground: {output_file.name}")
    else:
        print(
            "Skipping height above ground computation (missing cameras.xml or dtm-ptcloud.tif)"
        )

    ## Copy non-raster files

    other_files = photogrammetry_output_files[
        ~photogrammetry_output_files["extension"].isin(["tif", "tiff"])
    ]

    if len(other_files) > 0:
        print(f"Copying {len(other_files)} non-raster files")

        for _, row in other_files.iterrows():
            output_filepath = os.path.join(
                postprocessed_path, "full", row["postprocessed_filename"]
            )
            shutil.copy(row["full_path"], output_filepath)
            print(f"  Copied: {row['postprocessed_filename']}")

    # Count output files
    full_files = os.listdir(os.path.join(postprocessed_path, "full"))
    thumbnail_files = os.listdir(os.path.join(postprocessed_path, "thumbnails"))

    print(f"Post-processing completed for mission: {mission_id}")
    print(
        f"Created {len(full_files)} full-resolution products and {len(thumbnail_files)} thumbnails"
    )

    return True

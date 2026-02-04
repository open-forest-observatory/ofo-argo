"""
Photogrammetry post-processing functions.
Converts raw photogrammetry products into deliverable versions (COGs, CHMs, thumbnails).
Python conversion of 20_postprocess-photogrammetry-products.R
"""

import os
import shutil
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import ColorInterp
from rasterio.mask import mask
from rasterio.warp import Resampling, calculate_default_transform, reproject
from shapely.geometry import Point

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


def _crop_rgb_orthomosaic(src, geometries, output_filename):
    """
    Crop an RGB orthomosaic and return 4-band uint8 with alpha mask.

    Handles both 3-band and 4-band uint8 inputs. The output is always
    4-band uint8 where band 4 is an alpha mask (0=nodata, 255=valid).

    Args:
        src: Open rasterio dataset
        geometries: Geometries to use for masking
        output_filename: Output filename (for logging)

    Returns:
        Tuple of (cropped_data, cropped_transform, profile)
    """
    has_alpha = src.count == 4

    if has_alpha:
        print(f"  {output_filename}: 4-band uint8 with alpha detected, preserving format")
    else:
        print(f"  {output_filename}: 3-band uint8 detected, adding alpha band")

    # Read RGB bands (first 3 bands)
    # Use nodata=0 for the mask operation on RGB bands
    cropped_rgb, cropped_transform = mask(
        src, geometries, crop=True, indexes=[1, 2, 3], nodata=0, filled=True
    )

    # Create alpha band: 255 where valid, 0 where nodata
    # Start with all zeros (nodata)
    alpha_band = np.zeros(
        (1, cropped_rgb.shape[1], cropped_rgb.shape[2]), dtype=np.uint8
    )

    if has_alpha:
        # Read and crop the existing alpha band
        cropped_alpha, _ = mask(
            src, geometries, crop=True, indexes=[4], nodata=0, filled=True
        )
        # Alpha is valid (255) only where:
        # 1. Original alpha was valid (non-zero)
        # 2. Pixel is inside the crop polygon (handled by mask with nodata=0)
        alpha_band = cropped_alpha
    else:
        # For 3-band input, create alpha from the mask operation
        # Pixels inside polygon get alpha=255, outside get alpha=0
        # We need to re-run mask to get the valid mask
        cropped_with_mask, _ = mask(
            src, geometries, crop=True, indexes=[1], filled=False
        )
        # Where mask is False (valid data), set alpha to 255
        alpha_band[0] = np.where(cropped_with_mask.mask[0], 0, 255).astype(np.uint8)

    # Combine RGB + alpha
    cropped_data = np.vstack([cropped_rgb, alpha_band])

    # Build profile for 4-band uint8 output
    profile = src.profile.copy()
    profile.update(
        {
            "driver": "COG",
            "compress": "deflate",
            "tiled": True,
            "height": cropped_data.shape[1],
            "width": cropped_data.shape[2],
            "transform": cropped_transform,
            "count": 4,
            "dtype": "uint8",
            "nodata": None,  # Alpha band handles nodata
            "BIGTIFF": "IF_SAFER",
        }
    )

    return cropped_data, cropped_transform, profile


def crop_raster_save_cog(
    raster_filepath, output_filename, mission_polygon, output_path
):
    """
    Crop raster to mission polygon boundary and save as Cloud Optimized GeoTIFF (COG).

    For RGB orthomosaics (3 or 4 band uint8), outputs 4-band uint8 with alpha mask.
    For other rasters, uses standard nodata value handling.

    Args:
        raster_filepath: Path to input raster file
        output_filename: Output filename
        mission_polygon: GeoDataFrame containing mission boundary polygon
        output_path: Base output directory path
    """
    # Read raster
    with rasterio.open(raster_filepath) as src:
        # Reproject mission polygon to match raster CRS
        mission_polygon_matched = mission_polygon.to_crs(src.crs)

        # Get geometries for masking
        geometries = mission_polygon_matched.geometry.values

        # Handle RGB orthomosaics specially (3 or 4 band uint8)
        if _is_rgb_orthomosaic(src):
            cropped_data, cropped_transform, profile = _crop_rgb_orthomosaic(
                src, geometries, output_filename
            )
        else:
            # Standard handling for non-RGB rasters (elevation data, etc.)
            # Determine nodata value and output dtype
            output_dtype = None
            if src.nodata is not None:
                nodata_value = src.nodata
            elif src.dtypes[0] == "uint8":
                # Single-band uint8 without nodata: promote to int16
                nodata_value = -32767
                output_dtype = "int16"
                print(
                    f"  Warning: {output_filename} has no nodata defined. "
                    "Promoting uint8 to int16 to enable nodata masking."
                )
            else:
                nodata_value = -9999

            # Convert float64 to float32 to save space
            if src.dtypes[0] == "float64":
                output_dtype = "float32"

            # Crop raster to polygon, explicitly setting nodata outside polygon
            cropped_data, cropped_transform = mask(
                src, geometries, crop=True, nodata=nodata_value, filled=True
            )

            # Update metadata for COG
            profile = src.profile.copy()
            profile.update(
                {
                    "driver": "COG",
                    "compress": "deflate",
                    "tiled": True,
                    "height": cropped_data.shape[1],
                    "width": cropped_data.shape[2],
                    "transform": cropped_transform,
                    "nodata": nodata_value,
                    "BIGTIFF": "IF_SAFER",
                }
            )

            # Apply dtype conversion if needed
            if output_dtype is not None:
                profile["dtype"] = output_dtype
                cropped_data = cropped_data.astype(output_dtype)

        # Write output
        output_file_path = os.path.join(output_path, "full", output_filename)
        with rasterio.open(output_file_path, "w", **profile) as dst:
            dst.write(cropped_data)

            # Set color interpretation for RGBA so QGIS recognizes alpha band
            if profile.get("count") == 4 and profile.get("dtype") == "uint8":
                dst.colorinterp = [
                    ColorInterp.red,
                    ColorInterp.green,
                    ColorInterp.blue,
                    ColorInterp.alpha,
                ]

    print(f"  Saved COG: {output_filename}")


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
            data = src.read(1, out_shape=(new_n_row, new_n_col))
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
    mission_id, boundary_file_path, product_file_paths
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

    Returns:
        True on success, raises exception on failure
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
    working_dir = os.environ.get("TEMP_WORKING_DIR_POSTPROCESSING", "/tmp/processing")
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
            try:
                crop_raster_save_cog(
                    raster_filepath=row["full_path"],
                    output_filename=row["postprocessed_filename"],
                    mission_polygon=mission_polygon,
                    output_path=postprocessed_path,
                )
            except Exception as e:
                print(
                    f"  Warning: Failed to process {row['photogrammetry_output_filename']}: {e}"
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

        try:
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

        except Exception as e:
            print(f"Failed to create chm-ptcloud: {e}")

    # Try to create chm-mesh
    if "dsm-mesh" in available_types and "dtm-ptcloud" in available_types:
        print("Creating chm-mesh from dsm-mesh and dtm-ptcloud")
        dsm_filepath = dem_files[dem_files["type"] == "dsm-mesh"][
            "postprocessed_filepath"
        ].iloc[0]
        dtm_filepath = dem_files[dem_files["type"] == "dtm-ptcloud"][
            "postprocessed_filepath"
        ].iloc[0]

        try:
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

        except Exception as e:
            print(f"Failed to create chm-mesh: {e}")

    ## Copy non-raster files

    other_files = photogrammetry_output_files[
        ~photogrammetry_output_files["extension"].isin(["tif", "tiff"])
    ]

    if len(other_files) > 0:
        print(f"Copying {len(other_files)} non-raster files")

        for _, row in other_files.iterrows():
            try:
                output_filepath = os.path.join(
                    postprocessed_path, "full", row["postprocessed_filename"]
                )
                shutil.copy(row["full_path"], output_filepath)
                print(f"  Copied: {row['postprocessed_filename']}")
            except Exception as e:
                print(
                    f"Warning: Failed to copy {row['photogrammetry_output_filename']}: {e}"
                )

    ## Create thumbnails

    output_max_dim = int(os.environ.get("OUTPUT_MAX_DIM", "800"))

    # List all TIF files in output folder
    full_output_dir = os.path.join(postprocessed_path, "full")
    tif_files = [f for f in os.listdir(full_output_dir) if f.lower().endswith(".tif")]

    print(f"Creating thumbnails for {len(tif_files)} raster files")

    for tif_file in tif_files:
        try:
            tif_file_path = os.path.join(full_output_dir, tif_file)
            thumbnail_filename = os.path.splitext(tif_file)[0] + ".png"
            thumbnail_filepath = os.path.join(
                postprocessed_path, "thumbnails", thumbnail_filename
            )

            create_thumbnail(tif_file_path, thumbnail_filepath, max_dim=output_max_dim)

        except Exception as e:
            print(f"Warning: Failed to create thumbnail for {tif_file}: {e}")

    # Count output files
    full_files = os.listdir(os.path.join(postprocessed_path, "full"))
    thumbnail_files = os.listdir(os.path.join(postprocessed_path, "thumbnails"))

    print(f"Post-processing completed for mission: {mission_id}")
    print(
        f"Created {len(full_files)} full-resolution products and {len(thumbnail_files)} thumbnails"
    )

    return True

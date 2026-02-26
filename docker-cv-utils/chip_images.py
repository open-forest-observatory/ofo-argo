import json
from math import ceil, floor
from multiprocessing import Pool
from pathlib import Path
from argparse import ArgumentParser

import geopandas as gpd
import numpy as np
import shapely
from imageio import imread, imwrite
from PIL import Image
from rasterio import features
from rasterio.features import shapes
from scipy.ndimage import label
from shapely.affinity import translate


# Background masking configuration
MASK_BACKGROUND = True  # Whether to mask out background trees
MASK_BUFFER_PIXELS = 20  # Buffer zone around mask in pixels to retain
BACKGROUND_VALUE = (
    128,
    128,
    128,
)  # Value to set background pixels (0-255, recommend 128 for mid-gray)

# Other parameters
BBOX_PADDING_RATIO = 0.02
IMAGE_RES_CONSTRAINT = 50  # min edge length (height and width) to save
# The number of processes to use for chipping.


def filter_contours_by_area(binary_mask, area_threshold=0.5):
    """
    Filter contours in a binary mask, keeping only the largest contour and
    any contours with area >= area_threshold * largest_contour_area.
    """
    # Label connected regions (contours) in the binary mask
    labeled_mask, num_features = label(binary_mask)

    # If only one contour, return the original mask
    if num_features <= 1:
        return binary_mask

    # Calculate area (pixel count) for each contour
    # TODO: Find a more efficient way to compute areas
    contour_areas = [(i, np.sum(labeled_mask == i)) for i in range(1, num_features + 1)]
    contour_areas.sort(key=lambda x: x[1], reverse=True)

    # Find largest contour area and set minimum area threshold
    largest_area = contour_areas[0][1]
    min_area = largest_area * area_threshold

    # Build mask with only contours meeting the area threshold (ideally should be only one)
    filtered_mask = np.zeros_like(binary_mask, dtype=bool)
    for contour_id, area in contour_areas:
        if area >= min_area:
            # Set elements to True wherever either filtered_mask is already True or (labeled_mask == contour_id)
            filtered_mask |= labeled_mask == contour_id

    return filtered_mask


def chip_images(image_path, mask_path, output_folder, IDs_to_labels):
    img = Image.open(image_path)  # load image
    img_array = (
        np.array(img) if MASK_BACKGROUND else None
    )  # Convert to numpy array for masking

    mask_ids = imread(mask_path)  # load tif tree id mask
    mask_ids = np.squeeze(mask_ids)  # (H, W, 1) -> (H, W)

    if mask_ids.dtype == np.uint32:
        # Indicates a mallformed image in the current experiments
        return

    # TODO remove the 255 filter once it's reset to 0 being the background
    individual_shapes = list(shapes(mask_ids, mask=mask_ids != 255))

    # No polygons, skip
    if len(individual_shapes) == 0:
        return

    # Extract the potentially-multiple polygons from each shape along with the original value,
    # now encoded as a zero-padded string
    polys = [
        (shapely.Polygon(poly), int(shape[1]))
        for shape in individual_shapes
        for poly in shape[0]["coordinates"]
    ]
    # Split into geometries and IDs and build a geodataframe
    geometry, ids = list(zip(*polys))
    # Create a GDF using an arbitrary CRS
    shapes_gdf = gpd.GeoDataFrame({"geometry": geometry, "IDs": ids}, crs=3310)

    # Store the area as an attribute for future use
    shapes_gdf["polygon_area"] = shapes_gdf.area
    # Find the max area per ID
    max_area_per_class = shapes_gdf[["polygon_area", "IDs"]].groupby("IDs").max()

    # Merge the area and max area by IDs
    shapes_gdf = shapes_gdf.join(max_area_per_class, on="IDs", rsuffix="_max")

    # Compute for each polygon what fraction of the max area for that ID it is
    shapes_gdf["frac_of_max"] = (
        shapes_gdf["polygon_area"] / shapes_gdf["polygon_area_max"]
    )
    # Remove the polygons which are less than the threshold fraction of the max for that ID
    shapes_gdf = shapes_gdf[shapes_gdf["frac_of_max"] > 0.5]
    # Remove the columns we no longer need
    shapes_gdf.drop(
        ["frac_of_max", "polygon_area", "polygon_area_max"], axis=1, inplace=True
    )

    # Merge by ID, forming multipolygons as needed
    shapes_gdf = shapes_gdf.dissolve("IDs", as_index=False)

    # Compute the axis-aligned height and width of each ID
    width = shapes_gdf.bounds.maxx - shapes_gdf.bounds.minx
    height = shapes_gdf.bounds.maxy - shapes_gdf.bounds.miny

    # Remove IDs that are too small
    valid_dims = (height > IMAGE_RES_CONSTRAINT) & (width > IMAGE_RES_CONSTRAINT)
    shapes_gdf = shapes_gdf[valid_dims]

    # Remove any zero area polygons
    shapes_gdf = shapes_gdf[shapes_gdf.area > 0]
    shapes_gdf.IDs.replace(IDs_to_labels, inplace=True)

    # Make the output folder
    Path(output_folder).mkdir(exist_ok=True, parents=True)
    # iterate over ids
    for _, row in shapes_gdf.iterrows():
        tree_unique_id = row.IDs
        # Create the mask
        minx, miny, maxx, maxy = row.geometry.bounds
        width = maxx - minx
        height = maxy - miny

        pad_width = width * BBOX_PADDING_RATIO
        pad_height = height * BBOX_PADDING_RATIO

        # padded floating coords
        left = minx - pad_width
        top = miny - pad_height
        right = maxx + pad_width
        bottom = maxy + pad_height

        # image shape (rows=height, cols=width)
        img_h, img_w = img_array.shape[:2]

        # integer pixel coordinates, clamped to image bounds
        crop_minx = max(0, int(floor(left)))
        crop_miny = max(0, int(floor(top)))
        crop_maxx = min(img_w, int(ceil(right)))
        crop_maxy = min(img_h, int(ceil(bottom)))

        # extract crop
        crop = img_array[crop_miny:crop_maxy, crop_minx:crop_maxx].copy()

        # Apply background masking if enabled
        if MASK_BACKGROUND:
            # shift geometry into crop-local coordinates (use integer crop offsets)
            shifted_geometry = translate(row.geometry, xoff=-crop_minx, yoff=-crop_miny)

            # Expand the mask
            buffered_geometry = shifted_geometry.buffer(MASK_BUFFER_PIXELS)

            # rasterize the shifted geometry to a mask (0 inside geometry, 1 outside)
            mask = features.rasterize(
                [(buffered_geometry, 0)],
                out_shape=(crop.shape[0], crop.shape[1]),
                fill=1,
                dtype="uint8",
            ).astype(bool)

            bg = np.array(BACKGROUND_VALUE, dtype=crop.dtype)
            crop[mask] = bg

        # Create the output path
        output_path = Path(output_folder, f"{tree_unique_id}.png")

        # save cropped img
        imwrite(output_path, crop)


def process_folder(
    images_folder,
    renders_folder,
    output_dir,
    images_ext="JPG",
    renders_ext="tif",
    n_workers=1,
) -> tuple:
    """Create the per-tree chips for one dataset"""
    images_folder = Path(images_folder)
    renders_folder = Path(renders_folder)

    image_files = sorted(images_folder.rglob(f"*{images_ext}"))
    render_files = sorted(renders_folder.rglob(f"*{renders_ext}"))

    images_stems = [f.relative_to(images_folder).with_suffix("") for f in image_files]
    renders_stems = [
        f.relative_to(renders_folder).with_suffix("") for f in render_files
    ]

    missing_images = set(renders_stems) - set(images_stems)
    if len(missing_images) > 0:
        raise ValueError(
            f"{len(missing_images)} renders do not have a corresponding images. The first 10 are {list(missing_images)[:10]}"
        )
    additional_images = set(images_stems) - set(renders_stems)
    if len(additional_images) > 0:
        raise ValueError(
            f"{len(additional_images)} images do not have a corresponding renders. The first 10 are {list(additional_images)[:10]}"
        )

    with open(Path(renders_folder, "IDs_to_labels.json"), "r") as file_h:
        IDs_to_labels = json.load(file_h)
        IDs_to_labels = {int(k): v for k, v in IDs_to_labels.items()}

    output_folders = [Path(output_dir, image_stem) for image_stem in images_stems]

    # Replicate IDs_to_labels the appropriate number of times
    inputs = list(
        zip(
            image_files,
            render_files,
            output_folders,
            [IDs_to_labels] * len(image_files),
        )
    )

    with Pool(n_workers) as p:
        p.starmap(chip_images, inputs)


def parse_args():
    parser = ArgumentParser()
    parser.add_argument("images_folder")
    parser.add_argument("renders_folder")
    parser.add_argument("output_folder")
    parser.add_argument("--n-workers", type=int, default=1)

    args = parser.parse_args()
    return args


if __name__ == "__main__":
    # Parse args
    args = parse_args()

    # Run
    process_folder(
        args.images_folder,
        args.renders_folder,
        args.output_folder,
        n_workers=args.n_workers,
    )

import json
from argparse import ArgumentParser, BooleanOptionalAction
from functools import partial
from math import ceil, floor
from multiprocessing import Pool
from pathlib import Path
import time
import warnings
import pandas as pd

import geopandas as gpd
import numpy as np
import shapely
from imageio.v2 import imread, imwrite
from PIL import Image
from rasterio import features
from rasterio.features import shapes
from shapely.affinity import translate

# Background masking configuration
MASK_BACKGROUND = True  # Whether to mask out background trees
MASK_BUFFER_PIXELS = 20  # Buffer zone around mask in pixels to retain
BACKGROUND_VALUE = (
    128,
    128,
    128,
)  # Value to set background pixels (0-255, recommend 128 for mid-gray)

# This value is what is used as the background value for the rendered masks.
# Be careful since IDs_to_labels must be overwritten to force 0 to be the background class during
# the rendering process.
RENDER_NULL_ID = 0

# Other parameters
BBOX_PADDING_RATIO = 0.02
IMAGE_RES_CONSTRAINT = 50  # min edge length (height and width) to save
# The number of processes to use for chipping.


def find_nth_element(df):
    breakpoint()
    sorted_values = df.sort_values("min_dim")
    index = min(len(sorted_values), 20) - 1

    return sorted_values.iloc[index]["min_dim"]


def extract_shapes_from_mask(
    mask_path: str,
    render_null_ID: int = RENDER_NULL_ID,
    mask_background: bool = MASK_BACKGROUND,
):
    """
    Take an image and a one-channel mask and create a chip corresponding to each unique ID in the
    mask. The content outside of the geometry can be masked to a background value.

    Args:
        image_path (str): Path to an RGB image, which will be chipped
        mask_path (str): Path to a one-channel integer image, where unique IDs define the chips
        output_folder (str): Where to write all chips
        IDs_to_labels (dict): Mapping from integer values in the mask image to the filenames used for the output chips
        render_null_ID (int, optional): The ID of the background content in the mask, which is not chipped. Defaults to RENDER_NULL_ID.
        mask_background (bool, optional): Should the content outside of the geometry be set to a background value. Defaults to MASK_BACKGROUND.
        mask_buffer_pixels (int, optional): How many pixels to expand the geometry. Defaults to MASK_BUFFER_PIXELS.
        background_value (tuple, optional): The RGB color to use for the background if masking is applied. Defaults to BACKGROUND_VALUE.
        image_res_constraint (int, optional): Only save out chips that are at least this size in both dimensions. Defaults to IMAGE_RES_CONSTRAINT.

    Raises:
        ValueError: If values in the mask image are not included in the IDs_to_labels keys, meaning they cannot be remapped
    """
    mask_ids = imread(mask_path)  # load tif tree id mask
    mask_ids = np.squeeze(mask_ids)  # (H, W, 1) -> (H, W)

    if mask_ids.dtype == np.uint32:
        # Indicates a mallformed image in the current experiments
        return

    # The background is all non-tree pixels
    individual_shapes = list(shapes(mask_ids, mask=mask_ids != render_null_ID))

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
    # Create a geodataframe. Note, this data is not geospatial, but this is the easiest way to work
    # abstract working with vector data.
    shapes_gdf = gpd.GeoDataFrame({"geometry": geometry, "IDs": ids})
    shapes_gdf["filename"] = mask_path
    return shapes_gdf

    ## Store the area as an attribute for future use
    # shapes_gdf["polygon_area"] = shapes_gdf.area
    ## Find the max area per ID
    # max_area_per_class = shapes_gdf[["polygon_area", "IDs"]].groupby("IDs").max()

    ## Merge the area and max area by IDs
    # shapes_gdf = shapes_gdf.join(max_area_per_class, on="IDs", rsuffix="_max")

    ## Compute for each polygon what fraction of the max area for that ID it is
    # shapes_gdf["frac_of_max"] = (
    #    shapes_gdf["polygon_area"] / shapes_gdf["polygon_area_max"]
    # )
    ## Remove the polygons which are less than the threshold fraction of the max for that ID
    # shapes_gdf = shapes_gdf[shapes_gdf["frac_of_max"] > 0.5]
    ## Remove the columns we no longer need
    # shapes_gdf.drop(
    #    ["frac_of_max", "polygon_area", "polygon_area_max"], axis=1, inplace=True
    # )

    ## Merge by ID, forming multipolygons as needed
    # shapes_gdf = shapes_gdf.dissolve("IDs", as_index=False)

    ## Compute the axis-aligned height and width of each ID
    # width = shapes_gdf.bounds.maxx - shapes_gdf.bounds.minx
    # height = shapes_gdf.bounds.maxy - shapes_gdf.bounds.miny

    ## Remove IDs that are too small
    # valid_dims = (height > image_res_constraint) & (width > image_res_constraint)
    # shapes_gdf = shapes_gdf[valid_dims]

    ## Remove any zero area polygons
    # shapes_gdf = shapes_gdf[shapes_gdf.area > 0]
    ## This cannot be done inplace in modern versions of pandas
    # shapes_gdf.IDs = shapes_gdf.IDs.replace(IDs_to_labels)
    ## Check that all items were remapped
    # if not (shapes_gdf.IDs.isin(IDs_to_labels.values())).all():
    #    un_mapped_values = list(
    #        set(list(shapes_gdf.IDs.unique())) - set(list(IDs_to_labels.values()))
    #    )
    #    raise ValueError(f"Not all values were remapped: {un_mapped_values}")

    ## Make the output folder
    # Path(output_folder).mkdir(exist_ok=True, parents=True)
    ## iterate over ids
    # for _, row in shapes_gdf.iterrows():
    #    tree_unique_id = row.IDs
    #    # Create the mask
    #    minx, miny, maxx, maxy = row.geometry.bounds
    #    width = maxx - minx
    #    height = maxy - miny

    #    pad_width = width * BBOX_PADDING_RATIO
    #    pad_height = height * BBOX_PADDING_RATIO

    #    # padded floating coords
    #    left = minx - pad_width
    #    top = miny - pad_height
    #    right = maxx + pad_width
    #    bottom = maxy + pad_height

    #    # image shape (rows=height, cols=width)
    #    img_h, img_w = img_array.shape[:2]

    #    # integer pixel coordinates, clamped to image bounds
    #    crop_minx = max(0, int(floor(left)))
    #    crop_miny = max(0, int(floor(top)))
    #    crop_maxx = min(img_w, int(ceil(right)))
    #    crop_maxy = min(img_h, int(ceil(bottom)))

    #    # extract crop
    #    crop = img_array[crop_miny:crop_maxy, crop_minx:crop_maxx].copy()

    #    # Apply background masking if enabled
    #    if mask_background:
    #        # shift geometry into crop-local coordinates (use integer crop offsets)
    #        shifted_geometry = translate(row.geometry, xoff=-crop_minx, yoff=-crop_miny)

    #        # Catch warnings about invalid geometries
    #        with warnings.catch_warnings():
    #            warnings.simplefilter("ignore", category=RuntimeWarning)
    #            # Expand the mask
    #            buffered_geometry = shifted_geometry.buffer(mask_buffer_pixels)

    #        # rasterize the shifted geometry to a mask (0 inside geometry, 1 outside)
    #        mask = features.rasterize(
    #            [(buffered_geometry, 0)],
    #            out_shape=(crop.shape[0], crop.shape[1]),
    #            fill=1,
    #            dtype="uint8",
    #        ).astype(bool)

    #        bg = np.array(background_value, dtype=crop.dtype)
    #        crop[mask] = bg

    #    # Create the output path
    #    output_path = Path(output_folder, f"{tree_unique_id}.png")

    #    # save cropped img
    #    imwrite(output_path, crop)


def process_folder(
    images_folder,
    renders_folder,
    output_dir,
    images_ext=".JPG",
    renders_ext=".tif",
    n_workers=1,
    ensure_all_images_have_renders=False,
    mask_background: bool = MASK_BACKGROUND,
    mask_buffer_pixels: int = MASK_BUFFER_PIXELS,
    background_value: tuple = BACKGROUND_VALUE,
    image_res_constraint: int = IMAGE_RES_CONSTRAINT,
) -> tuple:
    """
    Chip every image in a folder based on a folder of mask images with a parellel structure, writing
    out the results in a parellel structure as the inputs. For more information, inspect the docstring
    of `chip_images`.
    """
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

    # In some cases, only a subset of the views are rendered, for example with a spatial subset.
    if ensure_all_images_have_renders:
        additional_images = set(images_stems) - set(renders_stems)
        if len(additional_images) > 0:
            raise ValueError(
                f"{len(additional_images)} images do not have a corresponding renders. The first 10 are {list(additional_images)[:10]}"
            )

    with open(Path(renders_folder, "IDs_to_labels.json"), "r") as file_h:
        IDs_to_labels = json.load(file_h)
        IDs_to_labels = {int(k): v for k, v in IDs_to_labels.items()}

    # Rebuild the image file lists to ensure it matches the order of the render files, even if
    # there are images without renders
    image_files = [
        Path(images_folder, render_stem).with_suffix(images_ext)
        for render_stem in renders_stems
    ]
    # Build the output folders list in the same order
    output_folders = [Path(output_dir, render_stem) for render_stem in renders_stems]

    # Create a partial function with arguments that remain unchanged across iterations
    # chip_images_partial = partial(
    #    extract_shapes_from_mask,
    #    IDs_to_labels=IDs_to_labels,
    #    mask_background=mask_background,
    #    mask_buffer_pixels=mask_buffer_pixels,
    #    background_value=background_value,
    #    image_res_constraint=image_res_constraint,
    # )
    with Pool(n_workers) as p:
        shapes = p.map(extract_shapes_from_mask, render_files[:10])
    all_shapes = pd.concat(shapes, ignore_index=True)

    width = all_shapes.bounds.maxx - all_shapes.bounds.minx
    height = all_shapes.bounds.maxy - all_shapes.bounds.miny
    min_dim = np.minimum(width, height)

    all_shapes["min_dim"] = min_dim
    # all_shapes = all_shapes[min_dim >= IMAGE_RES_CONSTRAINT]

    # Does there need to be some filtering here to get rid of multi-part goems

    n_to_take = 20
    min_size = all_shapes.groupby("IDs").apply(
        lambda x: x.nlargest(n_to_take, "min_dim").iloc[-1]["min_dim"]
    )
    breakpoint()


def parse_args():
    parser = ArgumentParser()
    parser.add_argument("images_folder")
    parser.add_argument("renders_folder")
    parser.add_argument("output_folder")
    parser.add_argument("--n-workers", type=int, default=1)
    parser.add_argument("--ensure-all-images-have-renders", action="store_true")
    parser.add_argument(
        "--mask-background",
        default=MASK_BACKGROUND,
        action=BooleanOptionalAction,
        help="Whether to mask out background pixels (default: %(default)s).",
    )
    parser.add_argument(
        "--mask-buffer-pixels",
        type=int,
        default=MASK_BUFFER_PIXELS,
        help="Buffer zone around mask in pixels to retain (default: %(default)s).",
    )
    parser.add_argument(
        "--background-value",
        type=int,
        nargs=3,
        default=list(BACKGROUND_VALUE),
        metavar=("R", "G", "B"),
        help="RGB value for background pixels, 0-255 (default: %(default)s).",
    )
    parser.add_argument(
        "--image-res-constraint",
        type=int,
        default=IMAGE_RES_CONSTRAINT,
        help="Minimum edge length (height and width) in pixels to save a chip (default: %(default)s).",
    )

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
        ensure_all_images_have_renders=args.ensure_all_images_have_renders,
        mask_background=args.mask_background,
        mask_buffer_pixels=args.mask_buffer_pixels,
        background_value=tuple(args.background_value),
        image_res_constraint=args.image_res_constraint,
    )

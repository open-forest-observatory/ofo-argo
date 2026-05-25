import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

from postprocessing import crop_raster_save_cog, transform_to_local_utm


def preprocess(
    plot_id: str,
    dataset_dir: Path,
    local_files: dict,
    min_tree_height: float,
    output_path: Path = Path("/tmp/preprocessed-file-paths.json"),
):
    field_trees_path = local_files["field_trees"]
    plot_bounds_path = local_files["plot_bounds"]
    shift_file_path = local_files["shift"]
    ortho_path = local_files["ortho"]
    chm_path = local_files["chm"]

    # Destination path to save the preprocessed field trees
    ground_truth_path = dataset_dir / "ground_truth.gpkg"

    # Create the "full" directory for cropped rasters if it doesn't exist. This is where
    # crop_raster_save_cog writes to {output_path}/full/{filename}
    (dataset_dir / "full").mkdir(parents=True, exist_ok=True)

    # Load field trees
    field_trees = gpd.read_file(field_trees_path)
    field_trees = field_trees[field_trees["plot_id"] == plot_id].copy()
    print(f"[preprocess] {len(field_trees)} trees for plot_id={plot_id}")

    if len(field_trees) == 0:
        raise ValueError(f"No trees found for plot_id={plot_id} in {field_trees_path}")

    # Load plot bounds
    plot_bounds = gpd.read_file(plot_bounds_path)
    plot_bounds = plot_bounds[plot_bounds["plot_id"] == plot_id].copy()

    if len(plot_bounds) == 0:
        raise ValueError(f"No plot bounds found for plot_id={plot_id} in {plot_bounds_path}")

    # Load the shift information
    shift_df = pd.read_csv(shift_file_path)
    shift_x = float(shift_df["estimated_shift_x"].iloc[0])
    shift_y = float(shift_df["estimated_shift_y"].iloc[0])
    shift_crs = shift_df["shift_CRS"].iloc[0]

    # Convert field trees to the shift CRS
    original_crs = field_trees.crs
    field_trees  = field_trees.to_crs(shift_crs)
    # Apply the shift to the field trees
    field_trees["geometry"] = field_trees.geometry.translate(
        xoff=shift_x, yoff=shift_y
    )
    # Convert back to the original CRS
    field_trees = field_trees.to_crs(original_crs)

    # Filter out short trees based on the provided minimum tree height.
    n_before = len(field_trees)
    field_trees = field_trees[field_trees["height"] >= min_tree_height]
    print(f"[preprocess] Height filter: {n_before} -> {len(field_trees)} trees")

    # Save the shifted field trees as the ground truth for this plot.
    # This is what will be used for matching and evaluation.
    ground_truth_path.parent.mkdir(parents=True, exist_ok=True)
    field_trees.to_file(ground_truth_path)
    print(f"[preprocess] Saved ground_truth.gpkg: {ground_truth_path}")

    # Shift the plot bounds by the same amount as the trees,
    # so that they are aligned with the shifted trees and rasters.
    bounds_original_crs = plot_bounds.crs
    plot_bounds = plot_bounds.to_crs(shift_crs)
    plot_bounds["geometry"] = plot_bounds.geometry.translate(
        xoff=shift_x, yoff=shift_y
    )
    plot_bounds = plot_bounds.to_crs(bounds_original_crs)

    # Save the shifted plot bounds, which will be used for cropping the rasters and
    # for evaluation in a later step.
    shifted_plot_bounds_path = dataset_dir / "shifted_plot_bounds.gpkg"
    plot_bounds.to_file(shifted_plot_bounds_path)
    print(f"[preprocess] Saved shifted_plot_bounds.gpkg: {shifted_plot_bounds_path}")

    plot_bounds_utm = transform_to_local_utm(plot_bounds)
    plot_bounds_buffered = plot_bounds_utm.copy()
    # Buffer the plot bounds by 20 meters
    plot_bounds_buffered["geometry"] = plot_bounds_utm.geometry.buffer(20)
    plot_bounds_buffered = plot_bounds_buffered.to_crs(bounds_original_crs)

    print(f"[preprocess] Cropping orthomosaic to plot bounds")
    crop_raster_save_cog(
        raster_filepath=ortho_path,
        output_filename="cropped_ortho.tif",
        mission_polygon=plot_bounds_buffered,
        output_path=str(dataset_dir),
    )

    print(f"[preprocess] Cropping CHM to plot bounds")
    crop_raster_save_cog(
        raster_filepath=chm_path,
        output_filename="cropped_chm.tif",
        mission_polygon=plot_bounds_buffered,
        output_path=str(dataset_dir),
    )

    cropped_ortho = dataset_dir / "full" / "cropped_ortho.tif"
    cropped_chm = dataset_dir / "full" / "cropped_chm.tif"

    # Check that the cropped files were created successfully
    for f in [cropped_ortho, cropped_chm]:
        if not f.exists():
            raise RuntimeError(f"[preprocess] ERROR: expected cropped file not found: {f}")

    print(f"[preprocess] Cropped ortho: {cropped_ortho}")
    print(f"[preprocess] Cropped CHM:   {cropped_chm}")

    preprocessed_files = {
        **local_files,
        "ortho": str(cropped_ortho),
        "chm":   str(cropped_chm),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(preprocessed_files, f)

    print("[preprocess] preprocessed-file-paths.json written.")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Preprocess field trees and rasters for a single plot."
    )
    parser.add_argument(
        "--plot-id",
        required=True,
        help="Plot ID to subset field trees and plot bounds.",
    )
    parser.add_argument(
        "--dataset-dir",
        required=True,
        type=Path,
        help="Directory for dataset outputs.",
    )
    parser.add_argument(
        "--local-files",
        required=True,
        help="JSON string of local file paths (ortho, chm, shift, field_trees, plot_bounds).",
    )
    parser.add_argument(
        "--min-tree-height",
        required=True,
        type=float,
        help="Minimum tree height (meters) used to filter field trees.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("/tmp/preprocessed-file-paths.json"),
        help="Path to write the preprocessed file paths JSON.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    preprocess(
        plot_id=args.plot_id,
        dataset_dir=args.dataset_dir,
        local_files=json.loads(args.local_files),
        min_tree_height=args.min_tree_height,
        output_path=args.output_path,
    )

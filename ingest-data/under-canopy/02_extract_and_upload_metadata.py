"""
Extract per-image metadata from a folder of GoPro 360 images and save it as a
GeoPackage, with one row per image.

Reads every tag exiftool reports for each image (dynamically, not a fixed
schema), drops any fields holding large embedded binary data (thumbnails,
previews), and builds a point geometry from each image's GPS coordinates
when present.

Requires the `exiftool` binary and the `pandas` / `geopandas` / `shapely`
Python packages (see the `exif-parsing` conda environment).

Usage:
    python 02_extract_metadata.py <input_data_folder> <output_file.gpkg>

    # Also upload the result to S3:
    python 02_extract_metadata.py <input_data_folder> <output_file.gpkg> \
        --s3-dest <path_on_s3>
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

RCLONE_REMOTE = "js2s3"

BINARY_PLACEHOLDER_RE = re.compile(r"^\(Binary data \d+ bytes")

IMAGE_EXTENSIONS = ["jpg", "JPG", "jpeg", "JPEG"]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input_data_folder", type=Path, help="Folder of images to search (recursively)."
    )
    parser.add_argument(
        "output_file", type=Path, help="Path to write the output GeoPackage to."
    )
    parser.add_argument(
        "--s3-dest",
        type=str,
        default=None,
        help=(
            "S3 path to upload the output file to, without the rclone remote "
            f"prefix (e.g. 'ofo-public/under-canopy/mission_01/image-metadata.gpkg'). "
            f"Uploaded via the '{RCLONE_REMOTE}' rclone remote. If omitted, no upload "
            "is performed."
        ),
    )
    return parser.parse_args()


def rclone_copyto(src, dst):
    """Run an rclone copyto command (single file)."""
    cmd = ["rclone", "copyto", src, dst]
    print(f"  rclone copyto {src} -> {dst}", file=sys.stderr)
    subprocess.run(cmd, check=True)


def run_exiftool(input_data_folder):
    """Run exiftool once over the whole folder tree and return the parsed records."""
    cmd = ["exiftool", "-json", "-n", "-r"]
    for ext in IMAGE_EXTENSIONS:
        cmd += ["-ext", ext]
    cmd.append(str(input_data_folder))

    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def drop_binary_fields(df):
    """Drop any column whose values are exiftool's binary-data placeholders."""
    binary_columns = [
        col
        for col in df.columns
        if df[col]
        .apply(lambda v: isinstance(v, str) and bool(BINARY_PLACEHOLDER_RE.match(v)))
        .any()
    ]
    return df.drop(columns=binary_columns)


def stringify_nested_fields(df):
    """GeoPackage columns must hold scalar values; JSON-encode any list/dict fields."""
    for col in df.columns:
        if df[col].apply(lambda v: isinstance(v, (list, dict))).any():
            df[col] = df[col].apply(
                lambda v: json.dumps(v) if isinstance(v, (list, dict)) else v
            )
    return df


def build_geometry(df):
    """Build a GPS point geometry column, leaving rows without GPS as null geometry."""
    # TODO consider using a list of candidate column names to be more flexible
    if "GPSLongitude" not in df.columns or "GPSLatitude" not in df.columns:
        return [None] * len(df)

    return [
        Point(lon, lat) if pd.notna(lon) and pd.notna(lat) else None
        for lon, lat in zip(df["GPSLongitude"], df["GPSLatitude"])
    ]


def main():
    args = parse_args()

    records = run_exiftool(args.input_data_folder)
    if not records:
        raise SystemExit(f"No images found under {args.input_data_folder}")

    df = pd.DataFrame(records)
    df = df.sort_values("SourceFile").reset_index(drop=True)
    df = drop_binary_fields(df)
    df = stringify_nested_fields(df)

    geometry = build_geometry(df)
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(args.output_file, driver="GPKG")

    n_with_gps = sum(g is not None for g in geometry)
    print(f"Wrote {len(gdf)} rows ({len(gdf.columns)} columns) to {args.output_file}")
    print(f"  {n_with_gps} images had GPS coordinates, {len(gdf) - n_with_gps} did not")

    if args.s3_dest:
        rclone_copyto(str(args.output_file), f"{RCLONE_REMOTE}:{args.s3_dest}")


if __name__ == "__main__":
    main()

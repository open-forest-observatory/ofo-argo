"""
Check user-entered collect metadata against image metadata.

Matches each image to a collect using the collect's file prefixes and its
start/end times (with some flexibility for camera clock drift), then reports:
  - collects with no matching images, long gaps between images, or images
    outside the time bounds (each gets a timeline plot)
  - images matched to more than one collect
  - images not matched to any collect (written to a CSV and plotted)
  - for unmatched images, which collects' time windows they fall within, i.e.
    collects they would have matched if their prefix were listed
  - maps of GPS locations of matched images and those potential matches, one
    per collect (only for images with GPSLatitude/GPSLongitude)

The image metadata can be the GeoPackage written by 02_extract_and_upload_metadata.py
(.gpkg), exiftool JSON output (.json), or a CSV (.csv). It needs SourceFile and
DateTimeOriginal ("YYYY:MM:DD HH:MM:SS") columns, and GPSLatitude and GPSLongitude
in decimal degrees for the location maps (as written by exiftool -n).

Usage:
    python util_check_collect_metadata.py <mission_metadata_csv> <image_metadata> \
        <output_folder>

    # Only make the per-date plots of unmatched images, and skip the GPS maps:
    python util_check_collect_metadata.py <mission_metadata_csv> <image_metadata> \
        <output_folder> --unmatched-plot-mode by_date --skip-location-plots

Outputs, all inside <output_folder>:
    unmatched_images.csv        images not matched to any collect
    collect_visualizations/     timelines for collects flagged as problematic
    unmatched_visualizations/   timelines of unmatched images (cleared each run)
    unmatched_images_in_collect_windows.csv
                                each unmatched image paired with every collect
                                whose time window it falls within
    potential_match_locations/  GPS maps of matched vs. potential images per
                                collect (cleared each run)
"""

import argparse
import shutil
from datetime import timedelta
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Images within this much of a collect's start/end times are matched to it
TIMESTAMP_FLEXIBILITY = timedelta(seconds=6 * 60)
# Wider window used to look for images that are close to, but outside, a collect
TIMESTAMP_CHECK_DELTA = timedelta(seconds=60 * 60)
# Gaps between consecutive images longer than this (seconds) are reported
TIMESTAMP_MAX_GAP = 60 * 0.5

UNMATCHED_PLOT_MODES = ("by_date", "by_date_prefix", "both", "none")

MATCHED_COLOR = "tab:blue"
POTENTIAL_COLOR = "tab:orange"


def check_for_duplicates(
    image_metadata, all_matched_image_metadata, unmatched_images_output_file
):
    # Check for images that were matched to more than one collect
    duplicated_images = all_matched_image_metadata[
        all_matched_image_metadata.SourceFile.duplicated(keep=False)
    ]
    print(
        f"{duplicated_images.SourceFile.nunique()} images matched to multiple collects "
        f"({len(duplicated_images)} rows)"
    )
    if len(duplicated_images) > 0:
        collects_per_duplicated_image = duplicated_images.groupby(
            "SourceFile"
        ).collect_ID.apply(lambda ids: tuple(sorted(ids)))
        print("Collect ID combinations for duplicated images (and counts):")
        print(collects_per_duplicated_image.value_counts().to_string())

    # Check for images that were not matched to any collect
    unmatched_images = image_metadata[
        ~image_metadata.SourceFile.isin(all_matched_image_metadata.SourceFile)
    ]
    print(f"{len(unmatched_images)} images not matched to any collect")

    unmatched_images.to_csv(unmatched_images_output_file)

    return unmatched_images


def read_image_metadata(image_metadata_file):
    """Read per-image metadata from a GeoPackage, exiftool JSON or CSV file.

    Returns a DataFrame with SourceFile, DateTimeOriginal, GPSLatitude and
    GPSLongitude columns. GPS columns are filled with NaN if the file has none.
    """
    image_metadata_file = Path(image_metadata_file)
    suffix = image_metadata_file.suffix.lower()
    if suffix == ".gpkg":
        image_metadata = pd.DataFrame(
            gpd.read_file(image_metadata_file).drop(columns="geometry")
        )
    elif suffix == ".json":
        image_metadata = pd.read_json(image_metadata_file)
    elif suffix == ".csv":
        image_metadata = pd.read_csv(image_metadata_file)
    else:
        raise ValueError(
            f"Unsupported image metadata file type {suffix!r}; "
            "expected .gpkg, .json or .csv"
        )

    missing = {"SourceFile", "DateTimeOriginal"} - set(image_metadata.columns)
    if missing:
        raise ValueError(
            f"{image_metadata_file} is missing required columns: {sorted(missing)}"
        )

    columns = ["SourceFile", "DateTimeOriginal", "GPSLatitude", "GPSLongitude"]
    for col in ["GPSLatitude", "GPSLongitude"]:
        if col not in image_metadata:
            print(f"{image_metadata_file} has no {col} column; images have no GPS")
            image_metadata[col] = np.nan
        image_metadata[col] = pd.to_numeric(image_metadata[col], errors="coerce")

    return image_metadata[columns].copy()


def load_and_preprocess(mission_metadata_file, image_metadata_file):
    mission_metadata = pd.read_csv(mission_metadata_file, encoding="utf-8-sig")
    image_metadata = read_image_metadata(image_metadata_file)

    # Standardization
    # Convert from string to datetime
    image_metadata["DateTimeOriginal"] = pd.to_datetime(
        image_metadata["DateTimeOriginal"], format="%Y:%m:%d %H:%M:%S"
    )
    # Extract the prefix from the filename
    image_metadata["prefix"] = (
        image_metadata["SourceFile"].str.split("/").str[-1].str[:4]
    )

    # Subset columns. contributor_dataset_name is optional and only used for labels
    columns = [
        "collect_id",
        "collect_start_datetime",
        "collect_end_datetime",
        "file_prefixes",
    ]
    if "contributor_dataset_name" in mission_metadata:
        columns.append("contributor_dataset_name")
    mission_metadata = mission_metadata[columns].copy()
    # Get a list of file prefixes
    mission_metadata.file_prefixes = mission_metadata.file_prefixes.str.split(" ")
    # Convert the start and end time to datetimes
    mission_metadata["collect_start_datetime"] = pd.to_datetime(
        mission_metadata["collect_start_datetime"], format="%Y-%m-%d %H:%M"
    )
    mission_metadata["collect_end_datetime"] = pd.to_datetime(
        mission_metadata["collect_end_datetime"], format="%Y-%m-%d %H:%M"
    )

    return mission_metadata, image_metadata


def match_images_to_collects(
    mission_metadata,
    image_metadata,
    vis_folder,
    timestamp_flexibility=TIMESTAMP_FLEXIBILITY,
    timestamp_check_delta=TIMESTAMP_CHECK_DELTA,
    timestamp_max_gap=TIMESTAMP_MAX_GAP,
):
    all_matched_image_metadata = []

    for _, row in mission_metadata.iterrows():
        collect_id = row["collect_id"]

        images_matching_prefix = image_metadata[
            image_metadata.prefix.isin(row["file_prefixes"])
        ]

        # Filter with a generous flexibility
        # This is meant to catch any images that could plausibly match to this user-entered metadata record
        start_time = row["collect_start_datetime"] - timestamp_check_delta
        end_time = row["collect_end_datetime"] + timestamp_check_delta
        images_to_check = images_matching_prefix[
            (images_matching_prefix.DateTimeOriginal > start_time)
            & (images_matching_prefix.DateTimeOriginal < end_time)
        ]

        # Important, these must be sorted
        images_to_check = images_to_check.sort_values("DateTimeOriginal")

        # Compute the max gap within this range
        max_delta_seconds = (
            images_to_check.DateTimeOriginal.diff().dt.total_seconds().max()
        )

        plot = False

        if len(images_to_check) == 0:
            images_matching_prefix.DateTimeOriginal.dt.date().unique()
            print(f"collect id {collect_id}: had no matching images")
            plot = True

        if max_delta_seconds > timestamp_max_gap:
            print(f"collect id {collect_id}: max delta {max_delta_seconds}")
            plot = True

        # See if there are any images outside of the flexibility afforded for timesync issues
        start_time = row["collect_start_datetime"] - timestamp_flexibility
        end_time = row["collect_end_datetime"] + timestamp_flexibility

        images_matching_time_bounds = images_to_check[
            (images_to_check.DateTimeOriginal > start_time)
            & (images_to_check.DateTimeOriginal < end_time)
        ]

        if len(images_to_check) != len(images_matching_time_bounds):
            print(f"collect id {collect_id}: images outside of bounds")
            plot = True

        images_matching_time_bounds["collect_ID"] = collect_id
        all_matched_image_metadata.append(images_matching_time_bounds)

        if plot:
            plt.scatter(
                images_to_check.DateTimeOriginal,
                np.zeros_like(images_to_check.DateTimeOriginal),
                c="b",
                label="Image metadata timetamps",
            )
            plt.scatter(
                [row["collect_start_datetime"], row["collect_end_datetime"]],
                [0, 0],
                c="r",
                label="User-provided start and end",
            )
            plt.legend()
            plt.savefig(f"{vis_folder}/{collect_id}.png")
            plt.close("all")

    all_matched_image_metadata = pd.concat(all_matched_image_metadata)
    all_matched_image_metadata = all_matched_image_metadata.sort_values("SourceFile")
    return all_matched_image_metadata


def plot_unmatched_by_date(unmatched_images, output_folder):
    """One plot per date, with each prefix on its own row."""
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    df = unmatched_images.sort_values("DateTimeOriginal")
    for date, group in df.groupby(df["DateTimeOriginal"].dt.date):
        for i, (prefix, g) in enumerate(group.groupby("prefix", sort=True)):
            plt.scatter(g["DateTimeOriginal"], [i] * len(g), label=prefix)

        plt.legend()
        plt.xticks(rotation=90)
        plt.tight_layout()
        plt.savefig(Path(output_folder, f"{date}.png"))
        plt.close()


def plot_unmatched_by_date_prefix(unmatched_images, output_folder):
    """One plot per (date, prefix) group, file names ordered from largest group to smallest."""
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    df = unmatched_images.sort_values("DateTimeOriginal")
    grouped = df.groupby([df["DateTimeOriginal"].dt.date.rename("date"), "prefix"])
    group_sizes = grouped.size().sort_values(ascending=False)

    for rank, ((date, prefix), size) in enumerate(group_sizes.items()):
        g = grouped.get_group((date, prefix))

        plt.scatter(g["DateTimeOriginal"], [0] * len(g), label=prefix)
        plt.title(f"{date} | {prefix} | n={size}")
        plt.yticks([])
        plt.xticks(rotation=90)
        plt.tight_layout()
        plt.savefig(Path(output_folder, f"{rank:03d}_{date}_{prefix}_n{size}.png"))
        plt.close()


def plot_unmatched_images(unmatched_images, output_folder, mode="both"):
    """Plot unmatched image timestamps.

    mode:
        "by_date"        - one plot per date, each prefix on its own row
        "by_date_prefix" - one plot per (date, prefix) group, ordered by group size
        "both"           - both, in by_date/ and by_date_prefix/ subfolders

    output_folder is deleted and recreated so plots from earlier runs don't linger.
    """
    if mode not in ("by_date", "by_date_prefix", "both"):
        raise ValueError(f"Unknown mode: {mode!r}")

    shutil.rmtree(output_folder, ignore_errors=True)

    if mode == "by_date":
        plot_unmatched_by_date(unmatched_images, output_folder)
    elif mode == "by_date_prefix":
        plot_unmatched_by_date_prefix(unmatched_images, output_folder)
    else:
        plot_unmatched_by_date(unmatched_images, Path(output_folder, "by_date"))
        plot_unmatched_by_date_prefix(
            unmatched_images, Path(output_folder, "by_date_prefix")
        )


def find_potential_collects(
    unmatched_images, mission_metadata, timestamp_flexibility=TIMESTAMP_FLEXIBILITY
):
    """Pair each unmatched image with every collect whose time window it falls in.

    The window is the collect's start/end +/- timestamp_flexibility, the same as
    used for matching, so each pair is a collect the image would have matched if
    its prefix were listed in that collect's file_prefixes.

    Returns one row per (image, collect) pair, sorted by time, with an
    n_candidate_collects column giving how many collects each image could belong to.
    """
    collect_columns = [
        c
        for c in [
            "collect_id",
            "contributor_dataset_name",
            "file_prefixes",
            "collect_start_datetime",
            "collect_end_datetime",
        ]
        if c in mission_metadata
    ]
    collects = mission_metadata.dropna(
        subset=["collect_start_datetime", "collect_end_datetime"]
    )[collect_columns]
    n_skipped = len(mission_metadata) - len(collects)
    if n_skipped:
        print(f"Skipping {n_skipped} collects with missing start/end times")

    pairs = unmatched_images.merge(collects, how="cross")
    potential = pairs[
        (
            pairs["DateTimeOriginal"]
            > pairs["collect_start_datetime"] - timestamp_flexibility
        )
        & (
            pairs["DateTimeOriginal"]
            < pairs["collect_end_datetime"] + timestamp_flexibility
        )
    ].copy()
    potential["n_candidate_collects"] = potential.groupby("SourceFile")[
        "collect_id"
    ].transform("size")
    return potential.sort_values(["DateTimeOriginal", "collect_id"])


def summarize_potential_collects(potential, n_unmatched):
    """Print how many unmatched images could belong to a collect, grouped by
    collect and prefix, largest groups first. Returns the summary table."""
    n_images = potential["SourceFile"].nunique()
    n_multi = potential.loc[
        potential["n_candidate_collects"] > 1, "SourceFile"
    ].nunique()
    print(
        f"{n_images} of {n_unmatched} unmatched images fall within at least one "
        f"collect's time window ({n_multi} within more than one)"
    )
    if potential.empty:
        return None

    group_columns = [
        c
        for c in ["collect_id", "contributor_dataset_name", "prefix"]
        if c in potential
    ]
    summary = (
        potential.assign(
            collect_prefixes=potential["file_prefixes"].map(
                lambda p: " ".join(p) if isinstance(p, list) else p
            )
        )
        .groupby(group_columns, dropna=False)
        .agg(
            n_images=("SourceFile", "size"),
            n_single_candidate=(
                "n_candidate_collects",
                lambda n: int((n == 1).sum()),
            ),
            first=("DateTimeOriginal", "min"),
            last=("DateTimeOriginal", "max"),
            collect_prefixes=("collect_prefixes", "first"),
            collect_start=("collect_start_datetime", "first"),
            collect_end=("collect_end_datetime", "first"),
        )
        .sort_values("n_images", ascending=False)
    )
    with pd.option_context(
        "display.max_rows", None, "display.max_columns", None, "display.width", 250
    ):
        print(summary)
    return summary


def plot_collect_locations(matched, potential, title, output_path):
    """Map matched and potential images for one collect, in local UTM meters.

    Both inputs need GPSLatitude, GPSLongitude and prefix columns. Images without
    GPS are left out and counted in the title. Returns False if nothing had GPS.
    """
    both = pd.concat(
        [matched.assign(kind="matched"), potential.assign(kind="potential")]
    )
    n_no_gps = both["GPSLatitude"].isna().sum()
    both = both.dropna(subset=["GPSLatitude", "GPSLongitude"])
    if both.empty:
        return False

    gdf = gpd.GeoDataFrame(
        both,
        geometry=gpd.points_from_xy(both["GPSLongitude"], both["GPSLatitude"]),
        crs="EPSG:4326",
    )
    gdf = gdf.to_crs(gdf.estimate_utm_crs())

    fig, ax = plt.subplots(figsize=(8, 8))
    for kind, color in [("matched", MATCHED_COLOR), ("potential", POTENTIAL_COLOR)]:
        sub = gdf[gdf["kind"] == kind]
        prefixes = " ".join(sorted(sub["prefix"].unique()))
        ax.scatter(
            sub.geometry.x,
            sub.geometry.y,
            s=6,
            c=color,
            alpha=0.7,
            label=f"{kind} (n={len(sub)}; {prefixes})",
        )
    ax.set_aspect("equal")
    ax.set_xlabel(f"Easting (m, {gdf.crs.name})")
    ax.set_ylabel("Northing (m)")
    if n_no_gps:
        title += f"\n({n_no_gps} images without GPS not shown)"
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return True


def plot_potential_match_locations(
    all_matched_image_metadata,
    potential,
    output_folder,
    only_single_candidate=True,
):
    """Map matched vs. potential images for each collect that has potential matches.

    Both inputs need the GPSLatitude and GPSLongitude columns carried through from
    the image metadata. potential is the output of find_potential_collects. If
    only_single_candidate
    is True, images that fall within more than one collect's window are left out,
    so every potential image shown has exactly one possible collect.

    output_folder is deleted and recreated so maps from earlier runs don't linger.
    """
    if only_single_candidate:
        n_multi = potential.loc[
            potential["n_candidate_collects"] > 1, "SourceFile"
        ].nunique()
        print(f"Leaving out {n_multi} images that fall within more than one collect")
        potential = potential[potential["n_candidate_collects"] == 1]

    collect_ids = sorted(potential["collect_id"].unique())
    matched = all_matched_image_metadata[
        all_matched_image_metadata["collect_ID"].isin(collect_ids)
    ]

    output_folder = Path(output_folder)
    shutil.rmtree(output_folder, ignore_errors=True)
    output_folder.mkdir(parents=True, exist_ok=True)

    for collect_id in collect_ids:
        m = matched[matched["collect_ID"] == collect_id]
        p = potential[potential["collect_id"] == collect_id]

        title = f"collect {collect_id}"
        if (
            "contributor_dataset_name" in p
            and p["contributor_dataset_name"].notna().any()
        ):
            title += f": {p['contributor_dataset_name'].dropna().iloc[0]}"

        plotted = plot_collect_locations(
            m,
            p,
            title,
            output_folder
            / f"collect_{collect_id:06}_prefix_{'_'.join(sorted(p['prefix'].unique()))}.png",
        )

        n_no_gps = m["GPSLatitude"].isna().sum() + p["GPSLatitude"].isna().sum()
        print(
            f"collect {collect_id}: {len(m)} matched, {len(p)} potential, "
            f"{n_no_gps} without GPS" + ("" if plotted else " (no GPS, not plotted)")
        )


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "mission_metadata",
        type=Path,
        help=(
            "CSV of user-entered collect metadata, with collect_id, "
            "collect_start_datetime, collect_end_datetime and file_prefixes columns."
        ),
    )
    parser.add_argument(
        "image_metadata",
        type=Path,
        help=(
            "Per-image metadata as a GeoPackage (from 02_extract_and_upload_metadata.py), "
            "exiftool -json -n output, or CSV. Needs SourceFile and DateTimeOriginal; "
            "GPSLatitude and GPSLongitude are used for the location maps."
        ),
    )
    parser.add_argument(
        "output_folder",
        type=Path,
        help="Folder to write the unmatched-images CSV and visualizations to.",
    )
    parser.add_argument(
        "--unmatched-plot-mode",
        choices=UNMATCHED_PLOT_MODES,
        default="both",
        help=(
            "How to plot unmatched images: one plot per date (by_date), one per "
            "date and prefix (by_date_prefix), both, or none. Default: both."
        ),
    )
    parser.add_argument(
        "--timestamp-flexibility-minutes",
        type=float,
        default=TIMESTAMP_FLEXIBILITY.total_seconds() / 60,
        help=(
            "Images within this many minutes of a collect's start/end are matched "
            "to it. Default: %(default)s."
        ),
    )
    parser.add_argument(
        "--timestamp-check-delta-minutes",
        type=float,
        default=TIMESTAMP_CHECK_DELTA.total_seconds() / 60,
        help=(
            "Window, in minutes either side of a collect, searched for nearby "
            "images that fall outside the matching bounds. Default: %(default)s."
        ),
    )
    parser.add_argument(
        "--max-gap-seconds",
        type=float,
        default=TIMESTAMP_MAX_GAP,
        help=(
            "Report collects with a gap between consecutive images longer than "
            "this. Default: %(default)s."
        ),
    )
    parser.add_argument(
        "--skip-location-plots",
        action="store_true",
        help=("Don't map GPS locations of matched and potential images."),
    )
    parser.add_argument(
        "--include-multi-candidate",
        action="store_true",
        help=(
            "In the GPS maps, also show unmatched images that fall within more than "
            "one collect's time window. By default only images with exactly one "
            "possible collect are shown."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()

    collect_vis_folder = args.output_folder / "collect_visualizations"
    collect_vis_folder.mkdir(parents=True, exist_ok=True)

    mission_metadata, image_metadata = load_and_preprocess(
        args.mission_metadata, args.image_metadata
    )

    all_matched_image_metadata = match_images_to_collects(
        mission_metadata,
        image_metadata,
        vis_folder=collect_vis_folder,
        timestamp_flexibility=timedelta(minutes=args.timestamp_flexibility_minutes),
        timestamp_check_delta=timedelta(minutes=args.timestamp_check_delta_minutes),
        timestamp_max_gap=args.max_gap_seconds,
    )

    # Check for images matching zero or multiple collects
    unmatched_images = check_for_duplicates(
        image_metadata=image_metadata,
        all_matched_image_metadata=all_matched_image_metadata,
        unmatched_images_output_file=args.output_folder / "unmatched_images.csv",
    )

    # Visualize the timestamps of images that weren't matched to any collect
    if args.unmatched_plot_mode != "none":
        plot_unmatched_images(
            unmatched_images,
            args.output_folder / "unmatched_visualizations",
            mode=args.unmatched_plot_mode,
        )

    # Find collects that unmatched images would have matched if their prefix were listed
    timestamp_flexibility = timedelta(minutes=args.timestamp_flexibility_minutes)
    potential = find_potential_collects(
        unmatched_images, mission_metadata, timestamp_flexibility
    )
    summarize_potential_collects(potential, n_unmatched=len(unmatched_images))
    potential_csv = args.output_folder / "unmatched_images_in_collect_windows.csv"
    potential.assign(
        file_prefixes=potential["file_prefixes"].map(
            lambda p: " ".join(p) if isinstance(p, list) else p
        )
    ).to_csv(potential_csv, index=False)
    print(f"Wrote {potential_csv}")

    # Map where those images were taken relative to each collect's matched images
    if not args.skip_location_plots and not potential.empty:
        plot_potential_match_locations(
            all_matched_image_metadata,
            potential,
            args.output_folder / "potential_match_locations",
            only_single_candidate=not args.include_multi_candidate,
        )


if __name__ == "__main__":
    main()

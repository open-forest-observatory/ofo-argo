import pandas as pd
from datetime import timedelta
import matplotlib.pyplot as plt

import numpy as np

MISSION_METADATA = "/ofo-share/repos/david/ofo-argo/scratch/gopro-timestamp-issues/mission_metadata.csv"
TIMESTAMPS = (
    "/ofo-share/repos/david/ofo-argo/scratch/gopro-timestamp-issues/timestamps.json"
)
OUTPUT_UNMATCHED_IMAGES = "/ofo-share/repos/david/ofo-argo/scratch/gopro-timestamp-issues/unmatched_images.csv"

#
TIMESTAMP_FLEXIBILITY = timedelta(seconds=6 * 60)
TIMESTAMP_CHECK_DELTA = timedelta(seconds=60 * 60)

TIMESTAMP_MAX_GAP = 60 * 0.5

mission_metadata = pd.read_csv(MISSION_METADATA)
image_metadata = pd.read_json(TIMESTAMPS)

# Standardization
# Convert from string to datetime
image_metadata["DateTimeOriginal"] = pd.to_datetime(
    image_metadata["DateTimeOriginal"], format="%Y:%m:%d %H:%M:%S"
)
# Extract the prefix from the filename
image_metadata["prefix"] = image_metadata["SourceFile"].str.split("/").str[-1].str[:4]

# Subset columns
mission_metadata = mission_metadata[
    ["collect_id", "collect_start_datetime", "collect_end_datetime", "file_prefixes"]
]
# Get a list of file prefixes
mission_metadata.file_prefixes = mission_metadata.file_prefixes.str.split(" ")
# Convert the start and end time to datetimes
mission_metadata["collect_start_datetime"] = pd.to_datetime(
    mission_metadata["collect_start_datetime"], format="%Y-%m-%d %H:%M"
)
mission_metadata["collect_end_datetime"] = pd.to_datetime(
    mission_metadata["collect_end_datetime"], format="%Y-%m-%d %H:%M"
)

all_matched_image_metadata = []

#
for id, row in mission_metadata.iterrows():
    collect_id = row["collect_id"]

    images_matching_prefix = image_metadata[
        image_metadata.prefix.isin(row["file_prefixes"])
    ]

    # Filter with a generous flexibility
    # This is meant to catch any images that could plausibly match to this user-entered metadata record
    start_time = row["collect_start_datetime"] - TIMESTAMP_CHECK_DELTA
    end_time = row["collect_end_datetime"] + TIMESTAMP_CHECK_DELTA
    images_to_check = images_matching_prefix[
        (images_matching_prefix.DateTimeOriginal > start_time)
        & (images_matching_prefix.DateTimeOriginal < end_time)
    ]

    # Important, these must be sorted
    images_to_check = images_to_check.sort_values("DateTimeOriginal")

    # Compute the max gap within this range
    max_delta_seconds = images_to_check.DateTimeOriginal.diff().dt.total_seconds().max()

    plot = False

    if collect_id == 155:
        breakpoint()

    if len(images_to_check) == 0:
        breakpoint()
        images_matching_prefix.DateTimeOriginal.dt.date().unique()
        print(f"collect id {collect_id}: had no matching images")
        plot = True

    if max_delta_seconds > TIMESTAMP_MAX_GAP:
        print(f"collect id {collect_id}: max delta {max_delta_seconds}")
        plot = True

    # See if there are any images outside of the flexibility afforded for timesync issues
    start_time = row["collect_start_datetime"] - TIMESTAMP_FLEXIBILITY
    end_time = row["collect_end_datetime"] + TIMESTAMP_FLEXIBILITY

    images_matching_time_bounds = images_to_check[
        (images_to_check.DateTimeOriginal > start_time)
        & (images_to_check.DateTimeOriginal < end_time)
    ]

    if len(images_to_check) != len(images_matching_time_bounds):
        print(f"collect id {collect_id}: images outside of bounds")
        plot = True

    images_matching_time_bounds["collect_ID"] = collect_id
    all_matched_image_metadata.append(images_matching_time_bounds)

    if plot or collect_id == 13:
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
        plt.savefig(
            f"/ofo-share/repos/david/ofo-argo/scratch/gopro-timestamp-issues/long_gap_visualizations/{collect_id}.png"
        )
        plt.close("all")

all_matched_image_metadata = pd.concat(all_matched_image_metadata)
all_matched_image_metadata = all_matched_image_metadata.sort_values("SourceFile")

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

unmatched_images.to_csv(OUTPUT_UNMATCHED_IMAGES)
#

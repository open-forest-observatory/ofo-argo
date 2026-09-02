from pathlib import Path
import argparse
import re
import os
import json
import shutil
import subprocess
import pandas as pd
from datetime import datetime, timedelta


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "input_data_folder",
        default=Path("/ofo-share/under-canopy-imagery-organization/0_raw/"),
        type=Path,
    )
    parser.add_argument(
        "output_data_folder",
        default=Path(
            "/ofo-share/under-canopy-imagery-organization/1_manually-cleaned/"
        ),
        type=Path,
    )
    parser.add_argument(
        "--collect-id",
        type=str,
        required=True,
        help="The OFO collect ID for this dataset, zero-padded to six digits.",
    )
    parser.add_argument(
        "--file-prefixes",
        type=str,
        required=True,
        help="One or more space-separated file prefixes for this mission.",
    )
    parser.add_argument(
        "--collect-start-datetime",
        type=str,
        required=True,
        help="Start of the inclusive datetime range to include, in 'YYYY-MM-DD HH:MM' format (e.g. '2026-08-15 09:30').",
    )
    parser.add_argument(
        "--collect-end-datetime",
        type=str,
        required=True,
        help="End of the inclusive datetime range to include, in 'YYYY-MM-DD HH:MM' format (e.g. '2026-08-15 11:30').",
    )
    parser.add_argument(
        "--max-allowable-delta",
        type=float,
        default=120.0,
        help="Fail if the max delta between image timestamps is greater than this number of seconds.",
    )
    parser.add_argument(
        "--time-bounds-tolerance",
        type=float,
        default=120.0,
        help="Include images within this number of seconds of the provided time bounds to account for sychronization errors between devices",
    )

    return parser.parse_args()


def main(
    input_data_folder: Path,
    output_data_folder: Path,
    collect_id: str,
    file_prefixes: str,
    collect_start_datetime: str,
    collect_end_datetime: str,
    max_allowable_delta: float = 120.0,
    time_bounds_tolerance: float = 120.0,
):
    """Subset images based on file_prefixes and a datetime range and hardlink to an output folder named based on the collect_id

    Args:
        input_data_folder (Path): Where to search for matching files
        output_data_folder (Path): Where to write the subset of matching images.
        collect_id (str): A six character string representing a zero-padded integer. The output images are written to {output_data_folder}/{collect_id}/images/
        file_prefixes (str): A space-separated list of file prefixes to include
        collect_start_datetime (str): Start of the inclusive datetime range in 'YYYY-MM-DD HH:MM' format.
        collect_end_datetime (str): End of the inclusive datetime range in 'YYYY-MM-DD HH:MM' format.
        max_allowable_delta (float): Fail if the difference in timestamps between any pair of consecutive images is larger than this number of seconds.
        time_bounds_tolerance (float): Include images within this number of seconds of the provided time bounds to account for sychronization errors between devices",

    Raises:
        ValueError: if the maximum delta between timestamps is larger than max_allowable_delta
    """
    print("Searching for files")
    # Find all files in the folder
    matching_files = list(input_data_folder.rglob("*"))

    print(f"Found {len(matching_files)}")
    # Find files matching any of the prefixes
    # Split the space-separated prefixes into individual prefixes
    file_prefixes = file_prefixes.split()
    matching_files = [
        str(f)
        for f in matching_files
        if (
            re.match("|".join(re.escape(p) for p in file_prefixes), f.name)
            and f.is_file()
        )
    ]

    print(f"Found {len(matching_files)} files which matched the file prefixes")
    # Parse the exif to determine the timestamp
    cmd = ["exiftool", "-DateTimeOriginal", "-json", "-n"] + matching_files

    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    # Convert to a dataframe with just the filename and datetime
    exif = pd.DataFrame(json.loads(result.stdout))[["SourceFile", "DateTimeOriginal"]]
    exif["DateTimeOriginal"] = pd.to_datetime(
        exif["DateTimeOriginal"], format="%Y:%m:%d %H:%M:%S"
    )

    # Sort by time
    exif = exif.sort_values(by="DateTimeOriginal")
    # Extract only the rows within the requested datetime range (inclusive)
    # This step adds the time_bound_tolerance to the window to make it more permissive
    start_dt = datetime.strptime(collect_start_datetime, "%Y-%m-%d %H:%M") - timedelta(
        seconds=time_bounds_tolerance
    )
    end_dt = (datetime.strptime(collect_end_datetime, "%Y-%m-%d %H:%M")) + timedelta(
        seconds=time_bounds_tolerance
    )
    exif = exif[(exif.DateTimeOriginal >= start_dt) & (exif.DateTimeOriginal <= end_dt)]

    # Check for large gaps in the timestamps
    max_delta_seconds = exif.DateTimeOriginal.diff().dt.total_seconds().max()
    print(f"Max delta {max_delta_seconds}")

    # Write a warning file if the gap is too large so the workflow can aggregate it.
    # Written to a sibling directory (not inside the per-collect folder) so the cleanup
    # step, which removes only the per-collect folder, doesn't delete it.
    if max_delta_seconds > max_allowable_delta:
        warning_file = Path(
            output_data_folder, "timestamp-gap-warnings", f"{collect_id}.json"
        )
        warning_file.parent.mkdir(parents=True, exist_ok=True)
        with open(warning_file, "w") as outfile:
            json.dump(
                {"collect_id": collect_id, "max_delta_seconds": max_delta_seconds},
                outfile,
            )
    print(
        f"The maximum time difference between consecutive images was {max_delta_seconds} seconds"
    )

    matching_files = exif.SourceFile.to_list()
    print(f"Found {len(matching_files)} files within the specified datetime range")

    # Create an output folder based on the output folder / collect_id
    output_folder = Path(output_data_folder, f"{collect_id}/images")
    # remove old folder, if present
    shutil.rmtree(output_folder, ignore_errors=True)
    # And recreate
    output_folder.mkdir(parents=True, exist_ok=True)

    # Hardlink all files to that location
    # The output format should be {collect_id}/images/{collect_id}_{image_id:06d}.JPG
    filename_remapping = {
        str(in_f): str(Path(output_folder, f"{collect_id}_{i:06d}.JPG"))
        for i, in_f in enumerate(matching_files)
    }

    # Perform the hardlinking
    for in_f, out_f in filename_remapping.items():
        os.link(in_f, out_f)

    # Write out the file summarizing the renaming
    with open(Path(output_folder, "filename-remapping.json"), "w") as outfile_h:
        json.dump(filename_remapping, outfile_h)


if __name__ == "__main__":
    args = parse_args()

    main(**args.__dict__)

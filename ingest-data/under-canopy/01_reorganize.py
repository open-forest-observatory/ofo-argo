from pathlib import Path
import argparse
import re
import os
import json
import shutil
import subprocess
import pandas as pd
from datetime import datetime


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
        type=int,
        required=True,
        help="The OFO collect ID for this dataset.",
    )
    parser.add_argument(
        "--file-prefixes",
        type=str,
        required=True,
        help="One or more space-separated file prefixes for this mission.",
    )
    parser.add_argument(
        "--date",
        type=str,
        required=True,
        help="Date to restrict images to in the YYYY-MM-DD format",
    )

    return parser.parse_args()


def main(
    input_data_folder: Path,
    output_data_folder: Path,
    collect_id: int,
    file_prefixes: str,
    date: str,
):
    """_summary_

    Args:
        input_data_folder (Path): Where to search for matching files
        output_data_folder (Path): Where to write the subset of matching images.
        collect_id (int): The output images are written to {output_data_folder}/{collect_id:06d}/{collect_id:06d}_images"
        file_prefixes (str): A space-separated list of file prefixes to include
        date (str): A YYYY-MM-DD date that the the included files must match based on the DateTimeOriginal attribute.
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
    # Extact only the rows matching the requested date
    exif = exif[
        exif.DateTimeOriginal.dt.date == datetime.strptime(date, "%Y-%m-%d").date()
    ]

    # TODO check that the maximum gap is less than a specified threshold and error if not
    matching_files = exif.SourceFile.to_list()
    print(f"Found {len(matching_files)} files which matched the specified date")

    # Create an output folder based on the output folder / collect_id
    output_folder = Path(
        output_data_folder, f"{collect_id:06d}/{collect_id:06d}_images"
    )
    # remove old folder, if present
    shutil.rmtree(output_folder, ignore_errors=True)
    # And recreate
    output_folder.mkdir(parents=True, exist_ok=True)

    # Hardlink all files to that location
    # The output format should be <collect_id>/<collect_id>-<image_id>.JPG
    filename_remapping = {
        str(in_f): str(Path(output_folder, f"{collect_id:06d}_{i:06d}.JPG"))
        for i, in_f in enumerate(matching_files)
    }

    # Perform the hardlinking
    for in_f, out_f in filename_remapping.items():
        os.link(in_f, out_f)

    with open(Path(output_folder, "filename-remapping.json"), "w") as outfile_h:
        json.dump(filename_remapping, outfile_h)


if __name__ == "__main__":
    args = parse_args()

    main(**args.__dict__)

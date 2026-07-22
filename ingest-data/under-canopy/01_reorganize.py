from pathlib import Path
import argparse
import re
import os
import json
import shutil


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
        "--ofo-mission-id",
        type=int,
        required=True,
        help="The OFO mission ID for this dataset.",
    )
    parser.add_argument(
        "--sd-card-id",
        type=str,
        required=True,
        help="The SD card ID for this dataset.",
    )
    parser.add_argument(
        "--gopro-file-prefix",
        type=str,
        required=True,
        help="One or more space-separated GoPro file prefixes for this mission.",
    )

    return parser.parse_args()


def main(input_data_folder, output_data_folder, ofo_mission_id, sd_card_id, gopro_file_prefix):
    # Split the space-separated prefixes into individual prefixes
    gopro_file_prefixes = gopro_file_prefix.split()

    # Find all files matching any prefixes
    matching_files = [
        f
        for f in input_data_folder.rglob(f"**/card_{sd_card_id:02}/**")
        if re.match("|".join(re.escape(p) for p in gopro_file_prefixes), f.name)
    ]

    # Sort files by name.
    # TODO we might want to parse the timestamp in the future but the names should be consecutive in time.
    matching_files = sorted(matching_files)

    # TODO: Consider a check to see whether this is within the start/end timestamps and/or if there are timestamp gaps
    # This would require first parsing the metadata

    # Create an output folder based on the output folder / ofo_mission_id
    output_folder = Path(output_data_folder, f"{ofo_mission_id:06d}")
    # remove old folder, if present
    shutil.rmtree(output_folder, ignore_errors=True)
    # And recreate
    output_folder.mkdir(parents=True, exist_ok=True)

    # Hardlink all files to that location
    # The output format should be <mission_id>/<mission_id>-<image_id>.JPG
    filename_remapping = {
        str(in_f): str(Path(output_folder, f"{ofo_mission_id:06d}_{i:06d}.JPG"))
        for i, in_f in enumerate(matching_files)
    }

    for in_f, out_f in filename_remapping.items():
        os.link(in_f, out_f)

    with open(Path(output_folder, "filename-remapping.json"), "w") as outfile_h:
        json.dump(filename_remapping, outfile_h)


if __name__ == "__main__":
    args = parse_args()

    main(**args.__dict__)

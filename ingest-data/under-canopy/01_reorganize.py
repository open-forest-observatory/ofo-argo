from pathlib import Path
import argparse
import re
import os
import json
import shutil

import pandas as pd


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
        "mission_file",
        type=Path,
        help="This should have the following fields: 'ofo_mission_id' and 'gopro_file_prefix'",
    )

    return parser.parse_args()


def main(input_data_folder, output_data_folder, mission_file):
    missions = pd.read_csv(mission_file)

    for _, row in missions.iterrows():
        ofo_mission_id = row.ofo_mission_id
        gopro_file_prefix = row.gopro_file_prefix

        # Split the gopro_collect_id by commas and remove whitespace to get all included prefixes
        gopro_file_prefixes = [x.strip() for x in gopro_file_prefix.split(",")]

        # Find all files matching any prefixes
        matching_files = sorted(
            [
                f
                for f in input_data_folder.rglob("*")
                if re.match("|".join(re.escape(p) for p in gopro_file_prefixes), f.name)
            ]
        )

        # TODO: Consider a check to see whether this is within the start/end timestamps and/or if there are timestamp gaps
        # This would require first parsing the metadata

        # Create an output folder based on the output folder / ofo_mission_id
        output_folder = Path(output_data_folder, f"{ofo_mission_id:06d}")
        # remove old folder
        shutil.rmtree(output_folder)
        # And recreate
        output_folder.mkdir(parents=True, exist_ok=True)

        # Hardlink all files to that location
        # The output format should be <mission_id>/<mission_id>-<image_id>.JPG
        filename_remapping = {
            str(in_f): str(Path(output_folder, f"{ofo_mission_id:06d}-{i:06d}.JPG"))
            for i, in_f in enumerate(matching_files)
        }

        for in_f, out_f in filename_remapping.items():
            os.link(in_f, out_f)

        with open(Path(output_folder, "filename-remapping.json"), "w") as outfile_h:
            json.dump(filename_remapping, outfile_h)


if __name__ == "__main__":
    args = parse_args()

    main(**args.__dict__)

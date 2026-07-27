"""
Zip all images for one dataset and upload the archive to S3.

Takes a folder of already-reorganized images for a single mission (as
produced by 01_reorganize.py) and packages it into a single zip archive,
which is optionally uploaded to S3 via rclone.

Usage:
    python 03_zip_and_upload_images.py <input_data_folder> <output_zip_file>

    # Also upload the result to S3:
    python 03_zip_and_upload_images.py <input_data_folder> <output_zip_file> \
        --s3-dest ofo-public/under-canopy/mission_01/mission_01_images.zip
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

RCLONE_REMOTE = "js2s3"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input_data_folder", type=Path, help="Folder of images for one dataset to zip."
    )
    parser.add_argument(
        "output_zip_file", type=Path, help="Path to write the output zip archive to."
    )
    parser.add_argument(
        "--s3-dest",
        type=str,
        default=None,
        help=(
            "S3 path to upload the output zip to, without the rclone remote "
            f"prefix (e.g. 'ofo-public/under-canopy/mission_01/mission_01_images.zip'). "
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


def zip_folder(input_data_folder, output_zip_file):
    """Zip the contents of input_data_folder into output_zip_file."""
    output_zip_file.parent.mkdir(parents=True, exist_ok=True)
    archive_base = output_zip_file.with_suffix("") if output_zip_file.suffix == ".zip" else output_zip_file
    archive_path = shutil.make_archive(str(archive_base), "zip", root_dir=input_data_folder)
    return Path(archive_path)


def main():
    args = parse_args()

    archive_path = zip_folder(args.input_data_folder, args.output_zip_file)
    print(f"Wrote {archive_path}")

    if args.s3_dest:
        rclone_copyto(str(archive_path), f"{RCLONE_REMOTE}:{args.s3_dest}")
        archive_path.unlink()


if __name__ == "__main__":
    main()

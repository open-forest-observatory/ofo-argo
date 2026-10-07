#!/usr/bin/env python3
"""
Main entrypoint for photogrammetry post-processing container.
Handles S3 downloads/uploads, mission detection, and orchestration.

Configuration is passed as command-line arguments. S3 credentials are read from
environment variables (S3_ENDPOINT, RCLONE_S3_ACCESS_KEY_ID, RCLONE_S3_SECRET_ACCESS_KEY,
and optionally S3_PROVIDER) so that they are not exposed in the process list or workflow spec.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Import processing functions
from postprocessing import postprocess_photogrammetry_containerized

REQUIRED_S3_ENV_VARS = [
    "S3_ENDPOINT",
    "RCLONE_S3_ACCESS_KEY_ID",
    "RCLONE_S3_SECRET_ACCESS_KEY",
]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-name",
        type=str,
        required=True,
        help="Name of the project to process. Product files are selected by the prefix '<project-name>_'.",
    )
    parser.add_argument(
        "--s3-bucket-internal",
        type=str,
        required=True,
        help="S3 bucket containing the raw Metashape products.",
    )
    parser.add_argument(
        "--s3-photogrammetry-dir",
        type=str,
        required=True,
        help="Directory within the internal bucket containing the photogrammetry products.",
    )
    parser.add_argument(
        "--photogrammetry-config-subfolder",
        type=str,
        default="",
        help="Subfolder for the photogrammetry config (e.g. 'photogrammetry_01'). Leave empty to skip the subfolder.",
    )
    parser.add_argument(
        "--s3-bucket-input-boundary",
        type=str,
        required=True,
        help="S3 bucket containing the mission boundary polygons.",
    )
    parser.add_argument(
        "--input-boundary-dir",
        type=str,
        required=True,
        help="Directory within the boundary bucket containing the per-mission boundary polygons.",
    )
    parser.add_argument(
        "--s3-bucket-public",
        type=str,
        required=True,
        help="S3 bucket to upload the final postprocessed outputs to.",
    )
    parser.add_argument(
        "--s3-postprocessed-dir",
        type=str,
        default="processed",
        help="Directory within the public bucket to upload the postprocessed outputs to.",
    )
    parser.add_argument(
        "--working-dir",
        type=str,
        default="/tmp/processing",
        help="Local directory where products are downloaded to and postprocessed.",
    )
    parser.add_argument(
        "--output-max-dim",
        type=int,
        default=800,
        help="Maximum dimension in pixels of the generated thumbnails.",
    )

    return parser.parse_args()


def validate_environment():
    """Check that the S3 credential environment variables and rclone are available."""
    missing_vars = [var for var in REQUIRED_S3_ENV_VARS if not os.environ.get(var)]
    if missing_vars:
        print(
            f"Error: Missing required environment variables: {' '.join(missing_vars)}"
        )
        sys.exit(1)

    if shutil.which("rclone") is None:
        print("Error: rclone not found")
        sys.exit(1)


def get_s3_flags():
    """Build common S3 flags for rclone commands.

    Credentials are not passed as flags: rclone reads RCLONE_S3_ACCESS_KEY_ID and
    RCLONE_S3_SECRET_ACCESS_KEY from the environment directly.
    """
    return [
        "--s3-provider",
        os.environ.get("S3_PROVIDER", "Other"),
        "--s3-endpoint",
        os.environ.get("S3_ENDPOINT"),
    ]


def setup_working_directory(working_dir):
    """
    Create base working directory structure.

    Creates all required base directories under working_dir:
    - input/: Directory for downloaded photogrammetry products
    - boundary/: Directory for mission boundary polygons
    - output/: Directory for processed outputs (full/ and thumbnails/ subdirectories created during processing)

    Since each iteration has its own isolated postprocessing folder, no mission-specific
    subdirectories are needed.

    Returns:
        bool: True if all directories created successfully

    Args:
        working_dir: Local working directory

    Raises:
        SystemExit: If working_dir doesn't exist, can't be created, or isn't writable
    """
    print(f"Setting up working directory: {working_dir}")

    # Validate working directory exists or can be created
    if not os.path.exists(working_dir):
        try:
            os.makedirs(working_dir, exist_ok=True)
            print(f"Created working directory: {working_dir}")
        except Exception as e:
            print(f"ERROR: Cannot create working directory '{working_dir}': {e}")
            sys.exit(1)

    # Validate working directory is writable
    if not os.access(working_dir, os.W_OK):
        print(f"ERROR: Working directory '{working_dir}' is not writable")
        sys.exit(1)

    # Define all base directories to create
    base_directories = [
        f"{working_dir}/input",
        f"{working_dir}/boundary",
        f"{working_dir}/output",
    ]

    # Create each base directory
    for directory in base_directories:
        try:
            os.makedirs(directory, exist_ok=True)
            print(f"✓ Created directory: {directory}")
        except Exception as e:
            print(f"ERROR: Failed to create directory '{directory}': {e}")
            sys.exit(1)

    print(f"Working directory setup complete")
    return True


def download_photogrammetry_products(
    project_name,
    input_bucket,
    s3_photogrammetry_dir,
    photogrammetry_config_subfolder,
    working_dir,
):
    """Download photogrammetry products from S3 directory structure.

    Downloads all files from S3 structure (s3_photogrammetry_dir/[photogrammetry_NN]/imagery_products)
    and filters by project_name prefix to get files for the specified mission.
    Files are downloaded directly to the input/ directory (no mission subdirectory needed
    since each iteration has its own isolated postprocessing folder).

    Args:
        project_name: Project to process
        input_bucket: S3 bucket containing the raw Metashape products
        s3_photogrammetry_dir: Directory within input_bucket containing the products
        photogrammetry_config_subfolder: Empty string (skip subfolder) or "photogrammetry_NN".
            If empty, we inject it and strip the trailing slash to get clean paths
        working_dir: Local working directory

    Returns:
        str: The project name
    """
    local_input_dir = f"{working_dir}/input"

    print(f"Processing mission: '{project_name}'")

    # Build remote path - always inject subfolder, rstrip handles empty string case
    # Empty: "bucket/s3_dir/" -> "bucket/s3_dir"
    # Non-empty: "bucket/s3_dir/photogrammetry_01" -> "bucket/s3_dir/photogrammetry_01"
    remote_base_path = f":s3:{input_bucket}/{s3_photogrammetry_dir}/{photogrammetry_config_subfolder}".rstrip(
        "/"
    )

    print(f"Downloading files from {remote_base_path} to {local_input_dir}")
    print(f"Filtering files with prefix: {project_name}_")

    # Download all files matching the project prefix directly to input/
    copy_cmd = [
        "rclone",
        "copy",
        remote_base_path,
        local_input_dir,
        "--include",
        f"{project_name}_*",  # Filter by project prefix
        "--progress",
        "--transfers",
        "8",
        "--checkers",
        "8",
        "--retries",
        "5",
        "--retries-sleep",
        "15s",
        "--stats",
        "30s",
    ] + get_s3_flags()

    try:
        print(
            f"DEBUG rclone command: {' '.join(copy_cmd)}"
        )  # TEMP: remove after debugging
        subprocess.run(copy_cmd, check=True)
        print("Download completed")
        files = os.listdir(local_input_dir) if os.path.exists(local_input_dir) else []

        if not files:
            print(
                f"Error: No files found matching prefix '{project_name}_*' in {remote_base_path}"
            )
            sys.exit(1)

        print(f"Downloaded {len(files)} files for {project_name}")

    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to download products for {project_name}: {e}")
        sys.exit(1)

    return project_name


def download_boundary_polygons(
    mission_name, boundary_bucket, boundary_base_dir, working_dir
):
    """Download boundary polygon from nested S3 structure for the specified mission.

    Downloads directly to the boundary/ directory (no mission subdirectory needed
    since each iteration has its own isolated postprocessing folder).

    Args:
        mission_name: Mission name (may include numeric prefix like '01_mission-name')
        boundary_bucket: S3 bucket containing the boundary polygons
        boundary_base_dir: Directory within boundary_bucket containing the per-mission polygons
        working_dir: Local working directory

    Returns:
        bool: True if boundary file was downloaded successfully
    """
    local_boundary_dir = f"{working_dir}/boundary"

    print(f"Downloading boundary polygon for mission: {mission_name}")

    # Construct path: <boundary_base>/<mission_name>/metadata-mission/<mission_name>_mission-metadata.gpkg
    remote_boundary_file = f":s3:{boundary_bucket}/{boundary_base_dir}/{mission_name}/metadata-mission/{mission_name}_mission-metadata.gpkg"
    local_boundary_file = os.path.join(
        local_boundary_dir, f"{mission_name}_mission-metadata.gpkg"
    )

    print(f"Downloading file from {remote_boundary_file} to {local_boundary_file}")

    copy_cmd = [
        "rclone",
        "copyto",
        remote_boundary_file,
        local_boundary_file,
        "--progress",
        "--retries",
        "5",
        "--retries-sleep",
        "15s",
    ] + get_s3_flags()

    try:
        print(
            f"DEBUG rclone command: {' '.join(copy_cmd)}"
        )  # TEMP: remove after debugging
        subprocess.run(copy_cmd, check=True)
        print("Download completed")
        if os.path.exists(local_boundary_file):
            print(f"Successfully downloaded boundary file")
            return True
        else:
            print(f"Error: Boundary file not found for {mission_name}")
            print(f"Attempted to download from: {remote_boundary_file}")
            return False
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to download boundary for {mission_name}: {e}")
        print(f"Attempted to download from: {remote_boundary_file}")
        return False


def detect_and_match_missions(project_name, working_dir):
    """
    Match products to boundary file for the single mission being processed.

    Files are located directly in input/ and boundary/ directories (no mission
    subdirectories since each iteration has its own isolated postprocessing folder).

    Args:
        project_name: Project being processed
        working_dir: Local working directory

    Returns:
        Dict with keys: 'prefix', 'boundary_file', 'product_files'
        Returns None if matching fails
    """
    input_dir = f"{working_dir}/input"
    boundary_dir = f"{working_dir}/boundary"

    # Validate directories exist
    if not os.path.exists(input_dir):
        raise ValueError("Input directory not found")

    if not os.path.exists(boundary_dir):
        raise ValueError("Boundary directory not found")

    # Get all product files directly from input/ directory
    product_files = [
        os.path.join(input_dir, f)
        for f in os.listdir(input_dir)
        if os.path.isfile(os.path.join(input_dir, f))
    ]

    if not product_files:
        print(f"Error: No product files found for mission: {project_name}")
        return None

    # Find boundary file directly in boundary/ directory
    boundary_file = os.path.join(boundary_dir, f"{project_name}_mission-metadata.gpkg")

    if not os.path.exists(boundary_file):
        print(
            f"Error: No boundary file found for mission: {project_name} (expected: {project_name}_mission-metadata.gpkg)"
        )
        return None

    print(f"Matched mission '{project_name}' with {len(product_files)} products")

    return {
        "prefix": project_name,
        "boundary_file": boundary_file,
        "product_files": product_files,
    }


def upload_processed_products(
    mission_id,
    output_bucket,
    s3_postprocessed_dir,
    photogrammetry_config_subfolder,
    working_dir,
):
    """
    Upload processed products for a specific mission to S3 in mission-specific directories.
    Uses photogrammetry_config_subfolder to organize outputs.

    Uploads from the output/ directory directly (no mission subdirectory since each
    iteration has its own isolated postprocessing folder).

    Examples:
        - photogrammetry_config_subfolder='photogrammetry_01' -> benchmarking-greasewood/photogrammetry_01/
        - photogrammetry_config_subfolder='photogrammetry_02' -> benchmarking-greasewood/photogrammetry_02/
        - photogrammetry_config_subfolder='' (empty) -> benchmarking-greasewood/

    Args:
        mission_id: Mission identifier (used for S3 destination path, not local path)
        output_bucket: S3 bucket to upload the postprocessed outputs to
        s3_postprocessed_dir: Directory within output_bucket to upload to
        photogrammetry_config_subfolder: Empty string (skip subfolder) or "photogrammetry_NN".
            If empty, we inject it and strip the trailing slash to get clean paths
        working_dir: Local working directory
    """
    # Local output directory (no mission subdirectory)
    local_output_dir = f"{working_dir}/output"

    # Build remote path with photogrammetry subfolder
    # Empty: "bucket/s3_dir/mission" -> "bucket/s3_dir/mission"
    # Non-empty: "bucket/s3_dir/mission/photogrammetry_01" -> "bucket/s3_dir/mission/photogrammetry_01"
    remote_base_path = f"{output_bucket}/{s3_postprocessed_dir}/{mission_id}/{photogrammetry_config_subfolder}".rstrip(
        "/"
    )
    remote_mission_path = f":s3:{remote_base_path}"

    print(f"Uploading to {remote_base_path}")

    # Verify local output directory exists
    if not os.path.exists(local_output_dir):
        print(f"Error: Local output directory not found: {local_output_dir}")
        sys.exit(1)

    # Count files to upload
    full_dir = os.path.join(local_output_dir, "full")
    thumbnails_dir = os.path.join(local_output_dir, "thumbnails")
    full_count = len(os.listdir(full_dir)) if os.path.exists(full_dir) else 0
    thumbnail_count = (
        len(os.listdir(thumbnails_dir)) if os.path.exists(thumbnails_dir) else 0
    )

    print(
        f"Uploading {full_count} full files and {thumbnail_count} thumbnails for mission {mission_id}"
    )

    # Upload output directory (includes full/ and thumbnails/ subdirectories)
    cmd = [
        "rclone",
        "copy",
        local_output_dir,
        remote_mission_path,
        "--progress",
        "--transfers",
        "8",
        "--checkers",
        "8",
        "--retries",
        "5",
        "--retries-sleep",
        "15s",
        "--stats",
        "30s",
    ] + get_s3_flags()

    try:
        print(f"DEBUG rclone command: {' '.join(cmd)}")  # TEMP: remove after debugging
        subprocess.run(cmd, check=True)
        print(f"Upload completed for mission: {mission_id}")
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to upload mission {mission_id}: {e}")
        sys.exit(1)


def cleanup_working_directory(working_dir):
    """Remove the entire postprocessing working directory.

    Since each project has its own isolated postprocessing folder under
    {project_name_sanitized}/postprocessing/, we can safely delete the entire directory.

    Args:
        working_dir: Local working directory
    """

    print(f"Cleaning up postprocessing directory: {working_dir}")

    if os.path.exists(working_dir):
        shutil.rmtree(working_dir)
        print(f"Removed: {working_dir}")

    print("Cleanup completed")


def main(
    project_name: str,
    s3_bucket_internal: str,
    s3_photogrammetry_dir: str,
    photogrammetry_config_subfolder: str,
    s3_bucket_input_boundary: str,
    input_boundary_dir: str,
    s3_bucket_public: str,
    s3_postprocessed_dir: str,
    working_dir: str,
    output_max_dim: int,
):
    """Main execution function."""
    print("=== Python Post-Processing Container Starting ===")
    print(f"S3 Endpoint: {os.environ.get('S3_ENDPOINT')}")
    print(f"Internal Bucket (raw Metashape products): {s3_bucket_internal}")
    print(f"Photogrammetry Directory: {s3_photogrammetry_dir}")
    print(f"Photogrammetry Config Subfolder: {photogrammetry_config_subfolder}")
    print(f"Input Boundary Bucket: {s3_bucket_input_boundary}")
    print(f"Input Boundary Directory: {input_boundary_dir}")
    print(f"Public Bucket (final postprocessed outputs): {s3_bucket_public}")
    print(f"Postprocessed Directory: {s3_postprocessed_dir}")
    print(f"Project Name: {project_name}")
    print(f"Working Directory: {working_dir}")
    print(f"Output Max Dimension: {output_max_dim}")

    validate_environment()

    # Set up working directory structure
    setup_working_directory(working_dir)

    # Set TMPDIR to use working directory for temporary files
    os.environ["TMPDIR"] = working_dir

    # Download data for the specified mission
    mission_name = download_photogrammetry_products(
        project_name,
        s3_bucket_internal,
        s3_photogrammetry_dir,
        photogrammetry_config_subfolder,
        working_dir,
    )

    boundary_success = download_boundary_polygons(
        mission_name, s3_bucket_input_boundary, input_boundary_dir, working_dir
    )
    if not boundary_success:
        print(f"Error: Failed to download boundary file for mission: {mission_name}")
        sys.exit(1)

    # Match products to boundary
    try:
        mission_match = detect_and_match_missions(project_name, working_dir)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if not mission_match:
        print("Error: Could not match photogrammetry products to boundary polygon")
        sys.exit(1)

    # Process the mission
    print(f"\n=== Processing mission: {mission_match['prefix']} ===")

    try:
        result = postprocess_photogrammetry_containerized(
            mission_match["prefix"],
            mission_match["boundary_file"],
            mission_match["product_files"],
            working_dir,
            output_max_dim,
        )

        if result:
            upload_processed_products(
                mission_match["prefix"],
                s3_bucket_public,
                s3_postprocessed_dir,
                photogrammetry_config_subfolder,
                working_dir,
            )
            print(f"✓ Successfully processed mission: {mission_match['prefix']}")

            cleanup_working_directory(working_dir)

            print("\n=== Summary ===")
            print(f"Mission '{mission_match['prefix']}' processed successfully!")
            sys.exit(0)
        else:
            print(f"✗ Failed to process mission: {mission_match['prefix']}")
            cleanup_working_directory(working_dir)
            sys.exit(1)

    except Exception as e:
        print(f"✗ Error processing mission {mission_match['prefix']}: {e}")
        import traceback

        traceback.print_exc()
        cleanup_working_directory(working_dir)
        sys.exit(1)


if __name__ == "__main__":
    args = parse_args()

    main(**args.__dict__)

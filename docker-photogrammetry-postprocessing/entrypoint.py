#!/usr/bin/env python3
"""
Main entrypoint for photogrammetry post-processing container.
Handles S3 downloads/uploads, mission detection, and orchestration.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Import processing functions
from postprocess import postprocess_photogrammetry_containerized


def get_s3_flags():
    """Build common S3 authentication flags for rclone commands."""
    return [
        "--s3-provider",
        os.environ.get("S3_PROVIDER"),
        "--s3-endpoint",
        os.environ.get("S3_ENDPOINT"),
        "--s3-access-key-id",
        os.environ.get("S3_ACCESS_KEY"),
        "--s3-secret-access-key",
        os.environ.get("S3_SECRET_KEY"),
    ]


def setup_working_directory():
    """
    Create base working directory structure.

    Creates all required base directories under TEMP_WORKING_DIR_POSTPROCESSING:
    - input/: Directory for downloaded photogrammetry products
    - boundary/: Directory for mission boundary polygons
    - output/: Directory for processed outputs (full/ and thumbnails/ subdirectories created during processing)

    Since each iteration has its own isolated postprocessing folder, no mission-specific
    subdirectories are needed.

    Returns:
        bool: True if all directories created successfully

    Raises:
        SystemExit: If TEMP_WORKING_DIR_POSTPROCESSING doesn't exist, can't be created, or isn't writable
    """
    working_dir = os.environ.get("TEMP_WORKING_DIR_POSTPROCESSING", "/tmp/processing")

    print(f"Setting up working directory: {working_dir}")

    # Validate TEMP_WORKING_DIR_POSTPROCESSING exists or can be created
    if not os.path.exists(working_dir):
        try:
            os.makedirs(working_dir, exist_ok=True)
            print(f"Created working directory: {working_dir}")
        except Exception as e:
            print(
                f"ERROR: Cannot create TEMP_WORKING_DIR_POSTPROCESSING '{working_dir}': {e}"
            )
            sys.exit(1)

    # Validate TEMP_WORKING_DIR_POSTPROCESSING is writable
    if not os.access(working_dir, os.W_OK):
        print(f"ERROR: TEMP_WORKING_DIR_POSTPROCESSING '{working_dir}' is not writable")
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


def download_photogrammetry_products():
    """Download photogrammetry products from S3 directory structure.

    Downloads all files from S3 structure (s3_photogrammetry_dir/[photogrammetry_NN]/imagery_products)
    and filters by PROJECT_NAME prefix to get files for the specified mission.
    Files are downloaded directly to the input/ directory (no mission subdirectory needed
    since each iteration has its own isolated postprocessing folder).

    Returns:
        str: The project name
    """
    input_bucket = os.environ.get("S3_BUCKET_INTERNAL")
    s3_photogrammetry_dir = os.environ.get("S3_PHOTOGRAMMETRY_DIR")
    # PHOTOGRAMMETRY_CONFIG_SUBFOLDER may be empty string (skip subfolder) or "photogrammetry_NN"
    # If empty, we inject it and strip the trailing slash to get clean paths
    photogrammetry_config_subfolder = os.environ.get(
        "PHOTOGRAMMETRY_CONFIG_SUBFOLDER", ""
    )
    project_name = os.environ.get("PROJECT_NAME")  # Required: project to process
    working_dir = os.environ.get("TEMP_WORKING_DIR_POSTPROCESSING")
    local_input_dir = f"{working_dir}/input"

    if not project_name:
        print("Error: PROJECT_NAME environment variable is required")
        sys.exit(1)

    if not s3_photogrammetry_dir:
        print("Error: S3_PHOTOGRAMMETRY_DIR environment variable is required")
        sys.exit(1)

    print(f"Processing mission: '{project_name}'")

    # Build remote path - always inject subfolder, rstrip handles empty string case
    # Empty: "bucket/s3_dir/" -> "bucket/s3_dir"
    # Non-empty: "bucket/s3_dir/photogrammetry_01" -> "bucket/s3_dir/photogrammetry_01"
    remote_base_path = f":s3:{input_bucket}/{s3_photogrammetry_dir}/{photogrammetry_config_subfolder}".rstrip(
        "/"
    )

    print(f"Downloading products from: {remote_base_path}")
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
        subprocess.run(copy_cmd, check=True)
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


def download_boundary_polygons(mission_name):
    """Download boundary polygon from nested S3 structure for the specified mission.

    Downloads directly to the boundary/ directory (no mission subdirectory needed
    since each iteration has its own isolated postprocessing folder).

    Args:
        mission_name: Mission name (may include numeric prefix like '01_mission-name')

    Returns:
        bool: True if boundary file was downloaded successfully
    """
    boundary_bucket = os.environ.get("S3_BUCKET_INPUT_BOUNDARY")
    boundary_base_dir = os.environ.get("INPUT_BOUNDARY_DIR")
    working_dir = os.environ.get("TEMP_WORKING_DIR_POSTPROCESSING")
    local_boundary_dir = f"{working_dir}/boundary"

    print(f"Downloading boundary polygon for mission: {mission_name}")

    # Construct path: <boundary_base>/<mission_name>/metadata-mission/<mission_name>_mission-metadata.gpkg
    remote_boundary_file = f":s3:{boundary_bucket}/{boundary_base_dir}/{mission_name}/metadata-mission/{mission_name}_mission-metadata.gpkg"
    local_boundary_file = os.path.join(
        local_boundary_dir, f"{mission_name}_mission-metadata.gpkg"
    )

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
        subprocess.run(copy_cmd, check=True)
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


def detect_and_match_missions():
    """
    Match products to boundary file for the single mission being processed.

    Files are located directly in input/ and boundary/ directories (no mission
    subdirectories since each iteration has its own isolated postprocessing folder).

    Returns:
        Dict with keys: 'prefix', 'boundary_file', 'product_files'
        Returns None if matching fails
    """
    working_dir = os.environ.get("TEMP_WORKING_DIR_POSTPROCESSING")
    input_dir = f"{working_dir}/input"
    boundary_dir = f"{working_dir}/boundary"
    project_name = os.environ.get("PROJECT_NAME")

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


def upload_processed_products(mission_id):
    """
    Upload processed products for a specific mission to S3 in mission-specific directories.
    Uses PHOTOGRAMMETRY_CONFIG_SUBFOLDER parameter to organize outputs.

    Uploads from the output/ directory directly (no mission subdirectory since each
    iteration has its own isolated postprocessing folder).

    Examples:
        - PHOTOGRAMMETRY_CONFIG_SUBFOLDER='photogrammetry_01' -> benchmarking-greasewood/photogrammetry_01/
        - PHOTOGRAMMETRY_CONFIG_SUBFOLDER='photogrammetry_02' -> benchmarking-greasewood/photogrammetry_02/
        - PHOTOGRAMMETRY_CONFIG_SUBFOLDER='' (empty) -> benchmarking-greasewood/

    Args:
        mission_id: Mission identifier (used for S3 destination path, not local path)
    """
    output_bucket = os.environ.get("S3_BUCKET_PUBLIC")
    s3_postprocessed_dir = os.environ.get("S3_POSTPROCESSED_DIR")
    working_dir = os.environ.get("TEMP_WORKING_DIR_POSTPROCESSING")

    # PHOTOGRAMMETRY_CONFIG_SUBFOLDER may be empty string (skip subfolder) or "photogrammetry_NN"
    # If empty, we inject it and strip the trailing slash to get clean paths
    photogrammetry_config_subfolder = os.environ.get(
        "PHOTOGRAMMETRY_CONFIG_SUBFOLDER", ""
    )

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
    ] + get_s3_flags()

    try:
        subprocess.run(cmd, check=True)
        print(f"Upload completed for mission: {mission_id}")
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to upload mission {mission_id}: {e}")
        sys.exit(1)


def cleanup_working_directory():
    """Remove the entire postprocessing working directory.

    Since each project has its own isolated postprocessing folder under
    {project_name_sanitized}/postprocessing/, we can safely delete the entire directory.
    """
    working_dir = os.environ.get("TEMP_WORKING_DIR_POSTPROCESSING")

    print(f"Cleaning up postprocessing directory: {working_dir}")

    if os.path.exists(working_dir):
        shutil.rmtree(working_dir)
        print(f"Removed: {working_dir}")

    print("Cleanup completed")


def main():
    """Main execution function."""
    print("Starting Python post-processing container...")

    # Set up working directory structure
    setup_working_directory()

    # Set TMPDIR to use working directory for temporary files
    working_dir = os.environ.get("TEMP_WORKING_DIR_POSTPROCESSING", "/tmp/processing")
    os.environ["TMPDIR"] = working_dir

    # Log processing configuration
    project_name = os.environ.get("PROJECT_NAME")
    print(f"Processing single mission: {project_name}")
    print(f"Output max dimension: {os.environ.get('OUTPUT_MAX_DIM')}")

    # Download data for the specified mission
    mission_name = download_photogrammetry_products()

    boundary_success = download_boundary_polygons(mission_name)
    if not boundary_success:
        print(f"Error: Failed to download boundary file for mission: {mission_name}")
        sys.exit(1)

    # Match products to boundary
    try:
        mission_match = detect_and_match_missions()
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
        )

        if result:
            upload_processed_products(mission_match["prefix"])
            print(f"✓ Successfully processed mission: {mission_match['prefix']}")

            cleanup_working_directory()

            print("\n=== Summary ===")
            print(f"Mission '{mission_match['prefix']}' processed successfully!")
            sys.exit(0)
        else:
            print(f"✗ Failed to process mission: {mission_match['prefix']}")
            cleanup_working_directory()
            sys.exit(1)

    except Exception as e:
        print(f"✗ Error processing mission {mission_match['prefix']}: {e}")
        import traceback

        traceback.print_exc()
        cleanup_working_directory()
        sys.exit(1)


if __name__ == "__main__":
    main()

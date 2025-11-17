#!/usr/bin/env python3
"""
Main entrypoint for photogrammetry post-processing container.
Handles S3 downloads/uploads, mission detection, and orchestration.
"""

import os
import sys
import subprocess
from pathlib import Path
import shutil
import re

# Import processing functions
from postprocess import postprocess_photogrammetry_containerized




def get_s3_flags():
    """Build common S3 authentication flags for rclone commands."""
    return [
        '--s3-provider', os.environ.get('S3_PROVIDER'),
        '--s3-endpoint', os.environ.get('S3_ENDPOINT'),
        '--s3-access-key-id', os.environ.get('S3_ACCESS_KEY'),
        '--s3-secret-access-key', os.environ.get('S3_SECRET_KEY')
    ]


def setup_working_directory():
    """
    Create base working directory structure.

    Creates all required base directories under WORKING_DIR:
    - input/: Base directory for downloaded photogrammetry products
    - boundary/: Base directory for mission boundary polygons
    - output/: Base directory for processed outputs (mission-specific subdirectories created during processing)
    - temp/: Reserved for temporary processing files

    Mission-specific subdirectories (e.g., input/01_mission-name/, output/01_mission-name/) are created
    on-the-fly by individual download/processing functions.

    Returns:
        bool: True if all directories created successfully

    Raises:
        SystemExit: If WORKING_DIR doesn't exist, can't be created, or isn't writable
    """
    working_dir = os.environ.get('WORKING_DIR', '/tmp/processing')

    print(f"Setting up working directory: {working_dir}")

    # Validate WORKING_DIR exists or can be created
    if not os.path.exists(working_dir):
        try:
            os.makedirs(working_dir, exist_ok=True)
            print(f"Created working directory: {working_dir}")
        except Exception as e:
            print(f"ERROR: Cannot create WORKING_DIR '{working_dir}': {e}")
            sys.exit(1)

    # Validate WORKING_DIR is writable
    if not os.access(working_dir, os.W_OK):
        print(f"ERROR: WORKING_DIR '{working_dir}' is not writable")
        sys.exit(1)

    # Define all base directories to create
    base_directories = [
        f"{working_dir}/input",
        f"{working_dir}/boundary",
        f"{working_dir}/output",
        f"{working_dir}/temp"
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

    Downloads all files from S3 structure (run_folder/[photogrammetry_NN]/imagery_products)
    and filters by DATASET_NAME prefix to get files for the specified mission.
    Organizes files locally into a mission subdirectory for processing.

    Returns:
        str: The dataset/mission name
    """
    input_bucket = os.environ.get('S3_BUCKET_INPUT_DATA')
    run_folder = os.environ.get('RUN_FOLDER')
    # PHOTOGRAMMETRY_CONFIG_SUBFOLDER may be empty string (skip subfolder) or "photogrammetry_NN"
    # If empty, we inject it and strip the trailing slash to get clean paths
    photogrammetry_config_subfolder = os.environ.get('PHOTOGRAMMETRY_CONFIG_SUBFOLDER', '')
    dataset_name = os.environ.get('DATASET_NAME')  # Required: mission to process
    working_dir = os.environ.get('WORKING_DIR')
    local_input_dir = f"{working_dir}/input"

    if not dataset_name:
        print("Error: DATASET_NAME environment variable is required")
        sys.exit(1)

    if not run_folder:
        print("Error: RUN_FOLDER environment variable is required")
        sys.exit(1)

    print(f"Processing mission: '{dataset_name}'")

    # Build remote path - always inject subfolder, rstrip handles empty string case
    # Empty: "bucket/run/" -> "bucket/run"
    # Non-empty: "bucket/run/photogrammetry_01" -> "bucket/run/photogrammetry_01"
    remote_base_path = f":s3:{input_bucket}/{run_folder}/{photogrammetry_config_subfolder}".rstrip('/')
    local_mission_dir = os.path.join(local_input_dir, dataset_name)
    # Create mission-specific subdirectory (base input/ directory already exists from setup)
    os.makedirs(local_mission_dir, exist_ok=True)

    print(f"Downloading products from: {remote_base_path}")
    print(f"Filtering files with prefix: {dataset_name}_")

    # Download all files matching the dataset prefix
    copy_cmd = [
        'rclone', 'copy',
        remote_base_path,
        local_mission_dir,
        '--include', f'{dataset_name}_*',  # Filter by mission prefix
        '--progress',
        '--transfers', '8',
        '--checkers', '8',
        '--retries', '5',
        '--retries-sleep', '15s',
        '--stats', '30s'
    ] + get_s3_flags()

    try:
        subprocess.run(copy_cmd, check=True)
        files = os.listdir(local_mission_dir) if os.path.exists(local_mission_dir) else []

        if not files:
            print(f"Error: No files found matching prefix '{dataset_name}_*' in {remote_base_path}")
            sys.exit(1)

        print(f"Downloaded {len(files)} files for {dataset_name}")

    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to download products for {dataset_name}: {e}")
        sys.exit(1)

    return dataset_name


def download_boundary_polygons(mission_name):
    """Download boundary polygon from nested S3 structure for the specified mission.

    Args:
        mission_name: Mission name (may include numeric prefix like '01_mission-name')

    Returns:
        bool: True if boundary file was downloaded successfully
    """
    boundary_bucket = os.environ.get('S3_BUCKET_INPUT_BOUNDARY')
    boundary_base_dir = os.environ.get('INPUT_BOUNDARY_DIRECTORY')
    working_dir = os.environ.get('WORKING_DIR')
    local_boundary_dir = f"{working_dir}/boundary"

    print(f"Downloading boundary polygon for mission: {mission_name}")

    # Construct path: <boundary_base>/<mission_name>/metadata-mission/<mission_name>_mission-metadata.gpkg
    remote_boundary_file = f":s3:{boundary_bucket}/{boundary_base_dir}/{mission_name}/metadata-mission/{mission_name}_mission-metadata.gpkg"
    local_mission_boundary_dir = os.path.join(local_boundary_dir, mission_name)
    # Create mission-specific subdirectory (base boundary/ directory already exists from setup)
    os.makedirs(local_mission_boundary_dir, exist_ok=True)
    local_boundary_file = os.path.join(local_mission_boundary_dir, f"{mission_name}_mission-metadata.gpkg")

    copy_cmd = [
        'rclone', 'copyto',
        remote_boundary_file,
        local_boundary_file,
        '--progress',
        '--retries', '5',
        '--retries-sleep', '15s'
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

    Returns:
        Dict with keys: 'prefix', 'boundary_file', 'product_files'
        Returns None if matching fails
    """
    working_dir = os.environ.get('WORKING_DIR')
    input_dir = f"{working_dir}/input"
    boundary_dir = f"{working_dir}/boundary"
    dataset_name = os.environ.get('DATASET_NAME')

    # Validate directories exist
    if not os.path.exists(input_dir):
        raise ValueError("Input directory not found")

    if not os.path.exists(boundary_dir):
        raise ValueError("Boundary directory not found")

    # Get the mission directory
    mission_input_dir = os.path.join(input_dir, dataset_name)
    mission_boundary_dir = os.path.join(boundary_dir, dataset_name)

    if not os.path.exists(mission_input_dir):
        raise ValueError(f"Mission input directory not found: {mission_input_dir}")

    # Get all product files for this mission
    product_files = []
    if os.path.exists(mission_input_dir):
        product_files = [
            os.path.join(mission_input_dir, f)
            for f in os.listdir(mission_input_dir)
            if os.path.isfile(os.path.join(mission_input_dir, f))
        ]

    if not product_files:
        print(f"Error: No product files found for mission: {dataset_name}")
        return None

    # Find boundary file
    boundary_file = os.path.join(mission_boundary_dir, f"{dataset_name}_mission-metadata.gpkg")

    if not os.path.exists(boundary_file):
        print(f"Error: No boundary file found for mission: {dataset_name} (expected: {dataset_name}_mission-metadata.gpkg)")
        return None

    print(f"Matched mission '{dataset_name}' with {len(product_files)} products")

    return {
        'prefix': dataset_name,
        'boundary_file': boundary_file,
        'product_files': product_files
    }


def upload_processed_products(mission_id):
    """
    Upload processed products for a specific mission to S3 in mission-specific directories.
    Uses PHOTOGRAMMETRY_CONFIG_SUBFOLDER parameter to organize outputs.

    Examples:
        - PHOTOGRAMMETRY_CONFIG_SUBFOLDER='photogrammetry_01' -> benchmarking-greasewood/photogrammetry_01/
        - PHOTOGRAMMETRY_CONFIG_SUBFOLDER='photogrammetry_02' -> benchmarking-greasewood/photogrammetry_02/
        - PHOTOGRAMMETRY_CONFIG_SUBFOLDER='' (empty) -> benchmarking-greasewood/

    Args:
        mission_id: Mission identifier
    """
    output_bucket = os.environ.get('S3_BUCKET_OUTPUT')
    output_base_dir = os.environ.get('OUTPUT_DIRECTORY')
    working_dir = os.environ.get('WORKING_DIR')

    # PHOTOGRAMMETRY_CONFIG_SUBFOLDER may be empty string (skip subfolder) or "photogrammetry_NN"
    # If empty, we inject it and strip the trailing slash to get clean paths
    photogrammetry_config_subfolder = os.environ.get('PHOTOGRAMMETRY_CONFIG_SUBFOLDER', '')

    # Construct local and remote paths
    local_mission_dir = f"{working_dir}/output/{mission_id}"

    # Build remote path with photogrammetry subfolder
    # Empty: "bucket/output/mission" -> "bucket/output/mission"
    # Non-empty: "bucket/output/mission/photogrammetry_01" -> "bucket/output/mission/photogrammetry_01"
    remote_base_path = f"{output_bucket}/{output_base_dir}/{mission_id}/{photogrammetry_config_subfolder}".rstrip('/')
    remote_mission_path = f":s3:{remote_base_path}"

    print(f"Uploading to {remote_base_path}")

    # Verify local mission directory exists
    if not os.path.exists(local_mission_dir):
        print(f"Error: Local mission output directory not found: {local_mission_dir}")
        sys.exit(1)

    # Count files to upload
    full_dir = os.path.join(local_mission_dir, "full")
    thumbnails_dir = os.path.join(local_mission_dir, "thumbnails")
    full_count = len(os.listdir(full_dir)) if os.path.exists(full_dir) else 0
    thumbnail_count = len(os.listdir(thumbnails_dir)) if os.path.exists(thumbnails_dir) else 0

    print(f"Uploading {full_count} full files and {thumbnail_count} thumbnails for mission {mission_id}")

    # Upload entire mission directory (includes full/ and thumbnails/ subdirectories)
    cmd = [
        'rclone', 'copy',
        local_mission_dir,
        remote_mission_path,
        '--progress',
        '--transfers', '8',
        '--checkers', '8',
        '--retries', '5',
        '--retries-sleep', '15s'
    ] + get_s3_flags()

    try:
        subprocess.run(cmd, check=True)
        print(f"Upload completed for mission: {mission_id}")
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to upload mission {mission_id}: {e}")
        sys.exit(1)


def cleanup_working_directory(mission_id):
    """Remove temporary processing files for a specific mission.

    Only deletes mission-specific directories to support parallel
    processing where multiple containers may share the same WORKING_DIR.

    Args:
        mission_id: Mission identifier
    """
    print(f"Cleaning up temporary files for mission: {mission_id}")
    working_dir = os.environ.get('WORKING_DIR')

    # Delete mission-specific input directory
    mission_input_dir = os.path.join(working_dir, 'input', mission_id)
    if os.path.exists(mission_input_dir):
        shutil.rmtree(mission_input_dir)
        print(f"Removed: {mission_input_dir}")

    # Delete mission-specific boundary directory
    mission_boundary_dir = os.path.join(working_dir, 'boundary', mission_id)
    if os.path.exists(mission_boundary_dir):
        shutil.rmtree(mission_boundary_dir)
        print(f"Removed: {mission_boundary_dir}")

    # Delete mission-specific output directory (includes full/ and thumbnails/)
    mission_output_dir = os.path.join(working_dir, 'output', mission_id)
    if os.path.exists(mission_output_dir):
        shutil.rmtree(mission_output_dir)
        print(f"Removed: {mission_output_dir}")

    print(f"Cleanup completed for mission: {mission_id}")


def main():
    """Main execution function."""
    print("Starting Python post-processing container...")

    # Set up working directory structure
    setup_working_directory()

    # Set TMPDIR to use working directory for temporary files
    working_dir = os.environ.get('WORKING_DIR', '/tmp/processing')
    os.environ['TMPDIR'] = working_dir

    # Log processing configuration
    dataset_name = os.environ.get('DATASET_NAME')
    print(f"Processing single mission: {dataset_name}")
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
            mission_match['prefix'],
            mission_match['boundary_file'],
            mission_match['product_files']
        )

        if result:
            upload_processed_products(mission_match['prefix'])
            print(f"✓ Successfully processed mission: {mission_match['prefix']}")

            cleanup_working_directory(mission_match['prefix'])

            print("\n=== Summary ===")
            print(f"Mission '{mission_match['prefix']}' processed successfully!")
            sys.exit(0)
        else:
            print(f"✗ Failed to process mission: {mission_match['prefix']}")
            cleanup_working_directory(mission_match['prefix'])
            sys.exit(1)

    except Exception as e:
        print(f"✗ Error processing mission {mission_match['prefix']}: {e}")
        import traceback
        traceback.print_exc()
        cleanup_working_directory(mission_match['prefix'])
        sys.exit(1)


if __name__ == '__main__':
    main()

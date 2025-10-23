#!/usr/bin/env python3
"""
Main entrypoint for photogrammetry post-processing container.
Handles S3 downloads/uploads, mission detection, and orchestration.
Python conversion of entrypoint.R
"""

import os
import sys
import subprocess
from pathlib import Path
import shutil
import re

# Import processing functions
from postprocess import postprocess_photogrammetry_containerized


def extract_base_mission_name(dataset_name):
    """
    Extract base mission name from dataset name by removing numeric prefix.

    Handles patterns like:
    - '01_benchmarking-greasewood' -> 'benchmarking-greasewood'
    - '02_benchmarking-greasewood' -> 'benchmarking-greasewood'
    - 'benchmarking-greasewood' -> 'benchmarking-greasewood' (no prefix)

    Args:
        dataset_name: Dataset/mission name (may include numeric prefix)

    Returns:
        Base mission name with numeric prefix removed
    """
    # Match pattern: optional digits followed by underscore, then capture the rest
    match = re.match(r'^(?:\d+_)?(.+)$', dataset_name)
    if match:
        return match.group(1)
    return dataset_name


def extract_prefix_number(dataset_name):
    """
    Extract numeric prefix from dataset name to determine processed_NN directory number.

    Handles patterns like:
    - '01_benchmarking-greasewood' -> 1
    - '02_benchmarking-greasewood' -> 2
    - '15_benchmarking-greasewood' -> 15
    - 'benchmarking-greasewood' -> 1 (default when no prefix)

    Args:
        dataset_name: Dataset/mission name (may include numeric prefix)

    Returns:
        Integer representing the prefix number (defaults to 1 if no prefix)
    """
    # Match pattern: digits at start followed by underscore
    match = re.match(r'^(\d+)_', dataset_name)
    if match:
        return int(match.group(1))
    return 1  # Default to 1 if no numeric prefix


def setup_rclone_config():
    """Create rclone configuration file from environment variables."""
    s3_endpoint = os.environ.get('S3_ENDPOINT')
    s3_provider = os.environ.get('S3_PROVIDER', 'Other')
    s3_access_key = os.environ.get('S3_ACCESS_KEY')
    s3_secret_key = os.environ.get('S3_SECRET_KEY')

    # Create config content
    config_content = f"""[s3remote]
type = s3
provider = {s3_provider}
access_key_id = {s3_access_key}
secret_access_key = {s3_secret_key}
endpoint = {s3_endpoint}
"""

    # Write config file
    config_dir = Path.home() / '.config' / 'rclone'
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / 'rclone.conf'

    with open(config_file, 'w') as f:
        f.write(config_content)

    print("rclone configuration created")


def download_photogrammetry_products():
    """Download photogrammetry products from flat S3 directory structure.

    Downloads all files from the flat S3 structure (run_folder/imagery_products)
    and filters by DATASET_NAME prefix to get files for the specified mission.
    Organizes files locally into a mission subdirectory for processing.

    Returns:
        str: The dataset/mission name
    """
    input_bucket = os.environ.get('S3_BUCKET_INPUT_DATA')
    input_dir = os.environ.get('INPUT_DATA_DIRECTORY')
    dataset_name = os.environ.get('DATASET_NAME')  # Required: mission to process
    working_dir = os.environ.get('WORKING_DIR', '/tmp/processing')
    local_input_dir = f"{working_dir}/input"

    if not dataset_name:
        print("Error: DATASET_NAME environment variable is required")
        sys.exit(1)

    print(f"Processing mission: '{dataset_name}'")

    # Remote path now points directly to the flat directory structure
    remote_base_path = f"s3remote:{input_bucket}/{input_dir}"
    local_mission_dir = os.path.join(local_input_dir, dataset_name)
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
    ]

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
    working_dir = os.environ.get('WORKING_DIR', '/tmp/processing')
    local_boundary_dir = f"{working_dir}/boundary"

    print(f"Downloading boundary polygon for mission: {mission_name}")

    # Extract base mission name (strip numeric prefix) for boundary lookup
    base_mission_name = extract_base_mission_name(mission_name)

    # Construct path using base name: <boundary_base>/<base_name>/metadata-mission/<base_name>_mission-metadata.gpkg
    remote_boundary_file = f"s3remote:{boundary_bucket}/{boundary_base_dir}/{base_mission_name}/metadata-mission/{base_mission_name}_mission-metadata.gpkg"
    local_mission_boundary_dir = os.path.join(local_boundary_dir, mission_name)
    os.makedirs(local_mission_boundary_dir, exist_ok=True)
    local_boundary_file = os.path.join(local_mission_boundary_dir, f"{base_mission_name}_mission-metadata.gpkg")

    print(f"Using base name for boundary lookup: {base_mission_name}")

    copy_cmd = [
        'rclone', 'copyto',
        remote_boundary_file,
        local_boundary_file,
        '--progress',
        '--retries', '5',
        '--retries-sleep', '15s'
    ]

    try:
        subprocess.run(copy_cmd, check=True)
        if os.path.exists(local_boundary_file):
            print(f"Successfully downloaded boundary file")
            return True
        else:
            print(f"Error: Boundary file not found for {mission_name}")
            return False
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to download boundary for {mission_name}: {e}")
        return False


def detect_and_match_missions():
    """
    Match products to boundary file for the single mission being processed.
    Handles numeric prefixes (e.g., 01_mission-name, 02_mission-name) by mapping
    to the same base boundary file.

    Returns:
        Dict with keys: 'prefix', 'boundary_file', 'product_files'
        Returns None if matching fails
    """
    working_dir = os.environ.get('WORKING_DIR', '/tmp/processing')
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

    # Find boundary file using base mission name (strips numeric prefix)
    base_mission_name = extract_base_mission_name(dataset_name)
    boundary_file = os.path.join(mission_boundary_dir, f"{base_mission_name}_mission-metadata.gpkg")

    if not os.path.exists(boundary_file):
        print(f"Error: No boundary file found for mission: {dataset_name} (expected: {base_mission_name}_mission-metadata.gpkg)")
        return None

    print(f"Matched mission '{dataset_name}' with {len(product_files)} products")

    return {
        'prefix': dataset_name,
        'boundary_file': boundary_file,
        'product_files': product_files
    }


def upload_processed_products(mission_prefix):
    """
    Upload processed products for a specific mission to S3 in mission-specific directories.
    Uses numeric prefix from dataset name to determine processed_NN directory number.

    Examples:
        - '01_benchmarking-greasewood' -> benchmarking-greasewood/processed_01/
        - '02_benchmarking-greasewood' -> benchmarking-greasewood/processed_02/
        - 'benchmarking-greasewood' -> benchmarking-greasewood/processed_01/

    Args:
        mission_prefix: Mission identifier prefix (may include numeric prefix like 01_name)
    """
    output_bucket = os.environ.get('S3_BUCKET_OUTPUT')
    output_base_dir = os.environ.get('OUTPUT_DIRECTORY')

    # Extract base mission name and numeric prefix
    base_mission_name = extract_base_mission_name(mission_prefix)
    processed_num = extract_prefix_number(mission_prefix)

    print(f"Uploading to {base_mission_name}/processed_{processed_num:02d}/")

    # Upload both full resolution and thumbnails to mission-specific processed_NN directories
    working_dir = os.environ.get('WORKING_DIR', '/tmp/processing')
    for subdir in ['full', 'thumbnails']:
        local_path = f"{working_dir}/output/{subdir}"
        # Remote path: <output_base>/<base_mission_name>/processed_NN/<subdir>/
        remote_path = f"s3remote:{output_bucket}/{output_base_dir}/{base_mission_name}/processed_{processed_num:02d}/{subdir}"

        # Only upload files that match this mission prefix
        if not os.path.exists(local_path):
            continue

        files_to_upload = [
            f for f in os.listdir(local_path)
            if f.startswith(f"{mission_prefix}_")
        ]

        if files_to_upload:
            print(f"Uploading {len(files_to_upload)} {subdir} files for mission {mission_prefix}")

            # Copy files one by one to ensure proper naming
            for filename in files_to_upload:
                file_path = os.path.join(local_path, filename)
                remote_file_path = f"{remote_path}/{filename}"

                cmd = [
                    'rclone', 'copyto',
                    file_path,
                    remote_file_path,
                    '--progress',
                    '--retries', '5',
                    '--retries-sleep', '15s'
                ]

                try:
                    subprocess.run(cmd, check=True)
                except subprocess.CalledProcessError as e:
                    print(f"Warning: Failed to upload file: {filename}")

    print(f"Upload completed for mission: {mission_prefix}")


def cleanup_working_directory():
    """Remove temporary processing files."""
    print("Cleaning up temporary files...")
    working_dir = os.environ.get('WORKING_DIR', '/tmp/processing')

    if os.path.exists(working_dir):
        shutil.rmtree(working_dir)

    print("Cleanup completed")


def main():
    """Main execution function."""
    working_dir = os.environ.get('WORKING_DIR', '/tmp/processing')

    print("Starting Python post-processing container...")
    print(f"Working directory: {working_dir}")

    # Validate required parameters (including DATASET_NAME)
    required_vars = [
        'S3_ENDPOINT',
        'S3_ACCESS_KEY',
        'S3_SECRET_KEY',
        'S3_BUCKET_INPUT_DATA',
        'S3_BUCKET_INPUT_BOUNDARY',
        'DATASET_NAME'
    ]

    missing_vars = [var for var in required_vars if not os.environ.get(var)]

    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        sys.exit(1)

    # Validate WORKING_DIR exists and is writable
    if not os.path.exists(working_dir):
        try:
            os.makedirs(working_dir, exist_ok=True)
            print(f"Created working directory: {working_dir}")
        except Exception as e:
            print(f"ERROR: Cannot create WORKING_DIR '{working_dir}': {e}")
            sys.exit(1)

    if not os.access(working_dir, os.W_OK):
        print(f"ERROR: WORKING_DIR '{working_dir}' is not writable")
        sys.exit(1)

    # Set up working directory
    os.environ['TMPDIR'] = working_dir
    Path(working_dir).mkdir(parents=True, exist_ok=True)

    # Log processing configuration
    dataset_name = os.environ.get('DATASET_NAME')
    print(f"Processing single mission: {dataset_name}")
    print(f"Output max dimension: {os.environ.get('OUTPUT_MAX_DIM', '800')}")

    # Configure rclone
    setup_rclone_config()

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


if __name__ == '__main__':
    main()

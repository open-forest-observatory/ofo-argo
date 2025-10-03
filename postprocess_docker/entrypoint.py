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

# Import processing functions
from postprocess import postprocess_photogrammetry_containerized


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
    """Download all photogrammetry products from S3 mission subdirectories."""
    input_bucket = os.environ.get('S3_BUCKET_INPUT_DATA')
    input_dir = os.environ.get('INPUT_DATA_DIRECTORY')
    local_input_dir = "/tmp/processing/input"

    remote_base_path = f"s3remote:{input_bucket}/{input_dir}"

    print(f"Discovering mission subdirectories in: {remote_base_path}")

    # List subdirectories (mission folders) using rclone lsd
    lsd_cmd = ['rclone', 'lsd', remote_base_path]

    try:
        result = subprocess.run(lsd_cmd, check=True, capture_output=True, text=True)
        # Parse output: each line format is like "          -1 2024-10-03 12:00:00        -1 mission-name"
        mission_dirs = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                parts = line.split()
                if parts:
                    mission_name = parts[-1]  # Last part is directory name
                    mission_dirs.append(mission_name)

        print(f"Found {len(mission_dirs)} mission directories: {', '.join(mission_dirs)}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to list mission directories: {e}")
        sys.exit(1)

    if not mission_dirs:
        print("Error: No mission directories found")
        sys.exit(1)

    # Download each mission's products
    total_files = 0
    for mission_name in mission_dirs:
        remote_mission_path = f"{remote_base_path}/{mission_name}"
        local_mission_dir = os.path.join(local_input_dir, mission_name)

        print(f"Downloading products for mission: {mission_name}")

        copy_cmd = [
            'rclone', 'copy',
            remote_mission_path,
            local_mission_dir,
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
            total_files += len(files)
            print(f"  Downloaded {len(files)} files for {mission_name}")
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to download products for {mission_name}: {e}")

    print(f"Total downloaded: {total_files} photogrammetry files from {len(mission_dirs)} missions")

    return mission_dirs


def download_boundary_polygons(mission_dirs):
    """Download boundary polygons from nested S3 structure for each mission.

    Args:
        mission_dirs: List of mission directory names
    """
    boundary_bucket = os.environ.get('S3_BUCKET_INPUT_BOUNDARY')
    boundary_base_dir = os.environ.get('INPUT_BOUNDARY_DIRECTORY')
    local_boundary_dir = "/tmp/processing/boundary"

    print(f"Downloading boundary polygons for {len(mission_dirs)} missions")

    downloaded_count = 0
    for mission_name in mission_dirs:
        # Construct path: <boundary_base>/<mission_name>/metadata-mission/<mission_name>_mission-metadata.gpkg
        remote_boundary_file = f"s3remote:{boundary_bucket}/{boundary_base_dir}/{mission_name}/metadata-mission/{mission_name}_mission-metadata.gpkg"
        local_mission_boundary_dir = os.path.join(local_boundary_dir, mission_name)
        os.makedirs(local_mission_boundary_dir, exist_ok=True)
        local_boundary_file = os.path.join(local_mission_boundary_dir, f"{mission_name}_mission-metadata.gpkg")

        print(f"Downloading boundary for {mission_name}")

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
                downloaded_count += 1
                print(f"  Downloaded boundary: {mission_name}_mission-metadata.gpkg")
            else:
                print(f"  Warning: Boundary file not found for {mission_name}")
        except subprocess.CalledProcessError as e:
            print(f"  Warning: Failed to download boundary for {mission_name}: {e}")

    print(f"Downloaded {downloaded_count} boundary files")

    return downloaded_count


def detect_and_match_missions():
    """
    Auto-detect missions using directory names and match products to boundaries.

    Returns:
        List of dicts with keys: 'prefix', 'boundary_file', 'product_files'
    """
    input_dir = "/tmp/processing/input"
    boundary_dir = "/tmp/processing/boundary"

    # Get list of mission directories
    if not os.path.exists(input_dir):
        raise ValueError("Input directory not found")

    if not os.path.exists(boundary_dir):
        raise ValueError("Boundary directory not found")

    mission_dirs = [d for d in os.listdir(input_dir) if os.path.isdir(os.path.join(input_dir, d))]

    if not mission_dirs:
        raise ValueError("No mission directories found")

    print(f"Found {len(mission_dirs)} mission directories")

    mission_matches = []

    for mission_name in sorted(mission_dirs):
        mission_input_dir = os.path.join(input_dir, mission_name)
        mission_boundary_dir = os.path.join(boundary_dir, mission_name)

        # Get all product files for this mission
        product_files = []
        if os.path.exists(mission_input_dir):
            product_files = [
                os.path.join(mission_input_dir, f)
                for f in os.listdir(mission_input_dir)
                if os.path.isfile(os.path.join(mission_input_dir, f))
            ]

        # Find boundary file
        boundary_file = os.path.join(mission_boundary_dir, f"{mission_name}_mission-metadata.gpkg")

        if os.path.exists(boundary_file) and product_files:
            mission_matches.append({
                'prefix': mission_name,
                'boundary_file': boundary_file,
                'product_files': product_files
            })
            print(f"Matched mission '{mission_name}' with {len(product_files)} products")
        elif not os.path.exists(boundary_file):
            print(f"Warning: No boundary file found for mission: {mission_name}")
        elif not product_files:
            print(f"Warning: No product files found for mission: {mission_name}")

    return mission_matches


def upload_processed_products(mission_prefix):
    """
    Upload processed products for a specific mission to S3 in mission-specific directories.

    Args:
        mission_prefix: Mission identifier prefix
    """
    output_bucket = os.environ.get('S3_BUCKET_OUTPUT')
    output_base_dir = os.environ.get('OUTPUT_DIRECTORY')

    # Upload both full resolution and thumbnails to mission-specific processed_01 directories
    for subdir in ['full', 'thumbnails']:
        local_path = f"/tmp/processing/output/{subdir}"
        # Remote path: <output_base>/<mission_name>/processed_01/<subdir>/
        remote_path = f"s3remote:{output_bucket}/{output_base_dir}/{mission_prefix}/processed_01/{subdir}"

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
    working_dir = "/tmp/processing"

    if os.path.exists(working_dir):
        shutil.rmtree(working_dir)

    print("Cleanup completed")


def main():
    """Main execution function."""
    working_dir = os.environ.get('WORKING_DIR', '/tmp/processing')

    print("Starting Python post-processing container...")
    print(f"Working directory: {working_dir}")

    # Validate required parameters
    required_vars = [
        'S3_ENDPOINT',
        'S3_ACCESS_KEY',
        'S3_SECRET_KEY',
        'S3_BUCKET_INPUT_DATA',
        'S3_BUCKET_INPUT_BOUNDARY'
    ]

    missing_vars = [var for var in required_vars if not os.environ.get(var)]

    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        sys.exit(1)

    # Set up working directory
    os.environ['TMPDIR'] = working_dir
    Path(working_dir).mkdir(parents=True, exist_ok=True)

    print(f"Output max dimension: {os.environ.get('OUTPUT_MAX_DIM', '800')}")

    # Configure rclone
    setup_rclone_config()

    # Download all available data
    mission_dirs = download_photogrammetry_products()
    download_boundary_polygons(mission_dirs)

    # Auto-detect and match missions
    try:
        mission_matches = detect_and_match_missions()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if not mission_matches:
        print("Error: No matching photogrammetry products and boundary polygons found")
        sys.exit(1)

    print(f"Found {len(mission_matches)} missions to process")

    # Process each detected mission
    success_count = 0

    for i, mission in enumerate(mission_matches):
        print(f"\n=== Processing mission {i+1} of {len(mission_matches)}: {mission['prefix']} ===")

        try:
            result = postprocess_photogrammetry_containerized(
                mission['prefix'],
                mission['boundary_file'],
                mission['product_files']
            )

            if result:
                upload_processed_products(mission['prefix'])
                success_count += 1
                print(f"✓ Successfully processed mission: {mission['prefix']}")
            else:
                print(f"✗ Failed to process mission: {mission['prefix']}")

        except Exception as e:
            print(f"✗ Error processing mission {mission['prefix']}: {e}")
            import traceback
            traceback.print_exc()

    cleanup_working_directory()

    # Print summary
    print("\n=== Summary ===")
    print(f"Total missions found: {len(mission_matches)}")
    print(f"Successfully processed: {success_count}")
    print(f"Failed: {len(mission_matches) - success_count}")

    if success_count == len(mission_matches):
        print("All missions processed successfully!")
        sys.exit(0)
    elif success_count > 0:
        print("Partial success - some missions failed")
        sys.exit(1)
    else:
        print("All missions failed")
        sys.exit(1)


if __name__ == '__main__':
    main()

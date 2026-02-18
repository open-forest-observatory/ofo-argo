#!/usr/bin/env python3
"""
Download and extract imagery zip files from S3 for photogrammetry workflow.

This script downloads zip files containing imagery from S3 using rclone,
extracts them to a project-specific directory, and cleans up the zip files
to save space.

Usage:
    python download_imagery.py

Environment Variables:
    IMAGERY_ZIP_URLS: JSON array of S3 paths to download (e.g., '["bucket/path/file.zip"]')
                      Paths should be in format 'bucket/path/to/file.zip' without remote prefix.
                      The S3 connection is configured via the credentials below.
    DOWNLOAD_DIR: Directory for downloads (e.g., '{TEMP_WORKING_DIR}/{workflow_name}/{iteration_id}/photogrammetry/downloaded-raw-imagery')
    S3_PROVIDER: S3 provider for rclone (e.g., 'Ceph', 'AWS')
    S3_ENDPOINT: S3 endpoint URL
    S3_ACCESS_KEY: S3 access key ID
    S3_SECRET_KEY: S3 secret access key

Output:
    Prints the download directory path to stdout on success.
    Exits with non-zero status on failure.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List


def get_s3_flags() -> List[str]:
    """Build common S3 authentication flags for rclone commands."""
    return [
        "--s3-provider",
        os.environ.get("S3_PROVIDER", ""),
        "--s3-endpoint",
        os.environ.get("S3_ENDPOINT", ""),
        "--s3-access-key-id",
        os.environ.get("S3_ACCESS_KEY", ""),
        "--s3-secret-access-key",
        os.environ.get("S3_SECRET_KEY", ""),
    ]


def extract_filename_from_url(url: str) -> str:
    """
    Extract the filename from an S3 path.

    Args:
        url: S3 path in format 'bucket/path/to/file.zip'

    Returns:
        The filename (e.g., 'file.zip')
    """
    # Path format: bucket/path/to/filename.zip
    # Extract the last path component
    return url.rstrip("/").split("/")[-1]


def download_zip(s3_path: str, download_dir: str) -> str:
    """
    Download a zip file from S3 using rclone.

    Args:
        s3_path: S3 path to download (format: 'bucket/path/to/file.zip')
        download_dir: Local directory to download to

    Returns:
        Local path to the downloaded zip file

    Raises:
        subprocess.CalledProcessError: If download fails
    """
    filename = extract_filename_from_url(s3_path)
    local_path = os.path.join(download_dir, filename)

    # Use rclone's on-the-fly backend syntax (:s3:) which configures the
    # S3 backend using command-line flags rather than a config file.
    # This avoids needing a pre-configured remote like "js2s3:".
    rclone_url = f":s3:{s3_path}"

    print(f"Downloading: {s3_path}")
    print(f"  -> {local_path}")

    cmd = [
        "rclone",
        "copyto",
        rclone_url,
        local_path,
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

    subprocess.run(cmd, check=True)

    # Verify download succeeded
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Download completed but file not found: {local_path}")

    file_size = os.path.getsize(local_path)
    print(f"  Downloaded: {file_size / (1024*1024):.1f} MB")

    return local_path


def extract_zip(zip_path: str, extract_dir: str) -> str:
    """
    Extract a zip file to the specified directory.

    Args:
        zip_path: Path to the zip file
        extract_dir: Directory to extract to

    Returns:
        Path to the extraction directory

    Raises:
        subprocess.CalledProcessError: If extraction fails
    """
    print(f"Extracting: {zip_path}")
    print(f"  -> {extract_dir}")

    # Create extraction directory
    os.makedirs(extract_dir, exist_ok=True)

    # Extract using unzip
    # -o: overwrite without prompting
    # -q: quiet mode (less verbose, but errors still shown)
    cmd = ["unzip", "-o", "-q", zip_path, "-d", extract_dir]

    subprocess.run(cmd, check=True)

    print(f"  Extraction complete")

    return extract_dir


def delete_zip(zip_path: str) -> None:
    """
    Delete a zip file to save space.

    Args:
        zip_path: Path to the zip file to delete
    """
    if os.path.exists(zip_path):
        os.remove(zip_path)
        print(f"  Deleted zip: {zip_path}")


def main() -> None:
    """Main entry point for download script."""
    print("=" * 60)
    print("Starting imagery download")
    print("=" * 60)

    # Get environment variables
    imagery_urls_json = os.environ.get("IMAGERY_ZIP_URLS", "[]")
    download_dir = os.environ.get("DOWNLOAD_DIR", "")

    # Validate required environment variables
    if not download_dir:
        print("ERROR: DOWNLOAD_DIR environment variable is required")
        sys.exit(1)

    # Parse URLs
    try:
        imagery_urls = json.loads(imagery_urls_json)
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse IMAGERY_ZIP_URLS as JSON: {e}")
        print(f"  Value: {imagery_urls_json}")
        sys.exit(1)

    if not isinstance(imagery_urls, list):
        print(
            f"ERROR: IMAGERY_ZIP_URLS must be a JSON array, got: {type(imagery_urls).__name__}"
        )
        sys.exit(1)

    if not imagery_urls:
        print("WARNING: No imagery paths provided, nothing to download")
        # Still create the directory and output the path for consistency
        os.makedirs(download_dir, exist_ok=True)
        print(f"DOWNLOAD_PATH={download_dir}")
        sys.exit(0)

    # Create download directory
    os.makedirs(download_dir, exist_ok=True)
    print(f"Download directory: {download_dir}")
    print(f"Paths to download: {len(imagery_urls)}")

    # Process each S3 path
    failed_paths = []
    for i, s3_path in enumerate(imagery_urls, 1):
        print(f"\n[{i}/{len(imagery_urls)}] Processing: {s3_path}")

        try:
            # Download the zip file
            zip_path = download_zip(s3_path, download_dir)

            # Determine extraction folder name (filename without .zip extension)
            filename = extract_filename_from_url(s3_path)
            if filename.lower().endswith(".zip"):
                folder_name = filename[:-4]
            else:
                folder_name = filename
            extract_dir = os.path.join(download_dir, folder_name)

            # Extract the zip file
            extract_zip(zip_path, extract_dir)

            # Delete the zip file to save space
            delete_zip(zip_path)

            print(f"  Successfully processed: {s3_path}")

        except subprocess.CalledProcessError as e:
            print(f"ERROR: Command failed for {s3_path}: {e}")
            failed_paths.append(s3_path)
        except FileNotFoundError as e:
            print(f"ERROR: File not found for {s3_path}: {e}")
            failed_paths.append(s3_path)
        except Exception as e:
            print(f"ERROR: Unexpected error for {s3_path}: {e}")
            failed_paths.append(s3_path)

    images_subset_file = os.environ.get("IMAGES_SUBSET_FILE", "")

    if images_subset_file != "":
        # Remove extra quotes if present
        images_subset_file = images_subset_file.strip('"')
        print(f"Trying to read from {images_subset_file}")

        files = list(Path("/data/argo-input").glob("*"))
        print("Files in /data/argo-input:")
        print(files)

        files = list(
            Path("/data/argo-input/david-photogrammetry-0218/subsets").glob("*")
        )
        print("Files in /data/argo-input/david-photogrammetry-0218/subsets:")
        print(files)

        with open(images_subset_file, "r") as f:
            images_subset = [line.strip() for line in f if line.strip()]

        print("Deleting images not in the specified subset")
        downloaded_files = [f for f in Path(download_dir).rglob("*") if f.is_file()]

        files_to_delete = [f for f in downloaded_files if f.name not in images_subset]

        print(f"Removing {len(files_to_delete)} files not in subset")
        for f in files_to_delete:
            os.remove(f)

    # Report results
    print("\n" + "=" * 60)
    if failed_paths:
        print(f"FAILED: {len(failed_paths)} of {len(imagery_urls)} downloads failed:")
        for s3_path in failed_paths:
            print(f"  - {s3_path}")
        sys.exit(1)
    else:
        print(f"SUCCESS: All {len(imagery_urls)} downloads completed")
        print(f"DOWNLOAD_PATH={download_dir}")
        sys.exit(0)


if __name__ == "__main__":
    main()

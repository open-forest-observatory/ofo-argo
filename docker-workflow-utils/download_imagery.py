#!/usr/bin/env python3
"""
Download and extract imagery zip files from S3 for photogrammetry workflow.

This script downloads zip files containing imagery from S3 using rclone,
extracts them to a project-specific directory, and cleans up the zip files
to save space.

Usage:
    python download_imagery.py

Environment Variables:
    IMAGERY_ZIP_URLS: JSON array of S3 URLs to download (e.g., '["js2s3:bucket/path/file.zip"]')
    DOWNLOAD_BASE_DIR: Base directory for downloads (e.g., '/ofo-share/argo-working/wf-abc/downloaded_imagery')
    ITERATION_ID: Unique identifier for this project iteration (e.g., '000_my_project')
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
    Extract the filename from an S3 URL.

    Args:
        url: S3 URL in format 'remote:bucket/path/to/file.zip'

    Returns:
        The filename (e.g., 'file.zip')
    """
    # URL format: js2s3:bucket/path/to/filename.zip
    # Extract the last path component
    return url.rstrip("/").split("/")[-1]


def download_zip(url: str, download_dir: str) -> str:
    """
    Download a zip file from S3 using rclone.

    Args:
        url: S3 URL to download
        download_dir: Local directory to download to

    Returns:
        Local path to the downloaded zip file

    Raises:
        subprocess.CalledProcessError: If download fails
    """
    filename = extract_filename_from_url(url)
    local_path = os.path.join(download_dir, filename)

    print(f"Downloading: {url}")
    print(f"  -> {local_path}")

    cmd = [
        "rclone",
        "copyto",
        url,
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
    download_base_dir = os.environ.get("DOWNLOAD_BASE_DIR", "")
    iteration_id = os.environ.get("ITERATION_ID", "")

    # Validate required environment variables
    if not download_base_dir:
        print("ERROR: DOWNLOAD_BASE_DIR environment variable is required")
        sys.exit(1)

    if not iteration_id:
        print("ERROR: ITERATION_ID environment variable is required")
        sys.exit(1)

    # Parse URLs
    try:
        imagery_urls = json.loads(imagery_urls_json)
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse IMAGERY_ZIP_URLS as JSON: {e}")
        print(f"  Value: {imagery_urls_json}")
        sys.exit(1)

    if not isinstance(imagery_urls, list):
        print(f"ERROR: IMAGERY_ZIP_URLS must be a JSON array, got: {type(imagery_urls).__name__}")
        sys.exit(1)

    if not imagery_urls:
        print("WARNING: No imagery URLs provided, nothing to download")
        # Still create the directory and output the path for consistency
        download_dir = os.path.join(download_base_dir, iteration_id)
        os.makedirs(download_dir, exist_ok=True)
        print(f"DOWNLOAD_PATH={download_dir}")
        sys.exit(0)

    # Create project-specific download directory
    download_dir = os.path.join(download_base_dir, iteration_id)
    os.makedirs(download_dir, exist_ok=True)
    print(f"Download directory: {download_dir}")
    print(f"URLs to download: {len(imagery_urls)}")

    # Process each URL
    failed_urls = []
    for i, url in enumerate(imagery_urls, 1):
        print(f"\n[{i}/{len(imagery_urls)}] Processing: {url}")

        try:
            # Download the zip file
            zip_path = download_zip(url, download_dir)

            # Determine extraction folder name (filename without .zip extension)
            filename = extract_filename_from_url(url)
            if filename.lower().endswith(".zip"):
                folder_name = filename[:-4]
            else:
                folder_name = filename
            extract_dir = os.path.join(download_dir, folder_name)

            # Extract the zip file
            extract_zip(zip_path, extract_dir)

            # Delete the zip file to save space
            delete_zip(zip_path)

            print(f"  Successfully processed: {url}")

        except subprocess.CalledProcessError as e:
            print(f"ERROR: Command failed for {url}: {e}")
            failed_urls.append(url)
        except FileNotFoundError as e:
            print(f"ERROR: File not found for {url}: {e}")
            failed_urls.append(url)
        except Exception as e:
            print(f"ERROR: Unexpected error for {url}: {e}")
            failed_urls.append(url)

    # Report results
    print("\n" + "=" * 60)
    if failed_urls:
        print(f"FAILED: {len(failed_urls)} of {len(imagery_urls)} downloads failed:")
        for url in failed_urls:
            print(f"  - {url}")
        sys.exit(1)
    else:
        print(f"SUCCESS: All {len(imagery_urls)} downloads completed")
        print(f"DOWNLOAD_PATH={download_dir}")
        sys.exit(0)


if __name__ == "__main__":
    main()

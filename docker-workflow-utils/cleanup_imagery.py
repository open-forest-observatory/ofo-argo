#!/usr/bin/env python3
"""
Clean up downloaded imagery after photogrammetry workflow completion.

This script safely deletes the downloaded imagery directory for a specific
project iteration after photogrammetry has completed. It includes safety
checks to prevent accidental deletion of important data.

Usage:
    python cleanup_imagery.py

Environment Variables:
    DOWNLOAD_DIR: Directory to delete (e.g., '/ofo-share/argo-working/wf-abc/downloaded_imagery/000_my_project')

Output:
    Prints status messages to stdout.
    Exits with non-zero status on failure.
"""

import os
import shutil
import sys


# Required path components for safety validation
REQUIRED_PATH_COMPONENTS = ["downloaded_imagery", "argo-working"]


def validate_path_safety(path: str) -> bool:
    """
    Validate that the path is safe to delete.

    This prevents accidental deletion of important data if paths are
    misconfigured. The path must contain expected components that indicate
    it's within the workflow's temporary directory structure.

    Args:
        path: The directory path to validate

    Returns:
        True if the path is safe to delete, False otherwise
    """
    # Normalize the path for consistent checking
    normalized_path = os.path.normpath(path)

    # Check that all required components are present in the path
    for component in REQUIRED_PATH_COMPONENTS:
        if component not in normalized_path:
            print(f"ERROR: Path missing required component '{component}'")
            print(f"  Path: {normalized_path}")
            return False

    # Additional safety: don't allow deletion of root-level directories
    # The path should have sufficient depth (at least /ofo-share/argo-working/xxx/downloaded_imagery/yyy)
    path_parts = [p for p in normalized_path.split(os.sep) if p]
    if len(path_parts) < 5:
        print(f"ERROR: Path appears too shallow to be a valid download directory")
        print(f"  Path: {normalized_path}")
        print(f"  Parts: {path_parts}")
        return False

    return True


def cleanup_directory(download_dir: str) -> bool:
    """
    Remove the download directory and all its contents.

    Args:
        download_dir: Path to the directory to delete

    Returns:
        True if cleanup was successful, False otherwise
    """
    # Check if directory exists
    if not os.path.exists(download_dir):
        print(f"Directory does not exist, nothing to clean up: {download_dir}")
        return True

    if not os.path.isdir(download_dir):
        print(f"ERROR: Path exists but is not a directory: {download_dir}")
        return False

    # Calculate directory size before deletion for logging
    total_size = 0
    file_count = 0
    try:
        for dirpath, dirnames, filenames in os.walk(download_dir):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                    file_count += 1
                except (OSError, IOError):
                    pass
    except Exception as e:
        print(f"WARNING: Could not calculate directory size: {e}")

    print(f"Removing directory: {download_dir}")
    print(f"  Files: {file_count}")
    print(f"  Size: {total_size / (1024*1024):.1f} MB")

    try:
        shutil.rmtree(download_dir)
        print("  Cleanup complete")
        return True
    except PermissionError as e:
        print(f"ERROR: Permission denied when deleting directory: {e}")
        return False
    except Exception as e:
        print(f"ERROR: Failed to delete directory: {e}")
        return False


def main() -> None:
    """Main entry point for cleanup script."""
    print("=" * 60)
    print("Starting imagery cleanup")
    print("=" * 60)

    # Get environment variable
    download_dir = os.environ.get("DOWNLOAD_DIR", "")

    # Validate required environment variable
    if not download_dir:
        print("ERROR: DOWNLOAD_DIR environment variable is required")
        sys.exit(1)

    print(f"Target directory: {download_dir}")

    # Safety validation - fail if path doesn't look right
    if not validate_path_safety(download_dir):
        print("\nFAILED: Path failed safety validation")
        print("This may indicate a bug or misconfiguration.")
        print("Please verify the DOWNLOAD_DIR path is correct.")
        sys.exit(1)

    # Perform cleanup
    if cleanup_directory(download_dir):
        print("\n" + "=" * 60)
        print("SUCCESS: Cleanup completed")
        sys.exit(0)
    else:
        print("\n" + "=" * 60)
        print("FAILED: Cleanup encountered errors")
        sys.exit(1)


if __name__ == "__main__":
    main()

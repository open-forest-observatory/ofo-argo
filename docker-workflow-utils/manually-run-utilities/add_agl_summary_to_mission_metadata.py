#!/usr/bin/env python3
"""
Backfill AGL summary columns onto mission image-metadata GeoPackages.

For each mission in S3, downloads the camera-locations file (which has per-image
altitude_agl), computes summary statistics, and writes them as new columns
(agl_mean, agl_fidelity) onto the image-metadata file, then re-uploads it.

Usage:
    python backfill_agl_summary.py \
        --bucket ofo-public \
        --missions-prefix drone/missions_03 \
        --photogrammetry-subfolder photogrammetry_03

    # Dry run (no uploads):
    python backfill_agl_summary.py \
        --bucket ofo-public \
        --missions-prefix drone/missions_03 \
        --photogrammetry-subfolder photogrammetry_03 \
        --dry-run

    # Process specific missions only:
    python backfill_agl_summary.py \
        --bucket ofo-public \
        --missions-prefix drone/missions_03 \
        --photogrammetry-subfolder photogrammetry_03 \
        --missions 000016 000017

Requirements:
    - boto3, geopandas, numpy
    - S3 credentials configured (env vars, ~/.aws/credentials, or IAM role)

Environment variables for S3:
    S3_ENDPOINT: S3 endpoint URL (for non-AWS S3)
    AWS_ACCESS_KEY_ID: Access key
    AWS_SECRET_ACCESS_KEY: Secret key
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

try:
    import boto3
    from botocore.config import Config
except ImportError:
    print("Error: boto3 required. Install with: pip install boto3", file=sys.stderr)
    sys.exit(1)

try:
    import geopandas as gpd
except ImportError:
    print(
        "Error: geopandas required. Install with: pip install geopandas",
        file=sys.stderr,
    )
    sys.exit(1)


def get_s3_client():
    """Create S3 client with optional custom endpoint."""
    endpoint = os.environ.get("S3_ENDPOINT")

    if endpoint:
        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID")
            or os.environ.get("S3_ACCESS_KEY"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY")
            or os.environ.get("S3_SECRET_KEY"),
            config=Config(signature_version="s3v4"),
        )
    else:
        return boto3.client("s3")


def discover_missions(client, bucket, missions_prefix):
    """List mission IDs by finding metadata-images subdirectories."""
    paginator = client.get_paginator("list_objects_v2")
    mission_ids = set()

    # Look for image-metadata files to discover missions
    for page in paginator.paginate(
        Bucket=bucket, Prefix=f"{missions_prefix}/", Delimiter="/"
    ):
        for prefix_obj in page.get("CommonPrefixes", []):
            # e.g. "drone/missions_03/000016/"
            parts = prefix_obj["Prefix"].rstrip("/").split("/")
            mission_ids.add(parts[-1])

    return sorted(mission_ids)


def s3_key_exists(client, bucket, key):
    """Check if an S3 key exists."""
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except client.exceptions.ClientError:
        return False


def download_s3_file(client, bucket, key, local_path):
    """Download a file from S3."""
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    client.download_file(bucket, key, local_path)


def upload_s3_file(client, bucket, key, local_path):
    """Upload a file to S3."""
    client.upload_file(local_path, bucket, key)


def compute_agl_summary(camera_locations_gdf):
    """
    Compute AGL summary stats from camera locations.

    Returns (agl_mean, agl_fidelity) or (None, None) if insufficient data.
    """
    agl = camera_locations_gdf["altitude_agl"].dropna()

    if len(agl) < 5:
        return None, None

    # Get the middle 80% of AGL (to exclude outliers like landscape shots)
    agl_lwr = agl.quantile(0.1)
    agl_upr = agl.quantile(0.9)
    agl_core = agl[(agl > agl_lwr) & (agl < agl_upr)]

    if len(agl_core) == 0:
        return None, None

    agl_mean = round(float(agl_core.mean()), 1)

    # Compute terrain follow fidelity: score = max(0, 100 - 2 * std_AGL)
    std_agl = float(agl_core.std())
    agl_fidelity = round(max(0, 100 - 2 * std_agl))

    return agl_mean, agl_fidelity


def process_mission(client, bucket, missions_prefix, photogrammetry_subfolder, mission_id, dry_run=False):
    """
    Process a single mission: download camera-locations, compute AGL summary,
    add columns to image-metadata, and re-upload.

    Returns True if processed successfully, False if skipped/failed.
    """
    metadata_key = f"{missions_prefix}/{mission_id}/metadata-images/{mission_id}_image-metadata.gpkg"
    camera_key = f"{missions_prefix}/{mission_id}/{photogrammetry_subfolder}/full/{mission_id}_camera-locations.gpkg"

    # Check both files exist
    if not s3_key_exists(client, bucket, metadata_key):
        print(f"  SKIP: image-metadata not found: {metadata_key}", file=sys.stderr)
        return False

    if not s3_key_exists(client, bucket, camera_key):
        print(f"  SKIP: camera-locations not found: {camera_key}", file=sys.stderr)
        return False

    with tempfile.TemporaryDirectory() as tmpdir:
        local_metadata = os.path.join(tmpdir, "image-metadata.gpkg")
        local_camera = os.path.join(tmpdir, "camera-locations.gpkg")

        # Download both files
        download_s3_file(client, bucket, metadata_key, local_metadata)
        download_s3_file(client, bucket, camera_key, local_camera)

        # Read camera locations and compute summary
        camera_gdf = gpd.read_file(local_camera)

        if "altitude_agl" not in camera_gdf.columns:
            print(f"  SKIP: no altitude_agl column in camera-locations", file=sys.stderr)
            return False

        agl_mean, agl_fidelity = compute_agl_summary(camera_gdf)

        if agl_mean is None:
            print(f"  SKIP: insufficient AGL data", file=sys.stderr)
            return False

        print(f"  agl_mean={agl_mean}, agl_fidelity={agl_fidelity}", file=sys.stderr)

        if dry_run:
            return True

        # Read image metadata, add columns, and save
        metadata_gdf = gpd.read_file(local_metadata)
        metadata_gdf["agl_mean"] = agl_mean
        metadata_gdf["agl_fidelity"] = agl_fidelity
        metadata_gdf.to_file(local_metadata, driver="GPKG")

        # Re-upload
        upload_s3_file(client, bucket, metadata_key, local_metadata)
        print(f"  Uploaded updated metadata", file=sys.stderr)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Backfill AGL summary columns onto mission image-metadata files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--bucket", required=True, help="S3 bucket (e.g. ofo-public)"
    )
    parser.add_argument(
        "--missions-prefix",
        required=True,
        help="S3 prefix for missions (e.g. drone/missions_03)",
    )
    parser.add_argument(
        "--photogrammetry-subfolder",
        required=True,
        help="Photogrammetry config subfolder (e.g. photogrammetry_03)",
    )
    parser.add_argument(
        "--missions",
        nargs="*",
        help="Specific mission IDs to process (default: all discovered missions)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print results without uploading",
    )

    args = parser.parse_args()

    client = get_s3_client()

    # Discover or use specified missions
    if args.missions:
        mission_ids = args.missions
        print(f"Processing {len(mission_ids)} specified missions", file=sys.stderr)
    else:
        print(f"Discovering missions in s3://{args.bucket}/{args.missions_prefix}/...", file=sys.stderr)
        mission_ids = discover_missions(client, args.bucket, args.missions_prefix)
        print(f"Found {len(mission_ids)} missions", file=sys.stderr)

    if args.dry_run:
        print("[DRY RUN] No files will be modified", file=sys.stderr)

    processed = 0
    skipped = 0

    for mission_id in mission_ids:
        print(f"\n{mission_id}:", file=sys.stderr)
        success = process_mission(
            client,
            args.bucket,
            args.missions_prefix,
            args.photogrammetry_subfolder,
            mission_id,
            dry_run=args.dry_run,
        )
        if success:
            processed += 1
        else:
            skipped += 1

    print(f"\nDone: {processed} processed, {skipped} skipped", file=sys.stderr)


if __name__ == "__main__":
    main()

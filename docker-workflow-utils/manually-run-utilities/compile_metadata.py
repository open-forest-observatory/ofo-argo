#!/usr/bin/env python3
"""
Compile all mission-level and image-level metadata into single GeoPackages.

Iterates over missions in S3, downloads each mission's metadata files,
concatenates them (adding a mission_id column), and uploads the compiled
files back to S3.

Usage:
    python compile_metadata.py \
        --bucket ofo-public \
        --missions-prefix drone/missions_03

    # Dry run (download and compile but don't upload):
    python compile_metadata.py \
        --bucket ofo-public \
        --missions-prefix drone/missions_03 \
        --dry-run

    # Process specific missions only:
    python compile_metadata.py \
        --bucket ofo-public \
        --missions-prefix drone/missions_03 \
        --missions 000016 000017

Requirements:
    - boto3, geopandas, pandas
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

try:
    import boto3
    from botocore.config import Config
except ImportError:
    print("Error: boto3 required. Install with: pip install boto3", file=sys.stderr)
    sys.exit(1)

try:
    import geopandas as gpd
    import pandas as pd
except ImportError:
    print(
        "Error: geopandas and pandas required. Install with: pip install geopandas pandas",
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
    """List mission IDs by finding top-level subdirectories."""
    paginator = client.get_paginator("list_objects_v2")
    mission_ids = set()

    for page in paginator.paginate(
        Bucket=bucket, Prefix=f"{missions_prefix}/", Delimiter="/"
    ):
        for prefix_obj in page.get("CommonPrefixes", []):
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
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    client.download_file(bucket, key, local_path)


def upload_s3_file(client, bucket, key, local_path):
    """Upload a file to S3."""
    client.upload_file(local_path, bucket, key)


def collect_metadata(client, bucket, missions_prefix, mission_ids):
    """
    Download and concatenate metadata files across all missions.

    Returns (missions_gdf, images_gdf) — either may be None if no data found.
    """
    mission_gdfs = []
    image_gdfs = []

    for mission_id in mission_ids:
        mission_key = f"{missions_prefix}/{mission_id}/metadata-mission/{mission_id}_mission-metadata.gpkg"
        image_key = f"{missions_prefix}/{mission_id}/metadata-images/{mission_id}_image-metadata.gpkg"

        print(f"\n{mission_id}:", file=sys.stderr)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Mission metadata
            if s3_key_exists(client, bucket, mission_key):
                local_path = os.path.join(tmpdir, "mission.gpkg")
                download_s3_file(client, bucket, mission_key, local_path)
                gdf = gpd.read_file(local_path)
                if "mission_id" not in gdf.columns:
                    gdf.insert(0, "mission_id", mission_id)
                mission_gdfs.append(gdf)
                print(f"  mission-metadata: {len(gdf)} rows", file=sys.stderr)
            else:
                print(f"  mission-metadata: not found", file=sys.stderr)

            # Image metadata
            if s3_key_exists(client, bucket, image_key):
                local_path = os.path.join(tmpdir, "images.gpkg")
                download_s3_file(client, bucket, image_key, local_path)
                gdf = gpd.read_file(local_path)
                if "mission_id" not in gdf.columns:
                    gdf.insert(0, "mission_id", mission_id)
                image_gdfs.append(gdf)
                print(f"  image-metadata: {len(gdf)} rows", file=sys.stderr)
            else:
                print(f"  image-metadata: not found", file=sys.stderr)

    missions_compiled = (
        gpd.GeoDataFrame(pd.concat(mission_gdfs, ignore_index=True))
        if mission_gdfs
        else None
    )
    images_compiled = (
        gpd.GeoDataFrame(pd.concat(image_gdfs, ignore_index=True))
        if image_gdfs
        else None
    )

    return missions_compiled, images_compiled


def main():
    parser = argparse.ArgumentParser(
        description="Compile per-mission metadata into single GeoPackages",
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
        "--missions",
        nargs="*",
        help="Specific mission IDs to process (default: all discovered missions)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compile and print summary without uploading",
    )

    args = parser.parse_args()

    client = get_s3_client()

    # Discover or use specified missions
    if args.missions:
        mission_ids = args.missions
        print(f"Processing {len(mission_ids)} specified missions", file=sys.stderr)
    else:
        print(
            f"Discovering missions in s3://{args.bucket}/{args.missions_prefix}/...",
            file=sys.stderr,
        )
        mission_ids = discover_missions(client, args.bucket, args.missions_prefix)
        print(f"Found {len(mission_ids)} missions", file=sys.stderr)

    if args.dry_run:
        print("[DRY RUN] No files will be uploaded", file=sys.stderr)

    # Collect all metadata
    missions_compiled, images_compiled = collect_metadata(
        client, args.bucket, args.missions_prefix, mission_ids
    )

    # Save and upload
    with tempfile.TemporaryDirectory() as tmpdir:
        if missions_compiled is not None:
            local_path = os.path.join(tmpdir, "metadata-missions-compiled.gpkg")
            missions_compiled.to_file(local_path, driver="GPKG")
            print(
                f"\nMissions compiled: {len(missions_compiled)} rows, "
                f"{len(missions_compiled.columns)} columns",
                file=sys.stderr,
            )
            if not args.dry_run:
                upload_key = f"{args.missions_prefix}/metadata-missions-compiled.gpkg"
                upload_s3_file(client, args.bucket, upload_key, local_path)
                print(f"Uploaded to s3://{args.bucket}/{upload_key}", file=sys.stderr)
        else:
            print("\nNo mission metadata found", file=sys.stderr)

        if images_compiled is not None:
            local_path = os.path.join(tmpdir, "metadata-images-compiled.gpkg")
            images_compiled.to_file(local_path, driver="GPKG")
            print(
                f"\nImages compiled: {len(images_compiled)} rows, "
                f"{len(images_compiled.columns)} columns",
                file=sys.stderr,
            )
            if not args.dry_run:
                upload_key = f"{args.missions_prefix}/metadata-images-compiled.gpkg"
                upload_s3_file(client, args.bucket, upload_key, local_path)
                print(f"Uploaded to s3://{args.bucket}/{upload_key}", file=sys.stderr)
        else:
            print("\nNo image metadata found", file=sys.stderr)

    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()

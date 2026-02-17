#!/usr/bin/env python3
"""
Compile all mission-level and image-level metadata into single GeoPackages.

Iterates over missions in S3, downloads each mission's metadata files using
rclone, concatenates them (adding a mission_id column), and uploads the
compiled files back to S3.

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
    - rclone, geopandas, pandas
    - rclone remote configured via environment variables (see below)

Environment variables for rclone (configures the js2s3 remote without a config file):
    RCLONE_CONFIG_JS2S3_TYPE: Set to "s3"
    RCLONE_CONFIG_JS2S3_PROVIDER: S3 provider (e.g., "Other")
    RCLONE_CONFIG_JS2S3_ENDPOINT: S3 endpoint URL
    RCLONE_CONFIG_JS2S3_ENV_AUTH: Set to "true" to use AWS env vars for auth
    AWS_ACCESS_KEY_ID: S3 access key
    AWS_SECRET_ACCESS_KEY: S3 secret key
"""

import argparse
import glob
import os
import subprocess
import sys
import tempfile

try:
    import geopandas as gpd
    import pandas as pd
except ImportError:
    print(
        "Error: geopandas and pandas required. Install with: pip install geopandas pandas",
        file=sys.stderr,
    )
    sys.exit(1)

RCLONE_REMOTE = "js2s3"


def rclone_copy(src, dst, includes=None):
    """Run an rclone copy command with optional --include filters."""
    cmd = ["rclone", "copy", src, dst, "--transfers", "32", "--checkers", "32"]
    if includes:
        for pattern in includes:
            cmd += ["--include", pattern]
    print(f"  rclone copy {src} -> {dst}", file=sys.stderr)
    subprocess.run(cmd, check=True)


def rclone_copyto(src, dst):
    """Run an rclone copyto command (single file)."""
    cmd = ["rclone", "copyto", src, dst]
    print(f"  rclone copyto {src} -> {dst}", file=sys.stderr)
    subprocess.run(cmd, check=True)


def rclone_lsf(remote_path, dirs_only=False):
    """List items at a remote path using rclone lsf."""
    cmd = ["rclone", "lsf", remote_path]
    if dirs_only:
        cmd += ["--dirs-only"]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return [
        line.rstrip("/") for line in result.stdout.strip().splitlines() if line.strip()
    ]


def discover_missions(bucket, missions_prefix):
    """List mission IDs by finding top-level subdirectories."""
    remote_path = f"{RCLONE_REMOTE}:{bucket}/{missions_prefix}/"
    return sorted(rclone_lsf(remote_path, dirs_only=True))


def collect_metadata(bucket, missions_prefix, mission_ids, tmpdir):
    """
    Download and concatenate metadata files across all missions.

    Uses a single rclone copy with --include filters to download all matching
    files in parallel, then reads and concatenates them locally.

    If specific mission_ids are provided, downloads only those missions'
    metadata. Otherwise downloads all metadata files matching the pattern.

    Returns (missions_gdf, images_gdf) — either may be None if no data found.
    """
    remote_path = f"{RCLONE_REMOTE}:{bucket}/{missions_prefix}/"

    if mission_ids:
        includes = []
        for mid in mission_ids:
            includes.append(f"{mid}/metadata-mission/{mid}_mission-metadata.gpkg")
            includes.append(f"{mid}/metadata-images/{mid}_image-metadata.gpkg")
    else:
        includes = [
            "*/metadata-mission/*_mission-metadata.gpkg",
            "*/metadata-images/*_image-metadata.gpkg",
        ]

    print(f"\nDownloading metadata files...", file=sys.stderr)
    rclone_copy(remote_path, tmpdir, includes=includes)

    # Read downloaded files
    mission_gdfs = []
    image_gdfs = []

    mission_files = sorted(
        glob.glob(os.path.join(tmpdir, "*/metadata-mission/*_mission-metadata.gpkg"))
    )
    image_files = sorted(
        glob.glob(os.path.join(tmpdir, "*/metadata-images/*_image-metadata.gpkg"))
    )

    for f in mission_files:
        mission_id = os.path.basename(f).split("_")[0]
        gdf = gpd.read_file(f)
        if "mission_id" not in gdf.columns:
            gdf.insert(0, "mission_id", mission_id)
        mission_gdfs.append(gdf)
        print(f"  {mission_id} mission-metadata: {len(gdf)} rows", file=sys.stderr)

    for f in image_files:
        mission_id = os.path.basename(f).split("_")[0]
        gdf = gpd.read_file(f)
        if "mission_id" not in gdf.columns:
            gdf.insert(0, "mission_id", mission_id)
        image_gdfs.append(gdf)
        print(f"  {mission_id} image-metadata: {len(gdf)} rows", file=sys.stderr)

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
    parser.add_argument("--bucket", required=True, help="S3 bucket (e.g. ofo-public)")
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

    # Discover or use specified missions
    if args.missions:
        mission_ids = args.missions
        print(f"Processing {len(mission_ids)} specified missions", file=sys.stderr)
    else:
        print(
            f"Discovering missions in {RCLONE_REMOTE}:{args.bucket}/{args.missions_prefix}/...",
            file=sys.stderr,
        )
        mission_ids = discover_missions(args.bucket, args.missions_prefix)
        print(f"Found {len(mission_ids)} missions", file=sys.stderr)

    if args.dry_run:
        print("[DRY RUN] No files will be uploaded", file=sys.stderr)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Download and collect all metadata
        missions_compiled, images_compiled = collect_metadata(
            args.bucket, args.missions_prefix, mission_ids, tmpdir
        )

        # Save and upload
        if missions_compiled is not None:
            local_path = os.path.join(tmpdir, "metadata-missions-compiled.gpkg")
            missions_compiled.to_file(local_path, driver="GPKG")
            print(
                f"\nMissions compiled: {len(missions_compiled)} rows, "
                f"{len(missions_compiled.columns)} columns",
                file=sys.stderr,
            )
            if not args.dry_run:
                remote_path = f"{RCLONE_REMOTE}:{args.bucket}/{args.missions_prefix}/metadata-missions-compiled.gpkg"
                rclone_copyto(local_path, remote_path)
                print(f"Uploaded to {remote_path}", file=sys.stderr)
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
                remote_path = f"{RCLONE_REMOTE}:{args.bucket}/{args.missions_prefix}/metadata-images-compiled.gpkg"
                rclone_copyto(local_path, remote_path)
                print(f"Uploaded to {remote_path}", file=sys.stderr)
        else:
            print("\nNo image metadata found", file=sys.stderr)

    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()

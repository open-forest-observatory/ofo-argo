#!/usr/bin/env python3
"""
Backfill AGL summary columns onto composite (paired-mission) metadata GeoPackages.

Composite equivalent of add_agl_summary_to_mission_metadata.py. For each composite in S3,
downloads the camera-locations file from the composite's own photogrammetry run, merges its
per-image photogrammetry columns into the composite image-metadata (replacing any values carried
over from the single-mission runs), and computes agl_mean and agl_fidelity separately for each
component mission (one row each in the composite mission-metadata), then re-uploads both files.
Safe to re-run: existing photogrammetry and AGL columns are replaced, not duplicated.

Usage:
    python add_agl_summary_to_composite_metadata.py \
        --bucket ofo-public \
        --composites-prefix drone/mission-composites_01 \
        --photogrammetry-subfolder photogrammetry_03

    # Dry run (no uploads):
    python add_agl_summary_to_composite_metadata.py \
        --bucket ofo-public \
        --composites-prefix drone/mission-composites_01 \
        --photogrammetry-subfolder photogrammetry_03 \
        --dry-run

    # Process specific composites only:
    python add_agl_summary_to_composite_metadata.py \
        --bucket ofo-public \
        --composites-prefix drone/mission-composites_01 \
        --photogrammetry-subfolder photogrammetry_03 \
        --composites 000016_000017

Requirements and S3 environment variables are the same as for
add_agl_summary_to_mission_metadata.py.
"""

import argparse
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import geopandas as gpd
from add_agl_summary_to_mission_metadata import (
    LEGACY_CAMERA_COLUMN_NAMES,
    compute_agl_summary,
    discover_missions,
    download_s3_file,
    get_s3_client,
    s3_key_exists,
    upload_s3_file,
)

# Dummy composite used for testing
EXCLUDED_COMPOSITES = {"000000_000000"}


def process_composite(
    bucket, composites_prefix, photogrammetry_subfolder, composite_id, dry_run=False
):
    """
    Process a single composite: download camera-locations, merge per-image photogrammetry columns
    into image-metadata, add per-mission AGL summary columns to mission-metadata, and re-upload.

    Creates its own S3 client so it can safely run in a thread pool.

    Returns (success: bool, message: str).
    """
    client = get_s3_client()
    base = f"{composites_prefix}/{composite_id}"
    mission_key = f"{base}/metadata-mission/{composite_id}_mission-metadata.gpkg"
    image_key = f"{base}/metadata-images/{composite_id}_image-metadata.gpkg"
    camera_key = (
        f"{base}/{photogrammetry_subfolder}/full/{composite_id}_camera-locations.gpkg"
    )

    # Check all files exist
    if not s3_key_exists(client, bucket, mission_key):
        return False, f"SKIP: mission-metadata not found: {mission_key}"

    if not s3_key_exists(client, bucket, image_key):
        return False, f"SKIP: image-metadata not found: {image_key}"

    if not s3_key_exists(client, bucket, camera_key):
        return False, f"SKIP: camera-locations not found: {camera_key}"

    with tempfile.TemporaryDirectory() as tmpdir:
        local_mission_metadata = os.path.join(
            tmpdir, f"{composite_id}_mission-metadata.gpkg"
        )
        local_image_metadata = os.path.join(
            tmpdir, f"{composite_id}_image-metadata.gpkg"
        )
        local_camera = os.path.join(tmpdir, f"{composite_id}_camera-locations.gpkg")

        # Download all metadata files
        download_s3_file(client, bucket, mission_key, local_mission_metadata)
        download_s3_file(client, bucket, image_key, local_image_metadata)
        download_s3_file(client, bucket, camera_key, local_camera)

        # Read camera locations, mapping any legacy column names to the current ones
        camera_gdf = gpd.read_file(local_camera)
        camera_gdf = camera_gdf.rename(
            columns={
                old: new
                for old, new in LEGACY_CAMERA_COLUMN_NAMES.items()
                if old in camera_gdf.columns and new not in camera_gdf.columns
            }
        )

        if "photogrammetry_altitude_agl" not in camera_gdf.columns:
            return (
                False,
                "SKIP: no photogrammetry_altitude_agl column in camera-locations",
            )

        # Add attributes to the camera_gdf for the three positional columns
        camera_gdf.to_crs(4326, inplace=True)
        camera_gdf["photogrammetry_lon"] = camera_gdf.geometry.x
        camera_gdf["photogrammetry_lat"] = camera_gdf.geometry.y
        camera_gdf["photogrammetry_asl"] = camera_gdf.geometry.z
        # Remove the geometry to avoid having two geometry columns
        camera_gdf = camera_gdf.drop(columns="geometry")

        # Read image locations
        image_gdf = gpd.read_file(local_image_metadata)
        # Drop photogrammetry columns carried over from the single-mission runs (or left by a
        # previous run of this script) so they are replaced rather than duplicated with _x/_y
        image_gdf = image_gdf.drop(
            columns=[c for c in camera_gdf.columns if c != "image_id"], errors="ignore"
        )
        # Merge the composite photogrammetry data into the composite imagery metadata
        image_gdf = image_gdf.merge(camera_gdf, on="image_id")

        if len(image_gdf) == 0:
            return False, "SKIP: no image_id matches between image-metadata and cameras"

        # Compute AGL summary separately for each component mission (hn and lo)
        metadata_gdf = gpd.read_file(local_mission_metadata)
        agl_by_mission = {
            mission_id: compute_agl_summary(images)
            for mission_id, images in image_gdf.groupby("mission_id")
        }
        metadata_gdf["agl_mean"] = metadata_gdf["mission_id"].map(
            lambda m: agl_by_mission.get(m, (None, None))[0]
        )
        metadata_gdf["agl_fidelity"] = metadata_gdf["mission_id"].map(
            lambda m: agl_by_mission.get(m, (None, None))[1]
        )

        summary = ", ".join(
            f"{m}: agl_mean={mean}, agl_fidelity={fid}"
            for m, (mean, fid) in sorted(agl_by_mission.items())
        )

        if metadata_gdf["agl_mean"].isna().all():
            return False, f"SKIP: insufficient AGL data ({summary})"

        if dry_run:
            return True, summary

        # Save after removing the old files (to avoid adding a second layer)
        os.remove(local_mission_metadata)
        metadata_gdf.to_file(local_mission_metadata, driver="GPKG")
        os.remove(local_image_metadata)
        image_gdf.to_file(local_image_metadata, driver="GPKG")

        # Re-upload
        upload_s3_file(client, bucket, mission_key, local_mission_metadata)
        upload_s3_file(client, bucket, image_key, local_image_metadata)
        return True, f"{summary} — uploaded"


def main():
    parser = argparse.ArgumentParser(
        description="Backfill AGL summary columns onto composite metadata files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--bucket", required=True, help="S3 bucket (e.g. ofo-public)")
    parser.add_argument(
        "--composites-prefix",
        required=True,
        help="S3 prefix for composites (e.g. drone/mission-composites_01)",
    )
    parser.add_argument(
        "--photogrammetry-subfolder",
        required=True,
        help="Photogrammetry config subfolder (e.g. photogrammetry_03)",
    )
    parser.add_argument(
        "--composites",
        nargs="*",
        help="Specific composite IDs to process (default: all discovered composites)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print results without uploading",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of parallel threads (default: 8)",
    )

    args = parser.parse_args()

    # Discover or use specified composites (uses its own client for the listing call)
    if args.composites:
        composite_ids = args.composites
        print(f"Processing {len(composite_ids)} specified composites", file=sys.stderr)
    else:
        client = get_s3_client()
        print(
            f"Discovering composites in s3://{args.bucket}/{args.composites_prefix}/...",
            file=sys.stderr,
        )
        composite_ids = [
            c
            for c in discover_missions(client, args.bucket, args.composites_prefix)
            if c not in EXCLUDED_COMPOSITES
        ]
        print(f"Found {len(composite_ids)} composites", file=sys.stderr)

    if args.dry_run:
        print("[DRY RUN] No files will be modified", file=sys.stderr)

    processed = 0
    skipped = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_composite,
                args.bucket,
                args.composites_prefix,
                args.photogrammetry_subfolder,
                composite_id,
                dry_run=args.dry_run,
            ): composite_id
            for composite_id in composite_ids
        }

        for future in as_completed(futures):
            composite_id = futures[future]
            try:
                success, message = future.result()
            except Exception as e:
                print(f"\n{composite_id}:\n  ERROR: {e}", file=sys.stderr)
                skipped += 1
                continue

            print(f"\n{composite_id}:\n  {message}", file=sys.stderr)
            if success:
                processed += 1
            else:
                skipped += 1

    print(f"\nDone: {processed} processed, {skipped} skipped", file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Pair high-nadir (hn) and low-oblique (lo) drone missions based on spatial overlap,
date proximity, altitude, pitch, and terrain-follow fidelity.

Outputs:
  - A pairs GeoPackage with one polygon per mission per pair (hn cropped to overlap
    with lo, lo cropped to 100 m beyond hn footprint).
  - A selected-images GeoPackage with images falling within each pair polygon.

Usage:
    python pair_missions.py \
        --bucket ofo-public \
        --missions-prefix drone/missions_03

    # With local files instead of S3:
    python pair_missions.py \
        --local-missions metadata-missions-compiled.gpkg \
        --local-images metadata-images-compiled.gpkg

    # Dry run (no file writes / uploads):
    python pair_missions.py \
        --bucket ofo-public \
        --missions-prefix drone/missions_03 \
        --dry-run

Requirements:
    - geopandas, pandas, numpy, shapely
    - boto3 (only when using --bucket)

Environment variables for S3:
    S3_ENDPOINT: S3 endpoint URL (for non-AWS S3)
    AWS_ACCESS_KEY_ID / S3_ACCESS_KEY: Access key
    AWS_SECRET_ACCESS_KEY / S3_SECRET_KEY: Secret key
"""

import argparse
import os
import sys
import tempfile
from collections import Counter

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.validation import make_valid

# ---------------------------------------------------------------------------
# Pairing criteria — edit these constants to adjust classification & matching
# ---------------------------------------------------------------------------

# High-nadir classification
HN_ALTITUDE_MIN = 100  # metres AGL
HN_ALTITUDE_MAX = 160
HN_PITCH_MIN = 0  # degrees from nadir
HN_PITCH_MAX = 10

# Low-oblique classification
LO_ALTITUDE_MIN = 60
LO_ALTITUDE_MAX = 120
LO_PITCH_MIN = 18
LO_PITCH_MAX = 38

# Minimum terrain-follow fidelity (0–100 scale) for either type
MIN_FIDELITY = 50

# Temporal pairing criterion: maximum difference in days between missions
MAX_DATE_DIFF_DAYS = 365*1.5 # (allows pairing between early in Year 1 and late in Year 2)

# Spatial pairing criterion: minimum intersection area in hectares
MIN_OVERLAP_HA = 2.0

# Buffer (metres) applied to hn footprint when cropping the lo polygon
LO_BUFFER_M = 100

# Projected CRS used for area calculations and buffering (metres)
WORKING_CRS = "EPSG:32610"

# Subset-filter: fraction of area to consider one footprint "entirely a subset"
SUBSET_AREA_THRESHOLD = 0.99

# Subset-filter: only drop the smaller footprint if its area is less than this
# fraction of the larger footprint's area (avoids dropping near-equal pairs)
SUBSET_SIZE_RATIO = 0.75

# Within-year preference: date-diff threshold (days) defining "within-year"
WITHIN_YEAR_DAYS = 150

# Within-year preference: keep a cross-year pairing only if its footprint area
# exceeds the best within-year footprint by more than this fraction
WITHIN_YEAR_AREA_MARGIN = 0.10

# # -------------------------------------------------------------------------
# # For interaactive running: define args as if called from command line
# # -------------------------------------------------------------------------

# args = argparse.Namespace(
#     bucket=None,
#     missions_prefix=None,
#     local_missions="~/repo-data-local/tmp/metadata-missions-compiled.gpkg",
#     local_images="~/repo-data-local/tmp/metadata-images-compiled.gpkg",
#     output_dir=".",
#     upload=False,
#     dry_run=True,
# )


# ---------------------------------------------------------------------------
# S3 helpers (only used when --bucket is supplied)
# ---------------------------------------------------------------------------


def get_s3_client():
    """Create S3 client with optional custom endpoint."""
    import boto3
    from botocore.config import Config

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
    return boto3.client("s3")


def download_s3_file(client, bucket, key, local_path):
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    client.download_file(bucket, key, local_path)


def upload_s3_file(client, bucket, key, local_path):
    client.upload_file(local_path, bucket, key)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_mission(row):
    """Return 'hn', 'lo', or None based on configurable thresholds."""
    alt = row.get("agl_mean")
    pitch = row.get("camera_pitch_derived")
    fidelity = row.get("agl_fidelity")

    if pd.isna(alt) or pd.isna(pitch):
        return None

    # Fidelity check (allow NaN fidelity to pass if we don't have it)
    if pd.notna(fidelity) and fidelity < MIN_FIDELITY:
        return None

    pitch = abs(float(pitch))

    if HN_ALTITUDE_MIN <= alt <= HN_ALTITUDE_MAX and HN_PITCH_MIN <= pitch <= HN_PITCH_MAX:
        return "hn"
    if LO_ALTITUDE_MIN <= alt <= LO_ALTITUDE_MAX and LO_PITCH_MIN <= pitch <= LO_PITCH_MAX:
        return "lo"

    return None


# ---------------------------------------------------------------------------
# Pairing logic
# ---------------------------------------------------------------------------


def find_valid_pairs(missions_gdf):
    """
    Classify missions then find all valid hn–lo pairs.

    Returns a DataFrame with one row per valid pair, including:
      hn_mission_id, lo_mission_id, overlap_area_ha, date_diff_days,
      hn_geom (original), lo_geom (original), intersection_geom
    """
    missions = missions_gdf.copy()

    # Parse date
    missions["earliest_date_derived"] = pd.to_datetime(
        missions["earliest_date_derived"], errors="coerce"
    )

    # Numeric coercion
    for col in ["agl_mean", "agl_fidelity", "camera_pitch_derived"]:
        if col in missions.columns:
            missions[col] = pd.to_numeric(missions[col], errors="coerce")

    # Classify
    missions["_type"] = missions.apply(classify_mission, axis=1)

    hn = missions[missions["_type"] == "hn"].copy()
    lo = missions[missions["_type"] == "lo"].copy()

    print(f"Classified {len(hn)} missions as hn, {len(lo)} as lo "
          f"(of {len(missions)} total)", file=sys.stderr)

    if hn.empty or lo.empty:
        print("No valid pairs possible — one side is empty.", file=sys.stderr)
        return pd.DataFrame()

    # Project to metre-based CRS for area / buffer calculations
    hn = hn.to_crs(WORKING_CRS)
    lo = lo.to_crs(WORKING_CRS)

    # Build pairs via spatial overlay (intersection)
    pairs = gpd.overlay(
        hn[["mission_id", "earliest_date_derived", "geometry"]].rename(
            columns={"mission_id": "hn_mission_id",
                     "earliest_date_derived": "hn_date",
                     "geometry": "geometry"}
        ),
        lo[["mission_id", "earliest_date_derived", "geometry"]].rename(
            columns={"mission_id": "lo_mission_id",
                     "earliest_date_derived": "lo_date",
                     "geometry": "geometry"}
        ),
        how="intersection",
        keep_geom_type=False,
    )

    if pairs.empty:
        print("No spatially overlapping hn–lo pairs found.", file=sys.stderr)
        return pd.DataFrame()

    # Compute overlap area in hectares
    pairs["overlap_area_ha"] = pairs.geometry.area / 1e4

    # Filter by minimum overlap
    pairs = pairs[pairs["overlap_area_ha"] >= MIN_OVERLAP_HA].copy()
    print(f"Pairs with >= {MIN_OVERLAP_HA} ha overlap: {len(pairs)}", file=sys.stderr)

    # Filter by date difference
    pairs["date_diff_days"] = (pairs["hn_date"] - pairs["lo_date"]).abs().dt.days
    pairs = pairs[
        pairs["date_diff_days"].isna() | (pairs["date_diff_days"] <= MAX_DATE_DIFF_DAYS)
    ].copy()
    print(f"Pairs within {MAX_DATE_DIFF_DAYS}-day window: {len(pairs)}", file=sys.stderr)

    if pairs.empty:
        return pd.DataFrame()

    # Attach original (projected) geometries for polygon cropping
    hn_geom = hn.set_index("mission_id")["geometry"].rename("hn_geom")
    lo_geom = lo.set_index("mission_id")["geometry"].rename("lo_geom")
    pairs = pairs.merge(hn_geom, left_on="hn_mission_id", right_index=True)
    pairs = pairs.merge(lo_geom, left_on="lo_mission_id", right_index=True)

    # Sort: largest overlap first, then smallest date diff — used for tie-breaking
    pairs = pairs.sort_values(
        ["overlap_area_ha", "date_diff_days"], ascending=[False, True]
    ).reset_index(drop=True)

    return pairs


def build_pair_polygons(pairs):
    """
    For each pair, produce the cropped hn and lo polygons.

    - hn polygon = intersection(hn_footprint, lo_footprint)
    - lo polygon = intersection(lo_footprint, hn_footprint.buffer(LO_BUFFER_M))

    Returns a GeoDataFrame with columns:
      pair_id, mission_type ('hn'/'lo'), mission_id, date, area_m2, geometry
    """
    rows = []
    for idx, row in pairs.iterrows():
        pair_id = idx
        hn_fp = make_valid(row["hn_geom"])
        lo_fp = make_valid(row["lo_geom"])

        hn_poly = hn_fp.intersection(lo_fp)
        lo_poly = lo_fp.intersection(hn_fp.buffer(LO_BUFFER_M))

        rows.append({
            "pair_id": pair_id,
            "mission_type": "hn",
            "mission_id": row["hn_mission_id"],
            "date": row["hn_date"],
            "area_m2": hn_poly.area,
            "geometry": hn_poly,
        })
        rows.append({
            "pair_id": pair_id,
            "mission_type": "lo",
            "mission_id": row["lo_mission_id"],
            "date": row["lo_date"],
            "area_m2": lo_poly.area,
            "geometry": lo_poly,
        })

    return gpd.GeoDataFrame(rows, crs=WORKING_CRS)


def filter_subset_pairs(pairs, pair_polygons):
    """
    Remove pairs where a mission's cropped footprint is entirely a subset of
    its cropped footprint in a different pairing.  When this occurs, keep only
    the pairing that gives that mission the larger footprint.
    """
    pairs_to_drop = set()

    for mission_id in pair_polygons["mission_id"].unique():
        rows = pair_polygons[pair_polygons["mission_id"] == mission_id]
        if len(rows) <= 1:
            continue

        idxs = rows.index.tolist()
        for i in range(len(idxs)):
            ai = rows.loc[idxs[i], "area_m2"]
            if ai <= 0:
                continue
            gi = make_valid(rows.loc[idxs[i], "geometry"])
            for j in range(len(idxs)):
                if i == j:
                    continue
                aj = rows.loc[idxs[j], "area_m2"]
                if ai >= aj:
                    continue  # only check if gi is the smaller one
                if ai >= SUBSET_SIZE_RATIO * aj:
                    continue  # too similar in size to consider a subset
                gj = make_valid(rows.loc[idxs[j], "geometry"])
                if gj.is_empty:
                    continue
                if gi.intersection(gj).area / ai >= SUBSET_AREA_THRESHOLD:
                    pairs_to_drop.add(rows.loc[idxs[i], "pair_id"])
                    break  # already dropping this pair, no need to check more

    if pairs_to_drop:
        print(
            f"\nDropping {len(pairs_to_drop)} pair(s) where a mission's footprint "
            f"is entirely a subset of its footprint in another pairing: "
            f"{sorted(int(p) for p in pairs_to_drop)}",
            file=sys.stderr,
        )
        pairs = pairs[~pairs.index.isin(pairs_to_drop)].reset_index(drop=True)
        pair_polygons = pair_polygons[
            ~pair_polygons["pair_id"].isin(pairs_to_drop)
        ].reset_index(drop=True)

    return pairs, pair_polygons


def filter_prefer_within_year(pairs, pair_polygons):
    """
    For missions appearing in multiple pairs, prefer within-year pairings
    (date_diff_days < WITHIN_YEAR_DAYS).  Drop cross-year pairings unless the
    mission's cropped footprint in the cross-year pairing is more than
    WITHIN_YEAR_AREA_MARGIN larger than its largest within-year footprint.
    """
    pairs_to_drop = set()

    # Merge date_diff_days onto pair_polygons for easy lookup
    pp = pair_polygons.merge(
        pairs[["date_diff_days"]],
        left_on="pair_id",
        right_index=True,
        how="left",
    )

    for mission_id in pp["mission_id"].unique():
        rows = pp[pp["mission_id"] == mission_id]
        if len(rows) <= 1:
            continue

        within = rows[rows["date_diff_days"].notna() & (rows["date_diff_days"] < WITHIN_YEAR_DAYS)]
        cross = rows[rows["date_diff_days"].isna() | (rows["date_diff_days"] >= WITHIN_YEAR_DAYS)]

        if within.empty or cross.empty:
            continue

        best_within_area = within["area_m2"].max()

        for _, crow in cross.iterrows():
            if crow["area_m2"] <= best_within_area * (1 + WITHIN_YEAR_AREA_MARGIN):
                pairs_to_drop.add(crow["pair_id"])

    if pairs_to_drop:
        print(
            f"\nDropping {len(pairs_to_drop)} pair(s) in favour of within-year "
            f"pairings: {sorted(int(p) for p in pairs_to_drop)}",
            file=sys.stderr,
        )
        pairs = pairs[~pairs.index.isin(pairs_to_drop)].reset_index(drop=True)
        pair_polygons = pair_polygons[
            ~pair_polygons["pair_id"].isin(pairs_to_drop)
        ].reset_index(drop=True)

    return pairs, pair_polygons


def select_images(pair_polygons, images_gdf):
    """
    Select images that fall within each pair polygon.

    Returns a GeoDataFrame of images with pair_id and mission_type attached.
    """
    images = images_gdf.to_crs(WORKING_CRS)

    # Spatial join: each image matched to the pair polygon(s) it falls within
    selected = gpd.sjoin(
        images,
        pair_polygons[["pair_id", "mission_type", "mission_id", "geometry"]].rename(
            columns={"mission_id": "pair_mission_id"}
        ),
        how="inner",
        predicate="within",
    )

    # Keep only images whose mission_id matches the pair's mission_id
    selected = selected[selected["mission_id"] == selected["pair_mission_id"]].copy()
    selected.drop(columns=["index_right", "pair_mission_id"], errors="ignore", inplace=True)

    return selected


# ---------------------------------------------------------------------------
# Duplication reporting
# ---------------------------------------------------------------------------


def report_duplications(pairs):
    """Print a summary of missions appearing in multiple pairs."""
    hn_counts = Counter(pairs["hn_mission_id"])
    lo_counts = Counter(pairs["lo_mission_id"])

    multi_hn = {m: c for m, c in hn_counts.items() if c > 1}
    multi_lo = {m: c for m, c in lo_counts.items() if c > 1}

    if not multi_hn and not multi_lo:
        print("\nNo missions appear in multiple pairs.", file=sys.stderr)
        return

    print("\n=== Duplication report ===", file=sys.stderr)

    hn_overlap_cache = {}
    for mission_id, count in sorted(multi_hn.items()):
        partner_rows = pairs[pairs["hn_mission_id"] == mission_id]
        partners = partner_rows["lo_mission_id"].tolist()
        partner_geoms = partner_rows["lo_geom"].tolist()
        overlaps = _compute_partner_overlaps(partner_geoms, partners)
        hn_overlap_cache[mission_id] = overlaps
        dup_type = "same-area" if _is_same_area(overlaps) else "different-area"
        overlap_str = ", ".join(
            f"{a}–{b}: {pct:.0f}%" for a, b, pct in overlaps
        )
        print(
            f"  hn {mission_id} appears in {count} pairs "
            f"(lo partners: {partners}, type: {dup_type}, "
            f"partner overlap: {overlap_str})",
            file=sys.stderr,
        )

    lo_overlap_cache = {}
    for mission_id, count in sorted(multi_lo.items()):
        partner_rows = pairs[pairs["lo_mission_id"] == mission_id]
        partners = partner_rows["hn_mission_id"].tolist()
        partner_geoms = partner_rows["hn_geom"].tolist()
        overlaps = _compute_partner_overlaps(partner_geoms, partners)
        lo_overlap_cache[mission_id] = overlaps
        dup_type = "same-area" if _is_same_area(overlaps) else "different-area"
        overlap_str = ", ".join(
            f"{a}–{b}: {pct:.0f}%" for a, b, pct in overlaps
        )
        print(
            f"  lo {mission_id} appears in {count} pairs "
            f"(hn partners: {partners}, type: {dup_type}, "
            f"partner overlap: {overlap_str})",
            file=sys.stderr,
        )

    # Tallies
    same_area_hn = sum(1 for m in multi_hn if _is_same_area(hn_overlap_cache[m]))
    diff_area_hn = len(multi_hn) - same_area_hn
    same_area_lo = sum(1 for m in multi_lo if _is_same_area(lo_overlap_cache[m]))
    diff_area_lo = len(multi_lo) - same_area_lo

    print(f"\n  Summary:", file=sys.stderr)
    print(f"    hn missions in multiple pairs: {len(multi_hn)} "
          f"(same-area: {same_area_hn}, different-area: {diff_area_hn})", file=sys.stderr)
    print(f"    lo missions in multiple pairs: {len(multi_lo)} "
          f"(same-area: {same_area_lo}, different-area: {diff_area_lo})", file=sys.stderr)


def _compute_partner_overlaps(geoms, labels):
    """
    Compute pairwise overlap percentages between partner geometries.

    Returns a list of (label_i, label_j, overlap_pct) tuples for all pairs,
    where overlap_pct is intersection area / smaller geometry area * 100.
    """
    overlaps = []
    for i in range(len(geoms)):
        for j in range(i + 1, len(geoms)):
            g1 = make_valid(geoms[i])
            g2 = make_valid(geoms[j])
            if g1.is_empty or g2.is_empty:
                overlaps.append((labels[i], labels[j], 0.0))
                continue
            inter = g1.intersection(g2).area
            smaller = min(g1.area, g2.area)
            pct = (inter / smaller * 100) if smaller > 0 else 0.0
            overlaps.append((labels[i], labels[j], pct))
    return overlaps


def _is_same_area(overlaps):
    """Return True if any pairwise overlap exceeds 25% of the smaller partner."""
    return any(pct > 25 for _, _, pct in overlaps)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Pair high-nadir and low-oblique drone missions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # S3 source
    parser.add_argument("--bucket", help="S3 bucket (e.g. ofo-public)")
    parser.add_argument(
        "--missions-prefix",
        help="S3 prefix for missions (e.g. drone/missions_03)",
    )

    # Local source (alternative to S3)
    parser.add_argument(
        "--local-missions",
        help="Path to local metadata-missions-compiled.gpkg",
    )
    parser.add_argument(
        "--local-images",
        help="Path to local metadata-images-compiled.gpkg",
    )

    # Output
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Local directory for output files (default: current dir)",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload outputs to S3 under --missions-prefix",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute pairs and report but don't write files",
    )

    args = parser.parse_args()

    # Expand ~ in paths
    if args.local_missions:
        args.local_missions = os.path.expanduser(args.local_missions)
    if args.local_images:
        args.local_images = os.path.expanduser(args.local_images)
    if args.output_dir:
        args.output_dir = os.path.expanduser(args.output_dir)

    # Validate args
    using_s3 = args.bucket and args.missions_prefix
    using_local = args.local_missions and args.local_images
    if not using_s3 and not using_local:
        parser.error(
            "Provide either --bucket + --missions-prefix or "
            "--local-missions + --local-images"
        )

    # ---- Load data --------------------------------------------------------
    if using_s3:
        client = get_s3_client()
        tmpdir = tempfile.mkdtemp()
        missions_path = os.path.join(tmpdir, "missions.gpkg")
        images_path = os.path.join(tmpdir, "images.gpkg")

        missions_key = f"{args.missions_prefix}/metadata-missions-compiled.gpkg"
        images_key = f"{args.missions_prefix}/metadata-images-compiled.gpkg"

        print(f"Downloading s3://{args.bucket}/{missions_key}", file=sys.stderr)
        download_s3_file(client, args.bucket, missions_key, missions_path)
        print(f"Downloading s3://{args.bucket}/{images_key}", file=sys.stderr)
        download_s3_file(client, args.bucket, images_key, images_path)
    else:
        missions_path = args.local_missions
        images_path = args.local_images

    missions_gdf = gpd.read_file(missions_path)
    images_gdf = gpd.read_file(images_path)

    print(f"Loaded {len(missions_gdf)} missions, {len(images_gdf)} images",
          file=sys.stderr)

    # ---- Find pairs -------------------------------------------------------
    pairs = find_valid_pairs(missions_gdf)
    if pairs.empty:
        print("No valid pairs found. Exiting.", file=sys.stderr)
        sys.exit(0)

    print(f"\nFound {len(pairs)} valid pairs", file=sys.stderr)
    report_duplications(pairs)

    # ---- Build output polygons --------------------------------------------
    pair_polygons = build_pair_polygons(pairs)

    # ---- Filter subset pairs ----------------------------------------------
    pairs, pair_polygons = filter_subset_pairs(pairs, pair_polygons)

    # ---- Prefer within-year pairings --------------------------------------
    pairs, pair_polygons = filter_prefer_within_year(pairs, pair_polygons)

    # Back to geographic CRS for output
    pair_polygons_out = pair_polygons.to_crs("EPSG:4326")

    print(f"\nPair polygons: {len(pair_polygons_out)} rows "
          f"({len(pairs)} pairs x 2 mission types)", file=sys.stderr)

    # ---- Select images ----------------------------------------------------
    selected_images = select_images(pair_polygons, images_gdf)
    selected_images_out = selected_images.to_crs("EPSG:4326")

    print(f"Selected images: {len(selected_images_out)} rows", file=sys.stderr)

    # Count duplicated images
    if "image_id" in selected_images_out.columns:
        dup_images = selected_images_out.duplicated(subset=["image_id"], keep=False).sum()
        unique_images = selected_images_out["image_id"].nunique()
        print(f"  Unique images: {unique_images}, duplicated rows: {dup_images}",
              file=sys.stderr)

    if args.dry_run:
        print("\n[DRY RUN] No files written.", file=sys.stderr)
        return

    # ---- Save outputs -----------------------------------------------------
    os.makedirs(args.output_dir, exist_ok=True)

    pairs_path = os.path.join(args.output_dir, "paired-mission-polygons.gpkg")
    images_out_path = os.path.join(args.output_dir, "paired-mission-images.gpkg")

    pair_polygons_out.to_file(pairs_path, driver="GPKG")
    print(f"\nWrote {pairs_path}", file=sys.stderr)

    selected_images_out.to_file(images_out_path, driver="GPKG")
    print(f"Wrote {images_out_path}", file=sys.stderr)

    # ---- Upload to S3 if requested ----------------------------------------
    if args.upload and using_s3:
        pairs_key = f"{args.missions_prefix}/paired-mission-polygons.gpkg"
        images_key = f"{args.missions_prefix}/paired-mission-images.gpkg"
        upload_s3_file(client, args.bucket, pairs_key, pairs_path)
        print(f"Uploaded s3://{args.bucket}/{pairs_key}", file=sys.stderr)
        upload_s3_file(client, args.bucket, images_key, images_out_path)
        print(f"Uploaded s3://{args.bucket}/{images_key}", file=sys.stderr)

    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()

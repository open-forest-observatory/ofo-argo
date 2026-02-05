#!/usr/bin/env python3
"""
Generate a completion log from existing S3 products.

Scans S3 buckets for products from workflow runs that completed before
the logging feature was implemented, and generates a compatible completion log.

Usage:
    python generate_retroactive_log.py \
        --internal-bucket ofo-internal \
        --internal-prefix photogrammetry/default-run \
        --public-bucket ofo-public \
        --public-prefix postprocessed \
        --config-id default \
        --output completion-log.jsonl

Requirements:
    - boto3 (pip install boto3)
    - S3 credentials configured (env vars, ~/.aws/credentials, or IAM role)

Environment variables for S3:
    S3_ENDPOINT: S3 endpoint URL (for non-AWS S3)
    AWS_ACCESS_KEY_ID: Access key
    AWS_SECRET_ACCESS_KEY: Secret key
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

try:
    import boto3
    from botocore.config import Config
except ImportError:
    print("Error: boto3 required. Install with: pip install boto3", file=sys.stderr)
    sys.exit(1)


def get_s3_client():
    """Create S3 client with optional custom endpoint."""
    endpoint = os.environ.get("S3_ENDPOINT")

    if endpoint:
        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("S3_ACCESS_KEY"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY") or os.environ.get("S3_SECRET_KEY"),
            config=Config(signature_version="s3v4"),
        )
    else:
        return boto3.client("s3")


def list_s3_objects(client, bucket: str, prefix: str, max_keys: int = 10000) -> List[dict]:
    """
    List objects in S3 bucket with prefix.

    Returns list of dicts with 'Key' and 'LastModified' fields.
    """
    objects = []
    paginator = client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, MaxKeys=max_keys):
        if "Contents" in page:
            objects.extend(page["Contents"])

    return objects


def extract_project_name_from_key(key: str, prefix: str) -> Optional[str]:
    """
    Extract project name from S3 object key.

    For internal bucket (metashape products):
        prefix/project_name/project_name_product.tif -> project_name

    For public bucket (postprocessed):
        prefix/project_name_product.tif -> project_name
    """
    # Remove prefix
    relative = key[len(prefix):].lstrip("/")

    # Check if it's in a subdirectory (internal bucket structure)
    parts = relative.split("/")
    if len(parts) >= 2:
        # Structure: project_name/filename
        return parts[0]
    elif len(parts) == 1:
        # Structure: project_name_product.ext (flat, postprocessed)
        filename = parts[0]
        # Extract project name by removing _product.ext suffix
        # Pattern: project_name_ortho.tif, project_name_dsm-ptcloud.tif, etc.
        match = re.match(r"^(.+?)_(ortho|dsm-ptcloud|dsm-mesh|dtm-ptcloud|chm-ptcloud|chm-mesh|ptcloud)\.", filename)
        if match:
            return match.group(1)

    return None


def detect_metashape_complete(
    client, bucket: str, prefix: str, config_subfolder: Optional[str] = None
) -> Dict[str, datetime]:
    """
    Detect projects with completed metashape products.

    Returns dict mapping project_name -> latest LastModified timestamp.
    """
    full_prefix = prefix
    if config_subfolder:
        full_prefix = f"{prefix}/{config_subfolder}"

    print(f"Scanning s3://{bucket}/{full_prefix} for metashape products...", file=sys.stderr)

    objects = list_s3_objects(client, bucket, full_prefix)
    print(f"  Found {len(objects)} objects", file=sys.stderr)

    # Sentinel patterns that indicate completion
    sentinel_patterns = [
        r"_report\.pdf$",
    ]

    projects: Dict[str, datetime] = {}

    for obj in objects:
        key = obj["Key"]

        # Check if this is a sentinel file
        is_sentinel = any(re.search(pattern, key) for pattern in sentinel_patterns)
        if not is_sentinel:
            continue

        project_name = extract_project_name_from_key(key, full_prefix)
        if project_name:
            timestamp = obj["LastModified"]
            if project_name not in projects or timestamp > projects[project_name]:
                projects[project_name] = timestamp

    print(f"  Detected {len(projects)} completed metashape projects", file=sys.stderr)
    return projects


def detect_postprocess_complete(
    client, bucket: str, prefix: str
) -> Dict[str, datetime]:
    """
    Detect projects with completed postprocessed products.

    Returns dict mapping project_name -> latest LastModified timestamp.
    """
    print(f"Scanning s3://{bucket}/{prefix} for postprocessed products...", file=sys.stderr)

    objects = list_s3_objects(client, bucket, prefix)
    print(f"  Found {len(objects)} objects", file=sys.stderr)

    # Look for report PDF as sentinel (last file produced by postprocessing)
    projects: Dict[str, datetime] = {}

    for obj in objects:
        key = obj["Key"]

        # Only consider report PDF as sentinel for postprocess completion
        if not re.search(r"_report\.pdf$", key):
            continue

        project_name = extract_project_name_from_key(key, prefix)
        if project_name:
            timestamp = obj["LastModified"]
            if project_name not in projects or timestamp > projects[project_name]:
                projects[project_name] = timestamp

    print(f"  Detected {len(projects)} completed postprocess projects", file=sys.stderr)
    return projects


def generate_log_entries(
    metashape_projects: Dict[str, datetime],
    postprocess_projects: Dict[str, datetime],
    config_id: str,
) -> List[dict]:
    """
    Generate completion log entries from detected projects.

    A project gets:
    - 'postprocess' level if found in postprocess_projects
    - 'metashape' level if found only in metashape_projects
    """
    entries = []
    all_projects = set(metashape_projects.keys()) | set(postprocess_projects.keys())

    for project_name in sorted(all_projects):
        # Determine completion level (postprocess > metashape)
        if project_name in postprocess_projects:
            level = "postprocess"
            timestamp = postprocess_projects[project_name]
        else:
            level = "metashape"
            timestamp = metashape_projects[project_name]

        entry = {
            "project_name": project_name,
            "config_id": config_id,
            "completion_level": level,
            "timestamp": timestamp.isoformat(),
            "workflow_name": "retroactive-bootstrap",
        }
        entries.append(entry)

    return entries


def main():
    parser = argparse.ArgumentParser(
        description="Generate completion log from existing S3 products",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Scan default locations
    python generate_retroactive_log.py \\
        --internal-bucket ofo-internal \\
        --internal-prefix photogrammetry/default-run \\
        --public-bucket ofo-public \\
        --public-prefix postprocessed \\
        --output completion-log.jsonl

    # With config subfolder
    python generate_retroactive_log.py \\
        --internal-bucket ofo-internal \\
        --internal-prefix photogrammetry/default-run \\
        --config-subfolder photogrammetry_highres \\
        --public-bucket ofo-public \\
        --public-prefix postprocessed \\
        --config-id highres \\
        --output completion-log.jsonl

    # Metashape only (no postprocess check)
    python generate_retroactive_log.py \\
        --internal-bucket ofo-internal \\
        --internal-prefix photogrammetry/default-run \\
        --level metashape \\
        --output completion-log.jsonl
        """,
    )

    parser.add_argument("--internal-bucket", required=True,
                        help="S3 bucket for internal/metashape products")
    parser.add_argument("--internal-prefix", required=True,
                        help="S3 prefix for metashape products (e.g., photogrammetry/default-run)")
    parser.add_argument("--config-subfolder", default="",
                        help="Optional config subfolder (e.g., photogrammetry_highres)")
    parser.add_argument("--public-bucket", default="",
                        help="S3 bucket for public/postprocessed products (optional)")
    parser.add_argument("--public-prefix", default="",
                        help="S3 prefix for postprocessed products (optional)")
    parser.add_argument("--config-id", default="default",
                        help="Config ID to use in log entries")
    parser.add_argument("--level", choices=["metashape", "postprocess", "both"], default="both",
                        help="Which completion levels to detect")
    parser.add_argument("--output", "-o", required=True,
                        help="Output file path for completion log")
    parser.add_argument("--append", action="store_true",
                        help="Append to existing log instead of overwriting")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written without writing")

    args = parser.parse_args()

    # Validate args
    if args.level in ["postprocess", "both"] and (not args.public_bucket or not args.public_prefix):
        parser.error("--public-bucket and --public-prefix required when checking postprocess level")

    # Create S3 client
    client = get_s3_client()

    # Detect completed projects
    metashape_projects: Dict[str, datetime] = {}
    postprocess_projects: Dict[str, datetime] = {}

    if args.level in ["metashape", "both"]:
        metashape_projects = detect_metashape_complete(
            client, args.internal_bucket, args.internal_prefix, args.config_subfolder or None
        )

    if args.level in ["postprocess", "both"]:
        postprocess_projects = detect_postprocess_complete(
            client, args.public_bucket, args.public_prefix
        )

    # Generate log entries
    entries = generate_log_entries(metashape_projects, postprocess_projects, args.config_id)

    print(f"\nGenerated {len(entries)} log entries:", file=sys.stderr)
    metashape_only = sum(1 for e in entries if e["completion_level"] == "metashape")
    postprocess_count = sum(1 for e in entries if e["completion_level"] == "postprocess")
    print(f"  - metashape level: {metashape_only}", file=sys.stderr)
    print(f"  - postprocess level: {postprocess_count}", file=sys.stderr)

    if args.dry_run:
        print("\n[DRY RUN] Would write:", file=sys.stderr)
        for entry in entries:
            print(json.dumps(entry))
        return

    # Write output
    mode = "a" if args.append else "w"
    with open(args.output, mode) as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    print(f"\nWrote {len(entries)} entries to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()

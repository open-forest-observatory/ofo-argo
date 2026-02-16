#!/usr/bin/env python3
"""
Generate a completion log from existing S3 products.

Scans S3 buckets for products from workflow runs that completed before
the logging feature was implemented, and generates a compatible completion log.

Usage:
    python generate_retroactive_log.py \
        --internal-bucket ofo-internal \
        --internal-prefix photogrammetry-outputs/photogrammetry_03 \
        --public-bucket ofo-public \
        --public-prefix drone/missions_03 \
        --public-config-subfolder photogrammetry_03 \
        --output completion-log_02.jsonl

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
from datetime import datetime
from typing import Dict, List, Optional

try:
    import boto3
    from botocore.config import Config
except ImportError:
    print("Error: boto3 required. Install with: pip install boto3", file=sys.stderr)
    sys.exit(1)

# Sentinel file pattern that indicates a completed project
SENTINEL_PATTERN = re.compile(r"_report\.pdf$")


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


def list_s3_objects(
    client, bucket: str, prefix: str, max_keys: int = 10000
) -> List[dict]:
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


def extract_project_name_from_sentinel(
    key: str, prefix: str, config_subfolder: Optional[str] = None
) -> Optional[str]:
    """
    Extract project name from a sentinel file's S3 key.

    Without config_subfolder, handles:
        prefix/project_name/project_name_report.pdf -> project_name (nested)
        prefix/project_name_report.pdf -> project_name (flat)

    With config_subfolder (e.g., "photogrammetry_03"), only matches:
        prefix/project_name/photogrammetry_03/..._report.pdf -> project_name
    """
    # Remove prefix
    relative = key[len(prefix) :].lstrip("/")

    parts = relative.split("/")

    if config_subfolder:
        # Require: project_name/config_subfolder/..._report.pdf
        if len(parts) >= 3 and parts[1] == config_subfolder:
            return parts[0]
        return None

    if len(parts) >= 2:
        # Nested structure: project_name/filename
        return parts[0]
    elif len(parts) == 1:
        # Flat structure: project_name_report.pdf
        filename = parts[0]
        # Remove _report.pdf suffix
        if filename.endswith("_report.pdf"):
            return filename[: -len("_report.pdf")]

    return None


def detect_completed_projects(
    client,
    bucket: str,
    prefix: str,
    label: str,
    config_subfolder: Optional[str] = None,
) -> Dict[str, datetime]:
    """
    Detect projects with sentinel files indicating completion.

    Args:
        config_subfolder: If provided, only match sentinels under this subfolder
            within each project directory (e.g., "photogrammetry_03").

    Returns dict mapping project_name -> latest LastModified timestamp.
    """
    print(f"Scanning s3://{bucket}/{prefix} for {label} products...", file=sys.stderr)
    if config_subfolder:
        print(f"  Filtering to config subfolder: {config_subfolder}", file=sys.stderr)

    objects = list_s3_objects(client, bucket, prefix)
    print(f"  Found {len(objects)} objects", file=sys.stderr)

    projects: Dict[str, datetime] = {}

    for obj in objects:
        key = obj["Key"]

        if not SENTINEL_PATTERN.search(key):
            continue

        project_name = extract_project_name_from_sentinel(key, prefix, config_subfolder)
        if project_name:
            timestamp = obj["LastModified"]
            if project_name not in projects or timestamp > projects[project_name]:
                projects[project_name] = timestamp

    print(f"  Detected {len(projects)} completed {label} projects", file=sys.stderr)
    return projects


def generate_log_entries(
    metashape_projects: Dict[str, datetime],
    postprocess_projects: Dict[str, datetime],
) -> List[dict]:
    """
    Generate completion log entries from detected projects.

    A project gets an entry for each phase it has completed (metashape, postprocess,
    or both).

    Note: config_id is not included in entries. Use separate log files per config.
    """
    entries = []
    all_projects = set(metashape_projects.keys()) | set(postprocess_projects.keys())

    for project_name in sorted(all_projects):
        if project_name in metashape_projects:
            entries.append(
                {
                    "project_name": project_name,
                    "phase": "metashape",
                    "timestamp": metashape_projects[project_name].isoformat(),
                    "workflow_name": "retroactive-bootstrap",
                }
            )
        if project_name in postprocess_projects:
            entries.append(
                {
                    "project_name": project_name,
                    "phase": "postprocess",
                    "timestamp": postprocess_projects[project_name].isoformat(),
                    "workflow_name": "retroactive-bootstrap",
                }
            )

    return entries


def main():
    parser = argparse.ArgumentParser(
        description="Generate completion log from existing S3 products",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Scan both phases for a specific config
    # Internal: photogrammetry-outputs/photogrammetry_03/<project>/*_report.pdf
    # Public:   drone/missions_03/<project>/photogrammetry_03/*_report.pdf
    python generate_retroactive_log.py \\
        --internal-bucket ofo-internal \\
        --internal-prefix photogrammetry-outputs/photogrammetry_03 \\
        --public-bucket ofo-public \\
        --public-prefix drone/missions_03 \\
        --public-config-subfolder photogrammetry_03 \\
        --output completion-log-03.jsonl

    # Metashape only (no postprocess check)
    python generate_retroactive_log.py \\
        --internal-bucket ofo-internal \\
        --internal-prefix photogrammetry-outputs/photogrammetry_03 \\
        --phase metashape \\
        --output completion-log-03.jsonl
        """,
    )

    parser.add_argument(
        "--internal-bucket",
        required=True,
        help="S3 bucket for internal/metashape products",
    )
    parser.add_argument(
        "--internal-prefix",
        required=True,
        help="S3 prefix for metashape products (e.g., photogrammetry/default-run or photogrammetry/default-run/photogrammetry_highres)",
    )
    parser.add_argument(
        "--public-bucket",
        default="",
        help="S3 bucket for public/postprocessed products (optional)",
    )
    parser.add_argument(
        "--public-prefix",
        default="",
        help="S3 prefix for postprocessed products (optional)",
    )
    parser.add_argument(
        "--public-config-subfolder",
        default="",
        help="Photogrammetry config subfolder to match within each project directory "
        "in the public bucket (e.g., photogrammetry_03). Only sentinel files under "
        "this subfolder will count as postprocess completions.",
    )
    parser.add_argument(
        "--phase",
        choices=["metashape", "postprocess", "both"],
        default="both",
        help="Which completion phases to detect",
    )
    parser.add_argument(
        "--output", "-o", required=True, help="Output file path for completion log"
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing log instead of overwriting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without writing",
    )

    args = parser.parse_args()

    # Validate args
    if args.phase in ["postprocess", "both"] and (
        not args.public_bucket or not args.public_prefix
    ):
        parser.error(
            "--public-bucket and --public-prefix required when checking postprocess phase"
        )

    # Create S3 client
    client = get_s3_client()

    # Detect completed projects
    metashape_projects: Dict[str, datetime] = {}
    postprocess_projects: Dict[str, datetime] = {}

    if args.phase in ["metashape", "both"]:
        metashape_projects = detect_completed_projects(
            client, args.internal_bucket, args.internal_prefix, "metashape"
        )

    if args.phase in ["postprocess", "both"]:
        postprocess_projects = detect_completed_projects(
            client,
            args.public_bucket,
            args.public_prefix,
            "postprocess",
            config_subfolder=args.public_config_subfolder or None,
        )

    # Generate log entries
    entries = generate_log_entries(metashape_projects, postprocess_projects)

    print(f"\nGenerated {len(entries)} log entries:", file=sys.stderr)
    metashape_only = sum(1 for e in entries if e["phase"] == "metashape")
    postprocess_count = sum(1 for e in entries if e["phase"] == "postprocess")
    print(f"  - metashape phase: {metashape_only}", file=sys.stderr)
    print(f"  - postprocess phase: {postprocess_count}", file=sys.stderr)

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

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
        --output completion-log-default.jsonl

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


def extract_project_name_from_sentinel(key: str, prefix: str) -> Optional[str]:
    """
    Extract project name from a sentinel file's S3 key.

    Handles two structures:
        prefix/project_name/project_name_report.pdf -> project_name (nested)
        prefix/project_name_report.pdf -> project_name (flat)
    """
    # Remove prefix
    relative = key[len(prefix) :].lstrip("/")

    parts = relative.split("/")
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
    client, bucket: str, prefix: str, label: str
) -> Dict[str, datetime]:
    """
    Detect projects with sentinel files indicating completion.

    Returns dict mapping project_name -> latest LastModified timestamp.
    """
    print(f"Scanning s3://{bucket}/{prefix} for {label} products...", file=sys.stderr)

    objects = list_s3_objects(client, bucket, prefix)
    print(f"  Found {len(objects)} objects", file=sys.stderr)

    projects: Dict[str, datetime] = {}

    for obj in objects:
        key = obj["Key"]

        if not SENTINEL_PATTERN.search(key):
            continue

        project_name = extract_project_name_from_sentinel(key, prefix)
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

    A project gets:
    - 'postprocess' level if found in postprocess_projects
    - 'metashape' level if found only in metashape_projects

    Note: config_id is not included in entries. Use separate log files per config.
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
    # Basic scan for default config
    python generate_retroactive_log.py \\
        --internal-bucket ofo-internal \\
        --internal-prefix photogrammetry/default-run \\
        --public-bucket ofo-public \\
        --public-prefix postprocessed \\
        --output completion-log-default.jsonl

    # For a specific config (use different prefix and output file)
    python generate_retroactive_log.py \\
        --internal-bucket ofo-internal \\
        --internal-prefix photogrammetry/default-run/photogrammetry_highres \\
        --public-bucket ofo-public \\
        --public-prefix postprocessed \\
        --output completion-log-highres.jsonl

    # Metashape only (no postprocess check)
    python generate_retroactive_log.py \\
        --internal-bucket ofo-internal \\
        --internal-prefix photogrammetry/default-run \\
        --level metashape \\
        --output completion-log-default.jsonl

Note on multiple configs:
- Use separate output files for different configs
- The log file name should indicate which config it's for
- Examples:
    completion-log-default.jsonl     (for default/NONE config)
    completion-log-highres.jsonl     (for highres config)
    completion-log-lowquality.jsonl  (for lowquality config)
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
        "--level",
        choices=["metashape", "postprocess", "both"],
        default="both",
        help="Which completion levels to detect",
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
    if args.level in ["postprocess", "both"] and (
        not args.public_bucket or not args.public_prefix
    ):
        parser.error(
            "--public-bucket and --public-prefix required when checking postprocess level"
        )

    # Create S3 client
    client = get_s3_client()

    # Detect completed projects
    metashape_projects: Dict[str, datetime] = {}
    postprocess_projects: Dict[str, datetime] = {}

    if args.level in ["metashape", "both"]:
        metashape_projects = detect_completed_projects(
            client, args.internal_bucket, args.internal_prefix, "metashape"
        )

    if args.level in ["postprocess", "both"]:
        postprocess_projects = detect_completed_projects(
            client, args.public_bucket, args.public_prefix, "postprocess"
        )

    # Generate log entries
    entries = generate_log_entries(metashape_projects, postprocess_projects)

    print(f"\nGenerated {len(entries)} log entries:", file=sys.stderr)
    metashape_only = sum(1 for e in entries if e["completion_level"] == "metashape")
    postprocess_count = sum(
        1 for e in entries if e["completion_level"] == "postprocess"
    )
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

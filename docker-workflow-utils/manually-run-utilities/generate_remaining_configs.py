#!/usr/bin/env python3
"""
Generate a config list of projects not yet completed.

Usage:
    python generate_remaining_configs.py <config_list> <completion_log> [--config-id ID] [--level LEVEL]

Example:
    python generate_remaining_configs.py /data/config_list.txt /data/completion-log.jsonl --level postprocess
"""

import argparse
import json
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="Generate remaining config list")
    parser.add_argument("config_list", help="Original config list file")
    parser.add_argument("completion_log", help="Completion log file")
    parser.add_argument("--config-id", default="default", help="Config ID to check")
    parser.add_argument(
        "--level",
        choices=["metashape", "postprocess"],
        default="postprocess",
        help="Completion level to check",
    )
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")

    args = parser.parse_args()

    # Load completion log
    completed = set()
    if os.path.exists(args.completion_log):
        with open(args.completion_log) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry["config_id"] == args.config_id:
                        if args.level == "metashape" or entry["completion_level"] == "postprocess":
                            completed.add(entry["project_name"])
                        elif args.level == "postprocess" and entry["completion_level"] == "postprocess":
                            completed.add(entry["project_name"])
                except (json.JSONDecodeError, KeyError):
                    continue

    # Read config list and filter
    config_list_dir = os.path.dirname(args.config_list)
    remaining = []

    with open(args.config_list) as f:
        for line in f:
            original_line = line
            line = line.split("#")[0].strip()
            if not line:
                continue

            # Resolve path
            if line.startswith("/"):
                config_path = line
            else:
                config_path = os.path.join(config_list_dir, line)

            # Extract project name from config (simplified - just use filename)
            project_name = os.path.splitext(os.path.basename(config_path))[0]

            if project_name not in completed:
                remaining.append(original_line.rstrip())

    # Output
    output = "\n".join(remaining) + "\n" if remaining else ""

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Wrote {len(remaining)} remaining configs to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(output)
        print(f"# {len(remaining)} remaining, {len(completed)} completed", file=sys.stderr)


if __name__ == "__main__":
    main()

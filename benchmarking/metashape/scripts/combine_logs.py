#!/usr/bin/env python3
"""Combine resource monitoring metrics from all *_log.txt files into a single CSV."""

import csv
import glob
import os
import re

# Mapping from original column names to R-friendly names
COLUMN_MAP = {
    "Step": "step",
    "API Call": "api_call",
    "Run Time": "run_time_sec",
    "CPU %": "cpu_pct_mean",
    "CPU%P90": "cpu_pct_p90",
    "GPU %": "gpu_pct_mean",
    "GPU%P90": "gpu_pct_p90",
    "CPU usage": "cpu_usage_mean",
    "CPUusgP90": "cpu_usage_p90",
    "PrcMem": "mem_process",
    "CtrLim": "mem_container_limit",
    "CtrUsd": "mem_container_used",
    "CtrAvl": "mem_container_avail",
    "SysTot": "mem_system_total",
    "SysUsd": "mem_system_used",
    "SysAvl": "mem_system_avail",
    "CPUs": "cpus",
    "GPUs": "gpus",
    "GPU Model": "gpu_model",
    "Node": "node",
}


def make_r_friendly(name):
    """Convert a column name to R-friendly format."""
    return COLUMN_MAP.get(name, name)


def time_to_seconds(time_str):
    """Convert HH:MM:SS to seconds."""
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        return h * 3600 + m * 60 + s
    return time_str  # Return original if format doesn't match


def parse_log_file(filepath):
    """Parse a log file and return the table rows as a list of dicts."""
    filename = os.path.basename(filepath)
    filename_no_ext = filename.replace("_log.txt", "")

    # Extract node_type and project from filename
    if filename_no_ext.startswith("cpu-"):
        node_type = "cpu"
        project = filename_no_ext[4:]  # Remove "cpu-"
    elif filename_no_ext.startswith("gpu-"):
        node_type = "gpu"
        project = filename_no_ext[4:]  # Remove "gpu-"
    else:
        node_type = "unknown"
        project = filename_no_ext

    rows = []
    headers = None

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()

            # Skip empty lines
            if not line:
                continue

            # Stop at "Run Completed"
            if line.startswith("Run Completed"):
                break

            # Check if this is a pipe-delimited table line
            if "|" in line:
                parts = [p.strip() for p in line.split("|")]

                # First pipe-delimited line is the header
                if headers is None:
                    headers = parts
                else:
                    # Data row - use R-friendly column names
                    row = {}
                    for orig_header, value in zip(headers, parts):
                        r_header = make_r_friendly(orig_header)
                        # Convert run time to seconds
                        if r_header == "run_time_sec":
                            value = time_to_seconds(value)
                        row[r_header] = value
                    row["filename"] = filename_no_ext
                    row["node_type"] = node_type
                    row["project"] = project
                    rows.append(row)

    # Convert headers to R-friendly names
    r_headers = [make_r_friendly(h) for h in headers] if headers else None
    return rows, r_headers


def main():
    # Get the directory where this script lives, then go up to metashape dir
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(script_dir)

    log_dir = os.path.join(base_dir, "logs")
    output_file = os.path.join(base_dir, "combined_metrics.csv")

    # Find all log files
    log_files = sorted(glob.glob(os.path.join(log_dir, "*_log.txt")))

    if not log_files:
        print("No log files found!")
        return

    all_rows = []
    headers = None

    for filepath in log_files:
        rows, file_headers = parse_log_file(filepath)
        if headers is None and file_headers:
            headers = file_headers
        all_rows.extend(rows)
        print(f"Parsed {os.path.basename(filepath)}: {len(rows)} rows")

    if not all_rows:
        print("No data rows found!")
        return

    # Add custom columns to headers
    output_headers = headers + ["filename", "node_type", "project"]

    # Write CSV
    with open(output_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_headers)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nWrote {len(all_rows)} rows to {output_file}")


if __name__ == "__main__":
    main()

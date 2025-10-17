#!/bin/bash
set -e

# Validate environment variables
echo "=== Python Post-Processing Container Starting ==="
echo "S3 Endpoint: ${S3_ENDPOINT}"
echo "Input Data Bucket: ${S3_BUCKET_INPUT_DATA}"
echo "Input Data Directory: ${INPUT_DATA_DIRECTORY}"
echo "Input Boundary Bucket: ${S3_BUCKET_INPUT_BOUNDARY}"
echo "Input Boundary Directory: ${INPUT_BOUNDARY_DIRECTORY}"
echo "Output Bucket: ${S3_BUCKET_OUTPUT}"
echo "Output Directory: ${OUTPUT_DIRECTORY}"
echo "Working Directory: ${WORKING_DIR:-/tmp/processing}"
echo "Output Max Dimension: ${OUTPUT_MAX_DIM:-800}"

# Check for required environment variables
required_vars=("S3_ENDPOINT" "S3_ACCESS_KEY" "S3_SECRET_KEY" "S3_BUCKET_INPUT_DATA" "S3_BUCKET_INPUT_BOUNDARY")
missing_vars=()

for var in "${required_vars[@]}"; do
    if [[ -z "${!var}" ]]; then
        missing_vars+=("$var")
    fi
done

if [[ ${#missing_vars[@]} -gt 0 ]]; then
    echo "Error: Missing required environment variables: ${missing_vars[*]}"
    exit 1
fi

# Set default values for optional variables
export WORKING_DIR="${WORKING_DIR:-/tmp/processing}"
export OUTPUT_MAX_DIM="${OUTPUT_MAX_DIM:-800}"
export S3_BUCKET_OUTPUT="${S3_BUCKET_OUTPUT:-${S3_BUCKET_INPUT_DATA}}"
export OUTPUT_DIRECTORY="${OUTPUT_DIRECTORY:-processed}"

echo "=== Environment validation complete ==="

# Test rclone installation
echo "=== Testing rclone installation ==="
if ! command -v rclone &> /dev/null; then
    echo "Error: rclone not found"
    exit 1
fi
rclone version

# Test Python installation and packages
echo "=== Testing Python installation ==="
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found"
    exit 1
fi

# Quick package test
python3 -c "
import sys
try:
    import rasterio
    import geopandas
    import numpy
    import pandas
    import matplotlib
    print('All required Python packages available')
except ImportError as e:
    print(f'Package import error: {e}')
    sys.exit(1)
"

if [ $? -ne 0 ]; then
    echo "Error: Python package import failed"
    exit 1
fi

echo "=== Starting Python post-processing script ==="

# Execute Python script
exec python3 /app/entrypoint.py "$@"

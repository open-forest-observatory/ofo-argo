#!/bin/bash
set -e

# =============================================================================
# Default values for optional environment variables
# These are the ONLY place defaults are set - entrypoint.py relies on these
# =============================================================================
export WORKING_DIR="${WORKING_DIR:-/tmp/processing}"
export OUTPUT_MAX_DIM="${OUTPUT_MAX_DIM:-800}"
export S3_PROVIDER="${S3_PROVIDER:-Other}"
export S3_BUCKET_OUTPUT="${S3_BUCKET_OUTPUT:-${S3_BUCKET_INPUT_DATA}}"
export OUTPUT_DIRECTORY="${OUTPUT_DIRECTORY:-processed}"

# Validate environment variables
echo "=== Python Post-Processing Container Starting ==="
echo "S3 Endpoint: ${S3_ENDPOINT}"
echo "Input Data Bucket: ${S3_BUCKET_INPUT_DATA}"
echo "Run Folder: ${RUN_FOLDER}"
echo "Metashape Config ID: ${METASHAPE_CONFIG_ID}"
echo "Input Boundary Bucket: ${S3_BUCKET_INPUT_BOUNDARY}"
echo "Input Boundary Directory: ${INPUT_BOUNDARY_DIRECTORY}"
echo "Output Bucket: ${S3_BUCKET_OUTPUT}"
echo "Output Directory: ${OUTPUT_DIRECTORY}"
echo "Dataset Name: ${DATASET_NAME}"
echo "Working Directory: ${WORKING_DIR:-/tmp/processing}"
echo "Output Max Dimension: ${OUTPUT_MAX_DIM:-800}"

# Check for required environment variables
required_vars=("S3_ENDPOINT" "S3_ACCESS_KEY" "S3_SECRET_KEY" "S3_BUCKET_INPUT_DATA" "RUN_FOLDER" "S3_BUCKET_INPUT_BOUNDARY" "DATASET_NAME")
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

echo "=== Environment validation complete ==="

# Test rclone installation
echo "=== Testing rclone installation ==="
if ! command -v rclone &> /dev/null; then
    echo "Error: rclone not found"
    exit 1
fi
rclone version

echo "=== Starting Python post-processing script ==="

# Execute Python script
exec python3 /app/entrypoint.py "$@"

#!/bin/bash
set -e

# =============================================================================
# Default values for optional environment variables
# These are the ONLY place defaults are set - entrypoint.py relies on these
# =============================================================================
export TEMP_WORKING_DIR_POSTPROCESSING="${TEMP_WORKING_DIR_POSTPROCESSING:-/tmp/processing}"
export OUTPUT_MAX_DIM="${OUTPUT_MAX_DIM:-800}"
export S3_PROVIDER="${S3_PROVIDER:-Other}"
export S3_BUCKET_PUBLIC="${S3_BUCKET_PUBLIC:-${S3_BUCKET_INTERNAL}}"
export S3_POSTPROCESSED_DIR="${S3_POSTPROCESSED_DIR:-processed}"

# Validate environment variables
echo "=== Python Post-Processing Container Starting ==="
echo "S3 Endpoint: ${S3_ENDPOINT}"
echo "Internal Bucket (raw Metashape products): ${S3_BUCKET_INTERNAL}"
echo "Photogrammetry Directory: ${S3_PHOTOGRAMMETRY_DIR}"
echo "Photogrammetry Config ID: ${PHOTOGRAMMETRY_CONFIG_ID}"
echo "Input Boundary Bucket: ${S3_BUCKET_INPUT_BOUNDARY}"
echo "Input Boundary Directory: ${INPUT_BOUNDARY_DIR}"
echo "Public Bucket (final postprocessed outputs): ${S3_BUCKET_PUBLIC}"
echo "Postprocessed Directory: ${S3_POSTPROCESSED_DIR}"
echo "Project Name: ${PROJECT_NAME}"
echo "Working Directory: ${TEMP_WORKING_DIR_POSTPROCESSING:-/tmp/processing}"
echo "Output Max Dimension: ${OUTPUT_MAX_DIM:-800}"

# Check for required environment variables
required_vars=("S3_ENDPOINT" "S3_ACCESS_KEY" "S3_SECRET_KEY" "S3_BUCKET_INTERNAL" "S3_PHOTOGRAMMETRY_DIR" "S3_BUCKET_INPUT_BOUNDARY" "PROJECT_NAME")
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

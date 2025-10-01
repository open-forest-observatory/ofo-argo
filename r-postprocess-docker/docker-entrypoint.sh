#!/bin/bash
set -e

# Validate environment variables
echo "=== R Post-Processing Container Starting ==="
echo "S3 Endpoint: ${S3_ENDPOINT}"
echo "Input Data Bucket: ${S3_BUCKET_INPUT_DATA}"
echo "Input Data Directory: ${INPUT_DATA_DIRECTORY}"
echo "Input Boundary Bucket: ${S3_BUCKET_INPUT_BOUNDARY}"
echo "Input Boundary Directory: ${INPUT_BOUNDARY_DIRECTORY}"
echo "Output Bucket: ${S3_BUCKET_OUTPUT}"
echo "Output Directory: ${OUTPUT_DIRECTORY}"
echo "Working Directory: ${WORKING_DIR:-/tmp/processing}"
echo "Terra Memory Fraction: ${TERRA_MEMFRAC:-0.9}"
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
export TERRA_MEMFRAC="${TERRA_MEMFRAC:-0.9}"
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

# Test R installation and packages
echo "=== Testing R installation ==="
if ! command -v Rscript &> /dev/null; then
    echo "Error: Rscript not found"
    exit 1
fi

# Quick package test
Rscript -e "
packages <- c('tidyverse', 'sf', 'terra', 'lidR', 'purrr')
for (pkg in packages) {
  if (!require(pkg, character.only=TRUE, quietly=TRUE)) {
    stop('Package not found: ', pkg)
  }
}
cat('All required R packages available\n')
"

echo "=== Starting R post-processing script ==="

# Execute R script
exec Rscript /app/entrypoint.R "$@"
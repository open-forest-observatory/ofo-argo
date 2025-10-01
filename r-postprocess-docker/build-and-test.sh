#!/bin/bash

# Build and test script for OFO R Post-Processing Docker Container

set -e

echo "=== OFO R Post-Processing Docker Container Build & Test ==="

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed"
    exit 1
fi

echo "✓ Docker found: $(docker --version)"

# Check Docker permissions
if ! docker info &> /dev/null; then
    echo "Error: Cannot connect to Docker daemon. You may need to:"
    echo "  1. Start Docker service: sudo systemctl start docker"
    echo "  2. Add user to docker group: sudo usermod -aG docker $USER"
    echo "  3. Log out and back in, or run: newgrp docker"
    exit 1
fi

echo "✓ Docker daemon accessible"

# Build the container
echo ""
echo "Building Docker container..."
cd "$(dirname "$0")"

if docker build -t ofo-r-postprocess:latest .; then
    echo "✓ Docker build successful"
else
    echo "✗ Docker build failed"
    exit 1
fi

# Test container basic functionality
echo ""
echo "Testing container basic functionality..."

# Test 1: Check if container starts and validates environment
echo "Test 1: Environment validation"
if docker run --rm ofo-r-postprocess:latest 2>&1 | grep -q "Missing required environment variables"; then
    echo "✓ Container properly validates environment variables"
else
    echo "✗ Container environment validation failed"
    exit 1
fi

# Test 2: Check if all required tools are available
echo "Test 2: Tool availability"
docker run --rm --entrypoint /bin/bash ofo-r-postprocess:latest -c "
    echo 'Checking R installation...'
    Rscript --version || exit 1
    echo 'Checking rclone installation...'
    rclone version || exit 1
    echo 'Checking R packages...'
    Rscript -e 'library(tidyverse); library(sf); library(terra); library(lidR); library(purrr); cat(\"All packages loaded successfully\n\")' || exit 1
" && echo "✓ All tools and packages available" || (echo "✗ Tool check failed" && exit 1)

echo ""
echo "=== Build and Basic Tests Complete ==="
echo ""
echo "To run the container with real data, use:"
echo ""
echo "docker run --rm \\"
echo "  -e S3_ENDPOINT=\"https://js2.jetstream-cloud.org:8001\" \\"
echo "  -e S3_PROVIDER=\"Other\" \\"
echo "  -e S3_ACCESS_KEY=\"your_access_key\" \\"
echo "  -e S3_SECRET_KEY=\"your_secret_key\" \\"
echo "  -e S3_BUCKET_INPUT_DATA=\"ofo-internal\" \\"
echo "  -e INPUT_DATA_DIRECTORY=\"run_folder\" \\"
echo "  -e S3_BUCKET_INPUT_BOUNDARY=\"ofo-public\" \\"
echo "  -e INPUT_BOUNDARY_DIRECTORY=\"mission_boundaries\" \\"
echo "  -e S3_BUCKET_OUTPUT=\"ofo-public\" \\"
echo "  -e OUTPUT_DIRECTORY=\"processed_products\" \\"
echo "  ofo-r-postprocess:latest"
echo ""
echo "Image size:"
docker images ofo-r-postprocess:latest
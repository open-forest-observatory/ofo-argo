#!/usr/bin/env Rscript

# Set up environment
suppressPackageStartupMessages({
  library(tidyverse)
  library(sf)
  library(lidR)
  library(terra)
  library(purrr)
})

# Source the main processing script
source("/app/20_postprocess-photogrammetry-products.R")

# Helper function to setup rclone configuration
setup_rclone_config <- function() {
  s3_endpoint <- Sys.getenv("S3_ENDPOINT")
  s3_provider <- Sys.getenv("S3_PROVIDER", "Other")
  s3_access_key <- Sys.getenv("S3_ACCESS_KEY")
  s3_secret_key <- Sys.getenv("S3_SECRET_KEY")

  # Create rclone config
  config_content <- paste0(
    "[s3remote]\n",
    "type = s3\n",
    "provider = ", s3_provider, "\n",
    "access_key_id = ", s3_access_key, "\n",
    "secret_access_key = ", s3_secret_key, "\n",
    "endpoint = ", s3_endpoint, "\n"
  )

  # Write config file
  config_dir <- "/root/.config/rclone"
  dir.create(config_dir, recursive = TRUE, showWarnings = FALSE)
  writeLines(config_content, file.path(config_dir, "rclone.conf"))

  cat("rclone configuration created\n")
}

# Download all photogrammetry products
download_photogrammetry_products <- function() {
  input_bucket <- Sys.getenv("S3_BUCKET_INPUT_DATA")
  input_dir <- Sys.getenv("INPUT_DATA_DIRECTORY")
  local_input_dir <- "/tmp/processing/input"

  remote_path <- paste0("s3remote:", input_bucket, "/", input_dir)

  cat("Downloading photogrammetry products from:", remote_path, "\n")

  cmd <- paste(
    "rclone copy",
    remote_path,
    local_input_dir,
    "--progress --transfers 8 --checkers 8 --retries 5",
    "--retries-sleep=15s --stats 30s"
  )

  result <- system(cmd)
  if (result != 0) {
    stop("Failed to download photogrammetry products")
  }

  # List downloaded files
  files <- list.files(local_input_dir)
  cat("Downloaded", length(files), "photogrammetry files\n")
  return(files)
}

# Download all boundary polygons
download_boundary_polygons <- function() {
  boundary_bucket <- Sys.getenv("S3_BUCKET_INPUT_BOUNDARY")
  boundary_dir <- Sys.getenv("INPUT_BOUNDARY_DIRECTORY")
  local_boundary_dir <- "/tmp/processing/boundary"

  remote_path <- paste0("s3remote:", boundary_bucket, "/", boundary_dir)

  cat("Downloading boundary polygons from:", remote_path, "\n")

  cmd <- paste(
    "rclone copy",
    remote_path,
    local_boundary_dir,
    "--progress --transfers 8 --checkers 8 --retries 5",
    "--retries-sleep=15s --stats 30s"
  )

  result <- system(cmd)
  if (result != 0) {
    stop("Failed to download boundary polygons")
  }

  # List downloaded files
  files <- list.files(local_boundary_dir)
  cat("Downloaded", length(files), "boundary files\n")
  return(files)
}

# Auto-detect and match missions
detect_and_match_missions <- function() {
  # Get list of downloaded photogrammetry products
  input_files <- list.files("/tmp/processing/input/", full.names = FALSE)

  # Get list of downloaded boundary files
  boundary_files <- list.files("/tmp/processing/boundary/", full.names = FALSE)

  if (length(input_files) == 0) {
    stop("No photogrammetry products found")
  }

  if (length(boundary_files) == 0) {
    stop("No boundary files found")
  }

  cat("Found", length(input_files), "product files and", length(boundary_files), "boundary files\n")

  # Extract unique mission prefixes from photogrammetry products
  # Strategy: split by underscore and remove the last part (product type)
  product_prefixes <- unique(sapply(input_files, function(f) {
    # Remove file extension first
    base_name <- tools::file_path_sans_ext(f)
    # Split by underscore
    parts <- strsplit(base_name, "_")[[1]]
    if (length(parts) > 1) {
      # Take all parts except the last one (which should be product type like 'ortho', 'dsm', etc.)
      paste(parts[-length(parts)], collapse = "_")
    } else {
      base_name
    }
  }))

  cat("Detected mission prefixes:", paste(product_prefixes, collapse = ", "), "\n")

  # Match each product prefix with corresponding boundary file
  mission_matches <- list()

  for (prefix in product_prefixes) {
    # Find matching boundary file (starts with same prefix)
    matching_boundary <- boundary_files[grepl(paste0("^", prefix, "_"), boundary_files)]

    if (length(matching_boundary) > 0) {
      # Find all product files for this mission
      matching_products <- input_files[grepl(paste0("^", prefix, "_"), input_files)]

      mission_matches[[length(mission_matches) + 1]] <- list(
        prefix = prefix,
        boundary_file = file.path("/tmp/processing/boundary", matching_boundary[1]),
        product_files = file.path("/tmp/processing/input", matching_products)
      )

      cat("Matched mission '", prefix, "' with ", length(matching_products), " products and boundary: ", matching_boundary[1], "\n", sep = "")
    } else {
      cat("Warning: No matching boundary found for mission prefix: ", prefix, "\n", sep = "")
    }
  }

  return(mission_matches)
}

# Upload processed products for a specific mission
upload_processed_products <- function(mission_prefix) {
  output_bucket <- Sys.getenv("S3_BUCKET_OUTPUT")
  output_dir <- Sys.getenv("OUTPUT_DIRECTORY")

  # Upload both full resolution and thumbnails
  for (subdir in c("full", "thumbnails")) {
    local_path <- file.path("/tmp/processing/output", subdir)
    remote_path <- paste0("s3remote:", output_bucket, "/", output_dir)

    # Only upload files that match this mission prefix
    files_to_upload <- list.files(local_path, pattern = paste0("^", mission_prefix, "_"), full.names = TRUE)

    if (length(files_to_upload) > 0) {
      cat("Uploading", length(files_to_upload), subdir, "files for mission", mission_prefix, "\n")

      # Copy files one by one to ensure proper naming
      for (file_path in files_to_upload) {
        filename <- basename(file_path)
        remote_file_path <- paste0(remote_path, "/", filename)

        cmd <- paste(
          "rclone copyto",
          file_path,
          remote_file_path,
          "--progress --retries 5 --retries-sleep=15s"
        )

        result <- system(cmd)
        if (result != 0) {
          warning("Failed to upload file: ", filename)
        }
      }
    }
  }

  cat("Upload completed for mission:", mission_prefix, "\n")
}

# Cleanup working directory
cleanup_working_directory <- function() {
  cat("Cleaning up temporary files...\n")
  unlink("/tmp/processing", recursive = TRUE)
  cat("Cleanup completed\n")
}

# Main execution function
main <- function() {
  working_dir <- Sys.getenv("WORKING_DIR", "/tmp/processing")

  cat("Starting R post-processing container...\n")
  cat("Working directory:", working_dir, "\n")

  # Validate required parameters
  required_vars <- c("S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY",
                     "S3_BUCKET_INPUT_DATA", "S3_BUCKET_INPUT_BOUNDARY")
  missing_vars <- required_vars[!nzchar(Sys.getenv(required_vars))]
  if (length(missing_vars) > 0) {
    stop("Missing required environment variables: ", paste(missing_vars, collapse = ", "))
  }

  # Set up working directory and terra options
  # Set TMPDIR environment variable for temporary files
  Sys.setenv(TMPDIR = working_dir)
  dir.create(working_dir, recursive = TRUE, showWarnings = FALSE)

  # Set terra memory fraction
  terra_memfrac <- as.numeric(Sys.getenv("TERRA_MEMFRAC", "0.9"))
  terra::terraOptions(memfrac = terra_memfrac)

  cat("Terra memory fraction set to:", terra_memfrac, "\n")

  # Configure rclone
  setup_rclone_config()

  # Download all available data
  download_photogrammetry_products()
  download_boundary_polygons()

  # Auto-detect and match missions
  mission_matches <- detect_and_match_missions()

  if (length(mission_matches) == 0) {
    stop("No matching photogrammetry products and boundary polygons found")
  }

  cat("Found", length(mission_matches), "missions to process\n")

  # Process each detected mission
  success_count <- 0
  for (i in seq_along(mission_matches)) {
    mission <- mission_matches[[i]]
    cat("\n=== Processing mission", i, "of", length(mission_matches), ":", mission$prefix, "===\n")

    tryCatch({
      result <- postprocess_photogrammetry_containerized(
        mission$prefix,
        mission$boundary_file,
        mission$product_files
      )

      if (result) {
        upload_processed_products(mission$prefix)
        success_count <- success_count + 1
        cat("✓ Successfully processed mission:", mission$prefix, "\n")
      } else {
        cat("✗ Failed to process mission:", mission$prefix, "\n")
      }
    }, error = function(e) {
      cat("✗ Error processing mission", mission$prefix, ":", e$message, "\n")
    })
  }

  cleanup_working_directory()

  cat("\n=== Summary ===\n")
  cat("Total missions found:", length(mission_matches), "\n")
  cat("Successfully processed:", success_count, "\n")
  cat("Failed:", length(mission_matches) - success_count, "\n")

  if (success_count == length(mission_matches)) {
    cat("All missions processed successfully!\n")
  } else if (success_count > 0) {
    cat("Partial success - some missions failed\n")
    quit(status = 1)
  } else {
    cat("All missions failed\n")
    quit(status = 1)
  }
}

# Execute main function
main()

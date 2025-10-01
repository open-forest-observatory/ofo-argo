#!/usr/bin/env Rscript

# Quick syntax test for our R scripts

cat("Testing R script syntax...\n")

# Test if we can source our scripts without errors
tryCatch({
  # Test package availability (using base packages only for now)
  cat("Testing base R functionality...\n")

  # Test file operations
  test_dir <- tempdir()
  cat("Temporary directory:", test_dir, "\n")

  # Test basic data manipulation
  test_data <- data.frame(
    filename = c("test_mission_ortho.tif", "test_mission_dsm.tif"),
    stringsAsFactors = FALSE
  )

  # Test string manipulation
  test_data$extension <- tools::file_ext(test_data$filename)
  test_data$type <- sapply(test_data$filename, function(f) {
    base_name <- tools::file_path_sans_ext(f)
    parts <- strsplit(base_name, "_")[[1]]
    if (length(parts) > 1) {
      parts[length(parts)]
    } else {
      "unknown"
    }
  })

  print(test_data)

  cat("✓ Basic R functionality works\n")

}, error = function(e) {
  cat("✗ Error in basic R test:", e$message, "\n")
  quit(status = 1)
})

# Try to source our main script (syntax check only)
tryCatch({
  # Parse the script to check syntax
  parse("/home/jgillan/ofo-argo/r-postprocess-docker/scripts/20_postprocess-photogrammetry-products.R")
  cat("✓ Post-processing script syntax is valid\n")

}, error = function(e) {
  cat("✗ Syntax error in post-processing script:", e$message, "\n")
  quit(status = 1)
})

# Try to parse the entrypoint script
tryCatch({
  parse("/home/jgillan/ofo-argo/r-postprocess-docker/entrypoint.R")
  cat("✓ Entrypoint script syntax is valid\n")

}, error = function(e) {
  cat("✗ Syntax error in entrypoint script:", e$message, "\n")
  quit(status = 1)
})

cat("All syntax tests passed!\n")
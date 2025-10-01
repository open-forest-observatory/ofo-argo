# Install required packages not in rocker/geospatial
# rocker/geospatial already includes: tidyverse, sf, terra

cat("Installing additional R packages...\n")

# Install packages with error handling
install_if_missing <- function(pkg) {
  if (!require(pkg, character.only = TRUE, quietly = TRUE)) {
    cat("Installing", pkg, "...\n")
    install.packages(pkg, repos = "https://cran.rstudio.com/", dependencies = TRUE)
    if (!require(pkg, character.only = TRUE, quietly = TRUE)) {
      stop("Failed to install package: ", pkg)
    }
  } else {
    cat(pkg, "already installed\n")
  }
}

# List of required packages
packages <- c(
  "lidR",      # Point cloud processing
  "purrr"      # Functional programming tools
)

# Install each package
for (pkg in packages) {
  install_if_missing(pkg)
}

cat("All packages installed successfully!\n")

# Verify installations
cat("\nVerifying package installations:\n")
for (pkg in c("tidyverse", "sf", "terra", "lidR", "purrr")) {
  if (require(pkg, character.only = TRUE, quietly = TRUE)) {
    cat("✓", pkg, "loaded successfully\n")
  } else {
    cat("✗", pkg, "failed to load\n")
  }
}
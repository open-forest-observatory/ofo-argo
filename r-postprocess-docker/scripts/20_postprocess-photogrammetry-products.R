# Purpose: Take the photogrammetry products and compute the "deliverable" versions of the outputs
# (e.g. CHM, cloud-optimized, thumbnails) by postprocessing. Containerized version.

# This script has been adapted from the original to work in a Docker container environment
# with data passed as function parameters rather than downloaded within the function.

## Utility functions (from utils.R)

# Create a directory if it doesn't exist
create_dir <- function(dir) {
  if (!dir.exists(dir)) {
    dir.create(dir, recursive = TRUE)
  }
}

drop_units_if_present = function(x) {
  if (inherits(x, "units")) {
    return(x |> units::drop_units())
  } else {
    return(x)
  }
}

# Reproject a sf object into the CRS representing its local UTM zone
transform_to_local_utm = function(sf) {
  geo = sf::st_transform(sf, 4326)
  geo_noz = sf::st_zm(geo, drop = TRUE)
  lonlat = sf::st_centroid(geo_noz) |> sf::st_coordinates()
  utm = lonlat_to_utm_epsg(lonlat)

  sf_transf = sf::st_transform(sf, utm)

  return(sf_transf)
}

# Take a lon/lat coordinates dataframe and convert to the local UTM zone EPSG code
lonlat_to_utm_epsg = function(lonlat) {
  utm = (floor((lonlat[, 1] + 180) / 6) %% 60) + 1
  utms = ifelse(lonlat[, 2] > 0, utm + 32600, utm + 32700)

  utms_unique = unique(utms)

  if (length(utms_unique) > 2) {
    stop("The geometry spans 3 or more UTM zones")
  } else if (length(utms_unique) > 1) {
    if (abs(diff(utms_unique)) > 1) {
      stop("The geometry spans 2 non-adjacent UTM zones.")
    }
  }

  return(utms_unique[1])
}

## Core processing functions

# Function to crop raster to mission polygon and write as COG
crop_raster_save_cog = function(raster_filepath_foc, output_filename, mission_polygon, output_path) {

  # Read, crop, and write the raster as COG
  raster = terra::rast(raster_filepath_foc)
  mission_polygon_matchedcrs = st_transform(mission_polygon, st_crs(raster))
  raster_cropped = terra::crop(raster, mission_polygon_matchedcrs, mask = TRUE)
  output_file_path = file.path(
    output_path, "full",
    output_filename
  )

  terra::writeRaster(
    raster_cropped,
    output_file_path,
    overwrite = TRUE,
    filetype = "COG",
    gdal = "BIGTIFF=IF_SAFER",
    todisk = TRUE
  )
}

# Function to make a CHM from two raster file paths
make_chm = function(dsm_filepath_foc, dtm_filepath_foc) {
  # Read the rasters
  dsm = terra::rast(dsm_filepath_foc)
  dtm = terra::rast(dtm_filepath_foc)

  # Make sure the rasters are in the same CRS
  dtm = terra::project(dtm, dsm)

  # Compute the CHM
  chm = dsm - dtm

  return(chm)
}

## Main containerized post-processing function
postprocess_photogrammetry_containerized = function(mission_prefix, boundary_file_path, product_file_paths) {

  cat("Starting post-processing for mission:", mission_prefix, "\n")

  # Validate inputs
  if (!file.exists(boundary_file_path)) {
    stop("Boundary file not found: ", boundary_file_path)
  }

  missing_products <- product_file_paths[!file.exists(product_file_paths)]
  if (length(missing_products) > 0) {
    stop("Product files not found: ", paste(missing_products, collapse = ", "))
  }

  # Create output directories
  postprocessed_path <- "/tmp/processing/output"
  create_dir(file.path(postprocessed_path, "full"))
  create_dir(file.path(postprocessed_path, "thumbnails"))

  # Read the mission polygon
  cat("Reading boundary polygon from:", boundary_file_path, "\n")
  mission_polygon <- st_read(boundary_file_path, quiet = TRUE)

  # Process product files - extract file information
  product_filenames <- basename(product_file_paths)

  photogrammetry_output_files <- data.frame(
    photogrammetry_output_filename = product_filenames,
    full_path = product_file_paths,
    stringsAsFactors = FALSE
  )

  # Extract file extensions and product types
  photogrammetry_output_files <- photogrammetry_output_files |>
    dplyr::mutate(extension = tools::file_ext(photogrammetry_output_filename)) |>
    dplyr::mutate(
      # Extract product type from filename
      # Example: "benchmarking_greasewood_ortho.tif" -> "ortho"
      type = sapply(photogrammetry_output_filename, function(f) {
        base_name <- tools::file_path_sans_ext(f)
        parts <- strsplit(base_name, "_")[[1]]
        if (length(parts) > 1) {
          parts[length(parts)]  # Take the last part as product type
        } else {
          "unknown"
        }
      })
    ) |>
    dplyr::mutate(
      # Create output filename maintaining mission prefix
      postprocessed_filename = paste0(mission_prefix, "_", type, ".", extension)
    )

  cat("Found", nrow(photogrammetry_output_files), "product files:\n")
  print(photogrammetry_output_files[, c("photogrammetry_output_filename", "type", "extension")])

  ## Crop DSMs, DTM, ortho to mission polygon and write as COG

  photogrammetry_outputs_rast <- photogrammetry_output_files |>
    dplyr::filter(extension %in% c("tif", "tiff"))

  if (nrow(photogrammetry_outputs_rast) > 0) {
    cat("Processing", nrow(photogrammetry_outputs_rast), "raster files\n")

    # Apply the raster crop & write function to all the rasters
    purrr::walk2(
      photogrammetry_outputs_rast$full_path,
      photogrammetry_outputs_rast$postprocessed_filename,
      crop_raster_save_cog,
      output_path = postprocessed_path,
      mission_polygon = mission_polygon
    )
  }

  ## Make CHMs

  # Determine what would be the filepaths of the potential DSM and DTM files (if they exist)
  dem_filepaths <- photogrammetry_output_files |>
    dplyr::filter(extension %in% c("tif", "tiff")) |>
    dplyr::filter(type %in% c("dsm-ptcloud", "dsm-mesh", "dsm", "dtm-ptcloud", "dtm")) |>
    # Add the paths of the cropped, COG versions
    dplyr::mutate(postprocessed_filepath = file.path(
      postprocessed_path, "full", postprocessed_filename
    ))

  # Check for DSM and DTM combinations and create CHMs
  available_types <- dem_filepaths$type

  # Try different DSM/DTM combinations
  dsm_types <- c("dsm-mesh", "dsm-ptcloud", "dsm")
  dtm_types <- c("dtm-ptcloud", "dtm")

  chm_created <- FALSE

  for (dsm_type in dsm_types) {
    for (dtm_type in dtm_types) {
      if (dsm_type %in% available_types && dtm_type %in% available_types && !chm_created) {

        cat("Creating CHM from", dsm_type, "and", dtm_type, "\n")

        dsm_filepath <- dem_filepaths |>
          dplyr::filter(type == dsm_type) |>
          dplyr::pull(postprocessed_filepath)

        dtm_filepath <- dem_filepaths |>
          dplyr::filter(type == dtm_type) |>
          dplyr::pull(postprocessed_filepath)

        # Take first file if multiple exist
        dsm_filepath <- dsm_filepath[1]
        dtm_filepath <- dtm_filepath[1]

        tryCatch({
          chm <- make_chm(dsm_filepath, dtm_filepath)

          # Write the CHM as a COG
          chm_filename <- paste0(mission_prefix, "_chm.tif")
          chm_filepath <- file.path(postprocessed_path, "full", chm_filename)

          terra::writeRaster(
            chm,
            chm_filepath,
            overwrite = TRUE,
            filetype = "COG",
            gdal = "BIGTIFF=IF_SAFER",
            todisk = TRUE
          )

          cat("Successfully created CHM:", chm_filename, "\n")
          chm_created <- TRUE

        }, error = function(e) {
          cat("Failed to create CHM from", dsm_type, "and", dtm_type, ":", e$message, "\n")
        })
      }
    }
  }

  if (!chm_created && length(dsm_types[dsm_types %in% available_types]) > 0 && length(dtm_types[dtm_types %in% available_types]) > 0) {
    cat("Warning: Could not create CHM despite having DSM and DTM files\n")
  }

  # Copy other files (non-raster files like point clouds, reports, etc.)
  other_files <- photogrammetry_output_files |>
    dplyr::filter(!(extension %in% c("tif", "tiff"))) |>
    dplyr::mutate(
      output_filepath = file.path(postprocessed_path, "full", postprocessed_filename)
    )

  if (nrow(other_files) > 0) {
    cat("Copying", nrow(other_files), "non-raster files\n")

    for (i in 1:nrow(other_files)) {
      tryCatch({
        file.copy(other_files$full_path[i], other_files$output_filepath[i], overwrite = TRUE)
      }, error = function(e) {
        cat("Warning: Failed to copy", other_files$photogrammetry_output_filename[i], ":", e$message, "\n")
      })
    }
  }

  ## Make thumbnails

  # Get OUTPUT_MAX_DIM from environment
  output_max_dim <- as.numeric(Sys.getenv("OUTPUT_MAX_DIM", "800"))

  # List all tifs within the output folder
  tif_files <- list.files(file.path(postprocessed_path, "full"), "*.tif", full.names = FALSE)

  cat("Creating thumbnails for", length(tif_files), "raster files\n")

  # For each full-resolution tif file
  for (tif_file in tif_files) {
    tryCatch({
      # Full path to the tif file
      tif_file_path <- file.path(postprocessed_path, "full", tif_file)
      # Create the output file in the thumbnails folder with the same name but png extension
      thumbnail_filepath <- file.path(
        postprocessed_path, "thumbnails",
        sub("\\.tif$", ".png", tif_file, ignore.case = TRUE)
      )

      cat("Creating thumbnail:", basename(thumbnail_filepath), "\n")

      # Read the raster
      raster <- terra::rast(tif_file_path)
      # Compute the number of rows and columns
      n_row <- terra::nrow(raster)
      n_col <- terra::ncol(raster)
      # Compute the maximum dimension and determine the scale factor to make it match the specified
      # maximum size
      max_dim <- max(n_row, n_col)
      scale_factor <- output_max_dim / max_dim
      new_n_row <- floor(n_row * scale_factor)
      new_n_col <- floor(n_col * scale_factor)

      # Specify a PNG file as the output device
      png(thumbnail_filepath, width = new_n_col, height = new_n_row, bg = "transparent")

      # Determine whether this is single-channel or RGB data
      n_lyr <- terra::nlyr(raster)
      if (n_lyr == 1) {
        # The mar argument ensures that there is not an excessive white border around the image
        plot(raster, axes = FALSE, legend = FALSE, mar = c(0, 0, 0, 0))
      } else if (n_lyr %in% c(3, 4)) {
        # Make sure the background is transparent
        terra::plotRGB(raster, bgalpha = 0)
      } else {
        cat("Warning: Raster has unexpected number of layers (", n_lyr, "), using default plot\n")
        plot(raster, axes = FALSE, legend = FALSE, mar = c(0, 0, 0, 0))
      }

      # Close the PNG
      dev.off()

    }, error = function(e) {
      cat("Warning: Failed to create thumbnail for", tif_file, ":", e$message, "\n")
    })
  }

  # Count output files
  full_files <- list.files(file.path(postprocessed_path, "full"))
  thumbnail_files <- list.files(file.path(postprocessed_path, "thumbnails"))

  cat("Post-processing completed for mission:", mission_prefix, "\n")
  cat("Created", length(full_files), "full-resolution products and", length(thumbnail_files), "thumbnails\n")

  return(TRUE)
}
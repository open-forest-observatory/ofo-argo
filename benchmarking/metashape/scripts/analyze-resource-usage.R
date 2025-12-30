# Purpose: Summarize and analyze resource usage across 20 Argo-based Metashape runs. They consist of
# 10 different datasets of different sizes, each run twice: once with GPU for every GPU-optional
# step, and once with CPU. The compute time and resource usage of each step was logged.

library(tidyverse)

d = read.csv("benchmarking/metashape/benchmarking-data-merged.csv")

# Convert "N/A" to NA
d[d == "N/A"] = NA

# Convert relevant columns to numeric
d = d |>mutate(across(run_time_sec:mem_system_avail, as.numeric))

means = d |>

    group_by(api_call, node_type) |>
    summarize(across(run_time_sec:mem_system_avail, mean, na.rm = TRUE))


# For looking at mean and max resource usage: filter out the GPU runs for all steps that don't
# optionally use GPU (all but match_photos and build_mesh)

gpu_optional_steps = c("match_photos", "build_mesh")

d2 = d |>
    filter(node_type == "cpu" | (node_type == "gpu" & step %in% gpu_optional_steps)) |>
    # Tack nod type onto API call and step name for summarizing purposes
    mutate(api_call_full = paste0(api_call, "_", node_type),
           step_full = paste0(step, "_", node_type))

# Compute the mean and max resource usage across all runs for each api_call_full, for each resource
mean_usage = d2 |>
    group_by(api_call_full) |>
    summarize(across(run_time_sec:mem_system_avail, mean, na.rm = TRUE)) |>
    mutate(metric = "mean")
max_usage = d2 |>
    group_by(api_call_full) |>
    summarize(across(run_time_sec:mem_system_avail, max, na.rm = TRUE)) |>
    mutate(metric = "max")

# Merge mean and max usage into one table
usage = bind_rows(mean_usage, max_usage) |>
    select(api_call_full, metric, everything()) |>
    arrange(api_call_full, metric)

# In col gpu_pct_mean and gpu_pct_p90, replace -Inf and NaN with NA
usage = usage |>
    mutate(gpu_pct_mean = ifelse(is.infinite(gpu_pct_mean) | is.nan(gpu_pct_mean), NA, gpu_pct_mean),
           gpu_pct_p90 = ifelse(is.infinite(gpu_pct_p90) | is.nan(gpu_pct_p90), NA, gpu_pct_p90))

# Write to CSV for easier viewing
write.csv(usage, "benchmarking/metashape/resource-usage-summary.csv")

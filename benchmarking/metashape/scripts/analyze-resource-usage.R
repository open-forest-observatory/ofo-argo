# Purpose: Summarize and analyze resource usage across 20 Argo-based Metashape runs (using xl nodes
# for cpu and xl for GPU), a subset of these (using large nodes for CPU and xl for GPU), and a
# similar subset (using xl nodes for CPU and mig for GPU). They consist of
# 10 different datasets of different sizes, each run twice: once with GPU for every GPU-optional
# step, and once with CPU. The compute time and resource usage of each step was logged.

library(tidyverse)

d_xl = read.csv("benchmarking/metashape/benchmarking-data-merged_xl.csv") |> mutate(run_type = "xl")
d_large = read.csv("benchmarking/metashape/benchmarking-data-merged_large.csv") |> mutate(run_type = "large")
d_mig = read.csv("benchmarking/metashape/benchmarking-data-merged_mig.csv") |> mutate(run_type = "mig")

# Combine all data frames into one
d = bind_rows(d_xl, d_large, d_mig)

# Convert "N/A" to NA
d[d == "N/A"] = NA

# Convert relevant columns to numeric
d = d |>mutate(across(run_time_sec:mem_system_avail, as.numeric))

means = d |>
    group_by(api_call, node_type, run_type) |>
    summarize(across(run_time_sec:mem_system_avail, mean, na.rm = TRUE))


# For looking at mean and max resource usage: filter out the GPU runs for all steps that don't
# optionally use GPU (all but match_photos and build_mesh)

gpu_optional_steps = c("match_photos", "build_mesh")

d2 = d |>
    filter(node_type == "cpu" | (node_type == "gpu" & step %in% gpu_optional_steps)) |>
    # Tack node type onto API call and step name for summarizing purposes
    mutate(api_call_full = paste0(api_call, "_", node_type),
           step_full = paste0(step, "_", node_type))

# Compute the mean and max resource usage across all runs for each api_call_full, for each resource
mean_usage = d2 |>
    group_by(api_call_full, run_type) |>
    summarize(across(run_time_sec:mem_system_avail, mean, na.rm = TRUE)) |>
    mutate(metric = "mean")
max_usage = d2 |>
    group_by(api_call_full, run_type) |>
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

## NOTE that this summary is an unfair comparison among the three run types, since the datasets (projects) used for each are different subsets. Redo now with only the datasets that are common to all three run types.

common_datasets_all = intersect(intersect(
    unique(d_xl$project),
    unique(d_large$project)),
    unique(d_mig$project)
)

# Or just the unique between xl and large
common_datasets_xl_large = intersect(
    unique(d_xl$project),
    unique(d_large$project)
)

# Start with just a comparison of large and XL, using the datasets in common among those two
d_common = d |> filter(project %in% common_datasets_xl_large)
d2_common = d_common |>
    filter(node_type == "cpu" | (node_type == "gpu" & step %in% gpu_optional_steps)) |>
    # Tack node type onto API call and step name for summarizing purposes
    mutate(
        api_call_full = paste0(api_call, "_", node_type),
        step_full = paste0(step, "_", node_type)
    )
# Compute the mean and max resource usage across all runs for each api_call_full, for each resource
mean_usage_common = d2_common |>
    group_by(api_call_full, run_type) |>
    summarize(across(run_time_sec:mem_system_avail, mean, na.rm = TRUE)) |>
    mutate(metric = "mean")
max_usage_common = d2_common |>
    group_by(api_call_full, run_type) |>
    summarize(across(run_time_sec:mem_system_avail, max, na.rm = TRUE)) |>
    mutate(metric = "max")
# Merge mean and max usage into one table
usage_common = bind_rows(mean_usage_common, max_usage_common) |>
    select(api_call_full, metric, everything()) |>
    arrange(api_call_full, metric)
# In col gpu_pct_mean and gpu_pct_p90, replace -Inf and NaN with NA
usage_common = usage_common |>
    mutate(gpu_pct_mean = ifelse(is.infinite(gpu_pct_mean) | is.nan(gpu_pct_mean), NA, gpu_pct_mean),
           gpu_pct_p90 = ifelse(is.infinite(gpu_pct_p90) | is.nan(gpu_pct_p90), NA, gpu_pct_p90))
# Write to CSV for easier viewing
write.csv(usage_common, "benchmarking/metashape/resource-usage-summary_xl_large-common.csv")


## Now, redo with only the datasets that are common to all three run types, with the goal of looking at mig slice efficiency and memory usage, and also comparing the most efficient mig approach to match_photos to the CPU approach. 

d_common_all = d |> filter(project %in% common_datasets_all)
d2_common_all = d_common_all |>
    # filter(node_type == "cpu" | (node_type == "gpu" & step %in% gpu_optional_steps)) |>
    # Tack node type onto API call and step name for summarizing purposes
    mutate(
        api_call_full = paste0(api_call, "_", node_type),
        step_full = paste0(step, "_", node_type)
    )
# Compute the mean and max resource usage across all runs for each api_call_full, for each resource
mean_usage_common_all = d2_common_all |>
    group_by(api_call_full, run_type) |>
    summarize(across(run_time_sec:mem_system_avail, mean, na.rm = TRUE)) |>
    mutate(metric = "mean")
max_usage_common_all = d2_common_all |>
    group_by(api_call_full, run_type) |>
    summarize(across(run_time_sec:mem_system_avail, max, na.rm = TRUE)) |>
    mutate(metric = "max")
# Merge mean and max usage into one table
usage_common_all = bind_rows(mean_usage_common_all, max_usage_common_all) |>
    select(api_call_full, metric, everything()) |>
    arrange(api_call_full, metric)
# In col gpu_pct_mean and gpu_pct_p90, replace -Inf and NaN with NA
usage_common_all = usage_common_all |>
    mutate(gpu_pct_mean = ifelse(is.infinite(gpu_pct_mean) | is.nan(gpu_pct_mean), NA, gpu_pct_mean),
           gpu_pct_p90 = ifelse(is.infinite(gpu_pct_p90) | is.nan(gpu_pct_p90), NA, gpu_pct_p90))
# Write to CSV for easier viewing
write.csv(usage_common_all, "benchmarking/metashape/resource-usage-summary_all-common.csv")

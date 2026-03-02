# Depth Mapping Performance: 2-Slice vs 3-Slice MIG Comparison

## Summary

Based on analysis of the benchmarking logs in `benchmarking/metashape/logs/merged/benchmarking-data-merged_mig.csv`, 
depth mapping on a **3-slice MIG is 1.27x faster** than a 2-slice MIG, representing approximately a **21% performance improvement**.

## Detailed Results

### Hardware Specifications
- **2-slice MIG**: NVIDIA A100-SXM4-40GB MIG 2g.10gb (1x2g)
- **3-slice MIG**: NVIDIA A100-SXM4-40GB MIG 3g.20gb (1x3g)

### Performance Metrics

Tested across 3 projects (000404, 000810, 0068_000434_000440):

| Configuration | Average Time | Min Time | Max Time |
|---------------|--------------|----------|----------|
| 2-slice MIG (1x2g) | 7,041 seconds (117.3 min) | 5,489 sec | 8,024 sec |
| 3-slice MIG (1x3g) | 5,551 seconds (92.5 min) | 4,191 sec | 6,346 sec |

**Time Savings**: 1,490 seconds (24.8 minutes) per project

**Speedup Factor**: 1.27x

**Percentage Faster**: 21.2%

## Cost-Efficiency Analysis

While the 3-slice MIG is faster, it's important to consider the cost implications:

- 3-slice MIG uses **1.5x** the GPU resources (3 slices vs 2 slices)
- 3-slice MIG provides **1.27x** speedup
- **Cost efficiency ratio**: 0.85x (speedup per unit of GPU resource)

This means the **2-slice MIG is approximately 15% more cost-efficient** per GPU slice.

## Recommendations

### Choose 2-Slice MIG when:
- Cost efficiency is the primary concern
- You can tolerate longer processing times (21% slower)
- Running many parallel jobs where resource utilization is key

### Choose 3-Slice MIG when:
- Faster turnaround time is critical
- You need results 25 minutes sooner per project
- The 15% cost premium is acceptable for the speed gain

## Reproducibility

The analysis can be reproduced by running:

```bash
cd benchmarking/metashape/scripts
python3 analyze_mig_depth_mapping_performance.py
```

## Data Source

All data is derived from actual benchmarking runs logged in:
- `benchmarking/metashape/logs/merged/benchmarking-data-merged_mig.csv`

The analysis specifically examines the `build_depth_maps` step with the `buildDepthMaps` API call across different MIG configurations.

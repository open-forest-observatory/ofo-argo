#!/usr/bin/env python3
"""
Analyze depth mapping performance across different MIG configurations.

This script analyzes the benchmarking data to compare the performance of depth mapping
(buildDepthMaps) across different MIG (Multi-Instance GPU) configurations, specifically
comparing 2-slice (1x2g) vs 3-slice (1x3g) MIG performance.
"""

import csv
from pathlib import Path


def analyze_depth_mapping_performance():
    """Analyze and compare depth mapping performance across MIG configurations."""
    
    # Path to the merged MIG benchmarking data
    data_file = Path(__file__).parent.parent / "logs" / "merged" / "benchmarking-data-merged_mig.csv"
    
    # Read the CSV file
    with open(data_file, 'r') as f:
        reader = csv.DictReader(f)
        data = list(reader)
    
    # Filter for build_depth_maps step
    depth_map_data = [row for row in data 
                      if row['step'] == 'build_depth_maps' 
                      and row['api_call'] == 'buildDepthMaps']
    
    # Separate by node type
    two_slice_data = [row for row in depth_map_data if row['node_type'] == '1x2g']
    three_slice_data = [row for row in depth_map_data if row['node_type'] == '1x3g']
    
    print("=" * 80)
    print("DEPTH MAPPING PERFORMANCE COMPARISON: 2-SLICE vs 3-SLICE MIG")
    print("=" * 80)
    print()
    
    # 2-slice analysis
    print("2-SLICE MIG (1x2g) - NVIDIA A100-SXM4-40GB MIG 2g.10gb")
    print("-" * 80)
    for row in two_slice_data:
        print(f"Project: {row['project']:30s} | Time: {row['run_time_sec']:>6s} sec")
    print()
    
    two_slice_times = [int(row['run_time_sec']) for row in two_slice_data]
    avg_2slice = sum(two_slice_times) / len(two_slice_times)
    print(f"Number of projects:   {len(two_slice_times)}")
    print(f"Average time:         {avg_2slice:.1f} seconds ({avg_2slice/60:.1f} minutes)")
    print(f"Min time:             {min(two_slice_times)} seconds")
    print(f"Max time:             {max(two_slice_times)} seconds")
    print()
    print()
    
    # 3-slice analysis
    print("3-SLICE MIG (1x3g) - NVIDIA A100-SXM4-40GB MIG 3g.20gb")
    print("-" * 80)
    for row in three_slice_data:
        print(f"Project: {row['project']:30s} | Time: {row['run_time_sec']:>6s} sec")
    print()
    
    three_slice_times = [int(row['run_time_sec']) for row in three_slice_data]
    avg_3slice = sum(three_slice_times) / len(three_slice_times)
    print(f"Number of projects:   {len(three_slice_times)}")
    print(f"Average time:         {avg_3slice:.1f} seconds ({avg_3slice/60:.1f} minutes)")
    print(f"Min time:             {min(three_slice_times)} seconds")
    print(f"Max time:             {max(three_slice_times)} seconds")
    print()
    print()
    
    # Performance comparison
    print("=" * 80)
    print("PERFORMANCE ANALYSIS")
    print("=" * 80)
    speedup = avg_2slice / avg_3slice
    time_saved = avg_2slice - avg_3slice
    percent_faster = ((avg_2slice - avg_3slice) / avg_2slice) * 100
    
    print(f"Average 2-slice time:     {avg_2slice:.1f} seconds ({avg_2slice/60:.1f} minutes)")
    print(f"Average 3-slice time:     {avg_3slice:.1f} seconds ({avg_3slice/60:.1f} minutes)")
    print(f"Time saved:               {time_saved:.1f} seconds ({time_saved/60:.1f} minutes)")
    print(f"Speedup factor:           {speedup:.2f}x")
    print(f"Percentage faster:        {percent_faster:.1f}%")
    print()
    print(f"CONCLUSION: Depth mapping on a 3-slice MIG is {speedup:.2f}x faster")
    print(f"            than a 2-slice MIG (or {percent_faster:.0f}% faster)")
    print()
    
    # Cost-efficiency analysis
    print("=" * 80)
    print("COST-EFFICIENCY CONSIDERATIONS")
    print("=" * 80)
    print(f"3-slice MIG uses 1.5x the GPU resources of 2-slice MIG")
    print(f"3-slice MIG provides {speedup:.2f}x speedup")
    cost_efficiency = speedup / 1.5
    print(f"Cost efficiency ratio: {cost_efficiency:.2f}x")
    print(f"  (speedup per unit of GPU resource)")
    print()
    if cost_efficiency > 1.0:
        print(f"→ 3-slice MIG is MORE cost-efficient than 2-slice MIG")
        print(f"  You get {(cost_efficiency - 1) * 100:.0f}% more performance per GPU slice")
    else:
        print(f"→ 2-slice MIG is MORE cost-efficient than 3-slice MIG")
        print(f"  You lose {(1 - cost_efficiency) * 100:.0f}% performance per GPU slice")
    print("=" * 80)


if __name__ == "__main__":
    analyze_depth_mapping_performance()

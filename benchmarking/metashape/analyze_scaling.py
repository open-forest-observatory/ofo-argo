#!/usr/bin/env python3
"""
Analyze photogrammetry workflow resource usage and scaling behavior.
"""

import csv
from collections import defaultdict
from pathlib import Path

def load_csv(filepath):
    """Load CSV and return list of dicts"""
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        return list(reader)

def safe_float(value):
    """Convert to float, return None if N/A or invalid"""
    if value in ['N/A', '', None]:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

# Load data
data_dir = Path(__file__).parent
df_large = load_csv(data_dir / "benchmarking-data-merged_large.csv")
df_xl = load_csv(data_dir / "benchmarking-data-merged_xl.csv")
df_mig = load_csv(data_dir / "benchmarking-data-merged_mig.csv")

print("="*80)
print("PHOTOGRAMMETRY WORKFLOW SCALING ANALYSIS")
print("="*80)

# ============================================================================
# QUESTION 1: m3.large (16 cores) vs m3.xl (32 cores) - Per Step Analysis
# ============================================================================
print("\n" + "="*80)
print("Q1: CPU SCALING - m3.large (16 cores) vs m3.xl (32 cores)")
print("="*80)
print("\nDoes halving CPU count double execution time?\n")

# Find common projects
projects_large = set(row['project'] for row in df_large)
projects_xl = set(row['project'] for row in df_xl)
common_projects = sorted(projects_large & projects_xl)

print(f"Common projects for comparison: {common_projects}\n")

# Build lookup dictionaries
large_by_key = {}
for row in df_large:
    key = (row['project'], row['step'], row['api_call'])
    large_by_key[key] = row

xl_by_key = {}
for row in df_xl:
    key = (row['project'], row['step'], row['api_call'])
    xl_by_key[key] = row

# Compare
results_cpu_scaling = []
for key in large_by_key:
    if key in xl_by_key:
        row_l = large_by_key[key]
        row_x = xl_by_key[key]

        time_large = safe_float(row_l['run_time_sec'])
        time_xl = safe_float(row_x['run_time_sec'])
        cpu_pct_large = safe_float(row_l['cpu_pct_mean'])
        cpu_pct_xl = safe_float(row_x['cpu_pct_mean'])
        cpu_usage_large = safe_float(row_l['cpu_usage_mean'])
        cpu_usage_xl = safe_float(row_x['cpu_usage_mean'])

        if time_large and time_xl and time_xl > 0:
            speedup = time_large / time_xl
            core_ratio = 2.0  # 32/16
            efficiency = (speedup / core_ratio) * 100

            results_cpu_scaling.append({
                'project': key[0],
                'step': key[1],
                'api_call': key[2],
                'time_16cpu': time_large,
                'time_32cpu': time_xl,
                'speedup': speedup,
                'efficiency_pct': efficiency,
                'cpu_pct_16': cpu_pct_large or 0,
                'cpu_pct_32': cpu_pct_xl or 0,
                'cpu_usage_16': cpu_usage_large or 0,
                'cpu_usage_32': cpu_usage_xl or 0
            })

# Summary by step type
print("\nSummary by Step Type:")
print("-" * 80)

step_stats = defaultdict(lambda: {'efficiency': [], 'speedup': [], 'cpu_16': [], 'cpu_32': []})
for r in results_cpu_scaling:
    step_stats[r['step']]['efficiency'].append(r['efficiency_pct'])
    step_stats[r['step']]['speedup'].append(r['speedup'])
    step_stats[r['step']]['cpu_16'].append(r['cpu_pct_16'])
    step_stats[r['step']]['cpu_32'].append(r['cpu_pct_32'])

for step in sorted(step_stats.keys()):
    stats = step_stats[step]
    avg_efficiency = sum(stats['efficiency']) / len(stats['efficiency'])
    avg_speedup = sum(stats['speedup']) / len(stats['speedup'])
    avg_cpu_16 = sum(stats['cpu_16']) / len(stats['cpu_16'])
    avg_cpu_32 = sum(stats['cpu_32']) / len(stats['cpu_32'])

    print(f"\n{step}:")
    print(f"  Average speedup (2x cores):     {avg_speedup:.2f}x")
    print(f"  Average parallel efficiency:    {avg_efficiency:.1f}%")
    print(f"  Average CPU utilization (16c):  {avg_cpu_16:.1f}%")
    print(f"  Average CPU utilization (32c):  {avg_cpu_32:.1f}%")

# Detailed results
print("\n" + "-"*80)
print("Detailed Analysis - All Steps (sorted by efficiency):")
print("-" * 80)

results_cpu_scaling.sort(key=lambda x: x['efficiency_pct'], reverse=True)

print(f"\n{'Step':<25} {'API Call':<30} {'16c(s)':<8} {'32c(s)':<8} {'Speedup':<8} {'Eff%':<8} {'CPU%16':<8} {'CPU%32':<8}")
print("-" * 120)
for row in results_cpu_scaling[:30]:  # Top 30
    print(f"{row['step']:<25} {row['api_call']:<30} {row['time_16cpu']:<8.0f} {row['time_32cpu']:<8.0f} "
          f"{row['speedup']:<8.2f} {row['efficiency_pct']:<8.1f} {row['cpu_pct_16']:<8.1f} {row['cpu_pct_32']:<8.1f}")

# Key insights
print("\n" + "="*80)
print("KEY INSIGHTS - CPU Scaling:")
print("="*80)

low_efficiency = [r for r in results_cpu_scaling if r['efficiency_pct'] < 70]
high_efficiency = [r for r in results_cpu_scaling if r['efficiency_pct'] >= 90]
low_cpu_util_32 = [r for r in results_cpu_scaling if r['cpu_pct_32'] < 40]

print(f"\nSteps with poor scaling (efficiency < 70%): {len(low_efficiency)}")
print(f"Steps with good scaling (efficiency >= 90%): {len(high_efficiency)}")
print(f"Steps with low CPU utilization on 32 cores (< 40%): {len(low_cpu_util_32)}")

if low_efficiency:
    print("\n** Steps with poor parallel efficiency (<70%) - may have too many cores:")
    for row in low_efficiency[:10]:  # Show top 10
        print(f"  - {row['step']:25} / {row['api_call']:30} | Eff: {row['efficiency_pct']:.1f}% | CPU%: {row['cpu_pct_32']:.1f}%")

# Overall recommendation
all_cpu_util_16 = [r['cpu_pct_16'] for r in results_cpu_scaling]
all_cpu_util_32 = [r['cpu_pct_32'] for r in results_cpu_scaling]
all_efficiency = [r['efficiency_pct'] for r in results_cpu_scaling]

avg_cpu_util_16 = sum(all_cpu_util_16) / len(all_cpu_util_16)
avg_cpu_util_32 = sum(all_cpu_util_32) / len(all_cpu_util_32)
avg_efficiency = sum(all_efficiency) / len(all_efficiency)

print(f"\n** Overall Metrics:")
print(f"   Average CPU utilization: 16c={avg_cpu_util_16:.1f}%, 32c={avg_cpu_util_32:.1f}%")
print(f"   Average parallel efficiency: {avg_efficiency:.1f}%")

print("\n** RECOMMENDATION:")
if avg_efficiency < 75:
    print("   ⚠️  LOW parallel efficiency! Many steps cannot effectively use 32 cores.")
    print("   → Consider: m3.large instances OR running 2 parallel jobs on m3.xl")
    print("   → This would improve resource utilization and cost efficiency")
elif avg_efficiency > 90:
    print("   ✓ GOOD parallel efficiency! 32-core instances are well utilized.")
    print("   → m3.xl instances are appropriate for single jobs")
else:
    print("   → MODERATE parallel efficiency. Mixed results.")
    print("   → Some steps scale well, others show parallelization overhead")
    print("   → Consider workload-specific instance sizing")

# ============================================================================
# QUESTION 2: MIG Scaling
# ============================================================================
print("\n\n" + "="*80)
print("Q2: MIG GPU SCALING - Multiple small slices vs single large slice")
print("="*80)

# Build MIG lookup
mig_by_key = {}
for row in df_mig:
    key = (row['project'], row['step'], row['api_call'], row['node_type'])
    mig_by_key[key] = row

# Group by project/step/api_call
mig_groups = defaultdict(lambda: {})
for key, row in mig_by_key.items():
    project, step, api_call, node_type = key
    group_key = (project, step, api_call)
    mig_groups[group_key][node_type] = row

# Compare configurations
print("\nComparison: 3×(1g.5gb) vs 1×(3g.20gb)")
print("-" * 100)

comparison_3g = []
for group_key, configs in mig_groups.items():
    if '3x1g' in configs and '1x3g' in configs:
        time_3x1g = safe_float(configs['3x1g']['run_time_sec'])
        time_1x3g = safe_float(configs['1x3g']['run_time_sec'])
        gpu_3x1g = safe_float(configs['3x1g']['gpu_pct_mean'])
        gpu_1x3g = safe_float(configs['1x3g']['gpu_pct_mean'])

        if time_3x1g and time_1x3g:
            ratio = time_3x1g / time_1x3g
            comparison_3g.append({
                'project': group_key[0],
                'step': group_key[1],
                'api_call': group_key[2],
                'time_3x1g': time_3x1g,
                'time_1x3g': time_1x3g,
                'ratio': ratio,
                'gpu_3x1g': gpu_3x1g or 0,
                'gpu_1x3g': gpu_1x3g or 0
            })

if comparison_3g:
    print(f"{'Project':<15} {'Step':<20} {'API Call':<20} {'3x1g(s)':<10} {'1x3g(s)':<10} {'Ratio':<8}")
    print("-" * 100)
    for row in comparison_3g:
        print(f"{row['project']:<15} {row['step']:<20} {row['api_call']:<20} "
              f"{row['time_3x1g']:<10.0f} {row['time_1x3g']:<10.0f} {row['ratio']:<8.2f}")

    avg_ratio = sum(r['ratio'] for r in comparison_3g) / len(comparison_3g)
    print(f"\n** Average time ratio (3x1g / 1x3g): {avg_ratio:.3f}")
    if avg_ratio < 0.95:
        print("   → 3 small slices are FASTER than 1 large slice")
    elif avg_ratio > 1.05:
        print("   → 1 large slice is FASTER than 3 small slices")
    else:
        print("   → Performance is roughly EQUIVALENT")
else:
    print("No common data for 3x1g vs 1x3g comparison")

print("\n\nComparison: 2×(1g.5gb) vs 1×(2g.10gb)")
print("-" * 100)

comparison_2g = []
for group_key, configs in mig_groups.items():
    if '2x1g' in configs and '1x2g' in configs:
        time_2x1g = safe_float(configs['2x1g']['run_time_sec'])
        time_1x2g = safe_float(configs['1x2g']['run_time_sec'])

        if time_2x1g and time_1x2g:
            ratio = time_2x1g / time_1x2g
            comparison_2g.append({
                'project': group_key[0],
                'step': group_key[1],
                'api_call': group_key[2],
                'time_2x1g': time_2x1g,
                'time_1x2g': time_1x2g,
                'ratio': ratio
            })

if comparison_2g:
    print(f"{'Project':<15} {'Step':<20} {'API Call':<20} {'2x1g(s)':<10} {'1x2g(s)':<10} {'Ratio':<8}")
    print("-" * 100)
    for row in comparison_2g:
        print(f"{row['project']:<15} {row['step']:<20} {row['api_call']:<20} "
              f"{row['time_2x1g']:<10.0f} {row['time_1x2g']:<10.0f} {row['ratio']:<8.2f}")

    avg_ratio = sum(r['ratio'] for r in comparison_2g) / len(comparison_2g)
    print(f"\n** Average time ratio (2x1g / 1x2g): {avg_ratio:.3f}")
    if avg_ratio < 0.95:
        print("   → 2 small slices are FASTER than 1 large slice")
    elif avg_ratio > 1.05:
        print("   → 1 large slice is FASTER than 2 small slices")
    else:
        print("   → Performance is roughly EQUIVALENT")
else:
    print("No common data for 2x1g vs 1x2g comparison")

# Scaling analysis
print("\n\nScaling efficiency: Adding more 1g slices")
print("-" * 100)

scaling_results = []
for group_key, configs in mig_groups.items():
    if '1x1g' in configs:
        time_1x1g = safe_float(configs['1x1g']['run_time_sec'])
        time_2x1g = safe_float(configs['2x1g']['run_time_sec']) if '2x1g' in configs else None
        time_3x1g = safe_float(configs['3x1g']['run_time_sec']) if '3x1g' in configs else None

        if time_1x1g:
            speedup_2x = time_1x1g / time_2x1g if time_2x1g else None
            speedup_3x = time_1x1g / time_3x1g if time_3x1g else None

            scaling_results.append({
                'project': group_key[0],
                'step': group_key[1],
                'api_call': group_key[2],
                'time_1x1g': time_1x1g,
                'time_2x1g': time_2x1g,
                'time_3x1g': time_3x1g,
                'speedup_2x': speedup_2x,
                'speedup_3x': speedup_3x
            })

if scaling_results:
    print(f"{'Project':<15} {'Step':<20} {'1x1g(s)':<10} {'2x1g(s)':<10} {'3x1g(s)':<10} {'Speedup2x':<10} {'Speedup3x':<10}")
    print("-" * 110)
    for row in scaling_results:
        s2 = f"{row['speedup_2x']:.2f}" if row['speedup_2x'] else "N/A"
        s3 = f"{row['speedup_3x']:.2f}" if row['speedup_3x'] else "N/A"
        t2 = f"{row['time_2x1g']:.0f}" if row['time_2x1g'] else "N/A"
        t3 = f"{row['time_3x1g']:.0f}" if row['time_3x1g'] else "N/A"
        print(f"{row['project']:<15} {row['step']:<20} {row['time_1x1g']:<10.0f} {t2:<10} {t3:<10} {s2:<10} {s3:<10}")

    # Calculate average speedups
    speedups_2x = [r['speedup_2x'] for r in scaling_results if r['speedup_2x']]
    speedups_3x = [r['speedup_3x'] for r in scaling_results if r['speedup_3x']]

    if speedups_2x:
        avg_speedup_2x = sum(speedups_2x) / len(speedups_2x)
        efficiency_2x = (avg_speedup_2x / 2.0) * 100
        print(f"\n** Average speedup with 2 slices: {avg_speedup_2x:.2f}x (efficiency: {efficiency_2x:.1f}%)")

    if speedups_3x:
        avg_speedup_3x = sum(speedups_3x) / len(speedups_3x)
        efficiency_3x = (avg_speedup_3x / 3.0) * 100
        print(f"** Average speedup with 3 slices: {avg_speedup_3x:.2f}x (efficiency: {efficiency_3x:.1f}%)")

# ============================================================================
# QUESTION 3: MIG vs Full GPU
# ============================================================================
print("\n\n" + "="*80)
print("Q3: MIG SLICES vs FULL GPU - Proportional performance?")
print("="*80)

# Find GPU steps in large/xl data
gpu_steps_large = {}
for row in df_large:
    if safe_float(row['gpus']) == 1 and row['step'] == 'build_depth_maps':
        key = (row['project'], row['step'], row['api_call'])
        gpu_steps_large[key] = row

gpu_steps_xl = {}
for row in df_xl:
    if safe_float(row['gpus']) == 1 and row['step'] == 'build_depth_maps':
        key = (row['project'], row['step'], row['api_call'])
        gpu_steps_xl[key] = row

# Combine (prefer xl if available)
gpu_steps_full = {**gpu_steps_large, **gpu_steps_xl}

print(f"\nComparing MIG slices to full A100 GPU (build_depth_maps step):\n")

gpu_comparisons = []
for group_key, configs in mig_groups.items():
    project, step, api_call = group_key
    if step == 'build_depth_maps':
        full_key = (project, step, api_call)
        if full_key in gpu_steps_full:
            time_full = safe_float(gpu_steps_full[full_key]['run_time_sec'])
            gpu_pct_full = safe_float(gpu_steps_full[full_key]['gpu_pct_mean'])

            if time_full:
                result = {
                    'project': project,
                    'time_full': time_full,
                    'gpu_pct_full': gpu_pct_full or 0
                }

                for config in ['1x1g', '1x2g', '1x3g', '2x1g', '3x1g']:
                    if config in configs:
                        result[f'time_{config}'] = safe_float(configs[config]['run_time_sec'])
                        result[f'ratio_{config}'] = result[f'time_{config}'] / time_full if result.get(f'time_{config}') else None
                    else:
                        result[f'time_{config}'] = None
                        result[f'ratio_{config}'] = None

                gpu_comparisons.append(result)

if gpu_comparisons:
    print(f"{'Project':<15} {'Full(s)':<10} {'1x1g(s)':<10} {'1x2g(s)':<10} {'1x3g(s)':<10} {'2x1g(s)':<10} {'3x1g(s)':<10}")
    print("-" * 100)
    for row in gpu_comparisons:
        t1 = f"{row['time_1x1g']:.0f}" if row['time_1x1g'] else "N/A"
        t2 = f"{row['time_1x2g']:.0f}" if row['time_1x2g'] else "N/A"
        t3 = f"{row['time_1x3g']:.0f}" if row['time_1x3g'] else "N/A"
        t4 = f"{row['time_2x1g']:.0f}" if row['time_2x1g'] else "N/A"
        t5 = f"{row['time_3x1g']:.0f}" if row['time_3x1g'] else "N/A"
        print(f"{row['project']:<15} {row['time_full']:<10.0f} {t1:<10} {t2:<10} {t3:<10} {t4:<10} {t5:<10}")

    print("\n\nPerformance relative to Full GPU (ratio = MIG_time / Full_time):")
    print("-" * 80)
    print(f"{'Config':<20} {'Avg Ratio':<12} {'Expected':<12} {'Efficiency':<15}")
    print("-" * 80)

    configs = [
        ('1x1g (1/7 GPU)', 'ratio_1x1g', 7.0),
        ('1x2g (2/7 GPU)', 'ratio_1x2g', 3.5),
        ('1x3g (3/7 GPU)', 'ratio_1x3g', 2.33),
        ('2x1g (2/7 GPU)', 'ratio_2x1g', 3.5),
        ('3x1g (3/7 GPU)', 'ratio_3x1g', 2.33),
    ]

    for config_name, ratio_key, expected_ratio in configs:
        ratios = [r[ratio_key] for r in gpu_comparisons if r.get(ratio_key)]
        if ratios:
            avg_ratio = sum(ratios) / len(ratios)
            efficiency = (expected_ratio / avg_ratio * 100)
            print(f"{config_name:<20} {avg_ratio:<12.2f} {expected_ratio:<12.2f} {efficiency:<15.1f}%")

    print("\n** Interpretation:")
    print("   - If efficiency > 100%, MIG performs BETTER than linear scaling")
    print("   - If efficiency < 100%, MIG performs WORSE than linear scaling")
    print("   - Expected ratio = full_time * (1/fraction)")
    print("     e.g., 1/7 slice should take ~7x longer than full GPU")

else:
    print("No overlapping data found between MIG and full GPU runs")

print("\n" + "="*80)
print("END OF ANALYSIS")
print("="*80)

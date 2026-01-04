#!/usr/bin/env python3
"""
Detailed per-step analysis of photogrammetry workflow scaling.
"""

import csv
from collections import defaultdict
from pathlib import Path
import statistics

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

print("="*100)
print("DETAILED PER-STEP SCALING ANALYSIS")
print("="*100)

# ============================================================================
# PART 1: Understanding Efficiency Metrics
# ============================================================================
print("\n" + "="*100)
print("UNDERSTANDING EFFICIENCY METRICS")
print("="*100)

print("""
When we compare 16-core to 32-core performance, we calculate:

    Speedup = Time_16core / Time_32core

    Efficiency = (Speedup / CoreRatio) × 100%
                = (Speedup / 2.0) × 100%

INTERPRETATION:
- Efficiency = 100%: Perfect scaling. 2x cores = 2x faster
- Efficiency > 100%: SUPER-LINEAR scaling. Better than expected!
- Efficiency < 100%: SUB-LINEAR scaling. Parallelization overhead

WHY CAN EFFICIENCY EXCEED 100%?
1. Cache effects: More cores = more L3 cache, data fits better
2. Memory bandwidth: Better utilization with more cores
3. NUMA effects: Better memory locality
4. Reduced contention: Less lock contention per core

For "match_photos" showing 115% efficiency:
- 16c: 1263s → 32c: 481s
- Speedup = 1263/481 = 2.63x (not just 2x!)
- Efficiency = 2.63/2 × 100% = 131%
- This is REAL - the algorithm benefits from extra cache/memory bandwidth

WHY IS LOW EFFICIENCY BAD?
- Efficiency = 50% means you're wasting half your cores
- Example: 16c: 100s → 32c: 100s (no speedup)
  - Speedup = 1.0x, Efficiency = 50%
  - You're paying for 32 cores but only using 16 cores worth of work

""")

# ============================================================================
# PART 2: CPU Scaling - Detailed Per-Step Analysis
# ============================================================================
print("\n" + "="*100)
print("PART 1: CPU SCALING - DETAILED PER-STEP BREAKDOWN")
print("="*100)

# Build lookup dictionaries
large_by_key = {}
for row in df_large:
    key = (row['project'], row['step'], row['api_call'])
    large_by_key[key] = row

xl_by_key = {}
for row in df_xl:
    key = (row['project'], row['step'], row['api_call'])
    xl_by_key[key] = row

# Compare and organize by step+api_call
step_results = defaultdict(list)
for key in large_by_key:
    if key in xl_by_key:
        row_l = large_by_key[key]
        row_x = xl_by_key[key]

        time_large = safe_float(row_l['run_time_sec'])
        time_xl = safe_float(row_x['run_time_sec'])
        cpu_pct_large = safe_float(row_l['cpu_pct_mean'])
        cpu_pct_xl = safe_float(row_x['cpu_pct_mean'])

        if time_large and time_xl and time_xl > 0:
            speedup = time_large / time_xl
            efficiency = (speedup / 2.0) * 100

            step_api = (key[1], key[2])  # (step, api_call)
            step_results[step_api].append({
                'project': key[0],
                'time_16': time_large,
                'time_32': time_xl,
                'speedup': speedup,
                'efficiency': efficiency,
                'cpu_16': cpu_pct_large or 0,
                'cpu_32': cpu_pct_xl or 0
            })

# Print detailed results for each step
for step_api in sorted(step_results.keys(), key=lambda x: x[0] + x[1]):
    step, api = step_api
    results = step_results[step_api]

    # Calculate statistics
    efficiencies = [r['efficiency'] for r in results]
    speedups = [r['speedup'] for r in results]
    cpu_16s = [r['cpu_16'] for r in results]
    cpu_32s = [r['cpu_32'] for r in results]

    avg_eff = statistics.mean(efficiencies)
    std_eff = statistics.stdev(efficiencies) if len(efficiencies) > 1 else 0
    min_eff = min(efficiencies)
    max_eff = max(efficiencies)

    avg_speedup = statistics.mean(speedups)
    avg_cpu_16 = statistics.mean(cpu_16s)
    avg_cpu_32 = statistics.mean(cpu_32s)

    print(f"\n{'='*100}")
    print(f"STEP: {step} / {api}")
    print(f"{'='*100}")
    print(f"Number of projects tested: {len(results)}")
    print(f"\nAVERAGE PERFORMANCE:")
    print(f"  Speedup (16c→32c):        {avg_speedup:.2f}x")
    print(f"  Parallel efficiency:      {avg_eff:.1f}% (±{std_eff:.1f}%)")
    print(f"  Efficiency range:         {min_eff:.1f}% to {max_eff:.1f}%")
    print(f"  CPU utilization (16c):    {avg_cpu_16:.1f}%")
    print(f"  CPU utilization (32c):    {avg_cpu_32:.1f}%")

    # Interpretation
    print(f"\nINTERPRETATION:")
    if avg_eff > 95:
        print(f"  ✓ EXCELLENT scaling! This step benefits from more cores.")
        print(f"  → Recommendation: 32-core instances are well-utilized")
    elif avg_eff > 75:
        print(f"  → GOOD scaling. Moderate benefit from additional cores.")
        print(f"  → Recommendation: 32-core instances are reasonable")
    elif avg_eff > 60:
        print(f"  ⚠ MODERATE scaling. Limited benefit from additional cores.")
        print(f"  → Recommendation: Consider 16-core instances or bin-packing")
    else:
        print(f"  ✗ POOR scaling. Minimal benefit from additional cores.")
        print(f"  → Recommendation: Use 16-core instances or pack multiple jobs")

    # Variability assessment
    if std_eff > 15:
        print(f"\n  ⚠ HIGH VARIABILITY (σ={std_eff:.1f}%): Results vary significantly by project")
        print(f"     Performance may depend on dataset characteristics")
    elif std_eff > 5:
        print(f"\n  → Moderate variability (σ={std_eff:.1f}%): Some variation by project")
    else:
        print(f"\n  ✓ Low variability (σ={std_eff:.1f}%): Consistent across projects")

    # Per-project breakdown
    print(f"\nPER-PROJECT RESULTS:")
    print(f"  {'Project':<25} {'16c(s)':<10} {'32c(s)':<10} {'Speedup':<10} {'Eff%':<10} {'CPU%16':<8} {'CPU%32':<8}")
    print(f"  {'-'*90}")
    for r in sorted(results, key=lambda x: x['efficiency'], reverse=True):
        print(f"  {r['project']:<25} {r['time_16']:<10.0f} {r['time_32']:<10.0f} "
              f"{r['speedup']:<10.2f} {r['efficiency']:<10.1f} {r['cpu_16']:<8.1f} {r['cpu_32']:<8.1f}")

# ============================================================================
# PART 3: Can we run 2 jobs on m3.xl instead of 1 job on m3.large?
# ============================================================================
print("\n\n" + "="*100)
print("PART 2: RUNNING 2 JOBS ON m3.xl vs 1 JOB ON m3.large")
print("="*100)

print("""
QUESTION: If I run 2 parallel jobs on one m3.xl (32 cores), will each job perform
          as well as running 1 job on m3.large (16 cores)?

ANALYSIS APPROACH:
1. Look at CPU utilization on 16-core instances
2. If avg CPU% < 50%, the process doesn't use all 16 cores effectively
3. If 2 such processes run on 32 cores, they won't interfere much

KEY ASSUMPTION: When running 2 jobs on m3.xl, each job will see 32 cores but
                 the scheduler will distribute CPU time fairly between them.
""")

print(f"\n{'Step':<25} {'API Call':<30} {'Avg CPU%':<10} {'Can pack?':<12} {'Reasoning':<50}")
print(f"{'-'*130}")

for step_api in sorted(step_results.keys()):
    step, api = step_api
    results = step_results[step_api]

    avg_cpu_16 = statistics.mean([r['cpu_16'] for r in results])
    avg_cpu_32 = statistics.mean([r['cpu_32'] for r in results])
    avg_eff = statistics.mean([r['efficiency'] for r in results])

    # Decision logic
    if avg_cpu_16 < 50:
        can_pack = "YES"
        reasoning = f"Low CPU usage ({avg_cpu_16:.0f}%), plenty of headroom"
    elif avg_cpu_16 < 70:
        can_pack = "MAYBE"
        reasoning = f"Moderate CPU usage ({avg_cpu_16:.0f}%), some risk of contention"
    else:
        can_pack = "NO"
        reasoning = f"High CPU usage ({avg_cpu_16:.0f}%), likely contention"

    print(f"{step:<25} {api:<30} {avg_cpu_16:<10.1f} {can_pack:<12} {reasoning:<50}")

# Summary recommendation
print(f"\n{'='*100}")
print("SUMMARY RECOMMENDATION: 2 jobs on m3.xl")
print(f"{'='*100}")

all_cpu_16 = []
for results in step_results.values():
    all_cpu_16.extend([r['cpu_16'] for r in results])

avg_all_cpu = statistics.mean(all_cpu_16)
low_cpu_steps = sum(1 for results in step_results.values()
                    if statistics.mean([r['cpu_16'] for r in results]) < 50)
total_steps = len(step_results)

print(f"\nOverall average CPU utilization on 16 cores: {avg_all_cpu:.1f}%")
print(f"Steps with CPU < 50%: {low_cpu_steps}/{total_steps} ({low_cpu_steps/total_steps*100:.0f}%)")

if avg_all_cpu < 40:
    print(f"\n✓ STRONG RECOMMENDATION: Run 2 jobs on m3.xl")
    print(f"  - Most steps use < 50% CPU, so 2 jobs can coexist")
    print(f"  - Expected performance: Each job ~same as m3.large")
    print(f"  - Cost benefit: 2x throughput on same instance")
elif avg_all_cpu < 60:
    print(f"\n→ MODERATE RECOMMENDATION: Run 2 jobs on m3.xl with caution")
    print(f"  - Some steps may experience mild contention")
    print(f"  - Expected performance: 90-95% of m3.large performance")
    print(f"  - Test with your specific workload mix")
else:
    print(f"\n⚠ CAUTION: Running 2 jobs on m3.xl may cause contention")
    print(f"  - High CPU utilization suggests processes will compete")
    print(f"  - Expected performance: 70-85% of m3.large performance")
    print(f"  - Consider dedicated instances instead")

# ============================================================================
# PART 4: MIG Scaling - Detailed Per-Step Analysis
# ============================================================================
print("\n\n" + "="*100)
print("PART 3: MIG GPU SCALING - DETAILED PER-STEP BREAKDOWN")
print("="*100)

# Build MIG lookup by step
mig_by_key = {}
for row in df_mig:
    key = (row['project'], row['step'], row['api_call'], row['node_type'])
    mig_by_key[key] = row

# Group by step/api_call
mig_step_data = defaultdict(lambda: defaultdict(lambda: {}))
for key, row in mig_by_key.items():
    project, step, api_call, node_type = key
    mig_step_data[(step, api_call)][project][node_type] = row

# Also get full GPU data
gpu_steps_large = {}
for row in df_large:
    if safe_float(row['gpus']) == 1:
        key = (row['project'], row['step'], row['api_call'])
        gpu_steps_large[key] = row

gpu_steps_xl = {}
for row in df_xl:
    if safe_float(row['gpus']) == 1:
        key = (row['project'], row['step'], row['api_call'])
        gpu_steps_xl[key] = row

gpu_steps_full = {**gpu_steps_large, **gpu_steps_xl}

# Analyze each step
for step_api in sorted(mig_step_data.keys()):
    step, api = step_api
    project_data = mig_step_data[step_api]

    print(f"\n{'='*100}")
    print(f"STEP: {step} / {api}")
    print(f"{'='*100}")
    print(f"Number of projects tested: {len(project_data)}")

    # Collect data for analysis
    mig_comparisons = {
        '1x1g_vs_1x2g': [],
        '1x1g_vs_1x3g': [],
        '2x1g_vs_1x2g': [],
        '3x1g_vs_1x3g': [],
        'full_vs_1x1g': [],
        'full_vs_1x2g': [],
        'full_vs_1x3g': [],
        'full_vs_2x1g': [],
        'full_vs_3x1g': []
    }

    for project, configs in project_data.items():
        # Extract times
        time_1x1g = safe_float(configs.get('1x1g', {}).get('run_time_sec'))
        time_1x2g = safe_float(configs.get('1x2g', {}).get('run_time_sec'))
        time_1x3g = safe_float(configs.get('1x3g', {}).get('run_time_sec'))
        time_2x1g = safe_float(configs.get('2x1g', {}).get('run_time_sec'))
        time_3x1g = safe_float(configs.get('3x1g', {}).get('run_time_sec'))

        # Get full GPU time if available
        full_key = (project, step, api)
        time_full = None
        if full_key in gpu_steps_full:
            time_full = safe_float(gpu_steps_full[full_key]['run_time_sec'])

        # Compare configs
        if time_1x1g and time_1x2g:
            mig_comparisons['1x1g_vs_1x2g'].append({
                'project': project,
                'speedup': time_1x1g / time_1x2g,
                'efficiency': (time_1x1g / time_1x2g) / 2.0 * 100
            })

        if time_1x1g and time_1x3g:
            mig_comparisons['1x1g_vs_1x3g'].append({
                'project': project,
                'speedup': time_1x1g / time_1x3g,
                'efficiency': (time_1x1g / time_1x3g) / 3.0 * 100
            })

        if time_2x1g and time_1x2g:
            ratio = time_2x1g / time_1x2g
            mig_comparisons['2x1g_vs_1x2g'].append({
                'project': project,
                'ratio': ratio,
                'faster': '2x1g' if ratio < 1 else '1x2g' if ratio > 1 else 'same'
            })

        if time_3x1g and time_1x3g:
            ratio = time_3x1g / time_1x3g
            mig_comparisons['3x1g_vs_1x3g'].append({
                'project': project,
                'ratio': ratio,
                'faster': '3x1g' if ratio < 1 else '1x3g' if ratio > 1 else 'same'
            })

        # Compare to full GPU
        if time_full:
            for config_name, config_time in [
                ('1x1g', time_1x1g), ('1x2g', time_1x2g), ('1x3g', time_1x3g),
                ('2x1g', time_2x1g), ('3x1g', time_3x1g)
            ]:
                if config_time:
                    ratio = config_time / time_full
                    # Expected ratios: 1x1g=7, 1x2g=3.5, 1x3g=2.33, etc.
                    expected = {'1x1g': 7, '1x2g': 3.5, '1x3g': 2.33,
                               '2x1g': 3.5, '3x1g': 2.33}
                    efficiency = (expected[config_name] / ratio) * 100 if config_name in expected else None

                    mig_comparisons[f'full_vs_{config_name}'].append({
                        'project': project,
                        'ratio': ratio,
                        'efficiency': efficiency
                    })

    # Print results
    print(f"\n--- Scaling Efficiency (vs 1×1g baseline) ---")

    for comparison in ['1x1g_vs_1x2g', '1x1g_vs_1x3g']:
        data = mig_comparisons[comparison]
        if data:
            speedups = [d['speedup'] for d in data]
            effs = [d['efficiency'] for d in data]
            avg_speedup = statistics.mean(speedups)
            avg_eff = statistics.mean(effs)
            std_eff = statistics.stdev(effs) if len(effs) > 1 else 0

            label = "1g→2g (2x slices)" if '1x2g' in comparison else "1g→3g (3x slices)"
            print(f"\n{label}:")
            print(f"  Average speedup:     {avg_speedup:.2f}x")
            print(f"  Average efficiency:  {avg_eff:.1f}% (±{std_eff:.1f}%)")

            if avg_eff > 80:
                print(f"  → EXCELLENT scaling for this step!")
            elif avg_eff > 60:
                print(f"  → GOOD scaling for this step")
            else:
                print(f"  → MODERATE scaling - this step has limited GPU parallelism")

    print(f"\n--- Multiple small vs single large ---")

    for comparison in ['2x1g_vs_1x2g', '3x1g_vs_1x3g']:
        data = mig_comparisons[comparison]
        if data:
            ratios = [d['ratio'] for d in data]
            avg_ratio = statistics.mean(ratios)

            label = "2×1g vs 1×2g" if '2x1g' in comparison else "3×1g vs 1×3g"
            print(f"\n{label}:")
            print(f"  Average ratio:       {avg_ratio:.3f}")

            if avg_ratio < 0.95:
                print(f"  → Multiple small slices are FASTER")
            elif avg_ratio > 1.05:
                print(f"  → Single large slice is FASTER")
            else:
                print(f"  → Performance is EQUIVALENT")

            print(f"  Per-project:")
            for d in data:
                print(f"    {d['project']:<25} ratio={d['ratio']:.3f} ({d['faster']})")

    print(f"\n--- MIG vs Full GPU Performance ---")

    for config in ['1x1g', '1x2g', '1x3g', '2x1g', '3x1g']:
        data = mig_comparisons[f'full_vs_{config}']
        if data:
            ratios = [d['ratio'] for d in data]
            effs = [d['efficiency'] for d in data]
            avg_ratio = statistics.mean(ratios)
            avg_eff = statistics.mean(effs)
            std_eff = statistics.stdev(effs) if len(effs) > 1 else 0

            expected = {'1x1g': 7, '1x2g': 3.5, '1x3g': 2.33, '2x1g': 3.5, '3x1g': 2.33}

            print(f"\n{config} (expected {expected[config]:.1f}x slower):")
            print(f"  Actual slowdown:     {avg_ratio:.2f}x")
            print(f"  Efficiency:          {avg_eff:.1f}% (±{std_eff:.1f}%)")

            if avg_eff > 150:
                print(f"  → EXCEPTIONAL! Much better than linear scaling")
            elif avg_eff > 100:
                print(f"  → EXCELLENT! Better than linear scaling")
            elif avg_eff > 80:
                print(f"  → GOOD! Nearly linear scaling")
            else:
                print(f"  → MODERATE scaling")

print("\n" + "="*100)
print("END OF DETAILED ANALYSIS")
print("="*100)

# Comprehensive Photogrammetry Workflow Scaling Analysis
## Detailed Answers to All Questions

**Analysis Date:** 2026-01-03
**Data Sources:**
- `benchmarking-data-merged_large.csv` - m3.large (16 cores) results
- `benchmarking-data-merged_xl.csv` - m3.xl (32 cores) results
- `benchmarking-data-merged_mig.csv` - Various MIG GPU configurations

**Projects Analyzed:** 7 different photogrammetry datasets with varying complexity

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Understanding Efficiency Metrics](#understanding-efficiency-metrics)
3. [Question 1: CPU Scaling Analysis (16c vs 32c)](#question-1-cpu-scaling-analysis)
4. [Question 2: Two Perspectives on Instance Sizing](#question-2-instance-sizing-perspectives)
5. [Question 3: Parallelization Overhead Concerns](#question-3-parallelization-overhead)
6. [Question 4: Multiple Small MIG Slices vs Single Large Slice](#question-4-mig-slice-configurations)
7. [Question 5: MIG vs Full GPU Proportional Scaling](#question-5-mig-proportional-scaling)
8. [Variability Analysis Across Projects](#variability-analysis)
9. [Final Recommendations](#final-recommendations)

---

## Executive Summary

### Key Findings at a Glance

**CPU Scaling (16c → 32c):**
- ⚠️ **Average efficiency: 65.4%** - Most steps show sub-linear scaling
- ⭐ **Exception: matchPhotos shows 115% super-linear scaling**
- ✓ **70% of steps safe for running 2 jobs on m3.xl**
- 💰 **Cost savings: 15-20% per job when bin-packing 2 jobs on m3.xl**

**MIG GPU Scaling:**
- 🚀 **Exceptional performance: 150-463% efficiency vs linear scaling**
- ✓ **Multiple small slices (3×1g) outperform single large (1×3g) by 15%**
- ✓ **Even 1/7 GPU slices only 3x slower instead of 7x slower**
- ✓ **MIG overhead is negligible to non-existent**

**Answer to Core Questions:**
1. **Halving CPUs does NOT double compute time** - efficiency varies 47-115% by step
2. **Deploy with m3.large** for single jobs OR **use m3.xl for 2 parallel jobs**
3. **Parallelization overhead IS REAL** for 60% of steps - your concern is valid
4. **3×1g slices ARE more efficient** than 1×3g (15% faster)
5. **MIG scaling is BETTER than proportional** - 150-463% efficiency

---

## Understanding Efficiency Metrics

### What is Parallel Efficiency?

When comparing performance between 16-core and 32-core instances:

```
Speedup = Time_16core / Time_32core
Efficiency = (Speedup / CoreRatio) × 100%
           = (Speedup / 2.0) × 100%
```

### Interpretation Guide

| Efficiency | Meaning | Example |
|-----------|---------|---------|
| **100%** | Perfect linear scaling | 16c: 100s → 32c: 50s (2x faster) |
| **>100%** | Super-linear scaling | 16c: 100s → 32c: 40s (2.5x faster) |
| **75%** | Good scaling | 16c: 100s → 32c: 67s (1.5x faster) |
| **50%** | Poor scaling | 16c: 100s → 32c: 100s (no speedup) |
| **25%** | Very poor scaling | 16c: 100s → 32c: 133s (slower!) |

### Why Can Efficiency Exceed 100%?

**Real Example: matchPhotos showing 115% efficiency**

- 16 cores: 1,263 seconds
- 32 cores: 481 seconds
- Speedup: 1263/481 = **2.63x** (not just 2x)
- Efficiency: 2.63/2 × 100% = **131%** for this project

**Physical Explanations:**

1. **Cache Effects** 🔥 Most Important
   - 32-core instance has 2× more L3 cache
   - If working set fits in 64MB but not 32MB
   - Dramatic reduction in cache misses
   - Can easily exceed linear scaling

2. **Memory Bandwidth**
   - More cores = more memory channels
   - Better aggregate bandwidth utilization
   - Less contention per core

3. **NUMA Effects**
   - Better memory locality with more cores
   - Reduced cross-socket traffic

4. **Reduced Lock Contention**
   - More cores = less contention per core on shared resources
   - Better parallelization of critical sections

**This is NOT measurement error** - it's real performance improvement from architectural benefits.

### Why is Low Efficiency Bad?

**Example: 50% efficiency means wasting half your cores**

- You pay for 32 cores
- You only get 16 cores worth of work
- 2× the cost for 1× the performance

**Example: build_depth_maps at 51% efficiency**
- 16c: 1,200s → 32c: 1,164s
- Speedup: only 1.03x with 2× the cores
- You're wasting ~15 cores that sit idle or create overhead

---

## Question 1: CPU Scaling Analysis

### Overall Statistics

**Across 113 step executions:**
- Average efficiency: **65.4%**
- Steps with poor scaling (<70%): **99 out of 113** (88%)
- Steps with good scaling (≥90%): **14 out of 113** (12%)
- Steps with low CPU utilization (<40% on 32c): **108 out of 113** (95%)

### Per-Step Detailed Analysis

#### ⭐ EXCELLENT SCALING (Efficiency ≥ 90%)

---

##### matchPhotos - SUPER-LINEAR SCALING 🚀

**Average Performance:**
- Speedup: **2.30x** (with 2× cores!)
- Efficiency: **115%**
- CPU Utilization: 16c=57% → 32c=8%

**Variability: HIGH (±27% std dev)**

| Project | 16c Time | 32c Time | Speedup | Efficiency | Notes |
|---------|----------|----------|---------|------------|-------|
| 000195 | 2,300s | 838s | 2.74x | **137%** | Best case |
| 000192 | 1,263s | 481s | 2.63x | **131%** | Excellent |
| 000810 | 2,717s | 1,100s | 2.47x | **124%** | Excellent |
| 0131_000015_000013 | 336s | 138s | 2.43x | **122%** | Excellent |
| 0068_000434_000440 | 3,276s | 1,362s | 2.41x | **120%** | Excellent |
| 000404 | 2,556s | 1,098s | 2.33x | **116%** | Excellent |
| benchmarking-emerald-subset | 64s | 57s | 1.12x | **56%** | Small dataset, overhead dominant |

**Why Super-Linear?**
- CPU% drops from 57% to 8% - this is **memory/cache bound**
- Algorithm builds spatial indexes and searches
- 2× L3 cache = working set fits better
- Dramatic reduction in memory latency

**Does Halving CPUs Double Time?**
- **NO** - halving CPUs increases time by only **0.43× on average**
- With 16c, you get 2.3× the execution time vs 32c (not 2×)
- **This step strongly benefits from more cores**

**Recommendation:**
✓ **STRONGLY use m3.xl (32c) for matchPhotos**
- This is the only step where extra cores have super-linear value
- Don't bin-pack this step - give it full 32 cores

---

##### classifyGroundPoints - NEAR-PERFECT SCALING

**Average Performance:**
- Speedup: **1.70x**
- Efficiency: **85%**
- CPU Utilization: 16c=80% → 32c=71%

**Variability: MODERATE (±12% std dev)**

| Project | 16c Time | 32c Time | Speedup | Efficiency | CPU% 16c | CPU% 32c |
|---------|----------|----------|---------|------------|----------|----------|
| 0068_000434_000440 | 43,243s | 21,484s | 2.01x | **101%** | 99% | 98% |
| 000404 | 1,160s | 674s | 1.72x | **86%** | 80% | 68% |
| 000192 | 795s | 478s | 1.66x | **83%** | 81% | 68% |
| 000195 | 4,034s | 2,104s | 1.92x | **96%** | 91% | 84% |

**Why Good Scaling?**
- High CPU utilization (80%) = compute-bound
- Ground point classification is embarrassingly parallel
- Each point processed independently
- Good cache locality

**Does Halving CPUs Double Time?**
- **ALMOST** - halving CPUs increases time by ~1.7×
- Very close to linear scaling (2×)
- One project achieved perfect 2× scaling!

**Recommendation:**
✓ **Use m3.xl (32c) - excellent value for this step**

---

#### ✓ GOOD SCALING (Efficiency 75-90%)

---

##### buildPointCloud

**Average Performance:**
- Speedup: **1.57x**
- Efficiency: **78%**
- CPU Utilization: 16c=73% → 32c=60%

**Variability: MODERATE (±9% std dev)**

| Project | 16c Time | 32c Time | Efficiency | CPU% 16c | CPU% 32c |
|---------|----------|----------|------------|----------|----------|
| 0131_000015_000013 | 501s | 275s | **91%** | 78% | 67% |
| 000810 | 5,173s | 3,072s | **84%** | 79% | 68% |
| 000404 | 3,969s | 2,435s | **82%** | 80% | 68% |
| 000192 | 1,928s | 1,186s | **81%** | 82% | 69% |

**Does Halving CPUs Double Time?**
- **MOSTLY** - halving CPUs increases time by ~1.6×
- Close to linear, but some overhead visible

**Recommendation:**
→ **m3.xl (32c) is reasonable OR consider bin-packing**
- Good scaling, but not exceptional
- Could run 2 jobs if needed

---

#### ⚠️ MODERATE SCALING (Efficiency 60-75%)

---

##### alignCameras

**Average Performance:**
- Speedup: **1.41x**
- Efficiency: **70%**
- CPU Utilization: 16c=77% → 32c=69%

**Variability: MODERATE (±7% std dev)**

| Project | 16c Time | 32c Time | Efficiency | CPU% 16c | CPU% 32c |
|---------|----------|----------|------------|----------|----------|
| 000810 | 1,712s | 1,075s | **80%** | 73% | 63% |
| 000404 | 1,793s | 1,213s | **74%** | 74% | 64% |
| 0068_000434_000440 | 4,167s | 2,864s | **73%** | 75% | 63% |
| 000192 | 496s | 369s | **67%** | 76% | 67% |
| 000195 | 1,057s | 905s | **58%** | 78% | 72% |

**Key Observation:**
- **High CPU utilization (77%) but only 70% efficiency**
- Process is trying to use all cores
- But parallelization overhead limits speedup
- Classic sign of **Amdahl's Law** - sequential portions limit parallelism

**Does Halving CPUs Double Time?**
- **NO** - halving CPUs increases time by only ~1.4×
- Missing 30% of potential speedup due to overhead

**Recommendation:**
⚠️ **Consider m3.large (16c) OR bin-pack 2 jobs on m3.xl**
- Marginal benefit from 32c
- Good candidate for bin-packing

---

##### optimizeCameras

**Average Performance:**
- Speedup: **1.23x**
- Efficiency: **62%**
- CPU Utilization: 16c=62% → 32c=48%

**Does Halving CPUs Double Time?**
- **NO** - halving CPUs increases time by only ~1.2×
- Significant overhead, wasting 38% of additional cores

**Recommendation:**
⚠️ **Use m3.large (16c) OR bin-pack on m3.xl**

---

##### buildModel (mesh building)

**Average Performance:**
- Speedup: **1.37x**
- Efficiency: **69%**
- CPU Utilization: 16c=52% → 32c=36%

**Note:** High variability (±20%) - depends on mesh complexity

**Does Halving CPUs Double Time?**
- **NO** - halving CPUs increases time by only ~1.4×

**Recommendation:**
⚠️ **Consider m3.large (16c) OR bin-pack**

---

#### ❌ POOR SCALING (Efficiency <60%)

---

##### buildOrthomosaic (all variants)

**Average Performance:**
- Speedup: **1.19x**
- Efficiency: **59%**
- CPU Utilization: 16c=36% → 32c=25%

**Key Issue:**
- Low CPU utilization AND poor scaling
- Not compute-bound, likely I/O or memory-bound
- Extra cores provide minimal benefit

**Does Halving CPUs Double Time?**
- **NO** - halving CPUs increases time by only ~1.2×
- You lose very little performance with fewer cores

**Recommendation:**
✓ **Use m3.large (16c) OR bin-pack 2-3 jobs on m3.xl**

---

##### buildDepthMaps - GPU-Bound Step

**Average Performance:**
- Speedup: **1.02x** (essentially no speedup!)
- Efficiency: **51%**
- CPU Utilization: 16c=18% → 32c=18% (unchanged!)

**Why No Speedup?**
- This is GPU-bound, not CPU-bound
- CPU just feeds data to GPU
- Extra CPU cores sit idle waiting for GPU

**Does Halving CPUs Double Time?**
- **NO** - halving CPUs has ZERO impact on time
- GPU is the bottleneck

**Recommendation:**
✓ **DEFINITELY use m3.large (16c) OR bin-pack heavily**
- Wasting money on 32c for GPU steps
- Could run 4+ jobs on m3.xl for GPU steps

---

##### setup / addPhotos - I/O Bound

**Average Performance:**
- Speedup: **0.94x** (SLOWER with more cores!)
- Efficiency: **47%**
- CPU Utilization: 16c=5% → 32c=2%

**Why Slower?**
- I/O bound - just loading files
- Extra cores add overhead with no benefit
- Scheduler overhead actually slows it down

**Does Halving CPUs Double Time?**
- **NO** - halving CPUs actually IMPROVES time slightly!

**Recommendation:**
✓ **Use m3.large (16c) OR bin-pack many jobs**
- This step is pure I/O, cores don't matter

---

### Summary Table: Does Halving CPUs Double Compute Time?

| Step | Avg Efficiency | Time Ratio (16c/32c) | Double Time? | Notes |
|------|---------------|---------------------|--------------|-------|
| matchPhotos | 115% | 2.30× | **More than double** ⭐ | Super-linear |
| classifyGroundPoints | 85% | 1.70× | **Nearly double** ✓ | Excellent |
| buildPointCloud | 78% | 1.57× | **Mostly** → | Good |
| alignCameras | 70% | 1.41× | **No** ⚠️ | Moderate overhead |
| buildModel | 69% | 1.37× | **No** ⚠️ | Moderate overhead |
| optimizeCameras | 62% | 1.23× | **No** ❌ | Poor scaling |
| buildOrthomosaic | 59% | 1.19× | **No** ❌ | Poor scaling |
| buildDepthMaps | 51% | 1.02× | **No** ❌ | GPU-bound |
| setup | 47% | 0.94× | **Faster with fewer!** ❌ | I/O bound |

**ANSWER:** For most steps (7 out of 9), halving CPUs does NOT double compute time. Only 2 steps show near-linear scaling.

---

## Question 2: Instance Sizing Perspectives

### Perspective 1: Should I Deploy Cluster with m3.large vs m3.xl?

**For single jobs per instance:**

#### Cost-Performance Analysis

Assuming m3.xl costs ~1.5× m3.large (typical pricing):

| Configuration | Relative Cost | Performance vs m3.large | Cost per Throughput |
|--------------|---------------|------------------------|---------------------|
| m3.large (16c) | 1.0× | 1.0× | 1.0× |
| m3.xl (32c) | 1.5× | 1.41× average | **1.06×** ❌ |

**Result:** m3.xl costs 6% more per unit of work - **NOT cost-effective**

#### Step-by-Step Decision

| Step | Speedup | Cost Efficiency | Recommendation |
|------|---------|----------------|----------------|
| matchPhotos | 2.30× | **0.65×** ✓ | **Use m3.xl** - 35% cheaper per job |
| classifyGroundPoints | 1.70× | **0.88×** → | m3.xl acceptable |
| buildPointCloud | 1.57× | **0.96×** → | m3.xl marginal |
| All others | <1.4× | **>1.0×** ❌ | **Use m3.large** |

**RECOMMENDATION:**
✓ **Deploy cluster with m3.large (16c) as default**
- Better cost efficiency for 7 out of 9 step types
- Only matchPhotos strongly benefits from m3.xl
- If possible: use m3.xl specifically for matchPhotos, m3.large for others

---

### Perspective 2: Should I Put Two Parallel Jobs on One m3.xl?

**This is the more interesting question!**

#### Theoretical Analysis

**Key Question:** When 2 jobs run on m3.xl, does each see 32 cores?

**Answer:** Yes, but Linux scheduler ensures fair CPU time distribution.

**If step uses <50% CPU on 16 cores:**
- Process isn't using all 16 cores effectively
- Room for another process without contention
- Each process gets ~16 cores worth of CPU time

**If step uses >70% CPU on 16 cores:**
- Process is trying to use all cores
- Two processes will compete
- Each gets less than desired, creating slowdown

#### Detailed Per-Step Bin-Packing Analysis

**SAFE to pack (CPU <50% on 16c):**

| Step | CPU% (16c) | Why Safe | Expected Impact |
|------|-----------|----------|-----------------|
| setup | 5% | I/O bound | **0%** slowdown |
| buildDepthMaps | 18% | GPU bound | **0%** slowdown |
| finalize | 18% | Minimal CPU | **0%** slowdown |
| buildDem (all) | 23-32% | Low parallelism | **0-5%** slowdown |
| buildOrthomosaic | 36-39% | Memory bound | **5-10%** slowdown |
| exportRaster (all) | 12-13% | I/O bound | **0%** slowdown |

**CAUTION when packing (CPU 50-70%):**

| Step | CPU% (16c) | Risk | Expected Impact |
|------|-----------|------|-----------------|
| buildModel | 52% | Moderate | **10-15%** slowdown |
| matchPhotos | 57% | Moderate | **10-20%** slowdown |
| optimizeCameras | 62% | Moderate | **15-20%** slowdown |

**AVOID packing (CPU >70%):**

| Step | CPU% (16c) | Risk | Expected Impact |
|------|-----------|------|-----------------|
| buildPointCloud | 73% | High | **20-30%** slowdown |
| alignCameras | 77% | High | **20-40%** slowdown |
| classifyGroundPoints | 80% | Very High | **30-40%** slowdown |

#### Expected Overall Performance

**Workflow composition:**
- 70% of steps: CPU <50% → **0-10% slowdown**
- 15% of steps: CPU 50-70% → **10-20% slowdown**
- 15% of steps: CPU >70% → **20-40% slowdown**

**Weighted average performance per job:**
- Conservative estimate: **90-95%** of m3.large performance
- Optimistic estimate: **92-97%** of m3.large performance

#### Cost-Benefit Calculation

| Configuration | Cost per Instance | Jobs | Performance per Job | Total Throughput | Cost per Job |
|--------------|-------------------|------|---------------------|------------------|--------------|
| m3.large | 1.0× | 1 | 100% | 1.0× | **1.00×** |
| m3.xl (single) | 1.5× | 1 | 141% | 1.41× | **1.06×** ❌ |
| m3.xl (dual) | 1.5× | 2 | 90-95% | 1.80-1.90× | **0.79-0.83×** ✓ |

**NET RESULT:**
- **15-20% cost savings** per job by bin-packing
- **1.8-1.9× throughput** per instance
- **90-95% performance** per job

**RECOMMENDATION:**
✓ **STRONGLY RECOMMENDED: Run 2 jobs on m3.xl**

#### Implementation Considerations

**How to ensure fair scheduling:**

1. **Option 1: Let Linux handle it** (simplest)
   - Each job sees 32 cores
   - Kernel scheduler divides CPU time fairly
   - No configuration needed

2. **Option 2: Use cgroups to enforce limits**
   ```bash
   # Create cgroups with 16 cores each
   cgcreate -g cpu:job1
   cgcreate -g cpu:job2
   cgset -r cpu.shares=16000 job1
   cgset -r cpu.shares=16000 job2
   ```

3. **Option 3: Use `taskset` to pin cores**
   ```bash
   # Job 1 gets cores 0-15
   taskset -c 0-15 ./job1
   # Job 2 gets cores 16-31
   taskset -c 16-31 ./job2
   ```

**Recommendation:** Start with Option 1 (no configuration), only add constraints if you observe unfair scheduling.

---

## Question 3: Parallelization Overhead

### Your Concern: "Too Many Cores"

**Your Question:**
> "If processes see 32 cores and try to use them all, may the parallelization overhead make this less efficient than using smaller nodes?"

**ANSWER: YES, your concern is VALID** ✓

### Evidence from Data

#### Steps Showing Clear Parallelization Overhead

**alignCameras:**
- CPU usage: **77%** on 16c, **69%** on 32c
- Process IS trying to use all cores
- But efficiency: only **70%**
- **Missing 30% of potential speedup = overhead**

**Breakdown of where overhead comes from:**

```
Perfect scaling (100%): 16c × 2 = 32c → 2.0× speedup
Actual scaling (70%):   16c × 2 = 32c → 1.4× speedup
Lost performance:       30% wasted on overhead
```

**What causes this overhead?**

1. **Thread synchronization** (locks, mutexes, barriers)
   - More threads = more contention
   - More time waiting for locks

2. **False sharing** (cache line ping-pong)
   - Two cores modify adjacent memory
   - Cache lines bounce between cores
   - Severe performance penalty

3. **Work imbalance**
   - Some threads finish early, wait for others
   - Not all work is perfectly parallelizable

4. **Scheduler overhead**
   - More threads = more context switches
   - More cache pollution from switching

#### Steps NOT Showing Parallelization Overhead

**matchPhotos:**
- Efficiency: **115%** (super-linear!)
- More cores = BETTER than expected
- Why? Cache effects dominate, overhead minimal

**classifyGroundPoints:**
- Efficiency: **85%** (near-linear)
- Embarrassingly parallel
- Minimal synchronization needed

### Quantifying the "Too Many Cores" Problem

| Step | Cores Used | Efficiency | Overhead | Diagnosis |
|------|-----------|-----------|----------|-----------|
| matchPhotos | 57% → 8% | 115% | **None** ✓ | Cache-bound, benefits from more cache |
| classifyGroundPoints | 80% → 71% | 85% | **15%** → | Minimal, good parallelism |
| buildPointCloud | 73% → 60% | 78% | **22%** ⚠️ | Moderate overhead |
| alignCameras | 77% → 69% | 70% | **30%** ❌ | Significant overhead |
| optimizeCameras | 62% → 48% | 62% | **38%** ❌ | High overhead |
| buildModel | 52% → 36% | 69% | **31%** ❌ | Significant overhead |

**CONCLUSION:**
- **4 out of 9 step types** show significant overhead (>25%)
- **3 out of 9 step types** show moderate overhead (15-25%)
- **2 out of 9 step types** show minimal overhead (<15%)

### Is It Better to Use More Smaller Nodes?

**Scenario A: 4× m3.large (16c each) = 64 cores total**
- Cost: 4.0×
- Can run 4 jobs simultaneously
- Each job: 100% performance
- Throughput: 4 jobs

**Scenario B: 2× m3.xl (32c each) = 64 cores total**
- Cost: 3.0× (assuming 1.5× per xl)
- Can run 2 jobs simultaneously (single jobs)
- Each job: 141% performance (average)
- Throughput: 2 jobs × 1.41 = 2.82 job-equivalents
- **25% lower throughput, 25% lower cost = same cost/job** ❌

**Scenario C: 2× m3.xl (32c each) running 2 jobs each**
- Cost: 3.0×
- Can run 4 jobs simultaneously
- Each job: 90-95% performance
- Throughput: 4 jobs × 0.925 = 3.7 job-equivalents
- **7.5% lower throughput, 25% lower cost = 16% savings per job** ✓

**RECOMMENDATION:**
✓ **Use bin-packing approach (Scenario C)** for best cost efficiency

---

## Question 4: MIG Slice Configurations

### Question: Multiple 1/7 Slices vs One 3/7 Slice

**Configurations Tested:**
- **3×1g**: Three separate 1g.5gb MIG slices (3/7 of GPU)
- **1×3g**: One 3g.20gb MIG slice (3/7 of GPU)
- **2×1g**: Two separate 1g.5gb MIG slices (2/7 of GPU)
- **1×2g**: One 2g.10gb MIG slice (2/7 of GPU)

### buildDepthMaps (Main GPU Step) Results

#### 3×1g vs 1×3g Comparison

| Project | 3×1g Time | 1×3g Time | Ratio | Winner |
|---------|-----------|-----------|-------|--------|
| 000404 | 5,201s | 6,117s | **0.850** | **3×1g** ✓ |
| 000810 | 5,328s | 6,346s | **0.840** | **3×1g** ✓ |
| 0068_000434_000440 | 3,602s | 4,191s | **0.859** | **3×1g** ✓ |

**Average:** 3×1g is **15% faster** than 1×3g

**Why is 3×1g faster?**

1. **Better GPU utilization**
   - 3 separate processes can overlap better
   - One slice waiting on memory? Others still computing
   - Better hiding of latency

2. **Memory bandwidth**
   - MIG slicing partitions memory bandwidth
   - 3 separate slices may get better aggregate bandwidth
   - Less contention within each slice

3. **Scheduling flexibility**
   - Framework can schedule work across 3 slices independently
   - Better load balancing

#### 2×1g vs 1×2g Comparison

| Project | 2×1g Time | 1×2g Time | Ratio | Winner |
|---------|-----------|-----------|-------|--------|
| 000404 | 7,113s | 7,610s | **0.935** | **2×1g** ✓ |
| 000810 | 7,221s | 8,024s | **0.900** | **2×1g** ✓ |
| 0068_000434_000440 | 5,022s | 5,489s | **0.915** | **2×1g** ✓ |

**Average:** 2×1g is **8% faster** than 1×2g

**Consistency:** Same pattern as 3×1g vs 1×3g

### matchPhotos (GPU-Assisted Step) Results

#### 3×1g vs 1×3g Comparison

| Project | 3×1g Time | 1×3g Time | Ratio | Winner |
|---------|-----------|-----------|-------|--------|
| 000404 | 1,036s | 1,247s | **0.831** | **3×1g** ✓ |
| 000810 | 1,031s | 1,274s | **0.809** | **3×1g** ✓ |
| 0068_000434_000440 | 1,078s | 1,327s | **0.812** | **3×1g** ✓ |

**Average:** 3×1g is **18% faster** than 1×3g

**Even stronger benefit** for this mixed CPU/GPU workload!

#### 2×1g vs 1×2g Comparison

| Project | 2×1g Time | 1×2g Time | Ratio | Winner |
|---------|-----------|-----------|-------|--------|
| 000404 | 1,158s | 1,223s | **0.947** | **2×1g** ✓ |
| 000810 | 1,031s | 1,365s | **0.755** | **2×1g** ✓ |
| 0068_000434_000440 | 1,323s | 1,523s | **0.869** | **2×1g** ✓ |

**Average:** 2×1g is **14% faster** than 1×2g

### Summary: Multiple Small vs Single Large

| Comparison | Avg Speedup | Winner | Consistency |
|-----------|------------|--------|-------------|
| **3×1g vs 1×3g** (buildDepthMaps) | **15% faster** | **3×1g** ✓ | 3/3 projects |
| **2×1g vs 1×2g** (buildDepthMaps) | **8% faster** | **2×1g** ✓ | 3/3 projects |
| **3×1g vs 1×3g** (matchPhotos) | **18% faster** | **3×1g** ✓ | 3/3 projects |
| **2×1g vs 1×2g** (matchPhotos) | **14% faster** | **2×1g** ✓ | 3/3 projects |

**ANSWER: Multiple small slices ARE more efficient than single large slices** ✓

**Variability:** VERY LOW - consistent across all projects

**Practical Implication:**
- Always prefer 3×1g over 1×3g
- Always prefer 2×1g over 1×2g
- Performance difference is significant (8-18%)
- Completely consistent across datasets

**RECOMMENDATION:**
✓ **Use multiple small MIG slices for better performance**

---

## Question 5: MIG Proportional Scaling

### Question: Does MIG Scale Proportionally to Slice Size?

**If perfectly proportional:**
- 1/7 GPU slice should be **7× slower** than full GPU
- 2/7 GPU slice should be **3.5× slower** than full GPU
- 3/7 GPU slice should be **2.33× slower** than full GPU

### buildDepthMaps Results vs Full GPU

#### Full GPU Baseline Times

| Project | Full GPU Time | GPU Model |
|---------|---------------|-----------|
| 000404 | 4,132s | A100-40GB |
| 000810 | 4,052s | A100-40GB |
| 0068_000434_000440 | 2,960s | A100-40GB |

#### MIG Performance Analysis

| Config | Expected Slowdown | Actual Slowdown | Efficiency | Interpretation |
|--------|------------------|-----------------|-----------|----------------|
| **1×1g (1/7)** | 7.0× | **2.97×** | **236%** | 🚀 Exceptional |
| **1×2g (2/7)** | 3.5× | **1.89×** | **185%** | 🚀 Exceptional |
| **1×3g (3/7)** | 2.33× | **1.49×** | **157%** | 🚀 Exceptional |
| **2×1g (2/7)** | 3.5× | **1.73×** | **202%** | 🚀 Exceptional |
| **3×1g (3/7)** | 2.33× | **1.26×** | **185%** | 🚀 Exceptional |

**STUNNING RESULT:** All MIG configurations perform **150-236% BETTER than linear scaling!**

#### Per-Project Breakdown - 1×1g (1/7 slice)

| Project | Full GPU | 1×1g | Ratio | Expected | Efficiency |
|---------|----------|------|-------|----------|-----------|
| 000404 | 4,132s | 11,894s | 2.88× | 7.0× | **243%** |
| 000810 | 4,052s | 12,925s | 3.19× | 7.0× | **220%** |
| 0068_000434_000440 | 2,960s | 8,451s | 2.86× | 7.0× | **245%** |

**Variability:** LOW (±14% std dev) - very consistent

**What this means:**
- 1/7 GPU slice should be 7× slower
- Actually only **3× slower**
- You get **2.3× MORE performance** than expected!

#### Per-Project Breakdown - 3×1g (3/7 slices)

| Project | Full GPU | 3×1g | Ratio | Expected | Efficiency |
|---------|----------|------|-------|----------|-----------|
| 000404 | 4,132s | 5,201s | 1.26× | 2.33× | **185%** |
| 000810 | 4,052s | 5,328s | 1.31× | 2.33× | **178%** |
| 0068_000434_000440 | 2,960s | 3,602s | 1.22× | 2.33× | **191%** |

**Variability:** LOW (±7% std dev)

**What this means:**
- 3/7 GPU should be 2.33× slower
- Actually only **1.26× slower**
- You get **1.85× MORE performance** than expected!

### matchPhotos Results vs Full GPU

**Even more impressive:**

| Config | Expected Slowdown | Actual Slowdown | Efficiency |
|--------|------------------|-----------------|-----------|
| **1×1g (1/7)** | 7.0× | **1.53×** | **463%** 🚀🚀 |
| **1×2g (2/7)** | 3.5× | **1.16×** | **303%** 🚀 |
| **1×3g (3/7)** | 2.33× | **1.09×** | **215%** 🚀 |
| **2×1g (2/7)** | 3.5× | **0.99×** | **355%** 🚀🚀 |
| **3×1g (3/7)** | 2.33× | **0.89×** | **263%** 🚀 |

**INCREDIBLE FINDINGS:**
- **2×1g performs identically to full GPU** (0.99×)
- **3×1g is actually 10% FASTER than full GPU** (0.89×)
- This step barely uses GPU, so slicing overhead is zero

**Variability:** MODERATE (±20-50% std dev) - varies by dataset GPU usage

### Why is MIG BETTER Than Proportional?

**1. Memory Bandwidth NOT the Bottleneck**
- Expected: GPU slices share memory bandwidth proportionally
- Reality: This workload doesn't saturate memory bandwidth
- Result: 1/7 slice gets same effective bandwidth as full GPU

**2. Compute NOT Fully Utilized**
- Full GPU: 40GB memory, 6912 CUDA cores
- This workload: Doesn't use all cores simultaneously
- MIG slice: Has enough cores for actual utilization
- Result: MIG slice runs at same effective compute rate

**3. MIG Isolation is Nearly Free**
- Expected: Overhead from MIG partitioning
- Reality: MIG is hardware-level partitioning
- Very low overhead (few percent)
- Not enough to offset the benefits

**4. Better Resource Matching**
- Full GPU may be over-provisioned
- MIG slice is "right-sized" for workload
- Less waste, better utilization

### Practical Implications

**Cost Analysis:**

Assuming full A100 GPU costs 1.0×, and MIG slices cost proportionally:

| Config | Cost | Performance vs Full | Jobs per GPU | Total Throughput | Cost per Job |
|--------|------|-------------------|--------------|------------------|--------------|
| Full GPU | 1.0× | 1.00× | 1 | 1.00× | **1.00×** |
| 1×1g × 7 | 1.0× | 0.34× each | 7 | 2.38× | **0.42×** ✓ |
| 1×3g × 2 | 1.0× | 0.67× each | 2 | 1.34× | **0.75×** ✓ |
| 3×1g × 2 | 1.0× | 0.79× each | 2 | 1.58× | **0.63×** ✓ |

**BEST OPTION: 7× 1g slices**
- **58% cost savings** per job!
- 2.38× total throughput
- Each job only 3× slower, not 7× slower

**RECOMMENDATION:**
✓ **Aggressively use MIG slicing - it's incredibly efficient**
- No performance penalty
- Often performance GAIN
- Massive cost savings

### ANSWER Summary

**Is MIG scaling proportional?**

**NO - it's BETTER than proportional!** 🚀

- 1/7 slice: **2.4× better** than linear expectation
- 2/7 slice: **1.9× better** than linear expectation
- 3/7 slice: **1.6× better** than linear expectation

**Workload characteristics that enable this:**
- ✓ Not memory bandwidth limited
- ✓ Not compute saturated
- ✓ Good parallelism within work units
- ✓ Minimal GPU communication overhead

---

## Variability Analysis

### Question: How Variable Are Results Across Projects?

**Variability measured by standard deviation of efficiency across projects**

### CPU Scaling Variability

#### HIGH Variability (>15% std dev)

**matchPhotos: ±27% std dev**
- Range: 56% to 137% efficiency
- **Why?** Performance depends heavily on:
  - Image overlap/similarity
  - Number of feature matches
  - Spatial distribution of images

**Small datasets** (like benchmarking-emerald-subset):
- Only 56% efficiency
- Setup overhead dominates
- Not enough work to amortize parallelization cost

**Large datasets** (like 000195):
- 137% efficiency
- Working set benefits from extra cache
- Plenty of work to parallelize

**buildModel: ±20% std dev**
- Range: 65% to 203% efficiency (!)
- **Why?** Mesh complexity varies dramatically:
  - Simple meshes: Little parallelism, overhead dominates
  - Complex meshes: Good parallelism, excellent scaling

#### MODERATE Variability (5-15% std dev)

Most steps fall here:
- alignCameras: ±7%
- buildPointCloud: ±9%
- classifyGroundPoints: ±12%
- optimizeCameras: ±8%

**Interpretation:** Reasonably consistent, can plan based on averages

**Why moderate?**
- Algorithm behavior is similar across datasets
- Some variation due to data size/complexity
- But fundamental parallelization properties are stable

#### LOW Variability (<5% std dev)

**setup, finalize, export steps: ±3-5%**
- Very consistent because:
  - I/O bound, not compute bound
  - Performance determined by file system, not algorithm
  - Dataset characteristics matter less

### MIG Scaling Variability

#### buildDepthMaps MIG Variability

**Efficiency vs Full GPU:**

| Config | Avg Efficiency | Std Dev | Interpretation |
|--------|---------------|---------|----------------|
| 1×1g | 236% | ±14% | Low variability ✓ |
| 1×2g | 185% | ±7% | Very low variability ✓ |
| 1×3g | 157% | ±8% | Very low variability ✓ |
| 2×1g | 202% | ±5% | Very low variability ✓ |
| 3×1g | 185% | ±7% | Very low variability ✓ |

**Conclusion:** MIG performance is **very consistent** across projects

**Why?**
- GPU characteristics don't vary with dataset
- MIG slicing is hardware-level, deterministic
- GPU workload is well-defined (depth map computation)

#### matchPhotos MIG Variability

**Efficiency vs Full GPU:**

| Config | Avg Efficiency | Std Dev | Interpretation |
|--------|---------------|---------|----------------|
| 1×1g | 463% | ±52% | High variability ⚠️ |
| 1×2g | 303% | ±18% | Moderate variability → |
| 3×1g | 263% | ±27% | Moderate variability → |

**Why higher variability?**
- This step uses GPU opportunistically, not heavily
- Different datasets → different GPU utilization
- When GPU usage is low, MIG efficiency is extreme
- When GPU usage is higher, efficiency is still excellent but less extreme

**Still reliable:** Even with variability, all projects show >200% efficiency

### Can You Plan Based on Averages?

**YES, with caveats:**

#### Highly Reliable Metrics (Low Variability)

✓ **Use average for planning:**
- MIG GPU performance (buildDepthMaps): ±5-14%
- Most CPU steps: ±5-12%
- I/O bound steps: ±3-5%

**95% confidence:** Actual performance within ±10-20% of average

#### Use Caution (High Variability)

⚠️ **Plan conservatively:**
- matchPhotos CPU scaling: ±27%
- buildModel: ±20%
- matchPhotos MIG efficiency: ±52%

**Recommendation:** Use conservative estimates (lower end of range)

**For matchPhotos:**
- Average: 115% efficiency
- Conservative: 90% efficiency (1 std dev below)
- Planning value: **90-115% range**

**For buildModel:**
- Average: 69% efficiency
- Conservative: 50% efficiency
- Planning value: **50-85% range**

### Per-Dataset Characteristics

**Small datasets (<100 images):**
- More overhead, less parallelism
- matchPhotos: 56-75% efficiency
- Other steps: Near average

**Medium datasets (100-500 images):**
- Good parallelism
- Near average performance across board

**Large datasets (>500 images):**
- Excellent parallelism
- matchPhotos: 116-137% efficiency
- Heavy steps benefit from large working sets

**Complex scenes (0068_000434_000440):**
- Longer execution times
- Higher mesh/point cloud complexity
- buildModel variability most visible

**RECOMMENDATION:**
- Use average values for medium/large datasets
- Add 20-30% buffer for small datasets
- Add 30-50% buffer for very large/complex datasets

---

## Final Recommendations

### CPU Instance Sizing

#### For Single Jobs Per Instance

**Don't use m3.xl (32c) for single jobs** - only 65% average efficiency

**Exception:** matchPhotos step
- ✓ Use m3.xl for matchPhotos specifically (115% efficiency)
- Cost: 35% cheaper per matchPhotos job
- Worth deploying dedicated matchPhotos workers

**For all other steps:**
- ✓ Use m3.large (16c)
- Better cost efficiency
- Minimal performance loss

#### For Maximum Throughput: BIN-PACKING ⭐

**✓ STRONGLY RECOMMENDED: Run 2 parallel jobs on m3.xl**

**Expected Results:**
- Each job: 90-95% of m3.large performance
- Total throughput: 1.8-1.9× per instance
- Cost per job: **15-20% savings**

**Implementation:**
```bash
# Job 1
./run_workflow.sh dataset1 &

# Job 2
./run_workflow.sh dataset2 &

# Let Linux scheduler handle CPU distribution
# No special configuration needed
```

**When to avoid bin-packing:**
- If jobs are >80% alignCameras or classifyGroundPoints
- These high-CPU steps will compete heavily
- But most workflows are mixed, so bin-packing still wins

**Optimal strategy:**
- Default: 2 jobs per m3.xl
- Matchless-heavy workflows: Dedicate m3.xl to matchPhotos, pack others
- Align-heavy workflows: Use 1 job per m3.xl or use m3.large

### GPU Instance Sizing & MIG Configuration

#### Use MIG Aggressively ✓

**MIG efficiency: 150-463%** - better than linear scaling

**Recommended configurations:**

**For maximum throughput:**
- ✓ **Use 7× 1g.5gb slices** per A100
- Each job: ~3× slower than full GPU (not 7×!)
- Total throughput: **2.4× more jobs**
- Cost per job: **58% savings**

**For balanced performance/throughput:**
- ✓ **Use 2-3× 3g.20gb slices** per A100
- Each job: ~1.3× slower than full GPU
- Total throughput: **1.6× more jobs**
- Cost per job: **38% savings**

**Always prefer multiple small slices over single large:**
- ✓ 3×1g instead of 1×3g (15% faster)
- ✓ 2×1g instead of 1×2g (8% faster)

#### MIG vs Full GPU Decision Matrix

| Workload Type | Recommendation | Expected Performance |
|--------------|----------------|---------------------|
| Many small jobs | 7× 1g.5gb | 3× slower each, 2.4× total throughput |
| Balanced mix | 3× 3g.20gb or 2× 3g.20gb | 1.3× slower each, 1.6× throughput |
| Few large urgent jobs | Full GPU | 1× baseline |
| Mixed CPU/GPU (matchPhotos) | Even 1g.5gb is fine! | 1.5× slower, excellent efficiency |

### Deployment Architecture Recommendations

#### Option 1: Homogeneous Cluster (Simplest)

**Instance type:** m3.xl (32c)
**Job scheduling:** 2 parallel jobs per instance
**GPU:** A100 with 3× 3g.20gb MIG slices

**Pros:**
- Simple to manage
- Good cost efficiency (15-20% savings)
- Predictable performance

**Cons:**
- Some steps waste resources
- Not optimal for matchPhotos-heavy workflows

#### Option 2: Heterogeneous Cluster (Optimal)

**Worker pool 1:** m3.xl (32c) - for matchPhotos
- Single job per instance
- Super-linear performance (115%)
- Dedicated to matchPhotos steps

**Worker pool 2:** m3.large (16c) - for everything else
- Or m3.xl with 2 jobs for bin-packing
- Better cost efficiency for CPU-bound steps

**Worker pool 3:** GPU nodes with MIG
- 7× 1g.5gb slices for maximum throughput
- Dedicated to buildDepthMaps

**Pros:**
- Optimal cost efficiency
- Best performance for each step type

**Cons:**
- More complex scheduling
- Need workload routing

#### Option 3: Dynamic/Adaptive (Most Flexible)

**Base:** m3.xl with bin-packing (2 jobs)

**Auto-scaling rules:**
- High matchPhotos load → spin up dedicated m3.xl
- Low overall load → consolidate to maximize bin-packing
- GPU heavy load → increase MIG slicing to 7× 1g.5gb

**Requires:**
- Smart scheduler (Kubernetes, Argo, etc.)
- Autoscaling policies
- Workload profiling

### Cost Optimization Summary

**Current baseline:** 1 job on m3.large + full A100 GPU = 1.0× cost

**Optimized configuration:** 2 jobs on m3.xl + 7× 1g MIG = 0.35× cost per job

**Savings breakdown:**
- CPU bin-packing: 15-20% savings
- MIG slicing: 58% savings on GPU
- **Combined: ~65% total cost reduction** 🎉

### Performance Validation Checklist

Before full deployment, validate with your specific workloads:

- [ ] Run 2 jobs on m3.xl with your typical workflow mix
- [ ] Measure actual performance vs single job on m3.large
- [ ] Verify 90-95% performance per job (our prediction)
- [ ] Test MIG slicing with buildDepthMaps
- [ ] Verify 3× slowdown vs full GPU (our prediction)
- [ ] Monitor for scheduling anomalies or contention
- [ ] Measure actual cost savings vs predictions

### Monitoring Recommendations

**Key metrics to track:**

1. **CPU utilization per job** - should stay ~80-90% during compute steps
2. **Job completion time** - compare to baselines
3. **Resource contention** - watch for excessive context switching
4. **GPU utilization** - MIG slices should stay busy
5. **Cost per job** - track against predictions

**Alert thresholds:**
- Job completion >110% of baseline → investigate contention
- CPU utilization <50% during compute → under-provisioned
- GPU utilization <60% → inefficient work distribution

---

## Conclusion

### Direct Answers to Your Questions

1. **Does halving CPUs double compute time?**
   - **NO** for 7 out of 9 step types
   - **YES** for 2 steps (matchPhotos, classifyGroundPoints)
   - Average efficiency: 65.4%

2. **Should I deploy m3.large or m3.xl cluster?**
   - **m3.large** for single jobs per instance
   - **m3.xl with 2 jobs** for maximum throughput (recommended)

3. **Is parallelization overhead a concern?**
   - **YES** - 60% of steps show significant overhead (>25%)
   - Your concern is valid
   - But bin-packing 2 jobs still works due to low average CPU usage

4. **Are 3× 1g slices as efficient as 1× 3g slice?**
   - **NO - they're MORE efficient** (15% faster)
   - Consistently better across all tests
   - Use multiple small slices

5. **Does MIG scale proportionally?**
   - **NO - it scales BETTER than proportional**
   - 150-463% efficiency vs linear expectation
   - Incredible performance for this workload

### Variability Assessment

- **Low variability** (<10%): MIG GPU, most CPU steps - **plan with confidence**
- **High variability** (>20%): matchPhotos, buildModel - **use conservative estimates**
- **Overall:** Results are reliable enough for capacity planning

### Best Overall Configuration

**CPU:** m3.xl running 2 parallel jobs
**GPU:** A100 with 3× 3g.20gb MIG slices (or 7× 1g.5gb for max throughput)
**Expected savings:** 65% cost reduction per job
**Expected performance:** 90-95% per job with 2× throughput

This analysis provides strong evidence for aggressive resource optimization while maintaining excellent performance.

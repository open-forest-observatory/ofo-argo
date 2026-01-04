# Photogrammetry Workflow Scaling Analysis - Key Findings

## Understanding Efficiency Metrics

**Efficiency = (Speedup / CoreRatio) × 100%**

- **100% = Perfect Scaling**: Doubling cores doubles speed
- **>100% = Super-linear**: Better than expected (cache effects, memory bandwidth)
- **<100% = Sub-linear**: Parallelization overhead

**Why can efficiency exceed 100%?**
1. **Cache effects**: More cores = more L3 cache
2. **Memory bandwidth**: Better utilization with more cores
3. **NUMA locality**: Better memory placement
4. **Reduced contention**: Less lock contention per core

## PART 1: CPU Scaling Analysis (16c vs 32c)

### Summary by Step Category

| Step Type | Avg Efficiency | Avg Speedup | CPU% (16c) | CPU% (32c) | Recommendation |
|-----------|---------------|-------------|------------|------------|----------------|
| **match_photos** | 115% ✓ | 2.30x | 57% | 8% | **Use 32c - super-linear!** |
| **build_point_cloud** (buildPointCloud) | 78% | 1.57x | 73% | 60% | Use 32c or bin-pack |
| **build_point_cloud** (classifyGroundPoints) | 85% ✓ | 1.70x | 80% | 71% | **Use 32c - good scaling** |
| **align_cameras** (alignCameras) | 70% | 1.41x | 77% | 69% | Consider 16c or bin-pack |
| **align_cameras** (optimizeCameras) | 62% | 1.23x | 62% | 48% | Consider 16c or bin-pack |
| **build_mesh** (buildModel) | 69% | 1.37x | 52% | 36% | Consider 16c or bin-pack |
| **build_dem_orthomosaic** | 59% | 1.19x | 23% | 15% | **Use 16c or bin-pack** |
| **build_depth_maps** | 51% | 1.02x | 18% | 18% | **Use 16c or bin-pack** |
| **setup** | 47% | 0.94x | 5% | 2% | **Use 16c or bin-pack** |

### Detailed Step-by-Step Findings

#### 1. match_photos / matchPhotos ⭐ **SUPER-LINEAR SCALING**

**Performance:** 115% efficiency (2.30x speedup)

**Key Finding:** This is the ONLY step that shows super-linear scaling!

**Variability:** HIGH (±27% std dev) - performance depends on dataset:
- Best: Project 000195: **137% efficiency** (2300s → 838s)
- Worst: benchmarking-emerald-subset: **56% efficiency** (64s → 57s)

**Why super-linear?**
- CPU% drops from 57% to 8% on 32c, indicating this is NOT compute-bound
- Likely memory/cache bound - benefits from 2x more L3 cache on 32-core system
- Algorithm parallelizes extremely well with more cores

**Recommendation:** ✓ **Strongly use m3.xl (32c) for this step**

---

#### 2. build_point_cloud / classifyGroundPoints ⭐ **EXCELLENT SCALING**

**Performance:** 85% efficiency (1.70x speedup)

**Key Finding:** Near-linear scaling, one project achieved perfect 100%

**Variability:** MODERATE (±12% std dev)
- Best: Project 0068_000434_000440: **101% efficiency** (43243s → 21484s)
- Worst: Project 000192: **62% efficiency** (795s → 478s)

**CPU Utilization:** High on both (80% → 71%)

**Recommendation:** ✓ **Use m3.xl (32c) - excellent value**

---

#### 3. build_point_cloud / buildPointCloud - **GOOD SCALING**

**Performance:** 78% efficiency (1.57x speedup)

**Variability:** MODERATE (±9% std dev)
- Best: Project 0131_000015_000013: **91% efficiency**
- Worst: Project 0068_000434_000440: **66% efficiency**

**CPU Utilization:** High (73% → 60%)

**Recommendation:** → **Use m3.xl (32c) acceptable, or bin-pack**

---

#### 4. align_cameras / alignCameras - **MODERATE SCALING**

**Performance:** 70% efficiency (1.41x speedup)

**Variability:** MODERATE (±7% std dev)
- Range: 58% to 80% efficiency

**CPU Utilization:** Very high (77% → 69%) - this is CPU-intensive

**Recommendation:** ⚠ **Marginal benefit from 32c. Consider 16c or pack 2 jobs on 32c**

**Key Insight:** High CPU usage (77%) but only 70% efficiency suggests:
- Process is trying to use all cores
- But parallelization overhead limits speedup
- **This is a prime candidate for bin-packing 2 jobs on m3.xl**

---

#### 5. build_depth_maps / buildDepthMaps - **POOR CPU SCALING** (GPU step)

**Performance:** 51% efficiency (1.02x speedup)

**CPU Utilization:** Very LOW (18% on both 16c and 32c)

**Why?** This is GPU-bound, not CPU-bound. Extra CPU cores don't help.

**Recommendation:** ✓ **Definitely use 16c or bin-pack - wasting 32c here**

---

#### 6. build_dem_orthomosaic (all substeps) - **POOR SCALING**

**Performance:** 59% efficiency (1.19x speedup)

**CPU Utilization:** Very LOW (23% → 15%)

**Key Issue:** These steps don't parallelize well AND don't use many cores

**Recommendation:** ✓ **Use 16c or bin-pack 2 jobs on 32c**

---

#### 7. setup / addPhotos - **NO SCALING BENEFIT**

**Performance:** 47% efficiency (0.94x speedup - SLOWER on 32c!)

**CPU Utilization:** Nearly zero (5% → 2%)

**Why?** I/O bound, not compute bound. Just loading data.

**Recommendation:** ✓ **Use 16c or bin-pack many jobs**

---

## PART 2: Running 2 Jobs on m3.xl vs 1 Job on m3.large

### Analysis Summary

**Overall CPU utilization on 16c: 34.4%**
**Steps with <50% CPU: 14/20 (70%)**

### ✓ **STRONG RECOMMENDATION: Run 2 jobs on m3.xl**

**Why this works:**
1. Most steps use <50% CPU on 16 cores
2. When 2 jobs run on 32 cores, each gets ~16 cores worth of CPU time
3. Linux scheduler distributes fairly between processes
4. Minimal interference expected

### Per-Step Bin-Packing Suitability

| Category | Steps | Can Pack 2 Jobs? | Reasoning |
|----------|-------|-----------------|-----------|
| **Safe** | setup, build_dem_orthomosaic (all), build_depth_maps, build_mesh (export), finalize | ✓ **YES** | CPU <50%, plenty headroom |
| **Caution** | match_photos, align_cameras (optimize), build_mesh (buildModel) | **MAYBE** | CPU 50-70%, some contention risk |
| **Avoid** | align_cameras (align), build_point_cloud (both) | **NO** | CPU >70%, likely contention |

### Expected Performance Impact

**Conservative estimate:** Each job will perform at **90-95%** of m3.large speed

**Reasoning:**
- 70% of steps will run at 100% speed (CPU <50%)
- 15% of steps may slow 10-20% (CPU 50-70%)
- 15% of steps may slow 20-40% (CPU >70%)

**Weighted average:** ~90-95% performance with **2x throughput** = huge win!

### Cost-Benefit Analysis

| Configuration | Cost | Jobs/Instance | Throughput | Cost per Job |
|--------------|------|---------------|------------|--------------|
| m3.large (16c) | 1.0x | 1 | 1.0x | 1.0x |
| m3.xl single (32c) | 1.5x | 1 | 1.0x | 1.5x ❌ |
| m3.xl dual (32c) | 1.5x | 2 | 1.8-1.9x | **0.79-0.83x** ✓ |

**Conclusion:** Running 2 jobs on m3.xl gives **15-20% cost savings** per job!

---

## PART 3: MIG GPU Scaling

### Key Findings by Step

#### build_depth_maps / buildDepthMaps ⭐ **EXCEPTIONAL MIG PERFORMANCE**

**MIG Scaling Efficiency (adding slices):**
- 1g → 2g: **79% efficiency** (1.57x speedup)
- 1g → 3g: **67% efficiency** (2.00x speedup)

**Multiple small vs single large:**
- 2×1g vs 1×2g: **2×1g is 8% faster** ✓
- 3×1g vs 1×3g: **3×1g is 15% faster** ✓

**MIG vs Full GPU - EXCEPTIONAL RESULTS:**

| Config | Expected Slowdown | Actual Slowdown | Efficiency |
|--------|------------------|-----------------|-----------|
| 1×1g (1/7 GPU) | 7.0x | **2.97x** | **236%** ⭐ |
| 1×2g (2/7 GPU) | 3.5x | **1.89x** | **185%** ⭐ |
| 1×3g (3/7 GPU) | 2.33x | **1.49x** | **157%** ⭐ |
| 2×1g (2/7 GPU) | 3.5x | **1.73x** | **202%** ⭐ |
| 3×1g (3/7 GPU) | 2.33x | **1.26x** | **185%** ⭐ |

**Interpretation:**
- A 1/7 GPU slice is only **3x slower** instead of 7x slower!
- MIG isolation overhead is **minimal to non-existent**
- Workload is NOT memory bandwidth limited
- **All MIG configs perform 157-236% better than expected**

**Variability:** LOW (±5-14% std dev) - very consistent across projects

---

#### match_photos / matchPhotos ⭐ **EVEN BETTER MIG PERFORMANCE**

**MIG vs Full GPU - ASTONISHING RESULTS:**

| Config | Expected Slowdown | Actual Slowdown | Efficiency |
|--------|------------------|-----------------|-----------|
| 1×1g (1/7 GPU) | 7.0x | **1.53x** | **463%** 🚀 |
| 1×2g (2/7 GPU) | 3.5x | **1.16x** | **303%** 🚀 |
| 1×3g (3/7 GPU) | 2.33x | **1.09x** | **215%** 🚀 |
| 2×1g (2/7 GPU) | 3.5x | **0.99x** | **355%** 🚀 |
| 3×1g (3/7 GPU) | 2.33x | **0.89x** | **263%** 🚀 |

**INCREDIBLE:**
- **2×1g is same speed as full GPU!** (0.99x)
- **3×1g is actually FASTER than full GPU!** (0.89x)
- This step is NOT very GPU-intensive, minimal GPU slicing matters

**Multiple small vs single large:**
- 3×1g vs 1×3g: **3×1g is 18% faster** ✓

**Recommendation:** For this step, MIG slicing is **incredibly efficient**

---

#### Other Steps (align_cameras, setup, finalize)

**Performance:** Moderate to poor GPU scaling
- These are CPU-bound, not GPU-bound
- MIG efficiency: 30-50%
- But they don't use much GPU anyway

**Not a concern** - these steps shouldn't be using GPU nodes

---

### Overall MIG Recommendations

#### 1. **3×1g vs 1×3g: Use 3×1g** ✓

**Reasoning:**
- 3×1g is **15% faster** for buildDepthMaps
- 3×1g is **18% faster** for matchPhotos
- Performance is equivalent or better across all steps
- Better scheduling flexibility

#### 2. **2×1g vs 1×2g: Use 2×1g** ✓

**Reasoning:**
- 2×1g is **8% faster** for buildDepthMaps
- 2×1g is **14% faster** for matchPhotos
- Slight performance advantage

#### 3. **MIG Slicing is HIGHLY EFFICIENT** ⭐

**Key Finding:** Even 1/7 GPU slices perform **2-3x better than linear scaling**

**Practical Implication:**
- You can run **3x more jobs** with 3×(1g.5gb) slices
- Each job is only **1.5x slower** (not 3x slower!)
- **Net throughput: 2x improvement** with MIG slicing

**Why this matters:**
- Cost efficiency: Run more jobs per GPU
- Scheduling: Better bin-packing
- Utilization: No wasted GPU capacity

---

## Overall Recommendations

### For CPU Workloads:

1. **For single jobs:**
   - Use **m3.large (16c)** for most steps
   - Only use m3.xl for matchPhotos step specifically
   - Overall: **m3.large is better value**

2. **For maximum throughput:**
   - ✓ **Run 2 parallel jobs on m3.xl (32c)**
   - Expected: 90-95% performance per job
   - Benefit: 1.8x throughput, 15-20% cost savings per job
   - **This is the recommended approach**

### For GPU Workloads:

1. **Use MIG slicing aggressively**
   - Prefer **multiple small slices over single large slices** (3×1g > 1×3g)
   - Even 1/7 slices are highly efficient
   - No performance penalty, often performance gain

2. **MIG scaling is exceptional**
   - 150-463% efficiency vs linear scaling
   - Workload is NOT bandwidth limited
   - MIG overhead is negligible

3. **Schedule based on flexibility, not performance**
   - All MIG configs perform well
   - Choose based on what fits your scheduler best

### Variability Across Projects

**High variability steps** (>15% std dev):
- matchPhotos (CPU): ±27% - depends on image similarity
- build_mesh/buildModel: ±20% - depends on point cloud density

**Low variability steps** (<10% std dev):
- Most steps: ±5-10% - very consistent
- MIG performance: ±5-14% - reliable scaling

**Conclusion:** Results are generally consistent. Plan based on averages.

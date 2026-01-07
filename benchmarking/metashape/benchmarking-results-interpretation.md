***Need to check how many matchPhotos pods we could run on a m3.xl, since we could probably run 3
(or more) on one MIG GPU node -- also ask Claude if we can have one GPU node that can be scheuled on
as a full or partial depending on the need.




GPU benefits
Overall, on average:

- buildModel takes 86% of the time (biggest savings for intermeiate-sized projects)
- matchPhotos takes 56% of the time (51-60 across all 10 sample projects, except worse for smallest
  ones)

Therefore, for matchPhotos it is marginally cheaper per project, but slower, to use CPU instead of GPU (since GPU costs 2x per
minute), and potentially a good strategy when GPU nodes are scarce. Confirming this: I can fit 2-3
matchPhotos on a m3.xl. Can fit 3-4 matchPhotos on a g3.xl MIG. The g3 costs twice but runs a little
less than double the speed, so still cheaper to use CPU for matching.


GPU usage (%) (range is mean to 90th percentile for the project with the greatest usage) (mean
project slightly lower unless noted otherwise)

- buildDepthMaps: 60-99 (mean is 50-95)
- buildModel: 2-0 (meaning there is a brief period of very high GPU usage, maybe we could disable
  texturing to save this and not have to do it by CPU either -- actually no, this is not texturing,
  that is a separate step we don't use)
- matchPhotos: 16-84 (mean is 12-50)

*What is more efficient, two m3.large instances each with one process, or two processes on a m3.xl?

The efficiency loss (ratio of core-hours required on xl vs. large) between the two ranges 0.9 to 1.6 (mean 1.2). For the key
time-consuming steps, it is:

- alignCameras: 1.2
- buildModel: 1.6
- buildPointCloud: 1.1
- classifyGroundPoints: 0.9-1.0
- matchPhotos (cpu): 1.2
- buildOrtho: 1.3

These were all tested with ONE PROCESS runing on the xl node. When those used more than 16 cores
(half the node) (true for: alignCameras 30, buildModel 19, buildOrtho 18-19, buildPointCloud 25, classifyGroundPoints
30, matchPhotos 20, optimizeCameras 29), we'd expect reduction in efficiency when running two
processes on an xl (by estimated 10-30% based on the observed overage past 16 of these processes). And we'd
expect further reduction in efficiency (possibly around 10%) due to increased memory pressure. So
the average efficiency loss overall appears it would be 1.3 to 1.9, average of 1.6, or 60%
efficiency loss by putting two processes on an xl. This would make sense if we had plenty of compute
credits and just wanted to process as fast as possible. For paying twice as much, the run would take
~80% the time.


CPU requirements (cores) (range is mean to 90th percentile for the project with the greatest usage)
(mean project slightly lower unless noted otherwise). Before the bar is for 32 core node, after is
for 16 core (slightly reduced subest of projects tested total).

- add: 1 | 0.5
- align: 24-32 | 14-16 (12-16)
- buildDem: 7-20 | 6-15 (4-12)
- buildDepth: 7-10 | 6-10 (6-9)
- buildModel (cpu): 18-32 | 10-16 (8-15)
- buildOrtho: 11-21 | 7-15 (6-14)
- buildPointCloud: 23-28 | 13-16 (12-15)
- classifyGroundPoints: 31-32 | 16-16 (13-16)
- exports (everything except ortho takes < 1 min; ortho takes 6 min): 2-6 | 2-4
- matchPhotos: 16-28 (mean project 15-20) | 10-14 (9-13)
- optimizeCameras (takes 15 min): 21-32 | 11-16 (10-15)

Determining CPU requests

Goal is to have the resources available when the process needs it, but request a bit less than its
max because other bursting resources could use the excess when the focal resource is lower, helping
to avoid underutilized CPU on nodes. So aim for mean util of the most demanding project of our
10-project sample. Also, reduce a bit more to allow for strategic bin-packing where possible (e.g.
if it was 8, reduce to 7 so we could fit two on a node along with the tiny daemons that take a
little cpu, or e.g. setup or exports). All this efficiency would only be even greater than the
efficiency gains estimated above of switching from xl to l.

API calls (* means can fit more than one on a 16-cpu node):

- (setup) add: 1 | 0.5
- (align) align: 22 | 14
- *(build dem ortho) buildDem: 7 | 5
- *(build depth) buildDepth: 6 | 6
- (build mesh) buildModel (cpu): 15 | 8
- *(build dem ortho) buildOrtho: 11 | 7
- (build point cloud) buildPointCloud: 20 | 11
- (build point cloud) classifyGroundPoints: 22 | 14
- *exports (everything except ortho takes < 1 min; ortho takes 6 min): 2 | 2
- (match photos) matchPhotos: 15 | 7
- (align) optimizeCameras (takes 15 min): 21 | 8

automate-metashape steps:

- setup: 1 | 0.5
- match_photos: 15 | 7
- align_cameras: 22 | 14
- build_depth_maps: 6 | 6
- build_point_cloud: 20 | 11  (or raise to 13 to keep CPU proportional with memory)
- build_mesh: 15 | 8
- build_dem_orthomosaic: 7-11 (7) | 5-7 (5) (or raise to 9 to keep CPU proportional with memory)
- match_photos_secondary: 12 | 7
- align_cameras_secondary: 22 | 14
- finalize: 2 | 1-2 (1)

(Have completed this:) The above numbers assume that as long as Metashape can use them, doubling the number of cores
doubles the processing speed. We should test if this is true: run on a 16-core machine and compare
the processing time per CPU core used. Select an array of 5 projects from the original run to re-run
(CPU version): 192, 195, 0068_000434_000440, emerald_subset, 810, 404.

Memory usage (GB) Value is the maximum usage in GB of the process (and children) over the 10
projects tested (rounded up to nearest half GB)) Before the bar is for 32 core node, after is for 16
core (slightly reduced subest of projects tested total).

- (setup) add: 1
- (align) align: 17.5
- (build dem ortho) buildDem: 2
- (build depth) buildDepth: 10.5
- (build mesh) buildModel (cpu): 23 | 18
- (build dem ortho) buildOrtho: 32 | 28
- (build point cloud) buildPointCloud: 41.5 | 27*
- (build point cloud) classifyGroundPoints: 17.5
- exports (everything except ortho takes < 1 min; ortho takes 6 min): 11 | 6 for model, 3.5 | 2.5 for raster
- (match photos) matchPhotos: 15 | 5*
- (align) optimizeCameras (takes 15 min): 17.5 | 5*

*: means that in the subset of projects that was also tested for m3.large, the max value recorded
  above for xl did not exist, meaning it existed only in the project we skipped.

Determining memory requests

Goal is to make a request with a comfortable buffer (25%?) over the maximum usage of the
most-demanding project of our 10-project sample. We will not set limits because if there is a
process that exceeds our max, there is a chance the node will have enough capacity to accommodate
it, whereas if we set a limit, it will get killed even if the node had the capacity.

API calls:

- (setup) add: 1.5
- (align) align: 22.5
- (build dem ortho) buildDem: 2.5
- (build depth) buildDepth: 13
- (build mesh) buildModel (cpu): 29 | 22
- (build dem ortho) buildOrtho: 40 | 35
- (build point cloud) buildPointCloud: 53 | 34*
- (build point cloud) classifyGroundPoints: 22
- exports (everything except ortho takes < 1 min; ortho takes 6 min): 14 | 6* for model, 4.5 for raster
- (match photos) matchPhotos: 19 | 7*
- (align) optimizeCameras (takes 15 min): 22 | 7*

automate-metashape steps (taking the max of all contributing API calls):

- setup: 1.5
- match_photos: 19 | 7*
- align_cameras: 22.5
- build_depth_maps: 13
- build_point_cloud: 53 | 34*
- build_mesh: 29 | 22
- build_dem_orthomosaic: 40 | 35
- match_photos_secondary: 19 | 7*
- align_cameras_secondary: 22.5
- finalize: 3 | 2


If these were proportional to the CPU requests, they would be:



- setup: 4 | 2
- match_photos: 46 | 28
- align_cameras: 84 | 56
- build_depth_maps: 23 | 24
- build_point_cloud: 76 | 44 <
- build_mesh: 57 | 32
- build_dem_orthomosaic: 27 | 20 <<
- match_photos_secondary: 46 | 28
- align_cameras_secondary: 84 | 56
- finalize: 8 | 4

So all of these steps use much less fraction of the memory as they do a fraction of the CPUs. **
(lower importance) Need to redo this for the m3.large runs: does the memory-per-core use go up? Or
if we give it fewer cores can we give it less memory? In particular, check align cameras (allocated 22
CPUs and 22.5 GB) and build point cloud (allocated 20 CPUs and 53 GB). So regradless, even if mem usage
didn't go down, if we ran this with 16 cores on a m3.large node (60 GB avail), we'd have enough
memory.

On a g3.large, the processes that use a greater fraction of memory than CPU are build_dem_ortho (specifically the
buildOrtho part) unless we raise the number of cores for that step from 5 to 9, and
build_point_cloud (only if there is an anomalously large project that used as much as it did on the
xl run) which could be abated by raising
the number of cores from 11 to 13.


*Testing efficiency of MIG relative to full-GPU node (g3.xl):

Two 1-slice GPUs (e.g. 2x1g) is slightly faster than single 2-slice GPUS (e.g. 1x2g).

BuildDepthMaps takes 3x the time on a 1-slice MIG vs. a full-GPU (but costs 14%). Slice-seconds used is 2.3x greater on
a full GPU node. On a 2-slice MIG, it takes 1.7x the time (but costs 28-33%, depending
whether we consider that there are only 3 possible 2-slice pods at a time). Slice-secods used is
1.7-2.0x greater on a full GPU node (meaning even with 2-slice nodes, we get ~ 2x efficiency). Moving
from 1 slice to 2 slices cuts processing time by x0.58.

For the most CPU-intensive project tested, CPU p90 was 7.7 cores (1/4 of the CPU of a g3.xl) for a 2-slice MIG, so
there would be no CPU bottlenecking. For a 1-slice, it was 5 cores, still no bottlenecking. Memory
wa 11.9 and 8.2 respectively, still no bottlenecking (120 GB mem total)

MatchPhotos takes 1.5x the time on a 1-slice MIG vs. a full-GPU (but costs 14%). Slice-seconds used
is 4.6x greater on a full GPU node. On a 2-slice MIG, it takes 0.99x the time (but costs 28-33%,
depending whether we consider that there are only 3 possible 2-slice pods at a time). Slice-seconds
used is 3-3.5x greater on a full GPU node (meaning even with 2-slice nodes, we get >= 3x
efficiency). Moving from 1 slice to 2 slices cuts processing time by x0.65. If we consider a
m3.large to have 3.5 slices, slice-seconds used is 5.6x greater than on a 1-slice MIG and 3.7-4.3x
greater than on a 2-slice MIG compared to a m3.large. Prehaps we could run 2 parallel matchPhotos
jobs on a m3.large, in which case these efficiencies would drop to 2.8x and 1.85-2.15x. But these
drops are probably less substantial than this (inferred from our testing) because our testing did
not have two jobs running at once, which would comparess CPU a bit and increase memory pressure such
that throughput is <2x . GPU slices cost 2x, so even with 2-slice pods, we probably at least break
even compared with CPU. Compute times compared with a m3.large CPU are 0.63x for 1-slice and 0.41x
for 2-slice. And separate testing (data not present here) shows that for some matching types, the
benefits of GPU relative to CPU greatly increase and in this case we should definitely use GPU, and
it could be nice to just use it generally to be prepared for these cases, and because it gets
through the projects faster. Could increas it to 3x1g to cut proessing tie to 0.73x of 2x1g for a
10% inefficiency (10% more slice-hours used). Compared to a 1x1g, that is 41% compute time for 3x
the GPU with a 1x3g. Or we can get 56% compute time for 2x the GPU with a 2x1g.

For the most CPU-intensive project tested, CPU p90 was 15 cores (1/2 of the CPU of a g3.xl) for a 2-slice MIG, so
there might be some minor CPU bottlenecking, but should be minor since mean usage of this project
was 4.6. For a 1-slice, it was 10.1 for p90 and 3.0 for mean, still minimal/no bottlenecking. Memory
was 5.2 for 1 and 2 slices, still no bottlenecking (120 GB mem total).

If we want to more fully utilize our GPU nodes, we could submit matching as 1-slice jobs and
depthmaps as 2-slice jobs, since a 2-slice depthmapping would still take 3.6x longer than a 1-slice
matching (i.e., save the bigger slices for the longer-running tasks where the overall speedup has a
greater impact). This assumes that there would be depthmapping and matching tasks trying to run at
once.

Prudent resource requests are likely to request CPU and mem proportional to the fractional GPU slice
(e.g. 1/7 of tot for 1-slice, 2/7 for 2), but maybe 10% less so the small daemons on the node don't
bump the GPU jobs.

So for our two GPU tasks:

build_depth_maps: 2x1g MIG, 8 CPU, 16 GB mem
match_photos: 1x1g MIG, 4 CPU, 8 GB mem


If we wanted to get really fancy, we could use autoscaler expander priorities and nodegroups of
different size nodes to encourage kubernetes to provision small nodes for small pods, large for
large. Would also have to have a preferred affinity, where each pod has an affinity for the size
nodes that best match it.

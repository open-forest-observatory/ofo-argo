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

For benchmarking GPU: run a medium and large project through depth maps with:

1x1g, 2x1g, 3x1g, 1x2g, 1x3g

Which projects? 0068_000434_000440, 000810, 000404

FIRST PREVENT EVICTION

GPU usage (%) (range is mean to 90th percentile for the project with the greatest usage) (mean
project slightly lower unless noted otherwise)

- buildDepthMaps: 60-99 (mean is 50-95)
- buildModel: 2-0 (meaning there is a brief period of very high GPU usage, maybe we could disable
  texturing to save this and not have to do it by CPU either -- actually no, this is not texturing,
  that is a separate step we don't use)
- matchPhotos: 16-84 (mean is 12-50)

CPU requirements (cores) (range is mean to 90th percentile for the project with the greatest usage)
(mean project slightly lower unless noted otherwise)

- add: 1
- align: 24-32
- buildDem: 7-20
- buildDepth: 7-10
- buildModel (cpu): 18-32
- buildOrtho: 11-21
- buildPointCloud: 23-28
- classifyGroundPoints: 31-32
- exports (everything except ortho takes < 1 min; ortho takes 6 min): 2-6
- matchPhotos: 16-28 (mean project 15-20)
- optimizeCameras (takes 15 min): 21-32

Determining CPU requests

Goal is to have the resources available when the process needs it, but request a bit less than its
max because other bursting resources could use the excess when the focal resource is lower, helping
to avoid underutilized CPU on nodes. So aim for mean util of the most demanding project of our
10-project sample.

API calls:

- (setup) add: 1
- (align) align: 22
- (build dem ortho) buildDem: 7
- (build depth) buildDepth: 6
- (build mesh) buildModel (cpu): 15
- (build dem ortho) buildOrtho: 11
- (build point cloud) buildPointCloud: 20
- (build point cloud) classifyGroundPoints: 22
- exports (everything except ortho takes < 1 min; ortho takes 6 min): 2
- (match photos) matchPhotos: 15
- (align) optimizeCameras (takes 15 min): 21

automate-metashape steps:

- setup: 1
- match_photos: 15
- align_cameras: 22
- build_depth_maps: 6
- build_point_cloud: 20
- build_mesh: 15
- build_dem_orthomosaic: 7-11 (7)
- match_photos_secondary: 12
- align_cameras_secondary: 22
- finalize: 2

The above numbers assume that as long as Metashape can use them, doubling the number of cores
doubles the processing speed. We should test if this is true: run on a 16-core machine and compare
the processing time per CPU core used. Select an array of 5 projects from the original run to re-run
(CPU version): 192, 195, 0068_000434_000440, emerald_subset, 810, 404.

Memory usage (GB)
Value is the maximum usage in GB of the process (and children) over the 10 projects tested (rounded
up to nearest half GB))

- (setup) add: 1
- (align) align: 17.5
- (build dem ortho) buildDem: 2
- (build depth) buildDepth: 10.5
- (build mesh) buildModel (cpu): 23
- (build dem ortho) buildOrtho: 32
- (build point cloud) buildPointCloud: 41.5
- (build point cloud) classifyGroundPoints: 17.5
- exports (everything except ortho takes < 1 min; ortho takes 6 min): 11 for model, 3.5 for raster
- (match photos) matchPhotos: 15
- (align) optimizeCameras (takes 15 min): 17.5


Determining memory requests

Goal is to make a request with a comfortable buffer (10%?) over the maximum usage of the
most-demanding project of our 10-project sample. We will not set limits because if there is a
process that exceeds our max, there is a chance the node will have enough capacity to accommodate
it, whereas if we set a limit, it will get killed even if the node had the capacity.

API calls:

- (setup) add: 1.5
- (align) align: 22.5
- (build dem ortho) buildDem: 2.5
- (build depth) buildDepth: 13
- (build mesh) buildModel (cpu): 29
- (build dem ortho) buildOrtho: 40
- (build point cloud) buildPointCloud: 53
- (build point cloud) classifyGroundPoints: 22
- exports (everything except ortho takes < 1 min; ortho takes 6 min): 14 for model, 4.5 for raster
- (match photos) matchPhotos: 19
- (align) optimizeCameras (takes 15 min): 22

automate-metashape steps (taking the max of all contributing API calls):

- setup: 1.5
- match_photos: 19
- align_cameras: 22.5
- build_depth_maps: 13
- build_point_cloud: 53
- build_mesh: 29
- build_dem_orthomosaic: 4.5
- match_photos_secondary: 19
- align_cameras_secondary: 22.5
- finalize: 3


If these were proportional to the CPU requests, they would be:

- setup: 4
- match_photos: 46
- align_cameras: 84
- build_depth_maps: 23
- build_point_cloud: 76
- build_mesh: 57
- build_dem_orthomosaic: 27
- match_photos_secondary: 46
- align_cameras_secondary: 84
- finalize: 8

So all of these steps use much less fraction of the memory as they do a fraction of the CPUs. **
(lower importance) Need to redo this for the m3.large runs: does the memory-per-core use go up? Or
if we give it fewer cores can we give it less memory? In particular, check align cameras (allocated 22
CPUs and 22.5 GB) and build point cloud (allocated 20 CPUs and 53 GB). So regradless, even if mem usage
didn't go down, if we ran this with 16 cores on a m3.large node (60 GB avail, we'd have enough memory)







If we wanted to get really fancy, we could use autoscaler expander priorities and nodegroups of
different size nodes to encourage kubernetes to provision small nodes for small pods, large for
large. Would also have to have a preferred affinity, where each pod has an affinity for the size
nodes that best match it.
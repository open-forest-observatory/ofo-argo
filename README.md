# Open Forest Observatory Argo Workflows

This repository contains [Argo Workflows](https://argoproj.github.io/workflows) used by the **Open Forest Observatory (OFO)** to process drone imagery at scale on [Jetstream2 Cloud](https://jetstream-cloud.org/).

## Documentation

**For complete documentation, visit [https://open-forest-observatory.github.io/ofo-argo/](https://open-forest-observatory.github.io/ofo-argo/)**

Quick links:
- [Running the photogrammetry workflow](https://open-forest-observatory.github.io/ofo-argo/usage/photogrammetry-workflow/)
- [Cluster access and resizing](https://open-forest-observatory.github.io/ofo-argo/usage/cluster-access-and-resizing/)
- [Admin guides](https://open-forest-observatory.github.io/ofo-argo/admin/)

## Overview

The workflow runs the [automate-metashape](https://github.com/open-forest-observatory/automate-metashape) pipeline, followed by post-processing steps, simultaneously across multiple virtual machines. This type of scaling enables OFO to process many photogrammetry projects simultaneously with a single run command.

The system uses [Kubernetes](https://kubernetes.io/docs/concepts/overview/) which orchestrates containers, scales the processing to multiple VMs, and balances the load between worker nodes. The current setup includes:

- **Controller node**: Manages the Kubernetes cluster and Argo workflows
- **Worker nodes**: Handle compute workloads, processing drone missions in parallel
- **Manila shared storage**: Provides working data storage to the nodes
- **S3 storage**: Stores the inputs/outputs of each step

### Step-Based Workflow (Recommended)

The **step-based workflow** (`photogrammetry-workflow-stepbased.yaml`) provides optimized resource utilization by splitting Metashape processing into individual steps:

- 🎯 **GPU steps** (match_photos, build_depth_maps, build_mesh) run on expensive GPU nodes only when needed
- 💻 **CPU steps** (align_cameras, build_point_cloud, build_dem_orthomosaic, etc.) run on cheaper CPU nodes
- ⚡ **Disabled steps** are completely skipped (no pod creation, no resource allocation)
- 📊 **Fine-grained monitoring** - Track progress of each step in the Argo UI
- 🔧 **Flexible GPU usage** - Configure whether GPU-capable steps use GPU or CPU nodes

**Documentation:**
- 📖 [Complete Guide](https://open-forest-observatory.github.io/ofo-argo/usage/stepbased-workflow/) - Full usage instructions, troubleshooting, and advanced topics
- ⚡ [Quick Reference](https://open-forest-observatory.github.io/ofo-argo/usage/stepbased-quick-reference/) - Command cheat sheet and common patterns

## Files & Directories In this Repository

| File/Directory   | Purpose       |
|  --- | ----  |
| photogrammetry-workflow.yaml | Original Argo Workflows configuration (monolithic, kept as reference) |
| photogrammetry-workflow-stepbased.yaml | **Step-based workflow** - Individual step execution with optimized CPU/GPU allocation |
| docs/ | Documentation site source (published to [GitHub Pages](https://open-forest-observatory.github.io/ofo-argo/)) |
| mkdocs.yml | Configuration for the MkDocs documentation site |
| docker-workflow-utils/ | Utility docker container for workflow scripts (preprocessing, DB logging) |
| docker-photogrammetry-postprocessing/ | Files defining custom docker containers performing core workflow tasks (e.g. postprocessing) |
| setup/ | Kubernetes and Argo setup configurations (described in [admin docs](https://open-forest-observatory.github.io/ofo-argo/admin)) |
| test-workflows/ | Test workflow definitions for development and validation |
| implementation-plans/ | Technical implementation plans for workflow development |

## Getting Started

For complete setup and usage instructions, please visit the [full documentation site](https://open-forest-observatory.github.io/ofo-argo/).

**Quick start guide:**

1. [Access the cluster](https://open-forest-observatory.github.io/ofo-argo/usage/cluster-access-and-resizing/)
1. [Get set up with Argo](https://open-forest-observatory.github.io/ofo-argo/usage/argo-usage/)
2. [Run the photogrammetry workflow](https://open-forest-observatory.github.io/ofo-argo/usage/photogrammetry-workflow/)

For cluster administration, see the [admin guides](https://open-forest-observatory.github.io/ofo-argo/admin/).

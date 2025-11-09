# Open Forest Observatory Argo Workflow

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

## Files & Directories In this Repository

| File Name   | Purpose       |
|  --- | ----  |
| argo-output-pv.yaml | Defines read-write PV for workflow output storage mounted at /ofo-share/argo-output |
| argo-output-pvc.yaml | PVC bound to output volume |
| ofo-share-pv.yaml | Defines read-only NFS PV for /ofo-share (input data) |
| ofo-share-pvc.yaml | PVC bound to shared data volume |
| workflow.yaml | Argo configuration for entire automated workflow |
| /ofo-argo-utils | files to build a docker image for database logging of argo workflow metadata |
| /postprocess_docker | files to build the docker image that does postprocessing of metashape products|
| /.github/workflows | a github action workflow to automatically build a new DB logging docker image if any changes have been made to repo. **CURRENTLY DISABLED in GITHUB ACTIONS** |

## Getting Started

For complete setup and usage instructions, please visit the [full documentation site](https://open-forest-observatory.github.io/ofo-argo/).

**Quick start guide:**

1. [Access the cluster](https://open-forest-observatory.github.io/ofo-argo/usage/cluster-access-and-resizing/)
2. [Run the photogrammetry workflow](https://open-forest-observatory.github.io/ofo-argo/usage/photogrammetry-workflow/) (includes input preparation)

For cluster administration, see the [admin guides](https://open-forest-observatory.github.io/ofo-argo/admin/).

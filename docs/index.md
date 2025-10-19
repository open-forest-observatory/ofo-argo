# OFO Argo Workflows Documentation

Welcome to the Open Forest Observatory (OFO) Argo Workflows documentation. This repository contains [Argo Workflows](https://argoproj.github.io/workflows) used to process photogrammetry data at scale on Kubernetes clusters.

## Overview

The OFO Argo system enables parallel processing of photogrammetry projects using the [automate-metashape](https://github.com/open-forest-observatory/automate-metashape) pipeline across multiple virtual machines on [Jetstream2 Cloud](https://jetstream-cloud.org/). This scaling capability allows OFO to process many photogrammetry projects simultaneously with a single run command.

## Architecture

The system runs on [Kubernetes](https://kubernetes.io/docs/concepts/overview/), which orchestrates containers, scales processing across multiple VMs, and balances the load between worker nodes. The current setup includes:

- **Controller node**: Manages the Kubernetes cluster and Argo workflows
- **Worker nodes**: Process Metashape projects in parallel
- **Manila shared storage**: Provides input data and configuration storage
- **S3 storage**: Stores final processing outputs

## Documentation Structure

This documentation is organized into the following sections:

### User Guides

- **[Cluster access and resizing](usage/cluster-access-and-resizing.md)**: Access the cluster and manage nodegroups for workflow runs

### Administrator Guides

- **[Cluster creation and resizing](admin/cluster-creation-and-resizing.md)**: Create and manage Kubernetes clusters using OpenStack Magnum
- **[Manila share mounting](admin/manila-share-mounting.md)**: Configure persistent storage for the cluster
- **[Argo installation on cluster](admin/argo-installation-on-cluster.md)**: Install and configure Argo Workflows

## Quick Links

- [OFO Argo GitHub Repository](https://github.com/open-forest-observatory/ofo-argo)
- [Automate-Metashape Pipeline](https://github.com/open-forest-observatory/automate-metashape)
- [Argo Workflows Documentation](https://argoproj.github.io/workflows)
- [Jetstream2 Cloud](https://jetstream-cloud.org/)

## Getting Started

If you're new to the OFO Argo system:

1. Start with the [Cluster Creation and Resizing](admin/cluster-creation-and-resizing.md) guide to set up a Kubernetes cluster
2. Follow the [Manila Share Mounting](admin/manila-share-mounting.md) guide to configure persistent storage
3. Complete the [Argo Installation on Cluster](admin/argo-installation-on-cluster.md) guide to deploy Argo Workflows
4. You're ready to submit workflows!

## Support

For issues or questions, please visit the [GitHub Issues page](https://github.com/open-forest-observatory/ofo-argo/issues).

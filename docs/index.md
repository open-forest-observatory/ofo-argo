# OFO Argo Workflows Documentation

Welcome to the Open Forest Observatory (OFO) Argo Workflows documentation. This repository specifies
workflows for processing drone data at scale using [Argo Workflows](https://argoproj.github.io/workflows) on a Kubernetes cluster. It also contains cluster setup resources.

## Overview

The OFO Argo system enables parallel processing of drone missions using the
[automate-metashape](https://github.com/open-forest-observatory/automate-metashape) pipeline across
multiple virtual machines on [Jetstream2 Cloud](https://jetstream-cloud.org/). This scaling
capability allows OFO to process many drone missions simultaneously with a single run command.

## Architecture

The system uses [Argo Workflows](https://argoproj.github.io/workflows) running on a
[Kubernetes](https://kubernetes.io/docs/concepts/overview/) cluster, which orchestrates containers,
scales processing across multiple VMs, and balances the load between worker nodes. The current setup
includes:

- **Controller node**: Manages the Kubernetes cluster and Argo workflows
- **Worker nodes**: Handle compute workloads, such as processing drone missions, in parallel
- **Manila shared storage**: Provides working data storage to the nodes
- **S3 storage**: Stores the inputs/outputs of each step

## Documentation Structure

- **[User guides](usage/index.md)**: Guides for accessing and managing the cluster to run workflows
- **[Administrator guides](admin/index.md)**: Guides for setting up and configuring the cluster infrastructure

## Quick Links

- [OFO Argo GitHub Repository](https://github.com/open-forest-observatory/ofo-argo)
- [Automate-Metashape Pipeline](https://github.com/open-forest-observatory/automate-metashape)
- [Argo Workflows Documentation](https://argoproj.github.io/workflows)
- [Jetstream2 Cloud](https://jetstream-cloud.org/)

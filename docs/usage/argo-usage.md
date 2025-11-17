---
title: Using Argo on the OFO cluster
weight: 15
---

# Using Argo on the OFO cluster

This guide describes how to submit workflows to Argo and monitor them. This is a generic guide for any Argo workflow.

For specific instructions on running the photogrammetry (automate-metashape) workflow, see the [Photogrammetry workflow guide](photogrammetry-workflow.md).

## Prerequisites

This guide assumes you already:

- Have access to the `ofocluster` kubernetes cluster
- Have resized the cluster to the apprpriate size for your workflow
- Have `kubectl` configured to connect to the cluster

For guidance on all of this setup, see [Cluster access and
resizing](cluster-access-and-resizing.md).

## Install the Argo CLI locally (one-time)

The Argo CLI is a wrapper around `kubectl` that simplifies communication with Argo on the cluster.
You should install it on your *local machine* since that is where you will have set up and
authenticated `kubectl` following the [Cluster access](cluster-access-and-resizing.md) guide.

```bash
# Specify the CLI version to install
ARGO_WORKFLOWS_VERSION="v3.7.2"
ARGO_OS="linux"

# Download the binary
wget "https://github.com/argoproj/argo-workflows/releases/download/${ARGO_WORKFLOWS_VERSION}/argo-${ARGO_OS}-amd64.gz"

# Unzip
gunzip "argo-${ARGO_OS}-amd64.gz"

# Make binary executable
chmod +x "argo-${ARGO_OS}-amd64"

# Move binary to path
sudo mv "./argo-${ARGO_OS}-amd64" /usr/local/bin/argo

# Test installation
argo version
```

## Authenticate with the cluster

Once after every reboot, you will need to re-set your `KUBECONFIG` environment variable so that
`argo` (and the underlying `kubectl`) CLI tools can authenticate with the cluster:

```bash
source ~/venv/openstack/bin/activate
export KUBECONFIG=~/.ofocluster/ofocluster.kubeconfig
```


## Submit a workflow

Simply run `argo submit -n argo /path/to/your/workflow.yaml`, optionally adding parameters
 by appending text in the format `-p PARAMETER_NAME=parameter_value`. The `parameter_value` can be
 an environment variable. For example:

```bash
argo submit -n argo workflow.yaml \
-p PARAMETER_NAME=parameter_value \
```

## Observe and manage workflows through the Argo web UI

Access the Argo UI at [argo.focal-lab.org](https://argo.focal-lab.org). When prompted to log in,
supply the client authentication token. You can find the token string in
[Vaultwarden](https://vault.focal-lab.org) under the record "Argo UI token".

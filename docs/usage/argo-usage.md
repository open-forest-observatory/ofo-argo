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
argo submit -n argo photogrammetry-workflow.yaml \
-p PARAMETER_NAME=parameter_value \
```

## Observe and manage workflows

### Argo web UI

Access the Argo UI at [argo.focal-lab.org](https://argo.focal-lab.org). When prompted to log in,
supply the client authentication token. You can find the token string in
[Vaultwarden](https://vault.focal-lab.org) under the record "Argo UI token".

### Command line

Argo provides a CLI to inspect and monitor workflows. But sometimes pure Kubernetes works well too.
For example, here is a snippet to show all nodes and which Argo pods are running on each.

```bash
# Get all nodes first
kubectl get nodes -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n' | grep -v '^$' > /tmp/nodes.txt

# Get all non-DaemonSet pods in argo namespace
kubectl get pods -n argo -o custom-columns=NODE:.spec.nodeName,NAMESPACE:.metadata.namespace,NAME:.metadata.name,STATUS:.status.phase,OWNER:.metadata.ownerReferences[0].kind --no-headers 2>/dev/null | \
  grep -v DaemonSet > /tmp/pods.txt

# Display results
while read node; do
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "NODE: $node"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  
  # Get pods for this node
  grep "^$node " /tmp/pods.txt 2>/dev/null | awk '{printf "  %-40s %-20s %s\n", $3, $2, $4}'
  
  # Check if node has no pods
  if ! grep -q "^$node " /tmp/pods.txt 2>/dev/null; then
    echo "  (no argo pods)"
  fi
  
  echo ""
done < /tmp/nodes.txt

# Cleanup
rm /tmp/nodes.txt /tmp/pods.txt
```

## Autoscaler considerations

Because our cluster is set up to autoscale (add/remove nodes to match demand), there is the
possibility that workflow pods that are running on underutilized nodes will get evicted (killed) and
rescheduled on a different node, in the autoscaler's effort to free up and remove the underutilized
node. To minimize the probability of this, we have implemented several measures:

1. **Pod packing via affinity rules**: Workflow pods prefer to schedule on nodes that already have
   other running workflow pods. This keeps pods consolidated on fewer nodes, reducing the chance
   that a node becomes "underutilized" while still running a workflow pod. This is configured via
   `podAffinity` rules that prefer nodes with pods labeled `workflows.argoproj.io/completed: "false"`.

2. **Automatic pod cleanup**: Completed pods are automatically deleted via `podGC: OnPodCompletion`.
   This prevents finished pods from lingering and confusing the scheduler's affinity decisions.

3. **S3 log archiving**: Workflow logs are archived to S3, so we don't need completed pods to stick
   around for log access.

4. **Eviction protection**: All workflow pods are annotated with
   `cluster-autoscaler.kubernetes.io/safe-to-evict: "false"`. This tells the cluster autoscaler to
   never evict running workflow pods, even if the node appears underutilized. Once pods complete,
   they are deleted by podGC, which allows the node to scale down normally.

These defaults are configured in the workflow controller configmap (see [Argo
installation](../admin/argo-installation-on-cluster.md)).

## GPU node scheduling

To prevent expensive GPU resources from being consumed by CPU-only workloads, the cluster uses explicit scheduling rules:

**How it works:**

- **CPU nodes** are labeled with `workload-type: cpu` based on their nodegroup naming pattern (any node with `cpu` in the name)
- **CPU pods** use `nodeSelector: workload-type: cpu` to explicitly target CPU nodes
- **GPU pods** request GPU resources (e.g., `nvidia.com/gpu` or MIG resources), which naturally constrains them to nodes advertising those resources
- All pods still inherit `podAffinity` from the workflow controller configmap to prefer scheduling on nodes with other running pods (to support autoscaling in removing empty nodes)

This approach ensures CPU pods cannot schedule on GPU nodes, even during the brief period when new GPU nodes join the cluster before NFD labels them.

For admin setup of CPU node labeling, see [CPU node labeling](../admin/cluster-creation-and-resizing.md#configure-cpu-node-labeling).

### MIG (Multi-Instance GPU)

For workloads with low GPU utilization, MIG nodegroups partition each A100 into multiple isolated slices. To use MIG, create a MIG nodegroup (see [MIG nodegroups](cluster-access-and-resizing.md#mig-nodegroups)).

**For custom workflows**, update the workflow GPU template to request MIG resources:

```yaml
resources:
  requests:
    nvidia.com/mig-2g.10gb: 1  # Instead of nvidia.com/gpu: 1
    cpu: "10"
    memory: "38Gi"
```

**For the photogrammetry workflow**, configure MIG resources (along with CPU/memory) in your config file's `argo` section instead of editing the workflow YAML. See [Step-based workflow resource configuration](stepbased-workflow.md#resource-configuration) for details.

Available MIG resource types:

- `nvidia.com/mig-1g.5gb` - 1/7 compute, 5GB VRAM (7 per GPU)
- `nvidia.com/mig-2g.10gb` - 2/7 compute, 10GB VRAM (3 per GPU)
- `nvidia.com/mig-3g.20gb` - 3/7 compute, 20GB VRAM (2 per GPU)

GPU resource requests work for both MIG and non-MIG GPU nodes.

---
title: Cluster access and resizing
weight: 5
---

# Cluster access and resizing

This guide assumes a cluster has already been created, any necessary persistent volumes (e.g. Manila
share) have already been configured, and Argo has already been installed. It describes how to access and resize the
cluster as a user. For details on initial cluster deployment and setup, including
installation of Argo and configuration of persistent volumes, see the [Admin
guides](../admin/index.md).

The OFO cluster is named `ofocluster`. The nodes that comprise it can be seen in Exosphere starting
with the string `ofocluster-`. They appear as created by `dyoung@access-ci.org`. The nodes should
not be modified via Exosphere or Horizon, only through the command line tools described below.

## OFO cluster management principles

When the cluster is not in use, we will downsize it to its minimum size: one m3.small control node
and one m3.small worker node. Just before running a compute load (e.g. Argo data processing run) on
the cluster, we will manually add one or more 'nodegroups', which contain a specified number of nodes of a
specified flavor. We can add CPU and/or GPU nodegroups. Soon after the workflow run is complete, we
will manually delete the nodegroup(s) so that the nodes do not consume our compute credits.

## One-time local machine software setup

These instructions will set up your local (Linux, Mac, or WSL) machine to control the cluster through the command line.

### Install Python and create virtual environment

Make sure you have a recent Python interpreter and the venv utility, then create a Python virtual
environment for OpenStack management. OpenStack is the platform Jetstream2 uses to allow users to
create and manage cloud resources.

```bash
sudo apt update
sudo apt install -y python3-full python3-venv
python3 -m venv ~/venv/openstack
source ~/venv/openstack/bin/activate
```

### Install OpenStack command line tools

```bash
pip install -U python-openstackclient python-magnumclient python-designateclient
```

### Install kubectl

Install the Kubernetes control utility `kubectl` (from the [official Kubernetes documentation](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/)):

```bash
# Install prerequisites
sudo apt install -y apt-transport-https ca-certificates curl gnupg

# Add Kubernetes apt repository
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.33/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
sudo chmod 644 /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.33/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo chmod 644 /etc/apt/sources.list.d/kubernetes.list

# Install kubectl
sudo apt update
sudo apt install -y kubectl
```

### Download OpenStack application credential

This is a credential (and associated secret key) that allows you to authenticate with OpenStack in
order to manage cloud resources in our project. It will be rotated occasionally, so if yours doesn't
appear to work, check whether you have the latest version. In the OFO
[Vaultwarden](http://vault.focal-lab.org), find the entry `OpenStack application credential`.
Download the attached file `app-cred-ofocluster-openrc.sh` onto your **local computer** (do not put
it on a JS2 machine), ideally into `~/.ofocluster/app-cred-ofocluster-openrc.sh` (which is where we
will assume it is in these docs).

Source the application credential (which sets relevant environment variables to authenticate the OpenStack command line tools):

```bash
source ~/.ofocluster/app-cred-ofocluster-openrc.sh
```

### Enable shell completion

This will allow you to use `tab` to autocomplete OpenStack and Kubectl commands in your shell.

```bash
# Create directory for completion scripts
mkdir -p ~/.bash_completion.d

# Generate completion scripts
openstack complete > ~/.ofocluster/openstack-completion.bash
kubectl completion bash > ~/.ofocluster/kubectl-completion.bash

# Add to ~/.bashrc
echo 'source ~/.ofocluster/openstack-completion.bash' >> ~/.bashrc
echo 'source ~/.ofocluster/kubectl-completion.bash' >> ~/.bashrc
```

### Set up `kubectl` to control Kubernetes

This is required the first time you interact with Kubernetes on the cluster. `kubectl` is a tool to
control Kubernetes (the cluster's software, not its compute nodes/VMs) from your local command line.

Get the Kubernetes configuration file (`kubeconfig`) and configure your environment:

```bash
# Get cluster configuration
openstack coe cluster config "ofocluster2" --force

# Set permissions and move to appropriate location
chmod 600 config
mkdir -p ~/.ofocluster
mv -i config ~/.ofocluster/ofocluster.kubeconfig

# Set KUBECONFIG environment variable
export KUBECONFIG=~/.ofocluster/ofocluster.kubeconfig
```


## Cluster resizing

These instructions are for managing which nodes are in the cluster, not what software is running on
them.

If you are resuming cluster management after a reboot, you will need to re-set environment variables
and source the application credential:

```bash
source ~/venv/openstack/bin/activate
export KUBECONFIG=~/.ofocluster/ofocluster.kubeconfig
source ~/.ofocluster/app-cred-ofocluster-openrc.sh
```


### Add a new nodegroup

Use OpenStack to create new nodegroups.

#### CPU nodegroups

CPU nodegroups must include `cpu` in the nodegroup name for automatic labeling to work:

```bash
openstack coe nodegroup create ofocluster2 cpu-group --min-nodes 1 --max-nodes 8 --flavor m3.large
```

The `cpu` substring triggers automatic labeling (`workload-type: cpu`) via NodeFeatureRule, which is part of ensuring CPU-only workflow pods schedule on these nodes (the other part is the NodeSelector attribute specified for the CPU task template in the Argo workflow YAML).

#### GPU nodegroups

GPU nodegroups consist of full-GPU nodes, and on JS2 must be an `xl` flavor. For automate-metashape runs via Argo, we now prefer MIG (split GPU) nodegroups (see below). Standard full-GPU nodegroups can use any name, as GPU resource requests handle scheduling:

```bash
openstack coe nodegroup create ofocluster2 gpu-group --min-nodes 1 --max-nodes 8 --flavor g3.xl
```

#### MIG nodegroups

MIG (Multi-Instance GPU) partitions full (e.g. JS2 g3.xl A100) GPUs into smaller isolated slices, allowing multiple pods per GPU. Use MIG when your GPU workloads have low utilization (<50%) and don't need full GPU memory. This is the preferred way to provide GPU resources to automate-metashape runs via the OFO Argo step-based workflow, as it provides much greater compute efficiency.

Create MIG nodegroups by including `mig1-`, `mig2-`, or `mig3-` in the nodegroup name. Our benchmarking has shown that automate-metashape is most efficient with `mig1` nodes 7 slices (and you can provide more than one slice to a step).

```bash
openstack coe nodegroup create ofocluster2 mig1-group --min-nodes 1 --max-nodes 4 --flavor g3.xl
```

!!! note "Resource limits for MIG"
    When using MIG, reduce CPU/memory requests to fit multiple pods per node:

    | Profile | MIG resource request | Max pods/node | CPU each | RAM each |
    |---------|----------------------|---------------|----------|----------|
    | mig1 (7 slices) | `nvidia.com/mig-1g.5gb` | 7 | 4 | 16GB |
    | mig2 (3 slices) | `nvidia.com/mig-2g.10gb` | 3 | 10 | 38GB |
    | mig3 (2 slices) | `nvidia.com/mig-3g.20gb` | 2 | 15 | 55GB |

!!! warning "Workflow compatibility"
    MIG nodegroups are only used by workflows that request MIG resources (e.g., `nvidia.com/mig-1g.5gb: 1`) instead of full GPUs (`nvidia.com/gpu: 1`). See [MIG workflow configuration](argo-usage.md#mig-multi-instance-gpu).

!!! note "GPU Node Scheduling"
    CPU-only workflow pods use `nodeSelector` to target CPU nodes explicitly, preventing them from scheduling on expensive GPU nodes. GPU pods request GPU resources, which naturally constrains them to GPU nodes. See [GPU node scheduling](argo-usage.md#gpu-node-scheduling) for details.


### Autoscaling

Due to OpenStack limitations, all nodegroups in the cluster are autoscaling. The cluster adds/removes nodes to schedule all pending pods while keeping nodes near full utilization. Set `--min-nodes` and `--max-nodes` to the same value for a fixed-size nodegroup. (But note, if you delete nodes manually or via `openstack coe nodegroup delete`, the autoscaler will try to replace the deleted nodes with new ones until the nodegroup is fully deleted -- see below for workarounds.) The `--node-count` parameter is essentially irrelevant and defaults to 1 if omitted.

By default, the autoscaler may delete undrerutilized nodes with running pods, in an effort to consolidate pods and minimize running nodes. While often acceptable in many k8s applications, this is unacceptable for automate-metashape because pods may take hours and cannot resume from where they were killed. Therefore, we have configured the Argo workflow controller to label pods as not evictable so this doesn't happen. In addition, we have configured it to prefer scheduling new pods on nodes that already have running pods (the opposite of default Kubernetes behavior) to increase the chances of empty nodes that can be scaled down.


#### Check if the autoscaler is planning any upsizing or downsizing

```bash
kubectl get configmap cluster-autoscaler-status -n kube-system -o yaml
```

### Update a nodegroup's min/max node count bounds

The autoscaler should take care of resizing to meet demand (within the node count bounds you
specify). Downscaling has a delay of at least 10 min from triggering before being implemented in an
effort to prevent cycling. You can change the min and max bounds on the number of nodes the
autoscaler will request:

```bash
openstack coe nodegroup update ofocluster2 cpu-group replace min_node_count=1 max_node_count=1
```

### Drain/cordon nodes before downsizing or deleting

**WORK IN PROGRESS**

It appears that draining will actually kill running pods. Still need to find a way
to simply prevent scheduling of new pods (possibly "cordoning"), and confirm that nodes are empty, before deleting.

When decreasing the number of nodes in a nodegroup, it is best practice to drain the Kubernetes pods
from them first. Given that we don't know which nodes OpenStack will delete when reducing the size, we
have to drain the whole nodegroup. This is also what you'd do when deleting a nodegroup entirely.

```bash
NODEGROUP_NAME=cpu-group
kubectl get nodes -l capi.stackhpc.com/node-group=$NODEGROUP_NAME -o name | xargs -I {} kubectl drain {} --ignore-daemonsets --delete-emptydir-data
```

To drain only a specific number of nodes (prioritizing the least utilitzed), sort by utilization and add `head` to limit the
selection:

```bash
NODEGROUP_NAME=cpu-group
NUM_TO_DRAIN=2
kubectl get nodes -l capi.stackhpc.com/node-group=$NODEGROUP_NAME \
  --sort-by='.status.allocatable.cpu' -o name | \
  head -n $NUM_TO_DRAIN | \
  xargs -I {} kubectl drain {} --ignore-daemonsets --delete-emptydir-data
```
It will print the IDs of the nodes, which you can then explicitly delete (see below)


### Delete a nodegroup

If you attempt to delete a nodegroup with many nodes and lots of pending compute jobs, the delete
command can compete with the autoscaler, which will try to add nodes to restore the target node
count. To prevent this, first reduce the max size of the nodegroup to 1 (the lowest allowed value),
then delete.

```bash
openstack coe nodegroup update ofocluster2 $NODEGROUP_NAME min_node_count=1 max_node_count=1
openstack coe nodegroup delete ofocluster2 $NODEGROUP_NAME
```


## Cluster inspection commands

If you are resuming cluster management after a reboot, you will need to re-set environment variables
and source the application credential:

```bash
source ~/venv/openstack/bin/activate
export KUBECONFIG=~/.ofocluster/ofocluster.kubeconfig
source ~/.ofocluster/app-cred-ofocluster-openrc.sh
```

### Check cluster VM status

This looks at the status of the nodes (e.g. size and quantity) from the perspective of OpenStack. It
does not examine the state of the software on the nodes (e.g. Kubernetes, Argo).

```bash
openstack coe cluster list
openstack coe cluster show ofocluster
openstack coe nodegroup list ofocluster
```


### View Kubernetes nodes

Display Kubernetes node names, including which 'nodegroup' each belongs to.

```bash
kubectl get nodes
```

Display the utilization of CPU and memory on the nodes.

```bash
kubectl top nodes
```


### Access the shell on cluster nodes

This can be useful for debugging. Run commands on a node with:

```bash
kubectl debug node/<node-name> -it --image=ubuntu
```

Once inside, you have access to the host VM's filesystem via /host. You could use this, for example,
to check kernel modules:

```
chroot /host modprobe ceph
chroot /host lsmod | grep ceph
```

Or to check disk usage:

```bash
kubectl debug node/<node-name> -it --image=busybox -- df -h
```

... then look for the `/dev/vda1` volume.

When done, delete the debugging pods:

```bash
kubectl get pods -o name | grep node-debugger | xargs kubectl delete
```

## Kubernetes monitoring dashboards

Incomplete notes in development.

### Grafana dashboard

```bash
# Port-forward Grafana to your local machine
kubectl port-forward -n monitoring-system svc/kube-prometheus-stack-grafana 3000:80
```

Then open http://localhost:3000 in your browser.

### Kubernetes dashboard

```bash
# Create service account
kubectl create serviceaccount dashboard-admin -n kubernetes-dashboard

# Create cluster role binding
kubectl create clusterrolebinding dashboard-admin \
    --clusterrole=cluster-admin \
    --serviceaccount=kubernetes-dashboard:dashboard-admin

# Create token (24 hour duration)
kubectl create token dashboard-admin -n kubernetes-dashboard --duration=24h

# Port-forward (if not already running)
kubectl port-forward -n kubernetes-dashboard svc/kubernetes-dashboard 8443:443
```

Then open https://localhost:8443 in your browser and use the token to log in.

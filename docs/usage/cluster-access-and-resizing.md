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
openstack coe cluster config "ofocluster" --force

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

To add a new nodegroup, first specify its parameters and then use OpenStack to create it:

```bash
# Set nodegroup parameters
NODEGROUP_NAME=cpu-group  # or gpu-group, or whatever is meaningful to you
FLAVOR=m3.quad  # or "g3.medium" etc for GPU
N_WORKER=1
AUTOSCALE=false
N_WORKER_MIN=1 # Only relevant for autoscale
N_WORKER_MAX=5 # Only relevant for autoscale
BOOT_VOLUME_SIZE_GB=80

# Create the nodegroup
openstack coe nodegroup create ofocluster $NODEGROUP_NAME \
    --flavor $FLAVOR \
    --node-count $N_WORKER \
    --labels auto_scaling_enabled=$AUTOSCALE \
    --labels min_node_count=$N_WORKER_MIN \
    --labels max_node_count=$N_WORKER_MAX \
    --labels boot_volume_size=$BOOT_VOLUME_SIZE_GB
```

Quick access to create a CPU nodegroup:

```bash
openstack coe nodegroup create ofocluster --labels boot_volume_size=80 cpu-group --flavor m3.large --node-count 2
```

Quick access to create a GPU nodegroup:

```bash
openstack coe nodegroup create ofocluster --labels boot_volume_size=80 gpu-group --flavor g3.xl --node-count 2
```



### Drain nodes before downsizing or deleting

When decreasing the number of nodes in a nodegroup, it is best practice to drain the Kubernetes pods
from them first. Given that we don't know which nodes OpenStack will delete when reducing the size, we
have to drain the whole nodegroup. This is also what you'd do when deleting a nodegroup entirely.

```bash
NODEGROUP_NAME=cpu-group
kubectl get nodes -l capi.stackhpc.com/node-group=$NODEGROUP_NAME -o name | xargs -I {} kubectl drain {} --ignore-daemonsets --delete-emptydir-data
```

### Resize a nodegroup

Change the number of nodes in an existing nodegroup:

```bash
NODEGROUP_NAME=cpu-group
N_WORKER=2
openstack coe cluster resize ofocluster --nodegroup $NODEGROUP_NAME $N_WORKER
```

### Delete a nodegroup

```bash
openstack coe nodegroup delete ofocluster $NODEGROUP_NAME
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

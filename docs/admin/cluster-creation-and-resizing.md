---
title: Cluster creation and resizing
weight: 5
---

# Cluster creation and resizing

This guide is for the cluster administrator (currently Derek). Since we only need one cluster and
Derek is taking care of creating it, this guide is not necessary for the whole team. There is a
separate guide on cluster management that is for the whole team.

**Key resource** referenced in creating this guide: [Beginner's Guide to Magnum on
Jetstream2](https://gitlab.com/jetstream-cloud/jetstream2/eot/tutorials/magnum-tutorial/-/wikis/beginners_guide_to_magnum_on_JS2)

## One-time local machine software setup

These instructions will set up your local (Linux, Mac, or WSL) machine to control the cluster through the command line.

### Install Python and create virtual environment

Make sure you have a recent Python interpreter and the venv utility, then create a virtual environment for OpenStack management:

```bash
sudo apt update
sudo apt install -y python3-full python3-venv
python3 -m venv ~/venv/openstack
```

### Install OpenStack command line tools

```bash
# Activate environment
source ~/venv/openstack/bin/activate

# Install OpenStack utilities
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

### Create application credential

In [Horizon](https://js2.jetstream-cloud.org), go to **Identity > Application Credentials**. Click **Create**:

- Do not change the roles
- Do not set a secret (one will be generated)
- **Do** set an expiration date
- **Do** check "unrestricted" (required because Magnum creates additional app credentials for the cluster)

Download the openrc file and store it in the OFO [Vaultwarden](http://vault.focal-lab.org) organization where OFO members can access it.

Copy the application credential onto your **local computer** (do not put it on a JS2 machine),
ideally into `~/.ofocluster/app-cred-ofocluster-openrc.sh` (which is where we will assume it is in
these docs).

Source the application credential (which sets relevant environment variables for the OpenStack command line tools):

```bash
source ~/.ofocluster/app-cred-ofocluster-openrc.sh
```

### Create OpenStack keypair

Create a keypair for cluster node access. If you want, you can save the private key that is displayed when you run this command in order to SSH into the cluster nodes later. However, they won't have public IP addresses, so this is mainly to satisfy Magnum's requirements.

```bash
# Create a new keypair (displays private key - save if needed)
openstack keypair create my-openstack-keypair-name
```

**Alternatively**, specify an existing public key you normally use, in this example `~/.ssh/id_rsa.pub`:

```bash
# Use existing public key
openstack keypair create my-openstack-keypair-name --public-key ~/.ssh/id_rsa.pub
```

### Enable shell completion

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

## Cluster creation

Assuming you're in a fresh shell session, enter your JS2 venv and source the application credential:

```bash
source ~/venv/openstack/bin/activate
source ~/.ofocluster/app-cred-ofocluster-openrc.sh
```

### View available cluster templates

```bash
openstack coe cluster template list
```

### Deploy the cluster

Specify the deployment parameters and create the cluster. Choose the most recent Kubernetes version
(highest number in the template list). The master node can be `m3.small`. We'll deploy a cluster
with a single worker node that is also `m3.small`. When we need to scale up, we'll add nodegroups.
This initial spec is just the base setup for when we're not running Argo workloads on it.

```bash
# Set deployment parameters
TEMPLATE="kubernetes-1-33-jammy"
FLAVOR="m3.small"
MASTER_FLAVOR="m3.small"
BOOT_VOLUME_SIZE_GB=80

# Number of instances
N_MASTER=1  # Needs to be odd
N_WORKER=1

# Min and max number of worker nodes (if using autoscaling)
AUTOSCALE=false
N_WORKER_MIN=1
N_WORKER_MAX=5

# Network configuration
NETWORK_ID=$(openstack network show --format value -c id auto_allocated_network)
SUBNET_ID=$(openstack subnet show --format value -c id auto_allocated_subnet_v4)
KEYPAIR=my-openstack-keypair-name

# Deploy the cluster
openstack coe cluster create \
    --cluster-template $TEMPLATE \
    --master-count $N_MASTER --node-count $N_WORKER \
    --master-flavor $MASTER_FLAVOR --flavor $FLAVOR \
    --merge-labels \
    --labels auto_scaling_enabled=$AUTOSCALE \
    --labels min_node_count=$N_WORKER_MIN \
    --labels max_node_count=$N_WORKER_MAX \
    --labels boot_volume_size=$BOOT_VOLUME_SIZE_GB \
    --keypair $KEYPAIR \
    --fixed-network "${NETWORK_ID}" \
    --fixed-subnet "${SUBNET_ID}" \
    "ofocluster"
```

### Check cluster status (optional)

```bash
openstack coe cluster list
openstack coe cluster show ofocluster
openstack coe nodegroup list ofocluster
```

Or with formatting that makes it easier to copy the cluster UUID:

```bash
openstack coe cluster list --format value -c uuid -c name
```

## Set up `kubectl` to control Kubernetes

This is required the first time you interact with Kubernetes on the cluster. `kubectl` is a tool to
control Kubernetes (the cluster's software, not its compute nodes/VMs) from your local command line.

Once the `openstack coe cluster list` status (command above) changes to `CREATE_COMPLETE`, get the Kubernetes configuration file (`kubeconfig`) and configure your environment:

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

## Kubernetes management

If you are resuming cluster management after a reboot, you will need to re-set environment variables and source the application credential:

```bash
source ~/venv/openstack/bin/activate
export KUBECONFIG=~/.ofocluster/ofocluster.kubeconfig
source ~/.ofocluster/app-cred-ofocluster-openrc.sh
```

### View cluster nodes

```bash
kubectl get nodes
```

### Access shell on cluster nodes

Run commands on a node with:

```bash
# Start a debug session on a specific node
kubectl debug node/<node-name> -it --image=ubuntu

# Once inside, you have host access via /host
# Check kernel modules
chroot /host modprobe ceph
chroot /host lsmod | grep ceph
```

### Check disk usage

Run a one-off command to check disk usage:

```bash
kubectl debug node/<node-name> -it --image=busybox -- df -h
```

Look for the `/dev/vda1` volume. Then delete the debugging pods:

```bash
kubectl get pods -o name | grep node-debugger | xargs kubectl delete
```

## Cluster resizing

These instructions are for managing which nodes are in the cluster, not what software is running on them.

### Resize the default worker group

Resize the cluster by adding or removing nodes from the original worker group (not a later-added nodegroup). We will likely not do this, relying instead on nodegroups for specific runs.

```bash
openstack coe cluster resize "ofocluster" 4
```

### Add a new nodegroup

To add a new nodegroup, first specify its parameters and then use OpenStack to create it:

```bash
# Set nodegroup parameters
NODEGROUP_NAME=cpu-group  # or gpu-group
FLAVOR=m3.quad  # or "g3.medium" for GPU
N_WORKER=1
AUTOSCALE=false
N_WORKER_MIN=1
N_WORKER_MAX=5
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

### Drain nodes before downsizing or deleting

When decreasing the number of nodes in a nodegroup, it's best practice to drain the Kubernetes pods from them first. Since we don't know which nodes OpenStack will delete when reducing the size, we have to drain the whole nodegroup. This is also what you'd do when deleting a nodegroup entirely.

```bash
NODEGROUP_NAME=cpu-group
kubectl get nodes -l capi.stackhpc.com/node-group=$NODEGROUP_NAME -o name | xargs -I {} kubectl drain {} --ignore-daemonsets --delete-emptydir-data
```

### Resize a nodegroup

Change the number of nodes in an existing nodegroup:

```bash
N_WORKER=2
NODEGROUP_NAME=cpu-group
openstack coe cluster resize ofocluster --nodegroup $NODEGROUP_NAME $N_WORKER
```

### Delete a nodegroup

```bash
openstack coe nodegroup delete ofocluster $NODEGROUP_NAME
```

### Delete the cluster

```bash
openstack coe cluster delete "ofocluster"
```

## Monitoring dashboards

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

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
This initial spec is just the base setup for when we're not running Argo workloads on it. We need to
enable audo-scaling now, even though we don't want it for the default worker nodegroup, because
these settings apply to child nodegroups and it appears the max node count cannot be overridden.

```bash
# Set deployment parameters
TEMPLATE="kubernetes-1-33-jammy"
KEYPAIR=my-openstack-keypair-name # what you created above

# Network configuration
NETWORK_ID=$(openstack network show --format value -c id auto_allocated_network)
SUBNET_ID=$(openstack subnet show --format value -c id auto_allocated_subnet_v4)

openstack coe cluster create \
    --cluster-template $TEMPLATE \
    --master-count 1 --node-count 1 \
    --master-flavor m3.small --flavor m3.small \
    --merge-labels \
    --labels auto_scaling_enabled=true,min_node_count=1,boot_volume_size=80 \
    --keypair $KEYPAIR \
    --fixed-network "${NETWORK_ID}" \
    --fixed-subnet "${SUBNET_ID}" \
    "ofocluster2"



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
openstack coe cluster config "ofocluster2" --force

# Set permissions and move to appropriate location
chmod 600 config
mkdir -p ~/.ofocluster
mv -i config ~/.ofocluster/ofocluster.kubeconfig

# Set KUBECONFIG environment variable
export KUBECONFIG=~/.ofocluster/ofocluster.kubeconfig
```

## Create the Argo namespace

We will install various resources into this namespace in this guide and subsequent ones.

```bash
kubectl create namespace argo
```


## Create Kubernetes secrets

The Argo workflows require two Kubernetes secrets to be created:

### S3 credentials secret

The Argo workflows upload to and download from Jetstream2's S3-compatible buckets. You need to
create a secret to store the S3 Access ID, Secret Key, provider type, and endpoint URL. Obtain the access key ID and
secret access key from the OFO [Vaultwarden](http://vault.focal-lab.org) organization. The
credentials were originally created by Derek following [JS2
docs](https://docs.jetstream-cloud.org/general/object/) and particularly `openstack ec2 credentials
create`.

```bash
kubectl create secret generic s3-credentials \
  --from-literal=provider='Other' \
  --from-literal=endpoint='https://js2.jetstream-cloud.org:8001' \
  --from-literal=access_key='<YOUR_ACCESS_KEY_ID>' \
  --from-literal=secret_key='<YOUR_SECRET_ACCESS_KEY>' \
  -n argo
```

### Agisoft Metashape license secret

The photogrammetry workflow requires access to an Agisoft Metashape floating license server. Create
a secret to store the license server address. Obtain the license server IP address from the OFO
[Vaultwarden](http://vault.focal-lab.org) organization.

```bash
kubectl create secret generic agisoft-license \
  --from-literal=license_server='<LICENSE_SERVER_IP>:5842' \
  -n argo
```

Replace `<LICENSE_SERVER_IP>` with the actual IP address from the credentials document.

These secrets only need to be created once per cluster.

## Configure GPU node tainting

GPU nodes are tainted to prevent non-GPU workloads from being scheduled on them. This ensures that expensive GPU resources are reserved for workloads that actually need them. The taint is applied automatically by Node Feature Discovery (NFD) based on the presence of an NVIDIA GPU.

### Enable NFD taints

NFD is pre-installed on Jetstream2 Magnum clusters but taints are disabled by default. Enable them:

```bash
# Add NFD helm repo (if not already added)
helm repo add nfd https://kubernetes-sigs.github.io/node-feature-discovery/charts
helm repo update nfd

# Check current NFD version
helm list -n node-feature-discovery

# Enable taints (use the same version as currently installed)
helm upgrade node-feature-discovery nfd/node-feature-discovery \
  -n node-feature-discovery \
  --version <CURRENT_VERSION> \
  --reuse-values \
  --set master.config.enableTaints=true
```

### Enable mixed MIG strategy

The GPU Operator defaults to "single" MIG strategy, which exposes MIG slices as generic `nvidia.com/gpu` resources. For MIG nodegroups to expose specific resources like `nvidia.com/mig-2g.10gb`, enable "mixed" strategy:

```bash
# Add NVIDIA helm repo (if not already added)
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
helm repo update nvidia

# Check current GPU Operator version
helm list -n gpu-operator

# Enable mixed MIG strategy (use the same version as currently installed)
helm upgrade nvidia-gpu-operator nvidia/gpu-operator \
  -n gpu-operator \
  --version <CURRENT_VERSION> \
  --reuse-values \
  --set mig.strategy=mixed
```

!!! note "Cluster upgrades"
    This setting may be reset if the cluster template is upgraded and Magnum redeploys the GPU Operator. Re-run this command after cluster upgrades if MIG resources stop appearing.

### Apply GPU taint rule

Apply the NodeFeatureRule that automatically taints any node with an NVIDIA GPU:

```bash
kubectl apply -f setup/k8s/gpu-taint-rule.yaml
```

This creates a taint `nvidia.com/gpu=true:NoSchedule` on all GPU nodes. The taint is applied automatically when:

- A new GPU node joins the cluster (e.g., via autoscaler)
- An existing node gains a GPU label

### Verify taint (when GPU nodes exist)

```bash
kubectl get nodes -l nvidia.com/gpu.present=true -o custom-columns='NAME:.metadata.name,TAINTS:.spec.taints'
```

### How it works

- **CPU pods**: No toleration needed. Automatically excluded from tainted GPU nodes.
- **GPU pods**: Must have a toleration AND request GPU resources. See the `metashape-gpu-step` template in `photogrammetry-workflow-stepbased.yaml` for an example.
- **System pods**: Not affected. DaemonSets (GPU Operator, NFD, Calico, kube-proxy, etc.) have built-in tolerations that allow them to run on tainted nodes.


## Configure MIG (Multi-Instance GPU)

MIG partitions A100 GPUs into isolated slices, allowing multiple pods to share one physical GPU with hardware-level isolation. This is optional - standard GPU nodegroups work without MIG.

### MIG profiles

| Nodegroup pattern | MIG profile | Pods/GPU | VRAM each | Compute each |
|-------------------|-------------|----------|-----------|--------------|
| `mig1-*` | `all-1g.10gb` | 4 | 10GB | 1/7 |
| `mig2-*` | `all-2g.10gb` | 3 | 10GB | 2/7 |
| `mig3-*` | `all-3g.20gb` | 2 | 20GB | 3/7 |

### Apply MIG configuration rule

```bash
kubectl apply -f setup/k8s/mig-nodegroup-labels.yaml
```

This creates a NodeFeatureRule that automatically labels GPU nodes based on their nodegroup name. The NVIDIA MIG manager watches for these labels and configures the GPU accordingly.

### Verify MIG is working

After creating a MIG nodegroup (see [MIG nodegroups](../usage/cluster-access-and-resizing.md#mig-nodegroups)):

```bash
# Check node MIG config label
kubectl get nodes -l nvidia.com/mig.config -o custom-columns='NAME:.metadata.name,MIG_CONFIG:.metadata.labels.nvidia\.com/mig\.config'

# Check MIG resources are available
kubectl get nodes -o custom-columns='NAME:.metadata.name,MIG-1G:.status.allocatable.nvidia\.com/mig-1g\.10gb,MIG-2G:.status.allocatable.nvidia\.com/mig-2g\.10gb,MIG-3G:.status.allocatable.nvidia\.com/mig-3g\.20gb'
```

### How it works

1. User creates nodegroup with MIG naming (e.g., `mig2-group`)
2. Node joins cluster with name containing `-mig2-`
3. NFD applies label `nvidia.com/mig.config=all-2g.10gb`
4. MIG manager detects label, configures GPU into 3 partitions
5. Device plugin exposes `nvidia.com/mig-2g.10gb: 3` as allocatable resources
6. Pods requesting `nvidia.com/mig-2g.10gb: 1` get one partition


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

### Rotating secrets

If you accidentally expose a secret, or for periodic rotation, delete, then re-create. Example for
S3 (assuming your S3 is via JS2 Swift):

List creds to get the ID of the cred you want to swap out: `openstack ec2 credentials list`
Delete it: `openstack ec2 credentials delete <your-access-key-id>`
Create a new one: `openstack ec2 credentials create`
Update it in [Vaultwarden](http://vault.focal-lab.org).
Delete the k8s secret: `kubectl delete secret -n argo s3-credentials`
Re-create k8s secret following the instructions above.
If you have already installed Argo on the cluster, restart the workflow controller so it picks up
the new creds: `kubectl rollout restart deployment workflow-controller -n argo`



## Cluster resizing

These instructions are for managing which nodes are in the cluster, not what software is running on them.

### Resize the default worker group

Resize the cluster by adding or removing nodes from the original worker group (not a later-added nodegroup). We will likely not do this, relying instead on nodegroups for specific runs.

```bash
openstack coe cluster resize "ofocluster" 4
```

### Add, resize, or delete nodegroups

For nodegroup management, see the corresponding [user guide](../usage/cluster-access-and-resizing.md).

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


## Notes from testing and experimentation attempting to set up autoscaling and fixed nodegroups

It seems impossible to set new (or override existing) labels when adding
nodegroups. Labels only seem to be intended/used for overall cluster creation. Also if
we deploy one nodegroup that violates the requirement for min_node_count to be specified, cannot
deploy any others (they all fail), even if they would have succeeded otherwise.

By not specifying a label `max_node_count` upon cluster creation, the default-worker nodegroup will
not autoscale. But still we need to set the label `auto_scaling_enabled` to `true` upon cluster
creation because cluster labels apparently cannot be overridden by nodegroups. This means that all
nodegroups will autoscale, and we are required to specify `--min-nodes`, or nodegroup clreation will
fail. If you don't specify `--max-nodes` when creating a nodegroup, it treats the `--node-count` as
the max and may scale down to the min.

I tried creating a cluster with no scaling (max nodes 1 and auto_scaling_enabled=false) and then
overriding it at the nodegroup level with values that should enable scaling, but it didn't scale
(apparently these values get overridden). Also tried not specifying
auto_scale_enabled label at all, but then specifying it for nodegroups, but these nodegroups did not
scale. Learned that `--node-count` needs to be within the range of the min and max (if omitted, it
is assumed to be 1).

### Testing/monitoring autoscaling behavior

Deploy a bunch of pods that will need to get scheduled:
```bash
kubectl create deployment scale-test --image=nginx --replicas=20 -- sleep infinity && kubectl set resources deployment scale-test --requests=cpu=500m,memory=512Mi
```

Make sure some become pending (which should trigger a scale up):
```bash
kubectl get pods
```

Monitor the cluster autoscaler status to see if it is planning any scaling up or down:
```bash
kubectl get configmap cluster-autoscaler-status -n kube-system -o yaml
```

When finished, delete the test deployment:
```bash
kubectl delete deployment scale-test
```

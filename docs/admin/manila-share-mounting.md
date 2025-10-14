# Manila share mounting

This guide covers mounting a Manila CephFS share to your Kubernetes cluster for persistent storage.

## Prerequisites

- A Kubernetes cluster created with Magnum (see [Cluster Creation guide](cluster-creation-and-resizing.md))
- `kubectl` configured to connect to the cluster
- OpenStack application credentials
- The Manila share already created in OpenStack

## One-time local machine software setup

Ensure your local system has the necessary tools. First, activate the OpenStack virtual environment created in the cluster creation guide.

Additionally, we need OpenStack app credentials to look up the parameters of our Manila share based
on its name, which in turn requires an additional OpenStack command-line tool for interacting with Manila. An alternative is to look these up from some other existing source (e.g. Horizon UI)
and provide them manually, in which case the OpenStack system tools are not necessary.

```bash
source ~/venv/openstack/bin/activate
source ~/.ofocluster/app-cred-ofocluster-openrc.sh

# Install Manila client and jq
pip install -U python-manilaclient
sudo apt install -y jq

# Install Helm
sudo snap install helm --classic
```

If returning to this after a reboot, and you know you already have the necessary tools, you still need to source the OpenStack environment and application credentials:

```bash
source ~/venv/openstack/bin/activate
source ~/.ofocluster/app-cred-ofocluster-openrc.sh
```

## Install the Ceph CSI driver on the cluster

The Ceph CSI (Container Storage Interface) driver enables Kubernetes to mount CephFS shares.

```bash
# Add Helm repository
helm repo add ceph-csi https://ceph.github.io/csi-charts
helm repo update

# Create namespace for Ceph CSI
kubectl create namespace ceph-csi-cephfs

# Install Ceph CSI driver
helm install --namespace "ceph-csi-cephfs" "ceph-csi-cephfs" ceph-csi/ceph-csi-cephfs

# Check installation status
helm status --namespace "ceph-csi-cephfs" "ceph-csi-cephfs"
```

## Look up Manila share parameters

Based on the share name and access rule name, query OpenStack to look up the necessary identifiers. The Kubernetes Manila config requires these values.

```bash
# Set your Manila share and access rule names
MANILA_SHARE_NAME=dytest3
export MANILA_ACCESS_RULE_NAME=dytest3-rw

# Extract Manila monitors (json-formatted list)
export MANILA_MONITORS_JSON=$(openstack share export location list "$MANILA_SHARE_NAME" -f json | jq -r '.[0].Path | split(":/")[0] | split(",") | map("\"" + . + "\"") | join(",")')

# Extract the root path to the Manila share
export MANILA_ROOT_PATH=$(openstack share export location list $MANILA_SHARE_NAME -f json | jq -r '.[0].Path' | awk -F':/' '{print "/"$2}')

# Get the access rule ID
ACCESS_RULE_ID=$(openstack share access list "$MANILA_SHARE_NAME" -f json | jq -r ".[] | select(.\"Access To\" == \"$MANILA_ACCESS_RULE_NAME\") | .ID")

# Extract the secret key for the access rule
export MANILA_ACCESS_KEY=$(openstack share access list "$MANILA_SHARE_NAME" -f json | jq -r ".[] | select(.\"Access To\" == \"$MANILA_ACCESS_RULE_NAME\") | .\"Access Key\"")

# Confirm we extracted the expected attributes
echo $MANILA_MONITORS_JSON
echo $MANILA_ROOT_PATH
echo $MANILA_ACCESS_RULE_NAME
echo $MANILA_ACCESS_KEY
```

As an alternative, you can look these parameters up in [Horizon](https://js2.jetstream-cloud.org).

## Clone or update the ofo-argo repository

The repository contains Kubernetes configuration templates for Manila share mounting.

```bash
# Clone the repository (first time)
cd ~/repos
git clone https://github.com/open-forest-observatory/ofo-argo
cd ofo-argo
```

Or, if you already have the repository cloned:

```bash
# Update existing repository
cd ~/repos/ofo-argo
git pull
```

## Apply the share configuration to the cluster

There is a [template Kubernetes config file](../../setup/k8s/manila-cephfs-csi-conifg.yaml) that contains variables such as
`${MANILA_ACCESS_RULE_NAME}`. These variables will be substituted with the environment variables we
prepared in the previous step. The following command substitutes the environment variables into the
config file and applies it to the cluster. It's done in one step so we don't save this file (which
contains secrets) to disk.

Note that the namespaces of the various resources are defined within the yaml, so `-n` does not have to be used here. If namespaces ever need to change, update the config yaml.

```bash
# Create the namespace for the PVC and Argo application
kubectl create namespace argo

# Substitute variables and apply configuration
envsubst < setup/k8s/manila-cephfs-csi-conifg.yaml | kubectl apply -f -

# Verify resources were created
kubectl describe secret -n ceph-csi-cephfs manila-share-secret
kubectl describe persistentvolume ceph-share-rw-pv
kubectl describe -n argo persistentvolumeclaim ceph-share-rw-pvc
```

## Test the PVC mount

Deploy a test pod to verify that the PVC mount works correctly.

**Note**: During development, we sometimes encountered the error `MountVolume.MountDevice failed for volume "ceph-share-rw-pv" : rpc error: code = Internal desc = rpc error: code = Internal desc = failed to fetch monitor list using clusterID (12345): missing configuration for cluster ID "12345"`. If this occurs, try deleting all deployed resources except the configmap and re-applying them. It may also be resolved by simply deleting and re-applying the test pod.

```bash
# Deploy test pod
kubectl apply -f setup/k8s/manila-test-pod.yaml

# Check pod status
kubectl get pod -n argo manila-test-pod
kubectl describe pod -n argo manila-test-pod

# Once running, exec into the pod
kubectl exec -n argo -it manila-test-pod -- /bin/sh

# Inside the pod, check the mount
ls -la /mnt/cephfs
df -h /mnt/cephfs

# Test write access
echo "test" > /mnt/cephfs/test-file.txt
cat /mnt/cephfs/test-file.txt

# Exit the pod
exit
```

### Clean up test resources

After verifying the mount works, delete the test pod:

```bash
kubectl delete -n argo pod manila-test-pod
```

## Delete all resources (if needed)

If you need to completely remove the Manila share mounting configuration:

```bash
kubectl delete -n argo pod manila-test-pod
kubectl delete -n argo pvc ceph-share-rw-pvc
kubectl delete pv ceph-share-rw-pv
kubectl delete -n ceph-csi-cephfs secret manila-share-secret
kubectl delete configmap -n ceph-csi-cephfs ceph-csi-config
```

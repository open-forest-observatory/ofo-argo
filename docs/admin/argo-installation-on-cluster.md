---
title: Argo installation on cluster
weight: 15
---

# Argo installation on cluster

This guide covers the installation of Argo Workflows, including the CLI on your local machine (required for all users) and the Kubernetes extension on the cluster (one-time admin installation).

## Prerequisites

This guide assumes you already have:

- A Kubernetes cluster created (see [Cluster creation and resizing](cluster-creation-and-resizing.md))
- Manila share PV and PVC configured (see [Manila share mounting](manila-share-mounting.md))
- `kubectl` configured to connect to the cluster

## Clone or update the ofo-argo repository

This repository contains files needed for deploying and testing Argo.

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

## Install the Argo CLI locally (one-time)

The Argo CLI is a wrapper around `kubectl` that simplifies communication with Argo on the cluster.

```bash
ARGO_WORKFLOWS_VERSION="v3.7.6"
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

## Install Argo workflow manager and server on the cluster

Create the Argo namespace and install Argo components:

```bash
# Create namespace
kubectl create namespace argo

# Install Argo workflows on cluster
kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/${ARGO_WORKFLOWS_VERSION}/install.yaml
```

Optionally, check that the pods are running:

```bash
kubectl get pods -n argo
kubectl describe pod -n argo <pod-name>
```

## Configure workflow permissions

The standard `install.yaml` configures permissions for the workflow controller, but does not configure permissions for the service accounts that workflow pods run as. Without these permissions, workflows will fail with an error like:

> workflowtaskresults.argoproj.io is forbidden: User "system:serviceaccount:argo:argo" cannot create resource "workflowtaskresults"

This step grants the `argo` service account (used by all our workflows via `serviceAccountName: argo`) the minimal permissions needed to create and update workflowtaskresults.

```bash
# Apply role and role binding
kubectl apply -f setup/argo/workflow-executor-rbac.yaml

# Confirm the necessary permission was granted (should return: yes)
kubectl auth can-i create workflowtaskresults.argoproj.io -n argo --as=system:serviceaccount:argo:argo
```

## Configure workflow controller: Delete completed pods, and use S3 for artifact and log storage

Argo Workflows can store workflow logs and artifacts in S3-compatible object storage. Also, it can
be configured to delete pods once they are done running (whether successful or unsuccessful). Given
we are storing pod logs in S3 (we don't require the pod to be in existence in order for Arto to access its logs
through kubernetes), there is no reason to keep pods around after they finish running. This section
configures Argo to use JS2 (Jetstream2) object storage for logs and to remove workflow pods that
have completed running. All of this is in support of configuring workflows to preferentially
schedule pods on nodes that have other running pods on them (to minimize the chances of being
evicted from an underutilized node that is being deleted by the autoscaler).

### Prerequisites

The S3 credentials secret must exist in the `argo` namespace. This secret should contain:
- `access_key`: Your S3 access key
- `secret_key`: Your S3 secret key

To verify the secret exists:

```bash
kubectl get secret s3-credentials -n argo
```

If it doesn't exist, create it (replacing placeholders with your actual credentials):

```bash
kubectl create secret generic s3-credentials -n argo \
  --from-literal=access_key='YOUR_ACCESS_KEY' \
  --from-literal=secret_key='YOUR_SECRET_KEY' \
  --from-literal=endpoint='https://js2.jetstream-cloud.org:8001' \
  --from-literal=provider='Other'
```

### Apply the workflow controller configuration

The workflow controller configmap tells Argo where to store artifacts and logs. Apply it:

```bash
kubectl apply -f setup/argo/workflow-controller-configmap.yaml
```

This configures:
- **Bucket**: `ofo-internal`
- **Path prefix**: `argo-logs-artifacts/`
- **Log archiving**: Enabled (workflow logs are stored in S3)
- **Key format**: `argo-logs-artifacts/{workflow-name}/{pod-name}`

### Restart the workflow controller

The workflow controller needs to be restarted to pick up the new configuration:

```bash
kubectl rollout restart deployment workflow-controller -n argo
kubectl rollout status deployment workflow-controller -n argo
```

### Verify the configuration

Check that the configmap was applied correctly:

```bash
kubectl get configmap workflow-controller-configmap -n argo -o yaml
```

You should see the `artifactRepository` section with the S3 configuration.

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
- **GPU pods**: Must have a toleration (configured in workflow templates) AND request GPU resources.
- **Pod affinity**: All pods still inherit `podAffinity` from `workflow-controller-configmap` to prefer nodes with running pods.

## Test the installation

Run a test workflow to verify everything is working:

```bash
argo submit -n argo test-workflows/dag-diamond.yaml --watch
```

## Set up Argo server with HTTPS access

The following steps configure secure external access to the Argo UI.

### Verify Argo server is ClusterIP

Ensure `argo-server` is set to ClusterIP, which means it's only accessible from within the cluster's internal network. We'll configure a secure gateway to the internet next.

```bash
# Check current type
kubectl get svc argo-server -n argo

# If it's LoadBalancer, change it back to ClusterIP
kubectl patch svc argo-server -n argo -p '{"spec":{"type":"ClusterIP"}}'

# Verify (should show: TYPE = ClusterIP)
kubectl get svc argo-server -n argo
```

### Install cert-manager

```bash
# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml

# Wait for cert-manager to be ready (takes 5-60 seconds)
kubectl wait --for=condition=available --timeout=300s deployment/cert-manager -n cert-manager
kubectl wait --for=condition=available --timeout=300s deployment/cert-manager-webhook -n cert-manager
kubectl wait --for=condition=available --timeout=300s deployment/cert-manager-cainjector -n cert-manager
```

### Install nginx ingress controller

```bash
# Install nginx ingress controller
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/cloud/deploy.yaml

# Wait for LoadBalancer IP to be assigned (may take 1-3 minutes)
kubectl get svc -n ingress-nginx ingress-nginx-controller -w

# Press Ctrl+C once you see an EXTERNAL-IP appear. Save this IP - you'll need it for DNS.
```

### Create DNS A record

Go to your DNS provider (GoDaddy, Cloudflare, Route53, etc.) and create:

- **Type**: A
- **Name**: argo (or your preferred subdomain) (in Netlify DNS, replace the `@` with `argo`)
- **Value**: `<IP from previous step>`
- **TTL**: 300 (or auto/default)

### Create Let's Encrypt cluster issuer

```bash
kubectl apply -f setup/argo/clusterissuer-letsencrypt.yaml
```

### Create ingress resource for Argo server

```bash
kubectl apply -f setup/argo/ingress-argo.yaml
```

Wait 1-10 minutes for DNS records to propagate, then verify:

```bash
nslookup argo.focal-lab.org
```

This should return the ingress controller IP. A "non-authoritative answer" from DNS queries is OK.

### Request and wait for certificate

```bash
# Watch certificate being issued (usually 1-3 minutes)
kubectl get certificate -n argo -w

# Wait until you see READY show True:
# NAME              READY   SECRET           AGE
# argo-server-tls   True    argo-server-tls  2m

# Press Ctrl+C when READY shows True
```

### Verify Argo UI access

The Argo UI should now be accessible at https://argo.focal-lab.org

Verification commands:

```bash
# Check all components are ready
kubectl get pods -n cert-manager
kubectl get pods -n ingress-nginx
kubectl get pods -n argo

# Check ingress created
kubectl get ingress -n argo

# Check certificate issued
kubectl get certificate -n argo

# Check DNS resolves
nslookup argo.focal-lab.org
```

## Create Argo UI server token

Create a token that lasts one year. This token will need to be re-created annually.

We're creating this for the `default` service account. In the future, we may want to create a dedicated service account for argo-server tokens, or separate accounts for each user to allow individual permission management.

```bash
# Create token (valid for 1 year)
kubectl create token argo-server -n argo --duration=8760h
```

Copy the token, preface it with `Bearer `, and add/update it in [Vaultwarden](http://vault.focal-lab.org).

### Token rotation (future)

To rotate the token in the future:

```bash
# Delete all tokens for the service account
kubectl delete secret -n argo -l kubernetes.io/service-account.name=argo-server
```

Then recreate it with the command above.

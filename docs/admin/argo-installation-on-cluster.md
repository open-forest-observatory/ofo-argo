# Argo installation on cluster

This guide covers the installation of Argo Workflows, including the CLI on your local machine (required for all users) and the Kubernetes extension on the cluster (one-time admin installation).

## Prerequisites

This guide assumes you already have:

- A Kubernetes cluster created (see [Cluster Creation guide](cluster-creation-and-resizing.md))
- Manila share PV and PVC configured (see [Manila Share Mounting guide](manila-share-mounting.md))
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

## Install Argo workflow manager and server on the cluster

Create the Argo namespace and install Argo components:

```bash
# Create namespace
kubectl create namespace argo

# Install Argo workflows
kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/${ARGO_WORKFLOWS_VERSION}/install.yaml
```

Optionally, check that the pods are running:

```bash
kubectl get pods -n argo
kubectl describe pod -n argo <pod-name>
```

## Configure workflow permissions

The standard `install.yaml` configures permissions for the workflow controller, but does not configure permissions for the service accounts that workflow pods run as. Without these permissions, the executor will fall back to the legacy insecure pod patch method. This step grants the `default` service account the minimal permissions needed to create and update workflowtaskresults.

If you use custom service accounts in your workflows, you'll need to create additional RoleBindings for those accounts.

```bash
# Apply role and role binding
kubectl apply -f setup/argo/role-rolebinding-default-create.yaml

# Confirm the necessary permission was granted (should return: yes)
kubectl auth can-i create workflowtaskresults.argoproj.io -n argo --as=system:serviceaccount:argo:default

# Optional: Describe the roles
kubectl describe role argo-role -n argo
kubectl describe role executor -n argo
```

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

# Wait for cert-manager to be ready (takes ~1 minute)
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
- **Name**: argo (or your preferred subdomain)
- **Value**: `<IP from previous step>`
- **TTL**: 300 (or auto/default)

A "non-authoritative answer" from DNS queries is OK.

### Create Let's Encrypt cluster issuer

```bash
kubectl apply -f setup/argo/clusterissuer-letsencrypt.yaml
```

### Create ingress resource for Argo server

```bash
kubectl apply -f setup/argo/ingress-argo.yaml
```

Wait 5-10 minutes for DNS records to propagate, then verify:

```bash
nslookup argo.focal-lab.org
# Should return the ingress controller IP
```

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

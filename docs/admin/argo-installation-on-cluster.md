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
Use the same version for the CLI as for the cluster installation below (`ARGO_WORKFLOWS_VERSION` is
reused there).

```bash
ARGO_WORKFLOWS_VERSION="v4.1.6"
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

We install Argo with [Kustomize](https://kustomize.io/) (built into `kubectl`), using
`setup/argo/kustomization.yaml`. It combines:

- the official Argo release manifest (`install.yaml`), pinned to a specific Argo version
- our workflow controller configuration (`workflow-controller-configmap.yaml`), merged into the
  release's empty `workflow-controller-configmap`
- the service account and permissions that workflow pods run with (`workflow-executor-rbac.yaml`)
- the service account and token for logging in to the Argo UI (`argo-ui-access.yaml`)

Because our configuration is part of the same install, it can't be lost by re-installing or
upgrading Argo. (Applying `install.yaml` on its own replaces the controller configuration with an
empty one; this happened on our cluster around May 2026 and went unnoticed for five months. Never
apply `install.yaml` directly; always use the kustomization.)

### Create the namespace and S3 credentials

```bash
kubectl create namespace argo
```

The workflow controller configuration stores workflow logs and artifacts in S3, using the
`s3-credentials` secret in the `argo` namespace. Check whether it exists:

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

### Install Argo

```bash
# Set the Argo version in the kustomization to match the CLI (ARGO_WORKFLOWS_VERSION, set above)
sed -i -E "s#(argo-workflows/releases/download/)[^/]+(/install\.yaml)#\1${ARGO_WORKFLOWS_VERSION:?not set - set it as in the CLI install step}\2#" setup/argo/kustomization.yaml
grep "releases/download" setup/argo/kustomization.yaml   # confirm the version

# Install
kubectl apply --server-side -k setup/argo
```

`--server-side` is required as of Argo v4.0: the release manifests ship CRDs with full validation
schemas, and the largest ones exceed the size limit of the annotation that a regular (client-side)
`kubectl apply` writes (the error is `metadata.annotations: Too long: may not be more than 262144
bytes`). If the command reports field-manager conflicts (e.g. on a cluster where Argo was
previously installed differently), re-run it with `--force-conflicts` added.

The Argo version is set by the `install.yaml` URL in `setup/argo/kustomization.yaml`; the `sed`
command sets it from `ARGO_WORKFLOWS_VERSION` so the cluster and CLI versions match. If it changed
the file, commit the change so the repo records the version that's installed.

### Verify the installation

```bash
# All 8 Argo CRDs exist
kubectl get crd | grep argoproj.io

# argo-server and workflow-controller are Running
kubectl get pods -n argo

# Our configuration is present: data should include workflowDefaults and artifactRepository
kubectl get configmap workflow-controller-configmap -n argo -o yaml

# Workflow pods' service account has the permissions it needs (should return: yes)
kubectl auth can-i create workflowtaskresults.argoproj.io -n argo --as=system:serviceaccount:argo:argo-workflow
```

### What's configured

**Workflow permissions** (`workflow-executor-rbac.yaml`). Workflow pods run as a dedicated
`argo-workflow` service account that has only the minimal permissions Argo's executor needs (create
and patch `workflowtaskresults`), following
[Argo's workflow RBAC guidance](https://argo-workflows.readthedocs.io/en/latest/workflow-rbac/).
Workflows use it by default via `workflowDefaults` in the controller configuration, so individual
workflows don't set `serviceAccountName`. Workflows should not run as the `argo` service account: it
belongs to the workflow controller and has cluster-wide permissions (creating, exec-ing into, and
deleting any pod; reading all secrets) that every workflow container would inherit. Without the
executor permissions, workflows fail with an error like:

> workflowtaskresults.argoproj.io is forbidden: User "system:serviceaccount:argo:argo-workflow" cannot create resource "workflowtaskresults"

**Workflow controller** (`workflow-controller-configmap.yaml`). Argo stores workflow logs and
artifacts in JS2 (Jetstream2) S3-compatible object storage, and deletes workflow pods once they
finish (successfully or not). Since logs are in S3, Argo doesn't need the pods to exist to show
their logs. Deleting finished pods supports configuring workflows to preferentially schedule pods on
nodes that have other running pods on them (to minimize the chances of being evicted from an
underutilized node that is being deleted by the autoscaler). Settings:

- **Workflow service account**: `argo-workflow`
- **Pod GC**: delete each pod when it completes
- **Eviction protection**: pods are annotated so the cluster autoscaler won't evict them
- **Pod packing**: pods prefer nodes running other in-progress workflow pods
- **Log S3 bucket**: `ofo-internal`
- **Log path prefix**: `argo-logs-artifacts/`
- **Log archiving**: Enabled (workflow logs are stored in S3)
- **Log key format**: `argo-logs-artifacts/{workflow-name}/{pod-name}`

To confirm logs are actually reaching S3, check that a recently completed workflow has a folder in
the bucket:

```bash
rclone lsf js2s3:ofo-internal/argo-logs-artifacts/<workflow-name>/
```

### Changing the configuration or upgrading Argo

Edit the files in `setup/argo/` as needed. To upgrade Argo, first check Argo's
[upgrading guide](https://argo-workflows.readthedocs.io/en/latest/upgrading/) for breaking changes,
update the CLI ([Install the Argo CLI locally](#install-the-argo-cli-locally-one-time)) with the new
`ARGO_WORKFLOWS_VERSION`, then set the same version in the kustomization:

```bash
# Set the Argo version in the kustomization to match the CLI (ARGO_WORKFLOWS_VERSION, set above)
sed -i -E "s#(argo-workflows/releases/download/)[^/]+(/install\.yaml)#\1${ARGO_WORKFLOWS_VERSION:?not set - set it as in the CLI install step}\2#" setup/argo/kustomization.yaml
grep "releases/download" setup/argo/kustomization.yaml   # confirm the version
```

Then re-apply the kustomization and restart the workflow controller so it picks up configuration
changes, and commit the changed files:

```bash
kubectl apply --server-side -k setup/argo
kubectl rollout restart deployment workflow-controller -n argo
kubectl rollout status deployment workflow-controller -n argo
```

## Test the installation

Run a test workflow to verify everything is working:

```bash
argo submit -n argo test-workflows/dag-diamond.yaml --watch
```

## Set up Argo server with HTTPS access

The following steps expose the Argo UI at `https://$ARGO_HOSTNAME`. The current cluster
(`ofocluster3`) uses `argo3.focal-lab.org` while the previous cluster still serves
`argo.focal-lab.org`. Once the old cluster is retired, point `argo.focal-lab.org` at the new
cluster, set `ARGO_HOSTNAME="argo.focal-lab.org"`, and re-run the gateway step. Set the hostname to
use:

```bash
ARGO_HOSTNAME="argo3.focal-lab.org"
```

How it works:

- [Envoy Gateway](https://gateway.envoyproxy.io/) (a [Gateway API](https://gateway-api.sigs.k8s.io/)
  implementation) receives traffic from the internet on a public IP, terminates HTTPS with a Let's
  Encrypt certificate, and redirects HTTP to HTTPS.
- [cert-manager](https://cert-manager.io/) obtains and automatically renews the Let's Encrypt
  certificate.
- Envoy forwards requests to `argo-server` over HTTPS inside the cluster. `argo-server` uses its
  default self-signed certificate, which Envoy is configured not to verify, so in-cluster traffic is
  encrypted but the backend certificate isn't authenticated.

!!! note "Why not ingress-nginx"
    Earlier versions of this guide used the ingress-nginx controller. That project was
    [retired](https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/) in March 2026 and no
    longer receives security fixes; Kubernetes recommends migrating to Gateway API.

### Verify Argo server is ClusterIP

Ensure `argo-server` is set to ClusterIP, which means it's only accessible from within the cluster's internal network. The gateway provides the secure entry point from the internet.

```bash
# Check current type
kubectl get svc argo-server -n argo

# If it's LoadBalancer, change it back to ClusterIP
kubectl patch svc argo-server -n argo -p '{"spec":{"type":"ClusterIP"}}'

# Verify (should show: TYPE = ClusterIP)
kubectl get svc argo-server -n argo
```

### Install Envoy Gateway

This also installs the Gateway API CRDs (v1.6.1, experimental channel). Install it before
cert-manager, which needs those CRDs to exist when it starts.

```bash
ENVOY_GATEWAY_VERSION="v1.10.0"

helm install eg oci://docker.io/envoyproxy/gateway-helm --version ${ENVOY_GATEWAY_VERSION} \
  -n envoy-gateway-system --create-namespace \
  --set config.envoyGateway.extensionApis.enableBackend=true

kubectl wait --timeout=5m -n envoy-gateway-system deployment/envoy-gateway --for=condition=Available
```

`enableBackend=true` enables Envoy Gateway's `Backend` resource (an alpha API), which we use to
connect to `argo-server`'s self-signed HTTPS endpoint without verifying its certificate.

### Install cert-manager

```bash
CERT_MANAGER_VERSION="v1.21.3"

helm install cert-manager oci://quay.io/jetstack/charts/cert-manager --version ${CERT_MANAGER_VERSION} \
  -n cert-manager --create-namespace \
  --set crds.enabled=true \
  --set config.gatewayAPI.enabled=true

kubectl wait --for=condition=available --timeout=300s deployment/cert-manager -n cert-manager
kubectl wait --for=condition=available --timeout=300s deployment/cert-manager-webhook -n cert-manager
kubectl wait --for=condition=available --timeout=300s deployment/cert-manager-cainjector -n cert-manager
```

`config.gatewayAPI.enabled=true` turns on cert-manager's Gateway API support (beta), which lets it
issue certificates for Gateways and solve Let's Encrypt challenges through them.

### Create Let's Encrypt issuer

```bash
kubectl apply -f setup/argo/issuer-letsencrypt.yaml
```

This is a namespaced `Issuer` in `argo`, since that's the only namespace that needs certificates.

### Create the gateway and routes for Argo server

```bash
# Substitutes ARGO_HOSTNAME for argo.focal-lab.org (no change if they're the same)
sed "s/argo\.focal-lab\.org/${ARGO_HOSTNAME:?not set - see the start of this section}/g" setup/argo/gateway-argo.yaml | kubectl apply -f -
```

This creates the `eg` GatewayClass, the `argo-gateway` Gateway (HTTP on port 80, HTTPS on port 443
for `$ARGO_HOSTNAME`), the HTTP-to-HTTPS redirect, and the route to `argo-server`. See the
comments in the file for details. Envoy Gateway then creates a LoadBalancer service for the gateway,
which gets a public IP.

```bash
# Wait for the gateway to get its public IP (may take 1-3 minutes); the ADDRESS column shows it.
# Save this IP - you'll need it for DNS.
kubectl get gateway argo-gateway -n argo -w
```

Press Ctrl+C once the ADDRESS appears. (`PROGRAMMED` may stay `False` until the certificate is
issued below.)

### Create DNS A record

Go to your DNS provider (GoDaddy, Cloudflare, Route53, etc.) and create (or update, if moving to a
new cluster):

- **Type**: A
- **Name**: the subdomain part of `$ARGO_HOSTNAME`, e.g. `argo` (in Netlify DNS, replace the `@` with `argo`)
- **Value**: `<gateway IP from previous step>`
- **TTL**: 300 (or auto/default)

Wait 1-10 minutes for DNS records to propagate, then verify:

```bash
nslookup ${ARGO_HOSTNAME}
```

This should return the gateway IP. A "non-authoritative answer" from DNS queries is OK.

### Wait for certificate

cert-manager creates the certificate automatically from the annotation on the Gateway. Let's
Encrypt can only validate it once DNS points at the gateway, so it may take a few minutes after the
DNS step.

```bash
# Watch certificate being issued (usually 1-3 minutes after DNS resolves)
kubectl get certificate -n argo -w

# Wait until you see READY show True:
# NAME              READY   SECRET           AGE
# argo-gateway-tls  True    argo-gateway-tls 2m

# Press Ctrl+C when READY shows True
```

If it stays `False`, check progress with `kubectl describe certificate argo-gateway-tls -n argo` and
`kubectl get challenges -n argo`. cert-manager renews the certificate automatically before it
expires.

### Verify Argo UI access

The Argo UI should now be accessible at `https://$ARGO_HOSTNAME` (and http:// should redirect to
https://).

Verification commands:

```bash
# Check all components are ready
kubectl get pods -n envoy-gateway-system
kubectl get pods -n cert-manager
kubectl get pods -n argo

# Check gateway is programmed (PROGRAMMED = True) and routes are accepted
kubectl get gateway argo-gateway -n argo
kubectl get httproute -n argo

# Check certificate issued
kubectl get certificate -n argo

# Check DNS resolves
nslookup ${ARGO_HOSTNAME}
```

## Create Argo UI access token

The Argo UI uses `client` auth mode (the default): you log in by pasting a Kubernetes service
account token, and you get that service account's permissions. We use a dedicated `argo-ui`
service account (created by the kustomization, from `setup/argo/argo-ui-access.yaml`), scoped to
the `argo` namespace, with permission to manage workflows (including deleting their pods, which
retrying a workflow requires) and view their pods, logs, and events.
(Don't use a token for the `argo-server` service account: it has cluster-wide permissions,
including reading all secrets and exec-ing into pods.)

```bash
# Print the token
kubectl get secret argo-ui.service-account-token -n argo -o jsonpath='{.data.token}' | base64 --decode; echo
```

Copy the token, preface it with `Bearer `, and add/update it in [Vaultwarden](http://vault.focal-lab.org).
Then confirm you can log in at `https://$ARGO_HOSTNAME`, open a completed workflow, and view its
logs (which come from S3).

The token does not expire. It stays valid until its secret is deleted, or the cluster is rebuilt.

### Token rotation

To revoke the current token and issue a new one (e.g. if it may have leaked):

```bash
# Revoke: deleting the secret immediately invalidates the token
kubectl delete secret argo-ui.service-account-token -n argo

# Re-apply to create a new token secret, then print it as above and update Vaultwarden
kubectl apply --server-side -k setup/argo
kubectl get secret argo-ui.service-account-token -n argo -o jsonpath='{.data.token}' | base64 --decode; echo
```

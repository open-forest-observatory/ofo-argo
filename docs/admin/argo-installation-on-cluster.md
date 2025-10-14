Steps for installing Argo, including installing the CLI on your local machine (all users need this) and the Kubernetes extension on the cluster (only the Admin has to install this once)

This guide assumes you already have a cluster, with a Manila share PV and PVC configured, and that you have kubectl to the cluster configured, following the steps in the cluster creation guide.

## Clone the ofo-argo repo locally (or update it if already present)

This repo contains files you’ll need for deploying Argo and testing the deployment.

`cd ~/repos`  
`git clone https://github.com/open-forest-observatory/ofo-argo`  
`cd ofo-argo`

OR, pull from existing repo

`cd ~/repos/ofo-argo`  
`git pull`

## One-time installation of the Argo CLI locally

This tool allows you to more easily communicate with Argo on the cluster. It is a wrapper around kubectl.

`ARGO_WORKFLOWS_VERSION="v3.7.2"`  
`ARGO_OS="linux"`

`wget "https://github.com/argoproj/argo-workflows/releases/download/${ARGO_WORKFLOWS_VERSION}/argo-${ARGO_OS}-amd64.gz"`

`# Unzip`  
`gunzip "argo-$ARGO_OS-amd64.gz"`

`# Make binary executable`  
`chmod +x "argo-$ARGO_OS-amd64"`

`# Move binary to path`  
`sudo mv "./argo-$ARGO_OS-amd64" /usr/local/bin/argo`

`# Test installation`  
`argo version`

## Install Argo workflow manager and server on the cluster

## kubectl create namespace argo

kubectl apply \-n argo \-f [https://github.com/argoproj/argo-workflows/releases/download/](https://github.com/argoproj/argo-workflows/releases/download/v3.6.5/install.yaml)`${ARGO_WORKFLOWS_VERSION}`[/install.yaml](https://github.com/argoproj/argo-workflows/releases/download/v3.6.5/install.yaml)

(Optional) Check that the pods are running and what nodes they are on.  
`kubectl get pods -n argo`  
`kubectl describe pod -n argo <pod-name>`

The standard `install.yaml` configures permissions for the workflow controller, but does not configure permissions for the service accounts that workflow pods run as. Without these permissions, the executor will fall back to the legacy insecure pod patch method, which requires broader permissions and is a security risk. This step grants the `default` service account (used by workflow pods unless otherwise specified) the minimal permissions needed to create and update workflowtaskresults. If you use custom service accounts in your workflows, you'll need to create additional RoleBindings for those accounts as well.

`kubectl apply -f argo-setup/role-rolebinding-default-create.yaml`

Confirm the necessary permission was granted

`kubectl auth can-i create workflowtaskresults.argoproj.io -n argo --as=system:serviceaccount:argo:default`  
`# Should return: yes`

`kubectl describe role argo-role -n argo`  
`kubectl describe role executor -n argo`

Run a test workflow

`argo submit -n argo test-workflows/dag-diamond.yaml --watch`

## Set up argo server

Ensure argo-server is ClusterIP, which means it is only accessible from within the cluster’s internal network. This is good because we don’t want it served directly to the internet. We will configure a more secure gateway to the internet next.

*\# Check current type*  
*kubectl get svc argo-server \-n argo*

*\# If it's LoadBalancer, change it back to ClusterIP*  
*kubectl patch svc argo-server \-n argo \-p '{"spec":{"type":"ClusterIP"}}'*

*\# Verify*  
*kubectl get svc argo-server \-n argo*  
*\# Should show: TYPE \= ClusterIP*

Install cert-manager

`# Install cert-manager`  
`kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml`

`# Wait for cert-manager to be ready (takes ~1 minute)`  
`kubectl wait --for=condition=available --timeout=300s deployment/cert-manager -n cert-manager`  
`kubectl wait --for=condition=available --timeout=300s deployment/cert-manager-webhook -n cert-manager`  
`kubectl wait --for=condition=available --timeout=300s deployment/cert-manager-cainjector -n cert-manager`

Install nginx Ingress Controller

`# Install nginx ingress controller`  
`kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/cloud/deploy.yaml`

`# Wait for LoadBalancer IP to be assigned (may take 1-3 minutes)`  
`kubectl get svc -n ingress-nginx ingress-nginx-controller -w`

`# Press Ctrl+C once you see an EXTERNAL-IP appear. Save this IP - you'll need it for DNS.`

Create DNS A Record  
Go to your DNS provider (GoDaddy, Cloudflare, Route53, etc.) and create:  
`Type: A`  
`Name: argo (or whatever subdomain you want)`  
`Value: <IP from previous step>`  
`TTL: 300 (or auto/default)`

“Non-authoritative answer” is OK.

Create Let's Encrypt ClusterIssuer

`kubectl apply -f argo-setup/clusterissuer-letsencrypt.yaml`

Create ingress resource for Argo server

`kubectl apply -f  argo-setup/ingress-argo.yaml`

**Wait 5-10 minutes** for DNS to record propagate, then verify:

`nslookup argo.focal-lab.org`  
`# Should return the ingress controller IP`

Request and wait for certificate

`# Watch certificate being issued (usually 1-3 minutes)`  
`kubectl get certificate -n argo -w`

`# Wait until you see:`  
`# NAME              READY   SECRET           AGE`  
`# argo-server-tls   True    argo-server-tls  2m`

`# Press Ctrl+C when READY shows True`

Argo UI should now be accessible at [https://argo.focal-lab.org](https://argo.focal-lab.org). Verification commands:

`# Check all components are ready`  
`kubectl get pods -n cert-manager`  
`kubectl get pods -n ingress-nginx`  
`kubectl get pods -n argo`

`# Check ingress created`  
`kubectl get ingress -n argo`

`# Check certificate issued`  
`kubectl get certificate -n argo`

`# Check DNS resolves`  
`nslookup argo.focal-lab.org`

Create the Argo UI server token. We’ll make one that lasts one year. So it will have to be re-created in a year. We’re creating this for the "default" service account. In the future we may want to create a new service account specifically for users’ argo-server tokens. Possibly a separate one for each user if we want the ability to grant or revoke individual users permissions. It would also allow for granting less than full permissions (subsets being things like workflow submit, watch, list, update, delete). Another benefit of associating the token with a non-default service account (even if it is just one token from one service account that is shared by the team) is that we could then differentiate between actions taken by the server itself (automated) vs human users.

`kubectl create token argo-server -n argo --duration=8760h`

Copy the token, preface it with “Bearer “, and add/update it in [Vaultwarden](http://vault.focal-lab.org).

In the future, for rotating the token: Delete the server token (actually all of them)

`# Delete all tokens for that service account`  
   `kubectl delete secret -n argo -l kubernetes.io/service-account.name=argo-server`

Then recreate it with the step above.
# Argo Workflow

This repository contains [Argo Workflows](https://argoproj.github.io/workflows) used by the **Open Forest Observatory (OFO)**. It is being developed to run the [automate-metashape](https://github.com/open-forest-observatory/automate-metashape) pipeline simultaneously across multiple virtual machines on [Jetstream2 Cloud](https://jetstream-cloud.org/). This type of scaling enables OFO to process many photogrammetry projects simultaneously (instead of sequentially) and vastly reduce total processing time. Argo is meant to work on [Kubernetes](https://kubernetes.io/docs/concepts/overview/) which orchestrates containers (ie, automate-metashape in docker), scales the processing to multiple VMs, and balances the load between the VMs. 

---

<br/>



## Setup

### 1. Add drone imagery data to OFO shared volume

The drone data to be processed and the workflow outputs are on the `ofo-share` volume. This volume will be automatically mounted to any VM built from `ofo-dev` image using [Exosphere interface](https://jetstream2.exosphere.app/exosphere/). The volume is mounted at `/ofo-share` of the VM. 

To add new drone imagery projects to be processed using Argo, transfer files from your local machine to the `/ofo-share` volume.

`scp -r <local/directory/drone_images> exouser@<vm.ip.address:/ofo-share/`

location of drone imagery projects to be processed: `/ofo-share`

Path for metashape output: `/ofo-share-serve/argo-output`



so the far the benchmarking datasets are: benchmarking-inputs, emerald-point-benchmark, benchmarking-swetnam-house, benchmarking-greasewood

<br/>
<br/>

### 2. Lauch VMs with CACAO

CACAO is an interface for provisioning and launching virtual machines on Jetstream2 Cloud. OFO is using this interface because it has the ability to quickly launch multiple VMs with kubernetes pre-installed. This capability does not currently exist in Exosphere (the default UI for JS2). 

Log into CACAO at https://cacao.jetstream-cloud.org/ using your ACCESS credentials. Before launching VMs, you should [add public ssh keys](https://docs.jetstream-cloud.org/ui/cacao/credentials/) to CACAO if you would like to acccess VMs from your local IDE. These keys are specific to the local computer you are using. Once your keys are in CACAO, they will be uploaded to any VM you launch in CACAO.  

On the left-side menu, select 'Templates' and look for the template called 'single-image-k3s'. Deploy this template. 

<img width="500" alt="cacao_k3" src="https://github.com/user-attachments/assets/deaafcef-dd91-4972-a9fb-dfc87ec2fc96" />

<br/>
<br/>


After clicking deploy, you will be stepped through a series of parameters to select

* Cloud = Jetstream2
* Project = your js2 allocation name
* Region = IU
* Type a deployment name (e.g., jgillan-test-0618)
* Make sure you are using Ubuntu22
* Choose the number of instances. This should be a miminum of 3 VMs. One VM will be the master (does no work), the other two will be workers.
* Choose the size of the VMs. It is recommended to start with `g3.medium` which has a gpu for each instance. GPUs are useful for accelerating some steps of the metashape pipeline. Having a GPU for the master instance seems wasteful, so we can `resize` the master instance later in Exosphere.


<img width="400" alt="cacao_parameters" src="https://github.com/user-attachments/assets/bb34c732-311d-4710-beba-19da1d3c0ad7" />



<br/>
<br/>

### 3. Connecting to the VM Instances

You can connect to the terminal of any of the VMs through two methods:

#### Click on the webshell icon associated with the VM 
<img width="660" alt="Screenshot 2025-06-20 at 9 33 53 AM" src="https://github.com/user-attachments/assets/a3ee09ba-d701-4fa5-97d3-586b4c640dc1" />

#### SSH into the VM from your local terminal or IDE
`ssh exouser@<vm_public_ip_address>`

<br/>
<br/>

### 4. Check Status of Kubernetes
Kubernetes (k3s) have been pre-installed on each of the instances. 

View nodes in your cluster
`kubectl get nodes`

Describe a specific node in your cluster
`kubectl describe <node-name>`

`kubectl cluster-info`


<br/>
<br/>

### 5. Install Argo on Master instance
The following commands will download argo, unzip it, and bring it into your system path ready for use. 

```
# Detect OS
ARGO_OS="linux"

# Download the binary
curl -sLO "https://github.com/argoproj/argo-workflows/releases/download/v3.6.5/argo-$ARGO_OS-amd64.gz"

# Unzip
gunzip "argo-$ARGO_OS-amd64.gz"

# Make binary executable
chmod +x "argo-$ARGO_OS-amd64"

# Move binary to path
sudo mv "./argo-$ARGO_OS-amd64" /usr/local/bin/argo

# Test installation
argo version
```
<br/>

The output of `argo version` should look like this:

<img width="400" alt="Screenshot 2025-06-20 at 10 03 30 AM" src="https://github.com/user-attachments/assets/06000374-86db-40f2-95f3-e89166a43a31" />

<br/>
<br/>

Create a isolated environment for the argo workflow on kubernetes

`kubectl create namespace argo`

<br/>
<br/>

Put argo on to new environment on kubernetes. Controller & Server

`kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v3.6.5/install.yaml`

<br/>
<br/>

Check if pods are running

`kubectl get pods -n argo`

<img width="682" alt="Screenshot 2025-06-20 at 10 15 41 AM" src="https://github.com/user-attachments/assets/9002ab34-f5f6-499b-a61d-a2588b0ef708" />

<br/>
<br/>

Describe pods

`kubectl describe pod <pod-name> -n argo`

<br/>
<br/>

Set up ofo-srv role in argo

`kubectl create role ofo-argo-srv -n argo --verb=list,update, --resource=workflows.argoproj.io`

`kubectl create rolebinding ofo-argo-srv -n argo --role=ofo-argo-srv --serviceaccount=argo:argo-server`

```
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: argo-workflow-role
rules:
- apiGroups: ["argoproj.io"]
  resources: 
    - workflows
    - workflowtaskresults
  verbs: 
    - create
    - get
    - list
    - watch
    - update
    - patch
    - delete
EOF
```
<br/>
<br/>

```
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: argo-workflow-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: argo-workflow-role
subjects:
- kind: ServiceAccount
  name: argo
  namespace: argo
EOF
```
<br/>
<br/>

Run the following command. The output should say 'yes'.

`kubectl auth can-i create workflowtaskresults.argoproj.io -n argo --as=system:serviceaccount:argo:argo`

<br/>
<br/>

Optional: check roles and role-bindings

`kubectl get role -n argo`

<img width="660" alt="Screenshot 2025-06-20 at 10 27 29 AM" src="https://github.com/user-attachments/assets/a62b6253-1c89-4008-bbbb-8c8403f5db45" />

<br/>
<br/>

`kubectl describe role <role_name> -n argo`

<img width="807" alt="Screenshot 2025-06-20 at 10 29 35 AM" src="https://github.com/user-attachments/assets/0357d932-ca01-4e52-8762-c8480700e3ed" />

<img width="822" alt="Screenshot 2025-06-20 at 10 30 17 AM" src="https://github.com/user-attachments/assets/9ab3d32a-4239-48d0-8129-1a191b0b2a76" />

<br/>
<br/>

### 6. Clone ofo-argo repository to Master instance

In the home directory of your terminal, type in the following

`git clone https://github.com/open-forest-observatory/ofo-argo.git`


<br/>

### 7. Connect VM instances to shared volume

The following is about connecting the VM instances with the `/ofo-share` volume so it can read the drone imagery to process and write the outputs.

a. Install Network File System (NFS) on all instances including the master and each worker. You will need to connect to each VM terminal to do installation. 

`sudo apt update`

`sudo apt install nfs-common -y`





persistent volume (PV)

persistent volume claim (PVC)

<br/>

## Files In this Repository

| File Name   | Purpose       |
|  --- | ----  |
| argo-output-pv.yaml | Defines read-write PV for workflow output storage mounted at /ofo-share/argo-output |
| argo-output-pvc.yaml | PVC bound to output volume | 
| ofo-share-pv.yaml | Defines read-only NFS PV for /ofo-share (input data) |
| ofo-share-pvc.yaml | PVC bound to shared data volume |
| workflow.yaml | Argo Workflow to automate Metashape runs per dataset |

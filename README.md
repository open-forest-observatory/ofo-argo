# Argo Workflow

This repository contains [Argo Workflows](https://argoproj.github.io/workflows) used by the **Open Forest Observatory (OFO)**. It is being developed to run the [automate-metashape](https://github.com/open-forest-observatory/automate-metashape) pipeline simultaneously across multiple virtual machines on [Jetstream2 Cloud](https://jetstream-cloud.org/). This type of scaling enables us to process many photogrammetry projects simultaneously (instead of sequentially) and vastly reduce total processing time. Argo is meant to work on [Kubernetes](https://kubernetes.io/docs/concepts/overview/) which orchestrates containers (ie, automate-metashape in docker), scales the processing to multiple VMs, and balances the load between the VMs. 

---

<br/>



## Setup

### Add drone imagery data to OFO shared volume

The drone data to be processed and the workflow outputs are on the `ofo-share` volume. This volume will be automatically mounted to any VM built from `ofo-dev` image using [Exosphere interface](https://jetstream2.exosphere.app/exosphere/). The volume is mounted at `/ofo-share` of the VM. 

To add new drone imagery projects to be processed using Argo, transfer files from your local machine to the `/ofo-share` volume.

`scp -r <local/directory/drone_images> exouser@<vm.ip.address:/ofo-share/`

location of drone imagery projects to be processed: `/ofo-share`

Path for metashape output: `/ofo-share-serve/argo-output`



so the far the benchmarking datasets are: benchmarking-inputs, emerald-point-benchmark, benchmarking-swetnam-house, benchmarking-greasewood

<br/>
<br/>

### Lauch VMs with CACAO

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

### Check Status of Kubernetes
Kubernetes (k3s) have been pre-installed on the instances. 
<br/>

### Install Argo on Master instance

<br/>

### Clone ofo-argo repository to Master instance

In the home directory of your terminal, type in the following

`git clone https://github.com/open-forest-observatory/ofo-argo.git`

<br/>

### Connect VM instances to shared volume

The following is about connecting the kubernetes instances with the `/ofo-share` volume so it can read the drone imagery to process and write the outputs.

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

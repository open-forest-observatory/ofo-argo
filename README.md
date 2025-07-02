# Argo Workflow

This repository contains [Argo Workflows](https://argoproj.github.io/workflows) used by the **Open Forest Observatory (OFO)**. It is being developed to run the [automate-metashape](https://github.com/open-forest-observatory/automate-metashape) pipeline simultaneously across multiple virtual machines on [Jetstream2 Cloud](https://jetstream-cloud.org/). This type of scaling enables OFO to process many photogrammetry projects simultaneously with a single run command. Argo is meant to work on [Kubernetes](https://kubernetes.io/docs/concepts/overview/) which orchestrates containers (ie, automate-metashape in docker), scales the processing to multiple VMs, and balances the load between the VMs. 


---

<br/>



## Setup

### 1. Add drone imagery data to OFO shared volume

The drone data to be processed and the workflow outputs are on the `ofo-share` volume. This volume will be automatically mounted to any VM built from `ofo-dev` image using [Exosphere interface](https://jetstream2.exosphere.app/exosphere/). The volume is mounted at `/ofo-share` of the VM. 
<br/>

To add new drone imagery datasets to be processed using Argo, transfer files from your local machine to the `/ofo-share` volume.

`scp -r <local/directory/drone_images> exouser@<vm.ip.address>:/ofo-share/`

Put the drone imagery projects to be processed in it's own directory in `/ofo-share`. For example, there are 4 testing datasets already in the directory called `benchmarking-inputs`, `emerald-point-benchmark`, `benchmarking-swetnam-house`, `benchmarking-greasewood`

The path for metashape output is: `/ofo-share/argo-output`

<br/>

#### Specify which datasets to process in Argo

You need to specify which datasets to be processed in the file `/ofo-share/datasets.txt`


<br/>
<br/>

### 2. Specify Metashape Parameters

All metashape parameters are specified in a config.yml file which is located at `/ofo-share/argo-output`. You can create your own config yml as long as it is kept in this directory. The exact file (e.g., config2.yml or projectname_config.yml) will be specified as a parameter in the argo run command later in this workflow. 

<br/>
<br/>

### 3. Lauch VMs with CACAO

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

### 4. Connecting to the VM Instances

You can connect to the terminal of any of the VMs through two methods:

#### Click on the webshell icon associated with the VM 
<img width="660" alt="Screenshot 2025-06-20 at 9 33 53 AM" src="https://github.com/user-attachments/assets/a3ee09ba-d701-4fa5-97d3-586b4c640dc1" />

#### SSH into the VM from your local terminal or IDE
`ssh <access_username>@<vm_public_ip_address>`

IMPORTANT NOTE. If you have launched VMs from Cacao, the ssh username is **<access_username>**! If you launch VMs from Exosphere, the ssh username is **exouser**!

<br/>
<br/>

### 5. Check Status of Kubernetes
Connect to the master VM instance either through webshell or local IDE

Kubernetes (k3s) have been pre-installed on each of the instances. 

View nodes in your cluster `kubectl get nodes`

Describe a specific node in your cluster
`kubectl describe <node-name>`

`kubectl cluster-info`


<br/>
<br/>


### 6. Prevent the Master Node from Processing a Job

`kubectl get nodes`

note the name of the master node

`kubectl taint nodes <master-node-name> node-role.kubernetes.io/master=:NoSchedule`

<br/>
<br/>

### 7. Install Argo on Master instance
a. The following commands will download argo, unzip it, and bring it into your system path ready for use. 

```
# Detect OS
ARGO_OS="linux"

# Download the binary
curl -sLO "https://github.com/argoproj/argo-workflows/releases/download/v3.6.10/argo-$ARGO_OS-amd64.gz"

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

b. Create a isolated environment for the argo workflow on kubernetes

`kubectl create namespace argo`

<br/>
<br/>

c. Put argo on to new environment on kubernetes. Installs workflow Controller which manages overall lifecycle of workflows. Also installs argo server which includes a web-based user interface. 

`kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v3.6.5/install.yaml`

<br/>
<br/>

d. Check if pods are running

`kubectl get pods -n argo`

<img width="682" alt="Screenshot 2025-06-20 at 10 15 41 AM" src="https://github.com/user-attachments/assets/9002ab34-f5f6-499b-a61d-a2588b0ef708" />

<br/>
<br/>

e. Describe pods

`kubectl describe pod <pod-name> -n argo`

<br/>
<br/>

f. Set up ofo-srv role in argo

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

g. Run the following command. The output should say 'yes'.

`kubectl auth can-i create workflowtaskresults.argoproj.io -n argo --as=system:serviceaccount:argo:argo`

<br/>
<br/>

h. Optional: check roles and role-bindings

`kubectl get role -n argo`

<img width="660" alt="Screenshot 2025-06-20 at 10 27 29 AM" src="https://github.com/user-attachments/assets/a62b6253-1c89-4008-bbbb-8c8403f5db45" />

<br/>
<br/>

`kubectl describe role <role_name> -n argo`

<img width="807" alt="Screenshot 2025-06-20 at 10 29 35 AM" src="https://github.com/user-attachments/assets/0357d932-ca01-4e52-8762-c8480700e3ed" />

<img width="822" alt="Screenshot 2025-06-20 at 10 30 17 AM" src="https://github.com/user-attachments/assets/9ab3d32a-4239-48d0-8129-1a191b0b2a76" />

<br/>
<br/>

### 8. Clone ofo-argo repository to Master instance

In the home directory of your terminal, type in the following

`git clone https://github.com/open-forest-observatory/ofo-argo.git`

NOTE: if you want to use a development branch of the repo `git checkout <branch name>`

<br/>

### 9. Connect VM instances to shared volume

The following is about connecting the VM instances with the `/ofo-share` volume so it can read the drone imagery to process and write the outputs.

a. Install Network File System (NFS) on all instances including the master and each worker. You will need to connect to each VM terminal to do installation. 

`sudo apt update`

`sudo apt install nfs-common -y`

`sudo reboot`

<br/>

b. Reconnect to the master instance and navigate into the cloned repository

`cd ~/ofo-argo`

<br/>

c. Set up the persistent volumes (PV) defined by the workflow. You are specifying the read (raw drone imagery on `ofo-share`) and the write (metashape output location)

`kubectl apply -f argo-output-pv.yaml`

`kubectl apply -f ofo-share-pv.yaml`

<br/>

d. Set up persistent volume claims (PVC)

`kubectl apply -f argo-output-pvc.yaml -n argo`

`kubectl apply -f ofo-share-pvc.yaml -n argo`

<br/>

e. Check the PVs

`kubectl get pv`

`kubectl get pvc -n argo`

<br/>
<br/>

## Run the Workflow

### 1. Declare the ip address of the metashape license server

On the master instance terminal, type:

`export AGISOFT_FLS=<ip_address>:5842`

This variable will only last during the terminal session and will have to be re-declared each time you start a new master terminal. 

<br/>

### 2. Run!!

```
argo submit -n argo workflow.yaml --watch \
-p CONFIG_FILE=config2.yml \
-p AGISOFT_FLS=$AGISOFT_FLS \
-p RUN_FOLDER=gillan_test_june27 \
-p DATASET_LIST=datasets.txt  
```

CONFIG_FILE is the config which specifies the metashape parameters which should be located in `/ofo-share/argo-output`

AGISOFT_FLS is the ip address of the metashape license server

RUN_FOLDER is what you want to name the parent directory of your output

DATSET_LIST is the txt file where you specified the names of the datasets you want to process located at `/ofo-share/argo-output`

<br/>

### 3. Monitor Argo Workflow
The Argo UI is great for troubleshooting and checking additional logs. You can access it with the following steps

a. In the CACAO interface, launch a WebDesktop for your master instance

<img width="660" alt="Screenshot 2025-06-20 at 9 33 53 AM" src="https://github.com/user-attachments/assets/a3ee09ba-d701-4fa5-97d3-586b4c640dc1" />

<br/>
<br/>

b. Launch a terminal in the WebDesktop and type the following

`argo server --auth-mode server -n argo`

<br/>

c. Now go to a browser (firefox) in the WebDesktop and go the address. You may receive a "Connection not secure" error but just bypass it.

`https://<master_public_ip_address>:2746`

<br/>

<img width="1190" alt="Screenshot 2025-06-20 at 12 48 46 PM" src="https://github.com/user-attachments/assets/bd6bd991-f108-4be9-a1aa-6cb0f1ab1db5" />

<br/>
<br/>
 The 'Workflows' tab on the left side menu shows you all running workflows. If you click a current workflow, it will show you a schematic of the jobs spread across multiple instances. 



<br/>
<br/>

If you click on a specific job, it will show you lots of information of the process including which VM it is running on, the duration of the process, and logs. 

<img width="1190" alt="Screenshot 2025-06-20 at 12 58 55 PM" src="https://github.com/user-attachments/assets/ab10f2b4-3120-47be-b1dd-601687707f0c" />

<br/>
<br/>

### 4. Metashape Outputs
The metashape outputs will be written to `/ofo-share/argo-outputs/<RUN_FOLDER>`. Each dataset will have its own subdirectory in the <RUN_FOLDER>. Output imagery products (DEMs, orthomosaics, point clouds, report) will be written to `/ofo-share/argo-outputs/<RUN_FOLDER>/<dataset_name>/output`. Metashape projects .psx will be written to `/ofo-share/argo-outputs/<RUN_FOLDER>/<dataset_name>/project`.





<br/>
<br/>
<br/>
<br/>

## Argo Workflow Logging in postGIS database (in development)

There is a [development branch of `ofo-argo`](https://github.com/open-forest-observatory/ofo-argo/tree/aa_setup_argo_utils) repo created by Arnav. This branch has developed a workflow to log argo process status (eg., started, finished, successful, failed) into a postGIS DB. This is done through an additional docker container (hosted on ghcr). The workflow is in the folder `ofo-argo-utils`. There is also a github action workflow that rebuilds this container if changes have been made in `workflow.yml`. This workflow is in the directory `.github/workflows`. There is an outstanding pull request regarding this development. 

To run this experimental workflow navigate to the `ofo-argo` repo and go into the branch `git checkout aa_setup_argo_utils`

<br/>

```
argo submit -n argo workflow.yaml --watch \
  -p AGISOFT_FLS=$AGISOFT_FLS \
  -p RUN_FOLDER=$RUN_FOLDER \
  -p DATASET_LIST=$DATASET_LIST \
  -p DB_PASSWORD=$DB_PASSWORD \
  -p DB_HOST=$DB_HOST \
  -p DB_NAME=$DB_NAME \
  -p DB_USER=$DB_USER
```
Replace the variables above (e.g., $AGISOFT_FLS, $RUN_FOLDER) with your actual environment values or export them beforehand. Get all variables associated with the database from the internal credentials doc.

During an automate-metashape run, we update an entry in the db as the run progresses. We do NOT add new rows to update the status. Moving forward, we might want to see if this is the best practice.


### Info on the postGIS DB
There is a JS2 VM called `ofo-postgis` that hosts a postgis DB in docker. When we process drone imagery in Metashape, we want workflow metadata to be put into this postGIS database. This server has persistent storage, tied to a storage volume made in Jetstream.

As of right now, the PostGIS server stores the following keys:

| **Column**   | **Type** | **Description**  |
|  --- | ----  | --- |
|id | integer | unique identifier for each call of automate-metashape (not run) |
|dataset_name | character varying(100) | dataset running for the individual call of automate-metashape |
| workflow_id | character varying(100) | identifier for run of ofo-argo |
| status | character varying(50)  | either queued, processing, or failed, based on current and final status of automate-metashape |
| start_time | timestamp without time zone | start time of automate-metashape run |
| finish_time  | timestamp without time zone | end time of automate-metashape run (if it was able to finish) |
| created_at | timestamp without time zone | creation time of entry in database |

### Access and Navigation of postgis DB  

* SSH into ofo-postgis `ssh exouser@<ip>`

* Enter the Docker container running the PostGIS server `sudo docker exec -ti ofo-postgis bash`

* Launch the PostgreSQL CLI as the intended user (grab from DB credentials) `psql -U postgres`

* List all tables in the database `\dt`

* Show the structure of a specific table (column names & data types) `\d automate_metashape`

* View all data records for a specific table `select * from automate_metashape;`



<br/>
<br/>
<br/>
<br/>
<br/>
<br/>



## Files In this Repository

| File Name   | Purpose       | 
|  --- | ----  |
| argo-output-pv.yaml | Defines read-write PV for workflow output storage mounted at /ofo-share/argo-output |
| argo-output-pvc.yaml | PVC bound to output volume | 
| ofo-share-pv.yaml | Defines read-only NFS PV for /ofo-share (input data) |
| ofo-share-pvc.yaml | PVC bound to shared data volume |
| workflow.yaml | Argo Workflow to automate Metashape runs per dataset |

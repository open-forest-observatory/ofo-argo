# Open Forest Observatory Argo Workflow

This repository contains [Argo Workflows](https://argoproj.github.io/workflows) used by the **Open Forest Observatory (OFO)**. It is being developed to run the [automate-metashape](https://github.com/open-forest-observatory/automate-metashape) pipeline simultaneously across multiple virtual machines on [Jetstream2 Cloud](https://jetstream-cloud.org/). This type of scaling enables OFO to process many photogrammetry projects simultaneously with a single run command. Argo is meant to work on [Kubernetes](https://kubernetes.io/docs/concepts/overview/) which orchestrates containers (ie, automate-metashape in docker), scales the processing to multiple VMs, and balances the load between the VMs. 


<br/>

#### Files & Directories In this Repository

| File Name   | Purpose       | 
|  --- | ----  |
| argo-output-pv.yaml | Defines read-write PV for workflow output storage mounted at /ofo-share/argo-output |
| argo-output-pvc.yaml | PVC bound to output volume | 
| ofo-share-pv.yaml | Defines read-only NFS PV for /ofo-share (input data) |
| ofo-share-pvc.yaml | PVC bound to shared data volume |
| workflow.yaml | Argo Workflow to automate Metashape runs per dataset |
| /ofo-argo-utils | files to build a docker image for database logging of argo workflow metadata |
| /.github/workflows | a github action workflow to automatically build a new DB logging docker image if any changes have been made to repo. **CURRENTLY DISABLED in GITHUB ACTIONS** |     

<br/>

---

<br/>
<br/>



## Setup

### 1. Inputs

Inputs to the metashape argo workflow include **1.** drone imagery datasets consisting of jpegs, **2.** a list (datasets.txt) of the dataset names to be processed, and **3.** a metashape config.yml. All of these inputs need to be on the `ofo-share` volume. This volume will be automatically mounted to any VM built from `ofo-dev` image using [Exosphere interface](https://jetstream2.exosphere.app/exosphere/). The volume is mounted at `/ofo-share` of the VM.

Here is a schematic of the `/ofo-share` directory. 
```bash
/ofo-share/
├── argo-input/
│   ├── config.yml
│   ├── datasets.txt
│   ├── benchmarking-greasewood/
│   │   ├── image_01.jpg
│   │   └── image_02.jpg
│   └── benchmarking-swetnam-house/
│       ├── image_01.jpg
│       └── image_02.jpg
└── argo-output/
    └── <RUN_FOLDER>/
        ├── benchmarking-greasewood/
        │   ├── output/
        │   │   ├── orthomosaic.tif
        │   │   ├── dsm.tif
        │   │   └── point-cloud.laz
        │   └── project/
        │       └── metashape_project.psx
        └── benchmarking-swetnam-house/
            ├── output/
            │   ├── orthomosaic.tif
            │   ├── dsm.tif
            │   └── point-cloud.laz
            └── project/
                └── metashape_project.psx
```

#### a. Add drone imagery to OFO shared volume
To add new drone imagery datasets to be processed using Argo, transfer files from your local machine to the `/ofo-share` volume.

`scp -r <local/directory/drone_image_dataset> exouser@<vm.ip.address>:/ofo-share/argo-input`

Put the drone imagery projects to be processed in it's own directory in `/ofo-share/argo-input`. For example, there are 4 testing datasets already in the directory called `benchmarking-emerald-subset`, `benchmarking-emerald-full`, `benchmarking-swetnam-house`, `benchmarking-greasewood`


<br/>

#### b. Specify which datasets to process in Argo
The file `/ofo-share/argo-input/datasets.txt` contains of list of the named datasets to process in argo. 


<br/>
<br/>

#### c. Specify Metashape Parameters

All metashape parameters are specified in a config.yml file which is located at `/ofo-share/argo-input`. You can create your own config yml as long as it is kept in this directory. The exact file (e.g., config2.yml or projectname_config.yml) will be specified as a parameter in the argo run command later in this workflow. 

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
* Featured Ubuntu24 
* Choose the number of instances. This should be a miminum of 3 VMs. One VM will be the master (does no work), the other two will be workers.
* Choose the size of the VMs. It is recommended to start with `g3.medium` which has a gpu for each instance. GPUs are useful for accelerating some steps of the metashape pipeline. Because the master node does no processing, it doesn't need to be GPU. After launch, you can resize to CPU using Exophere interface.
* Under Advanced Settings, specify to use a boot volume with 60 GB of storage. This will allow you to later resize the nodes to the smaller flavors. (If you leave the default of “local volume”, you will be unable to later resize any nodes to m3.quad or smaller.)


<img width="400" alt="cacao_parameters" src="https://github.com/user-attachments/assets/bb34c732-311d-4710-beba-19da1d3c0ad7" />



<br/>
<br/>

### 3. Connecting to the VM Instances

You can connect to the terminal of any of the VMs through two methods:

#### Click on the webshell icon associated with the VM 
<img width="660" alt="Screenshot 2025-06-20 at 9 33 53 AM" src="https://github.com/user-attachments/assets/a3ee09ba-d701-4fa5-97d3-586b4c640dc1" />

#### SSH into the VM from your local terminal or IDE
`ssh <access_username>@<vm_public_ip_address>`

IMPORTANT NOTE. If you have created VMs from Cacao, the ssh username is **<access_username>**! If you have created VMs in Exosphere, the ssh username is **exouser**!

<br/>
<br/>

### 4. Check Status of Kubernetes
Connect to the master VM instance either through webshell or local IDE

Kubernetes (k3s) have been pre-installed on each of the instances. 

View nodes in your cluster `kubectl get nodes`

Describe a specific node in your cluster
`kubectl describe node <node-name>`

Provides a summary of your Kubernetes cluster's core components and services.
`kubectl cluster-info`


<br/>
<br/>


### 5. Prevent the Master Node from Processing a Job

`kubectl get nodes`

note the name of the master node

`kubectl taint nodes <master-node-name> node-role.kubernetes.io/master=:NoSchedule`

<br/>
<br/>

### 6. Install Argo on Master instance
a. The following commands will download argo, unzip it, and bring it into your system path ready for use. 

```
# Download the binary
curl -sLO "https://github.com/argoproj/argo-workflows/releases/download/v3.6.10/argo-linux-amd64.gz"

# Unzip
gunzip "argo-linux-amd64.gz"

# Make binary executable
chmod +x "argo-linux-amd64"

# Move binary to path
sudo mv "./argo-linux-amd64" /usr/local/bin/argo

# Test installation
argo version
```
<br/>

The output of `argo version` should look similar to the following screen shot. 

<img width="400" alt="argo_version" src="https://github.com/user-attachments/assets/ae423ae7-56b9-4362-b88a-396eceec48cc" />


<br/>
<br/>

b. Create a isolated namespace for the argo workflow on kubernetes

`kubectl create namespace argo`

<br/>
<br/>

c. Installs workflow Controller which manages overall lifecycle of workflows and installs argo server which includes a web-based user interface. This specific url will install Argo workflow components in the `argo` kubernetes namespace, instead of cluster-wide. It provides an isolated environment separate from other applications in your cluster. The namespace acts as a virtual boundary that keeps Argo's resources (like its controller, server, and configurations) organized and segregated from other workloads.  

`kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v3.6.10/namespace-install.yaml`

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

f. Create a ClusterRole - a set of permissions that can be used across the entire Kubernetes cluster (not just one namespace). Then assign the permissions to the argo namespace in a process called ClusterRoleBinding. 


<br/>

Please run the following command to define the role and global permissions

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

Please run the following command to assing the permissions to namesspace argo

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

g. Run the following command to check permissions. The output should say 'yes'.

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

### 7. Clone ofo-argo repository to Master instance

In the home directory of your terminal, type in the following

`git clone https://github.com/open-forest-observatory/ofo-argo.git`

NOTE: if you want to use a development branch of the repo. eg, `git checkout docs/JG/readme-editing`

<br/>

### 8. Connect VM instances to shared volume

The following is about connecting the VM instances with the `/ofo-share` volume so it can read the drone imagery to process and write the outputs.

a. Install Network File System (NFS) on all instances including the master and each worker. You will need to connect to each VM terminal to do installation. 

`sudo apt update`

`sudo apt install nfs-common -y`


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
<br/>

## Run the Workflow

### 1. Declare the ip address of the metashape license server

On the master instance terminal, type:

`export AGISOFT_FLS=<ip_address>:5842`

This variable will only last during the terminal session and will have to be re-declared each time you start a new master terminal. We are not putting the ip address here to prevent unauthorized people from using it. Authorized users can find it [here](https://docs.google.com/document/d/155AP0P3jkVa-yT53a-QLp7vBAfjRa78gdST1Dfb4fls/edit?tab=t.0).

<br/>

### 2. Run!!

```
argo submit -n argo workflow.yaml --watch \
-p CONFIG_FILE=config2.yml \
-p AGISOFT_FLS=$AGISOFT_FLS \
-p RUN_FOLDER=gillan_june27 \
-p DATASET_LIST=datasets.txt \
-p DB_PASSWORD=<password> \
-p DB_HOST=<vm_ip_address> \
-p DB_NAME=<db_name> \
-p DB_USER=<user_name>
 
```

CONFIG_FILE is the configuration yml which specifies the metashape parameters which should be located in `/ofo-share/argo-output`

AGISOFT_FLS is the ip address of the metashape license server

RUN_FOLDER is what you want to name the parent directory of your output

DATSET_LIST is the txt file where you specified the names of the datasets you want to process located at `/ofo-share/argo-output`

The rest of the 'DB' parameters are for logging argo status in a postGIS database. These are not public credentials. Authorized users can find them [here](https://docs.google.com/document/d/155AP0P3jkVa-yT53a-QLp7vBAfjRa78gdST1Dfb4fls/edit?tab=t.0).

<br/>

### 3. Monitor Argo Workflow
The Argo UI is great for troubleshooting and checking additional logs. You can access it either through the Cacao WebDesktop or ssh from your local terminal.

#### WebDesktop Method
* In the CACAO interface, launch a WebDesktop for your master instance

<img width="660" alt="Screenshot 2025-06-20 at 9 33 53 AM" src="https://github.com/user-attachments/assets/a3ee09ba-d701-4fa5-97d3-586b4c640dc1" />

<br/>
<br/>

* Launch a terminal in the WebDesktop 

* Get around a known issue with v3.6.10
  
`export GRPC_ENFORCE_ALPN_ENABLED=false`

* Then type this to launch the server UI. 

`argo server --auth-mode server -n argo`

<br/>

* Now go to a browser (firefox) in the WebDesktop and go the address. You may receive a "Connection not secure" error but just bypass it.

`https://localhost:2746`

<br/>

#### Local ssh method

* Open a terminal or IDE on your local machine

* Connect via ssh to the master node 

`ssh <access_username>@<master_ip_address>` 

* Get around a known issue with v3.6.10
  
`export GRPC_ENFORCE_ALPN_ENABLED=false`

* Lauch server UI

`argo server --auth-mode server -n argo`

* Open a web browser on your local computer and type in the address (bypass the security warning)

  `https://<master_ip_address>:2746`

<br/>
<br/>

**Note on UI Server.** The command `argo server --auth-mode server -n argo`is not the most secure method because it is exposed to the open internet. In the future we may use `argo server --auth-mode client -n argo` which restricts access to users with tokens. More information on the topic [here](https://docs.google.com/document/d/1H1TWZAvRbiRLD4jBOIUFKLgV1vvD7FeXNG58IH0irJ8/edit?tab=t.0)

<br/>
<br/>

#### Navigating Argo UI

The 'Workflows' tab on the left side menu shows you all running workflows. If you click a current workflow, it will show you a schematic of the jobs spread across multiple instances. 

<img width="1000" alt="Screenshot 2025-06-20 at 12 48 46 PM" src="https://github.com/user-attachments/assets/bd6bd991-f108-4be9-a1aa-6cb0f1ab1db5" />

<br/>
<br/>

If you click on a specific job, it will show you lots of information of the process including which VM it is running on, the duration of the process, and logs. 

<img width="1000" alt="Screenshot 2025-06-20 at 12 58 55 PM" src="https://github.com/user-attachments/assets/ab10f2b4-3120-47be-b1dd-601687707f0c" />

<br/>
<br/>

A successfull argo run 

<img width="650" height="789" alt="argo_success" src="https://github.com/user-attachments/assets/201b0594-7557-4d85-a99b-677e6c173a44" />

<br/>
<br/>


### 4. Metashape Outputs
The metashape outputs will be written to `/ofo-share/argo-outputs/<RUN_FOLDER>`. Each dataset will have its own subdirectory in the <RUN_FOLDER>. Output imagery products (DEMs, orthomosaics, point clouds, report) will be written to `/ofo-share/argo-outputs/<RUN_FOLDER>/<dataset_name>/output`. Metashape projects .psx will be written to `/ofo-share/argo-outputs/<RUN_FOLDER>/<dataset_name>/project`.

```bash
/ofo-share/
├── argo-input/
│   ├── config.yml
│   ├── datasets.txt
│   ├── benchmarking-greasewood/
│   │   ├── image_01.jpg
│   │   └── image_02.jpg
│   └── benchmarking-swetnam-house/
│       ├── image_01.jpg
│       └── image_02.jpg
└── argo-output/
    └── <RUN_FOLDER>/
        ├── benchmarking-greasewood/
        │   ├── output/
        │   │   ├── orthomosaic.tif
        │   │   ├── dsm.tif
        │   │   └── point-cloud.laz
        │   └── project/
        │       └── metashape_project.psx
        └── benchmarking-swetnam-house/
            ├── output/
            │   ├── orthomosaic.tif
            │   ├── dsm.tif
            │   └── point-cloud.laz
            └── project/
                └── metashape_project.psx
```



<br/>
<br/>
<br/>
<br/>

### 5. Argo Workflow Logging in postGIS database 

Argo run status is logged into a postGIS DB. This is done through an additional docker container (hosted on github container registry `ghcr.io/open-forest-observatory/ofo-argo-utils:latest`) that is included in the argo workflow. The files to make the docker image are in the folder `ofo-argo-utils`. 

<br/>


#### Info on the postGIS DB
There is a JS2 VM called `ofo-postgis` that hosts a postGIS DB for storing metadata of argo workflows. 

<br/>

You can access the `ofo-postgis` VM through Webshell in Exosphere. Another access option is to SSH into `ofo-postgis` with the command `ssh exouser@<ip_address>`. This is not public and will require a password. 

<br/>

The DB is running in a docker container (`postgis/postgis`). The DB storage is a 10 GB volume at `/media/volume/ofo-postgis` on the VM. 

<br/>

View all running and stopped containers

`docker ps -a`

<br/>

Stop a running container

`docker stop <container_id>`

<br/>

Remove container

`docker rm <container_id>`

<br/>


Run the docker container DB

```
sudo docker run --name ofo-postgis   -e POSTGRES_PASSWORD=ujJ1tsY9OizN0IpOgl1mY1cQGvgja3SI   -p 5432:5432   -v /media/volume/ofo-postgis/data:/var/lib/postgresql/data  -d postgis/postgis
```
<br/>
<br/>

Enter the Docker container running the PostGIS server `sudo docker exec -ti ofo-postgis bash`

<br/>
<br/>

Launch the PostgreSQL CLI as the intended user (grab from DB credentials) `psql -U postgres`

<br/>

List all tables in the database `\dt`

<br/>

Show the structure of a specific table (column names & data types) `\d automate_metashape`

<br/>

Currently, the PostGIS server stores the following keys in the `automate_metashape` table:

| **Column**   | **Type** | **Description**  |
|  --- | ----  | --- |
|id | integer | unique identifier for each call of automate-metashape (not run) |
|dataset_name | character varying(100) | dataset running for the individual call of automate-metashape |
| workflow_id | character varying(100) | identifier for run of ofo-argo |
| status | character varying(50)  | either queued, processing, failed or completed, based on current and final status of automate-metashape |
| start_time | timestamp without time zone | start time of automate-metashape run |
| finish_time  | timestamp without time zone | end time of automate-metashape run (if it was able to finish) |
| created_at | timestamp without time zone | creation time of entry in database |


<br/>
<br/>

View all data records for a specific table `select * from automate_metashape ORDER BY id DESC;`
<img width="1000" height="183" alt="sql_query" src="https://github.com/user-attachments/assets/cba4532a-21de-4c35-8b2d-635eec326ef7" />

<br/>

Exit out of psql command-line `\q`

<br/>

Exit out of container `exit`

<br/>
<br/>
<br/>

#### Github action to rebuild logging docker image

There is github action workflow that rebuilds the logging docker image if any changes have been made at all in the repo. This workflow is in the directory `.github/workflows`. **The workflow is currently disabled in the 'Actions' section of the repository.**


<br/>
<br/>
<br/>





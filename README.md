# Open Forest Observatory Argo Workflow

This repository contains [Argo Workflows](https://argoproj.github.io/workflows) used by the **Open
Forest Observatory (OFO)**. The workflow runs the
[automate-metashape](https://github.com/open-forest-observatory/automate-metashape) pipeline,
followed by post-processing steps, simultaneously across multiple virtual machines on [Jetstream2
Cloud](https://jetstream-cloud.org/). This type of scaling enables OFO to process many
photogrammetry projects simultaneously with a single run command. Argo is meant to work on
[Kubernetes](https://kubernetes.io/docs/concepts/overview/) which orchestrates containers (ie,
automate-metashape in docker), scales the processing to multiple VMs, and balances the load between
the VMs. 

The current setup includes a _master_  VM instance and multiple _worker_ instances (they process metashape projects). The worker instances are configured to process one metashape project at a time. If there are more metashape projects than worker instances, the projects will be queued until a worker is free. GPU worker instances will greatly increase the speed of processing.  

The current workflow: 1. pulls raw drone imagery from `/ofo-share` onto the kubernetes VM cluster, 2. processes the imagery with Metashape, 3. writes the imagery products to `/ofo-share` and uploads them to `S3:ofo-internal`, 4. Deletes all outputs on `/ofo-share`, 5. Downloads the imagery products from S3 back to the cluster and performs [postprocessing](/postprocess_docker) (chms, clipping, COGs, thumbnails), 6. uploads the final products to `S3:ofo-public`. 

Go directly to the [Run Command!](https://github.com/open-forest-observatory/ofo-argo/blob/jgillan/R_post_process/README.md#run-the-workflow) 


<br/>

#### Files & Directories In this Repository

| File Name   | Purpose       | 
|  --- | ----  |
| argo-output-pv.yaml | Defines read-write PV for workflow output storage mounted at /ofo-share/argo-output |
| argo-output-pvc.yaml | PVC bound to output volume | 
| ofo-share-pv.yaml | Defines read-only NFS PV for /ofo-share (input data) |
| ofo-share-pvc.yaml | PVC bound to shared data volume |
| workflow.yaml | Argo configuration for entire automated workflow |
| /ofo-argo-utils | files to build a docker image for database logging of argo workflow metadata |
| /postprocess_docker | files to build the docker image that does postprocessing of metashape products|
| /.github/workflows | a github action workflow to automatically build a new DB logging docker image if any changes have been made to repo. **CURRENTLY DISABLED in GITHUB ACTIONS** |     

<br/>

---

<br/>
<br/>



## Setup

### 1. Inputs

Inputs to the metashape argo workflow include **1.** drone imagery datasets consisting of jpegs,
**2.** a list of the names of metashape configuration files (config_list.txt), and **3.** the
metashape config.ymls. All of these inputs need to be in `/ofo-share-2/argo-data/`.

Here is a schematic of the `/ofo-share-2/argo-data` directory.
```bash
/ofo-share-2/argo-data/
├── argo-input/
   ├── datasets/
   │   ├──dataset_1/
   │   │   ├── image_01.jpg
   │   │   └── image_02.jpg
   │   └──dataset_2/
   │       ├── image_01.jpg
   │       └── image_02.jpg
   ├── configs/
   │   ├──config_dataset_1.yml
   │   └──config_dataset_2.yml
   └── config_list.txt

```

#### a. Add drone imagery to /ofo-share-2/argo-data/argo-input
To add new drone imagery datasets to be processed using Argo, transfer files from your local machine (or the cloud) to the `/ofo-share-2` volume. Put the drone imagery projects to be processed in their own directory in `/ofo-share-2/argo-data/argo-input/datasets`. 

One data transfer method is a CLI tool called SCP

`scp -r <local/directory/drone_image_dataset/> exouser@<vm.ip.address>:/ofo-share-2/argo-data/argo-input/datasets`


<br/>

#### b. Specify Metashape Parameters

Metashape processing parameters are specified in [configuration
*.yml](https://github.com/open-forest-observatory/automate-metashape/blob/main/config/config-base.yml)
files which need to be located at `/ofo-share-2/argo-data/argo-input/configs`. Every dataset to be processed
needs to have its own standalone configuration file. These config files should be named to match the
naming convention `<config_id>_<datasetname.yml>`. DYCHECK. For example `01_benchmarking-greasewood.yml` or
`02_benchmarking-greasewood.yml`. 


Within each metashape config.yml file, you must specify `photo_path` which is the location of the drone imagery dataset to be processed. This path refers to the location of the images inside a docker container. For example, if your drone images were uploaded to `/ofo-share-2/argo-data/argo-input/datasets/dataset_1`, then the 'photo_path' should be written as `/data/argo-input/datasets/dataset_1`

The `output_path`, `project_path`, and `run_name` configuration parameters are handled in the
argo workflow. `output_path` and `project_path` are determined via the arguments passed to the
automate-metashape container, which in turn are derived from the `RUN_FOLDER` workflow parameter
passed when invoking `argo run`). `run_name` is pulled from the name of the config file (minus the
extension) by the Argo workflow. Any values specified for these parameters in the config.yml will be
ignored.

<br/>

#### c. Config List

Additionally we use a text file, for example `config_list.txt`, to tell the Argo workflow which config files should be processed in the current run. This text file should list each of the names of the config.yml files you want to process. One config file name per line. 

For example:

```
01_benchmarking-greasewood.yml
02_benchmarking-greasewood.yml
01_benchmarking-emerald-subset.yml
02_benchmarking-emerald-subset.yml
```  

You can create your own config_list.txt file and name it whatever you want as long as it is kept at
the root level of `/ofo-share-2/argo-data/argo-input/`.

<br/>
<br/>


## Run the Workflow

### 0. Authenticate to the cluster

DYTODO

### 1. Declare the ip address of the metashape license server

On the local machine you'll use to submit the Argo job, type:

`export AGISOFT_FLS=<ip_address>:5842`

This variable will only last during the terminal session and will have to be re-declared each time you start a new master terminal. We are not putting the ip address here to prevent unauthorized people from using it. Authorized users can find it [here](https://docs.google.com/document/d/155AP0P3jkVa-yT53a-QLp7vBAfjRa78gdST1Dfb4fls/edit?tab=t.0).

<br/>

### 2. Declare credentials for upload to S3 bucket

This Argo workflow uploads and downloads to Jetstream2's S3 compatible buckets. 

Please create a kubernetes secret to store the S3 Access ID and Secret Key

```
kubectl create secret generic s3-credentials \ --from-literal=access_key=<YOUR_ACCESS_KEY_ID> \ --from-literal=secret_key=<YOUR_SECRET_ACCESS_KEY> \ -n argo 
```

### 3. Run!!

```
argo submit -n argo workflow.yaml --watch \
-p CONFIG_LIST=config_list.txt \
-p AGISOFT_FLS=$AGISOFT_FLS \
-p RUN_FOLDER=gillan_june27 \
-p S3_BUCKET=ofo-internal \
-p S3_PROVIDER=Other \
-p S3_ENDPOINT=https://js2.jetstream-cloud.org:8001 \
-p S3_BUCKET_OUTPUT=ofo-public \
-p OUTPUT_DIRECTORY=jgillan_test \
-p BOUNDARY_DIRECTORY=jgillan_test \
-p WORKING_DIR=/tmp/processing 

Database parameters (not currently functional)
-p DB_PASSWORD=<password> \
-p DB_HOST=<vm_ip_address> \
-p DB_NAME=<db_name> \
-p DB_USER=<user_name> \
 
```

*CONFIG_LIST* is a text file that lists each of the metashape parameter config files to be processed which should be located in `/ofo-share-2/argo-data/argo-input`

*AGISOFT_FLS* is the ip address of the metashape license server. You declared this as an environmental variable in the previous step

*RUN_FOLDER* is what you want to name the parent directory of the Metashape outputs

*S3_BUCKET* is the bucket where Metashape products are uploaded to. Keep as 'ofo-internal'. 

*S3_PROVIDER* keep as 'Other'

*S3_ENDPOINT* is the url of the Jetstream2s S3 storage

*S3_BUCKET_OUTPUT* is the final resting place after postprocessing has been done on imagery products. Keep as 'ofo-public'

*OUTPUT_DIRECTORY* is the name of the parent folder where postprocessed products will be uploaded

*BOUNDARY_DIRECTORY* is the parent directory where the mission boundary polygons reside. These are used to clip imagery products.

*WORKING_DIR* parameter specifies the directory within the container where the imagery products are downloaded to and postprocessed. The typical place is`/tmp/processing` which means the data will be downloaded to the processing computer and postprocessed there. You have the ability to change the WORKING_DIR to a persistent volume (PVC).

The rest of the 'DB' parameters are for logging argo status in a postGIS database. These are not public credentials. Authorized users can find them [here](https://docs.google.com/document/d/155AP0P3jkVa-yT53a-QLp7vBAfjRa78gdST1Dfb4fls/edit?tab=t.0).

<br/>

### 4. Monitor Argo Workflow
The Argo UI is great for troubleshooting and checking additional logs. You can access it at at
argo.focal-lab.org, using the credentials explained in DYTODO.



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


### 5. Workflow Outputs

The final outputs will be written to 'S3:ofo-public' in the following directory structure. This structure should already exist prior to the argo workflow. 


```bash
/S3:ofo-public/
├── <OUTPUT_DIRECTORY>/
    ├── dataset1/
         ├── images/
         ├── metadata-images/
         ├── metadata-mission/
            └── dataset1_mission-metadata.gpkg
         ├──processed_01/
            ├── full/
               ├── 01_dataset1_cameras.xml
               ├── 01_dataset1_chm.tif
               ├── 01_dataset1_dsm-ptcloud.tif
               ├── 01_dataset1_dtm-ptcloud.tif
               ├── 01_dataset1_log.txt
               ├── 01_dataset1_ortho-dtm-ptcloud.tif
               ├── 01_dataset1_points-copc.laz
               └── 01_dataset1_report.pdf
            ├── thumbnails/
               ├── 01_dataset1_chm.png
               ├── 01_dataset1_dsm-ptcloud.png
               ├── 01_dataset1_dtm-ptcloud.png
               └── 01_dataset1-ortho-dtm-ptcloud.png
         ├──processed_02/
            ├── full/
               ├── 02_dataset1_cameras.xml
               ├── 02_dataset1_chm.tif
               ├── 02_dataset1_dsm-ptcloud.tif
               ├── 02_dataset1_dtm-ptcloud.tif
               ├── 02_dataset1_log.txt
               ├── 02_dataset1_ortho-dtm-ptcloud.tif
               ├── 02_dataset1_points-copc.laz
               └── 02_dataset1_report.pdf
            ├── thumbnails/
               ├── 02_dataset1_chm.png
               ├── 02_dataset1_dsm-ptcloud.png
               ├── 02_dataset1_dtm-ptcloud.png
               └── 02_dataset1-ortho-dtm-ptcloud.png
    ├── dataset2/

```




<br/>
<br/>
<br/>
<br/>

<!-- 

### 6. Argo Workflow Logging in postGIS database 

__THE DB LOGGING IS CURRENTLY DISABLED AND IS BEING MIGRATED TO A HOSTED SOLUTION THROUGH SUPABASE__

Argo run status is logged into a postGIS DB. This is done through an additional docker container (hosted on github container registry `ghcr.io/open-forest-observatory/ofo-argo-utils:latest`) that is included in the argo workflow. The files to make the docker image are in the folder `ofo-argo-utils`. 

<br/>


#### Info on the postGIS DB
There is a JS2 VM called `ofo-postgis` that hosts a postGIS DB for storing metadata of argo workflows. 

<br/>

You can access the `ofo-postgis` VM through Webshell in Exosphere. Another access option is to SSH into `ofo-postgis` with the command `ssh exouser@<ip_address>`. This is not public and will require a password. 

<br/>

The DB is running in a docker container (`postgis/postgis`). The DB storage is a 10 GB volume at `/media/volume/ofo-postgis` on the VM. 

<br/>

#### Steps to View the Logged Results

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

#### Other useful commands

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
<br/>

#### Github action to rebuild DB logging docker image

There is github action workflow that rebuilds the logging docker image if any changes have been made at all in the repo. This workflow is in the directory `.github/workflows`. **The workflow is currently disabled in the 'Actions' section of the repository.**


<br/>
<br/>
<br/>

-->



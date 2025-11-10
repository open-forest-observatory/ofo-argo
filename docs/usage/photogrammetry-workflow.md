---
title: Running the photogrammetry workflow
weight: 20
---

# Running the photogrammetry workflow

This guide describes how to run the OFO photogrammetry workflow, which processes drone imagery using [automate-metashape](https://github.com/open-forest-observatory/automate-metashape) and performs post-processing steps.

## Prerequisites

Before running the workflow, ensure you have:

1. [Installed and set up the `openstack` and `kubectl` utilities](cluster-access-and-resizing.md)
1. [Installed the Argo CLI](argo-usage.md)
1. Added the appropriate type and number of nodes to the cluster (cluster-access-and-resizing.md#cluster-resizing)
1. Set up your `kubectl` authentication env var (part of instructions for adding nodes). Quick reference:

```
source ~/venv/openstack/bin/activate
source ~/.ofocluster/app-cred-ofocluster-openrc.sh
export KUBECONFIG=~/.ofocluster/ofocluster.kubeconfig
```

## Workflow overview

The workflow performs the following steps:

1. Pulls raw drone imagery from `/ofo-share-2` onto the Kubernetes VM cluster
2. Processes the imagery with Metashape
3. Writes the imagery products to `/ofo-share-2`
4. Uploads the imagery products to `S3:ofo-internal` and deletes them from `/ofo-share`
5. Downloads the imagery products from S3 back to the cluster and performs [postprocessing](https://github.com/open-forest-observatory/ofo-argo/tree/main/postprocess_docker) (CHMs, clipping, COGs, thumbnails)
6. Uploads the final products to `S3:ofo-public`

## Setup

### 1. Prepare inputs

Before running the workflow, you need to prepare three types of inputs on the cluster's shared storage:

1. Drone imagery datasets (JPEG images)
2. Metashape configuration files
3. A config list file specifying which configs to process

All inputs must be placed in `/ofo-share-2/argo-data/`.

#### Directory structure

Here is a schematic of the `/ofo-share-2/argo-data` directory:

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

#### Add drone imagery datasets

To add new drone imagery datasets to be processed using Argo, transfer files from your local machine (or the cloud) to the `/ofo-share-2` volume. Put the drone imagery projects to be processed in their own directory in `/ofo-share-2/argo-data/argo-input/datasets`.

One data transfer method is the `scp` command-line tool:

```bash
scp -r <local/directory/drone_image_dataset/> exouser@<vm.ip.address>:/ofo-share-2/argo-data/argo-input/datasets
```

Replace `<vm.ip.address>` with the IP address of a cluster node that has the share mounted.

#### Specify Metashape parameters

Metashape processing parameters are specified in [configuration YAML files](https://github.com/open-forest-observatory/automate-metashape/blob/main/config/config-base.yml) which need to be located at `/ofo-share-2/argo-data/argo-input/configs/`.

Every dataset to be processed needs to have its own standalone configuration file.

**Naming convention:** Config files should be named to match the naming convention `<config_id>_<datasetname>.yml`. For example:

- `01_benchmarking-greasewood.yml`
- `02_benchmarking-greasewood.yml`

**Setting the `photo_path`:** Within each metashape config.yml file, you must specify `photo_path`
which is the location of the drone imagery dataset to be processed. When running via Argo workflows,
this path refers to the location of the images **inside the docker container**.

For example, if your drone images were uploaded to `/ofo-share-2/argo-data/argo-input/datasets/dataset_1`, then the `photo_path` should be written as:

```yaml
photo_path: /data/argo-input/datasets/dataset_1
```

**Parameters handled by Argo:** The `output_path`, `project_path`, and `run_name` configuration parameters are handled automatically by the Argo workflow:

- `output_path` and `project_path` are determined via the arguments passed to the automate-metashape container, which in turn are derived from the `RUN_FOLDER` workflow parameter passed when invoking `argo submit`
- `run_name` is pulled from the name of the config file (minus the extension) by the Argo workflow

Any values specified for these parameters in the config.yml will be ignored.

#### Create a config list file

We use a text file, for example `config_list.txt`, to tell the Argo workflow which config files should be processed in the current run. This text file should list the paths to each config.yml file you want to process (relative to `/ofo-share-2/argo-data`), one config file path per line.

For example:

```
argo-input/configs/01_benchmarking-greasewood.yml
argo-input/configs/02_benchmarking-greasewood.yml
argo-input/configs/01_benchmarking-emerald-subset.yml
argo-input/configs/02_benchmarking-emerald-subset.yml
```

This allows you to organize your config files in subdirectories or different locations. The dataset name will be automatically derived from the config filename (e.g., `argo-input/configs/dataset-name.yml` becomes dataset `dataset-name`).

You can create your own config_list.txt file and name it whatever you want as long as it is kept at the root level of `/ofo-share-2/argo-data/argo-input/`.


## Submit the workflow

Once your cluster authentication is set up and your inputs are prepared, run:

```bash
argo submit -n argo workflow.yaml --watch \
-p CONFIG_LIST=config_list.txt \
-p RUN_FOLDER=gillan_june27 \
-p S3_BUCKET=ofo-internal \
-p S3_BUCKET_OUTPUT=ofo-public \
-p OUTPUT_DIRECTORY=jgillan_test \
-p BOUNDARY_DIRECTORY=jgillan_test \
-p WORKING_DIR=/tmp/processing
```

Database parameters (not currently functional):
```bash
-p DB_PASSWORD=<password> \
-p DB_HOST=<vm_ip_address> \
-p DB_NAME=<db_name> \
-p DB_USER=<user_name>
```


### Workflow parameters

| Parameter | Description |
|-----------|-------------|
| `CONFIG_LIST` | Text file listing paths to metashape config files (relative to `/ofo-share-2/argo-data`) |
| `RUN_FOLDER` | Name for the parent directory of the Metashape outputs (locally under `argo-data/argo-outputs` and at the top level of the S3 bucket). Recommend `photogrammetry-outputs/config_<config_id>`. |
| `S3_BUCKET` | Bucket where Metashape products are uploaded (typically `ofo-internal`) |
| `S3_BUCKET_OUTPUT` | Final destination after postprocessing (typically `ofo-public`) |
| `OUTPUT_DIRECTORY` | Name of parent folder where postprocessed products are uploaded |
| `BOUNDARY_DIRECTORY` | Parent directory where mission boundary polygons reside (used to clip imagery) |
| `WORKING_DIR` | Directory within container for downloading and postprocessing (typically `/tmp/processing` which downloads data to the processing computer; can be changed to a persistent volume) |
| `DB_*` | Database parameters for logging Argo status (not currently functional; credentials in [OFO credentials document](https://docs.google.com/document/d/155AP0P3jkVa-yT53a-QLp7vBAfjRa78gdST1Dfb4fls/edit?tab=t.0)) |

**Secrets configuration:**
- **S3 credentials**: S3 access credentials, provider type, and endpoint URL are configured via the `s3-credentials` Kubernetes secret
- **Agisoft license**: Metashape floating license server address is configured via the
  `agisoft-license` Kubernetes secret

These secrets should have been created (within the `argo` namespace) during [cluster creation](../admin/cluster-creation-and-resizing.md).

## Monitor the workflow

### Using the Argo UI

The Argo UI is great for troubleshooting and checking additional logs. Access it at [argo.focal-lab.org](https://argo.focal-lab.org), using the credentials from [Vaultwarden](https://vault.focal-lab.org) under the record "Argo UI token".

#### Navigating the Argo UI

The **Workflows** tab on the left side menu shows all running workflows. Click a current workflow to see a schematic of the jobs spread across multiple instances:

![Argo workflow overview](https://github.com/user-attachments/assets/bd6bd991-f108-4be9-a1aa-6cb0f1ab1db5)

Click on a specific job to see detailed information including which VM it is running on, the duration of the process, and logs:

![Argo job details](https://github.com/user-attachments/assets/ab10f2b4-3120-47be-b1dd-601687707f0c)

A successful Argo run looks like this:

![Successful Argo run](https://github.com/user-attachments/assets/201b0594-7557-4d85-a99b-677e6c173a44)

## Workflow outputs

The final outputs will be written to `S3:ofo-public` in the following directory structure:

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

This directory structure should already exist prior to running the Argo workflow.

<!--

## Argo Workflow Logging in PostGIS Database

**THE DB LOGGING IS CURRENTLY DISABLED AND IS BEING MIGRATED TO A HOSTED SOLUTION THROUGH SUPABASE**

Argo run status is logged into a PostGIS DB. This is done through an additional docker container (hosted on GitHub Container Registry `ghcr.io/open-forest-observatory/ofo-argo-utils:latest`) that is included in the argo workflow. The files to make the docker image are in the folder `ofo-argo-utils`.

### Info on the PostGIS DB

There is a JS2 VM called `ofo-postgis` that hosts a PostGIS DB for storing metadata of argo workflows.

You can access the `ofo-postgis` VM through Webshell in Exosphere. Another access option is to SSH into `ofo-postgis` with the command `ssh exouser@<ip_address>`. This is not public and will require a password.

The DB is running in a docker container (`postgis/postgis`). The DB storage is a 10 GB volume at `/media/volume/ofo-postgis` on the VM.

### Steps to View the Logged Results

Enter the Docker container running the PostGIS server:
```bash
sudo docker exec -ti ofo-postgis bash
```

Launch the PostgreSQL CLI as the intended user (grab from DB credentials):
```bash
psql -U postgres
```

List all tables in the database:
```
\dt
```

Show the structure of a specific table (column names & data types):
```
\d automate_metashape
```

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

View all data records for a specific table:
```sql
select * from automate_metashape ORDER BY id DESC;
```

![SQL query results](https://github.com/user-attachments/assets/cba4532a-21de-4c35-8b2d-635eec326ef7)

Exit out of psql command-line:
```
\q
```

Exit out of container:
```bash
exit
```

### Other useful commands

View all running and stopped containers:
```bash
docker ps -a
```

Stop a running container:
```bash
docker stop <container_id>
```

Remove container:
```bash
docker rm <container_id>
```

Run the docker container DB:
```bash
sudo docker run --name ofo-postgis   -e POSTGRES_PASSWORD=ujJ1tsY9OizN0IpOgl1mY1cQGvgja3SI   -p 5432:5432   -v /media/volume/ofo-postgis/data:/var/lib/postgresql/data  -d postgis/postgis
```

### Github action to rebuild DB logging docker image

There is a GitHub action workflow that rebuilds the logging docker image if any changes have been made at all in the repo. This workflow is in the directory `.github/workflows`. **The workflow is currently disabled in the 'Actions' section of the repository.**

-->

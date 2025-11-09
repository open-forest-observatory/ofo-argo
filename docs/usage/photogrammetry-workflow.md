---
title: Running the photogrammetry workflow
weight: 20
---

# Running the photogrammetry workflow

This guide describes how to run the OFO photogrammetry workflow, which processes drone imagery using [automate-metashape](https://github.com/open-forest-observatory/automate-metashape) and performs post-processing steps.

## Prerequisites

Before running the workflow, ensure you have:

1. [Prepared your inputs](input-preparation.md) (drone imagery, config files, and config list)
2. [Authenticated to the cluster](argo-usage.md#authenticate-with-the-cluster)
3. Installed the [Argo CLI](argo-usage.md#install-the-argo-cli-locally-one-time)

## Workflow overview

The current workflow performs the following steps:

1. Pulls raw drone imagery from `/ofo-share` onto the Kubernetes VM cluster
2. Processes the imagery with Metashape
3. Writes the imagery products to `/ofo-share` and uploads them to `S3:ofo-internal`
4. Deletes all outputs on `/ofo-share`
5. Downloads the imagery products from S3 back to the cluster and performs [postprocessing](https://github.com/open-forest-observatory/ofo-argo/tree/main/postprocess_docker) (CHMs, clipping, COGs, thumbnails)
6. Uploads the final products to `S3:ofo-public`

## Setup: Declare credentials

### 1. Declare the Metashape license server address

On your local machine, set the Agisoft floating license server address as an environment variable:

```bash
export AGISOFT_FLS=<ip_address>:5842
```

This variable will only last during the terminal session and will have to be re-declared each time you start a new terminal. The IP address is not published here to prevent unauthorized use. Authorized users can find it in the [OFO credentials document](https://docs.google.com/document/d/155AP0P3jkVa-yT53a-QLp7vBAfjRa78gdST1Dfb4fls/edit?tab=t.0).

### 2. Create S3 credentials secret

This Argo workflow uploads and downloads to Jetstream2's S3-compatible buckets. You need to create a Kubernetes secret to store the S3 Access ID and Secret Key:

```bash
kubectl create secret generic s3-credentials \
  --from-literal=access_key=<YOUR_ACCESS_KEY_ID> \
  --from-literal=secret_key=<YOUR_SECRET_ACCESS_KEY> \
  -n argo
```

**This only needs to be done once per cluster.**

## Submit the workflow

Once your cluster authentication is set up and your inputs are prepared, run:

```bash
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
| `CONFIG_LIST` | Text file listing metashape config files to process (located in `/ofo-share-2/argo-data/argo-input`) |
| `AGISOFT_FLS` | IP address of the Metashape license server (declared as environment variable) |
| `RUN_FOLDER` | Name for the parent directory of the Metashape outputs |
| `S3_BUCKET` | Bucket where Metashape products are uploaded (typically `ofo-internal`) |
| `S3_PROVIDER` | Keep as `Other` |
| `S3_ENDPOINT` | URL of Jetstream2's S3 storage (`https://js2.jetstream-cloud.org:8001`) |
| `S3_BUCKET_OUTPUT` | Final destination after postprocessing (typically `ofo-public`) |
| `OUTPUT_DIRECTORY` | Name of parent folder where postprocessed products are uploaded |
| `BOUNDARY_DIRECTORY` | Parent directory where mission boundary polygons reside (used to clip imagery) |
| `WORKING_DIR` | Directory within container for downloading and postprocessing (typically `/tmp/processing` which downloads data to the processing computer; can be changed to a persistent volume) |
| `DB_*` | Database parameters for logging Argo status (not currently functional; credentials in [OFO credentials document](https://docs.google.com/document/d/155AP0P3jkVa-yT53a-QLp7vBAfjRa78gdST1Dfb4fls/edit?tab=t.0)) |

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

---
title: Preparing inputs for workflows
weight: 10
---

# Preparing inputs for workflows

Before running the Argo workflow, you need to prepare three types of inputs on the cluster's shared storage:

1. Drone imagery datasets (JPEG images)
2. Metashape configuration files
3. A config list file specifying which configs to process

All inputs must be placed in `/ofo-share-2/argo-data/`.

## Directory structure

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

## Add drone imagery datasets

To add new drone imagery datasets to be processed using Argo, transfer files from your local machine (or the cloud) to the `/ofo-share-2` volume. Put the drone imagery projects to be processed in their own directory in `/ofo-share-2/argo-data/argo-input/datasets`.

### Using SCP

One data transfer method is the `scp` command-line tool:

```bash
scp -r <local/directory/drone_image_dataset/> exouser@<vm.ip.address>:/ofo-share-2/argo-data/argo-input/datasets
```

Replace `<vm.ip.address>` with the IP address of a cluster node that has the share mounted.

## Specify Metashape parameters

Metashape processing parameters are specified in [configuration YAML files](https://github.com/open-forest-observatory/automate-metashape/blob/main/config/config-base.yml) which need to be located at `/ofo-share-2/argo-data/argo-input/configs`.

Every dataset to be processed needs to have its own standalone configuration file.

### Naming convention

Config files should be named to match the naming convention `<config_id>_<datasetname>.yml`. For example:

- `01_benchmarking-greasewood.yml`
- `02_benchmarking-greasewood.yml`

### Setting the photo_path

Within each metashape config.yml file, you must specify `photo_path` which is the location of the drone imagery dataset to be processed. This path refers to the location of the images **inside a docker container**.

For example, if your drone images were uploaded to `/ofo-share-2/argo-data/argo-input/datasets/dataset_1`, then the `photo_path` should be written as:

```yaml
photo_path: /data/argo-input/datasets/dataset_1
```

### Parameters handled by Argo

The `output_path`, `project_path`, and `run_name` configuration parameters are handled automatically by the Argo workflow:

- `output_path` and `project_path` are determined via the arguments passed to the automate-metashape container, which in turn are derived from the `RUN_FOLDER` workflow parameter passed when invoking `argo submit`
- `run_name` is pulled from the name of the config file (minus the extension) by the Argo workflow

Any values specified for these parameters in the config.yml will be ignored.

## Create a config list file

We use a text file, for example `config_list.txt`, to tell the Argo workflow which config files should be processed in the current run. This text file should list each of the names of the config.yml files you want to process, one config file name per line.

For example:

```
01_benchmarking-greasewood.yml
02_benchmarking-greasewood.yml
01_benchmarking-emerald-subset.yml
02_benchmarking-emerald-subset.yml
```

You can create your own config_list.txt file and name it whatever you want as long as it is kept at the root level of `/ofo-share-2/argo-data/argo-input/`.

## Next steps

Once your inputs are prepared, you're ready to [submit the workflow](argo-usage.md).

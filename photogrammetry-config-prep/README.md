## `create-derived-configs.py`
This script generates one derived automate-metashape config file per drone mission. Each derived config is a copy of a base config with a few mission-specific values overridden:

- `project.photo_path`: one `__DOWNLOADED__/{mission_id}_images/{sub_mission_id}` entry per sub-mission listed for the mission
- `project.project_crs`: the UTM zone EPSG code (e.g. `EPSG::32610`) computed from the centroid of the mission polygon
- `argo.s3_imagery_zip_download`: the S3 path of the mission's zipped imagery, `{S3_DRONE_MISSIONS_PATH}/{mission_id}/images/{mission_id}_images.zip`

### Usage
Edit the constants at the top of the script, then run it with no arguments:

```bash
python create-derived-configs.py
```

Dependencies: `geopandas`, `pyyaml`, and `shapely`.

### Configuration constants and input files
| Constant | Description |
| --- | --- |
| `MISSIONS_GPKG_PATH` | **Required input.** GeoPackage of mission polygons and metadata, one row per mission. It must have a `mission_id` column and a `sub_mission_ids` column (comma-separated, e.g. `000002-01, 000002-02`). The script raises an error if `sub_mission_ids` is empty for any mission. See below for how to create it. |
| `BASE_CONFIG_PATH` | **Required input.** The base automate-metashape config YAML that is copied and overridden for each mission. |
| `PRIORITY_AREA_KML_PATH` | Optional KML file defining a priority area. Missions whose centroid falls within the area (buffered by `PRIORITY_BUFFER_DEGREES`) are listed first in `config-list.txt`. Set to `None` to disable. |
| `PRIORITY_BUFFER_DEGREES` | Buffer around the priority area, in degrees (0.1 is roughly 10 km at mid-latitudes). |
| `OUTPUT_DIR` | Directory where the derived configs are written. Created if it does not exist. |
| `S3_DRONE_MISSIONS_PATH` | S3 `bucket/path` prefix under which each mission's `{mission_id}/images/{mission_id}_images.zip` is stored. No rclone remote prefix is needed; credentials come from the cluster's `s3-credentials` Kubernetes secret. |

### Creating the missions GeoPackage
The file at `MISSIONS_GPKG_PATH` can be created with [`deploy/drone-imagery-ingestion/10_drone-mission-web-catalog/05_get-all-mission-metadata.R`](https://github.com/open-forest-observatory/ofo-catalog-data-prep/blob/main/deploy/drone-imagery-ingestion/10_drone-mission-web-catalog/05_get-all-mission-metadata.R) in the [ofo-catalog-data-prep](https://github.com/open-forest-observatory/ofo-catalog-data-prep) repository. That script uses `rclone` to download every `*_mission-metadata.gpkg` file from the object store and compiles them into a single mission-polygon GeoPackage (it also compiles the image-point metadata into a second one, which is not needed here). It requires an rclone remote already configured on the machine (or S3 credentials set via environment variables), and is run from the root of that repository. The output location is set by the constants in `deploy/drone-imagery-ingestion/00_set-constants.R`.

### Outputs
- One `{mission_id}.yml` config per mission in `OUTPUT_DIR`.
- `config-list.txt` in `OUTPUT_DIR`, listing the config filenames under a `# High-priority missions` section followed by a `# Standard-priority missions` section.

## `create-derived-configs-paired-mission.py`
This script generates config files to run photogrammetry on pairs of missions. Much of the logic is similar to the the `created-derived-config.py` script, except that images from two datasets are used. Additionally, an altitude offset (config value `paired_altitude_offset`) is provided. Since the altitude is determined barometrically, there can be substantial variations between missions. To correct for this, the altitude above ground is computed for each single mission using the single-mission photogrammetry results. The photogrammetry-optimized locations of the images are compared to the DTM, and each camera is assigned an altitude. Then, the mean altitude for images included in the pair is computed per dataset. The difference between these two altitudes is provided to automate-metashape, along which which images correspond to each dataset. Automate-metashape then corrects the altitudes of the images such that the mean difference between the altitudes of the two sets matches what is specified. This functionality is specific to automate-metashape and not provided in the stand-alone version of Agisoft Metashape.

To run this script, the composite image- and mission-level metadata must be downloaded and pointed to by `COMPOSITE_IMAGES_GPKG_PATH` and `MISSION_METADATA_GPKG_PATH`, respectively. The path to the base config and output directory must be provided as well.

The composite images metadata should already have been subset to the images included within the paired mission polygons. Note, the low oblique polygon may be larger than that of the high nadir one to account for images looking inward to the central area. The information about the subset is uploaded directly to S3 so it can be obtained at the same time that the raw imagery is downloaded.
The S3 upload is controlled by the following four environment variables: `S3_PROVIDER`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, and `S3_SECRET_KEY`.

The newly-created derived configs are saved locally in the folder specified by `OUTPUT_DIR_CONFIGS`. This folder will also contain a `config-list.txt` file, which records the names of all generated configs.
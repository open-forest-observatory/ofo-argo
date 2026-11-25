## Tree Detection and Attribute Prediction
The `species-prediction-workflow.yaml` contains code to detect trees and classify their species and live/dead status. This workflow requires that photogrammetry and post-processing have been run on the corresponding datasets.

The workflow performs the follow series of steps
- **Downloading imagery**: Download the zipped mission-level images that were used for photogrammetry and optionally subset to the ones which were actually used.
- **Downloading photogrammetry products**: Download the mesh, cameras, CHM, and DTM.
- **Tree detection**: Using the two-stage geometric detector from TDF, first detect tree tops and then segment the crowns with watershed.
- **Instance ID rendering**: Using geograypher, render the `unique_ID` field of the segmented trees to the perspective of each image. These renders are saved out in a folder structure paralleling the input imagery.
- **Chipping**: Chip out the images corresponding to the view of each tree and mask the background. This structure parallels the structure of the input data, with one folder of chips for each input image. Within that folder, chips are named based on the tree `unique_ID` that generated them.
- **Prediction**: The species and live/dead predictions are generated using `MMPretrain` and the per-chip predictions are saved to a `.json` file.
- **Aggregation and merging**: The final step is to use the per-chip predictions to vote on the class per tree. Then this information is merged into the original geospatial data product as a new column. This step is computationally very fast, and is only distinct from the prediction step because the `MMPretrain` container does not have the required dependencies to load geospatial files.

## Registring Field Trees to Drone Products
There may be a spatial miss-alignment between the field reference data and the drone products. This is primarily driven by differences in the GPS bias between the surveys. The `register-field-trees-to-CHM.yaml` workflow can be used to estimate a shift which best aligns the field data with the drone products, specifically by using the CHM. This approach determines the shift which produces the best correlation between the field trees heights and the corresponding locations on the CHM. This is done in a two-stage coarse-to-fine manner.

The workflow takes as input field trees and field plot bounds from the shared data drive and downloads drone mission metadata and CHM products from `S3`. For each overlapping pair of field plot and drone mission, the output is a `.csv` file containing the shift which would best align the field trees to the corresponding CHM, with associated quality metrics. This file is uploaded to S3 and follows the convention `{missions dir}/{mission ID}/{photogrammetry ID}/ground-reference-shifts/{mission ID}_{plot ID}_ground-reference-shift.csv`. This means in can be uploaded into the processed data folder tree if desired.

For each paired drone mission ID and ground reference plot ID, the following steps are performed:
- The ground reference data is subset to the specified ground reference plot ID. The trees are validated to ensure each one is live, has height information, and is taller than a minimum height. If there are fewer than two trees meeting these criteria the step fails.
- The drone mission CHM derived from photogrammetry data is downloaded from S3.
- The registration step is run using the [register_trees_to_CHM.py](https://github.com/open-forest-observatory/tree-registration-and-matching/blob/main/tree_registration_and_matching/entrypoints/register_trees_to_CHM.py) entrypoint.
- The registration quality score is compared against a threshold value.
- If the shift is predicted to be high quality, the file defining the computed shift is uploaded to S3. In this case, all temporary data is removed from `per-pair-data`.
- If the shift does not meet the high quality criteria, a visualization is produced in the `shifts-to-validate` subfolder of the temp directory. Similarly, the raw data and computed shift is retained in the `per-pair-data` subfolder. In many cases, the computed shift is correct despite failing to meet the criteria for automatic inclusion. Therefore, it is suggested to manually inspect the `shifts-to-validate` visualizations and manually upload the subset of shifts that look correct. The data remaining in `per-pair-data` can be used to compute manual shifts.

### Parameters

- **`DATASETS_FILE`** (required): Path to a `.csv` file on the mounted volume specifying the (drone mission, field plot) pairs to run on. It should have no header and one line per pair, with three columns ordered: drone mission ID, field plot ID, photogrammetry ID. Drone mission IDs should be zero-padded to six digits and field plot IDs to four. The photogrammetry ID is the photogrammetry run to use for that pair (e.g. `photogrammetry_03`). Each pair may only be given one photogrammetry ID; repeated lines for the same pair are ignored, and the workflow fails if a pair is listed with two different photogrammetry IDs.

- **`GROUND_REFERENCE_TREES_FILE`** (required): Path to the file of ground reference trees for all plots, with a `plot_id` column.

- **`GROUND_REFERENCE_PLOTS_FILE`** (required): Path to the file of ground reference plot boundaries for all plots, with a `plot_id` column.

- **`RATIO_QUALITY_METRIC_THRESHOLD`** (default: `"0.4887"`): Pairs whose registration `ratio_quality_metric` is at or below this value are trusted automatically, and their shift file is uploaded to `S3`. Pairs above it require manual assessment: their shift file is not uploaded, and an image to support the assessment is saved to `TEMP_FOLDER/<workflow-name>/shifts-to-validate/<mission_id>_<plot_id>.png`.

- **`MIN_TREE_HEIGHT`** (default: `"5.0"`): The minimum height of a tree to use in registration. Ground reference trees below this height are dropped, and a pair fails if fewer than two trees remain.

- **`S3_BUCKET_PUBLIC`** (default: `"ofo-public"`): `S3` bucket to download the CHM files from.

- **`S3_DATA_FOLDER`** (default: `"drone/missions_03"`): Folder within `S3_BUCKET_PUBLIC` holding the drone mission products. The CHM for each pair is read from `<S3_BUCKET_PUBLIC>/<S3_DATA_FOLDER>/<mission_id>/<photogrammetry_id>/full/<mission_id>_chm-mesh.tif`.

- **`TEMP_FOLDER`** (default: `"/data/argo-output/temp-dir"`): Base directory for temporary products. All temp outputs for a run are saved under `TEMP_FOLDER/<workflow-name>`.

- **`TRAM_IMAGE_TAG`** (default: `"main"`): Version tag for the tree-registration-and-matching Docker image.

- **`S3_UPLOAD_PATH`** (default: `"ofo-internal/species-project/registration"`): Where on `S3` the shift files are uploaded, including the bucket name and no trailing slash. Each file is saved to `<S3_UPLOAD_PATH>/<mission_id>/<photogrammetry_id>/ground-reference-shifts/<mission_id>_<plot_id>_ground-reference-shift.csv`.

## Tree Detection and Evaluation
The `tree-detection-and-eval.yaml` workflow benchmarks one or more tree detectors against field reference data across a set of drone missions and field plots. It fans out over all `(mission, plot)` pairs in a datasets file and all detector configurations in a detection config file, running each combination in parallel.

The workflow performs the following steps for each `(mission, plot, detector config)` combination:
- **Download**: Pulls the orthomosaic, CHM, and ground-reference shift file from S3.
- **Preprocess**: Applies the spatial shift to field trees and plot bounds, filters by minimum tree height, and crops rasters to the shifted plot boundary.
- **Detect**: Runs the specified detector (geometric on CPU; all others on GPU) to produce raw detections.
- **Postprocess**: Applies the postprocessing chain for the config (or just a height filter for the geometric detector).
- **Evaluate**: Matches predicted tree points to ground truth and computes precision, recall, and F1.
- **Upload**: Writes per-run `eval_results.json` and `detections.gpkg` to S3. After all datasets finish, merges all results into a single summary CSV and uploads it.

### Input file structure examples

**`datasets.csv`** - one row per `(mission, plot)` pair to process:
```
mission_id,plot_id
000001,0052
000091,0040
000113,0028
```

**`detection_config.csv`** - one row per detector configuration to benchmark. `postprocessing_id` references a key in `postprocessing_config.yaml`; leave it empty for the geometric detector.
```
config_id,detector,chip_size,chip_stride,chip_overlap_percentage,resolution,batch_size,postprocessing_id
geometric_01,geometric,2000,1900,,0.2,1,
deepforest_01,deepforest,500,500,,0.2,4,postprocessing_01
detectree2_01,detectree2,500,500,,0.2,4,postprocessing_02
```

**`postprocessing_config.yaml`** - maps each `postprocessing_id` to an ordered list of postprocessor steps:
```yaml
postprocessing_01:
  - name: multi_region_NMS
    args:
      threshold: 0.5
      min_confidence: 0.3
      intersection_method: IOU
  - name: filter_by_chm
    args:
      min_height: 5.0
postprocessing_02:
  - name: suppress_tile_boundary_with_NMS
  - name: single_region_hole_suppression
    args:
      min_area_threshold: 25.0
```

## Creating chips for model training
The `species-prediction-training-data-prep.yaml` workflow is used to produce training data for tree-level attribute prediction tasks, such as predicting tree species. Specifically, the model operates (both for training and inference) on each individual view of a given tree, taken from the raw drone images captured by the survey. This process begins with manually collected field reference data and predicted tree crowns detected from drone-derived photogrammetry products. Then, the drone and field trees are matched and the matched drone crowns are rendered to the perspective of each image. These renders are then chipped to provided one image per view of each matched trees. These chips can be linked back to the attributes of the field tree and used to train a model for any attribute which was surveyed. Additionally, this workflow predicts a live/dead status for each view and adds the predicted status to the tree-level metadata. All data is uploaded to `S3` and can be downloaded to train models. A publication summarizing this workflow can be found [here](https://ecoevorxiv.org/repository/view/13675).

### Inputs
#### Workflow level-inputs
- **Which datasets to run**
You directly specifies which field-drone pairs to process in a two column csv file. The file should not contain a header. The first field represents which drone dataset to use. This can either be the `ofo_drone_mission_id` (padded to six digits) or a concatenation of two `id`s separated by an `_`, such as when nadir and oblique data is processed together. Note that concatenated IDs should always have the nadir ID first. The second field is the `ofo_plot_id` (padded to four digits). This file is pointed to by the `DATASETS_FILE` workflow parameter. An example row of the file for a paired mission is `001439_001440, 0045` and for a single mission,`001439, 0045`. In almost all cases, the file should only contain one format of missions (either paired or single) since this workflow expects all photogrammetry products to be uploaded to the same `S3_PROCESSED_MISSIONS_FOLDER` folder, which has only one format of mission.
- **Ground reference information**: You must provide two files on the `ofo-share` describing the field-surveyed tree points and the corresponding bounds of the surveyed plots. These files should both contain the `plot_id` key, which describes which surveyed plot they correspond to. The workflow parameters that control these inputs are `GROUND_REFERENCE_TREES_FILE` and `GROUND_REFERENCE_PLOTS_FILE`.
- **Live/dead classification model**: This generates predictions from individual cropped views of each tree of whether it is alive or not. This information can be later used to filter the training data only to live trees. The workflow parameters that control this are `LD_MODEL_PATH` and `LD_CONFIG_PATH`.

#### Per-pairing inputs:
- **Photogrammetry products**: The mesh file representing the 3D geometry of the scene and the cameras file representing the location and orientation of each camera is used for rendering and the CHM is used for tree detection. One set of photogrammetry data must be provided per drone mission. The photogrammetry files should be at the following path `s3:{S3_PROCESSED_MISSIONS_FOLDER}/{PROCESSED_DRONE_DATASET_ID}/{PHOTOGRAMMETRY_ID}/full/`. In this path, `PROCESSED_DRONE_DATASET_ID` represents the `ofo_drone_mission_id` or concatenation thereof provided as the first input column and `S3_PROCESSED_MISSIONS_FOLDER` and `PHOTOGRAMMETRY_ID` are workflow-level parameters.
- **Plot-drone spatial registration**: The spatial shift which aligns the photogrammetry data to the field survey data. This is represented as an x-y shift associated with a specific projected CRS. The shift file should be at `s3:{S3_PROCESSED_MISSIONS_FOLDER}/{PROCESSED_DRONE_DATASET_ID}/{PHOTOGRAMMETRY_ID}/ground-reference-shifts/{PAIR_NAME}_ground-reference-shift.csv`. In this path, `PROCESSED_DRONE_DATASET_ID` represents the `ofo_drone_mission_id` or concatenation thereof provided as the first input column and `S3_PROCESSED_MISSIONS_FOLDER` and `PHOTOGRAMMETRY_ID` are workflow-level parameters. The `PAIR_NAME` represents the concatenation of the `PROCESSED_DRONE_DATASET_ID` and `ofo_plot_id`.
- **Raw images**: The multiview drone images. The zipped folders of images should be found at `s3:{S3_IMAGERY_FOLDER}/{ofo_drone_mission_id}/images/{ofo_drone_mission_id}_images.zip`. The `S3_IMAGERY_FOLDER` is a workflow-level parameter and the `ofo_drone_mission_id` is parsed (potentially split) from the input file.

### Steps
The workflow completes the following steps.
- Downloads the zipped imagery, photogrammetry products, and the shift between the photogrammetry and field data.
- Detect the tree tops and tree crowns from the drone CHM.
- Shifts the field trees to match the tree tops.
- Matches the field trees to the tree tops. This in turn links to the tree crowns by way of the crown's `tree_top_unique_id` and the tree top's `unique_id`.
- Renders the crown's `unique_id` to the perspective of each image.
- Crops out each individual tree. This step also masks the background with gray.
- Generate per-view predictions of live vs. dead with the provided pretrained computer vision model.
- Aggregate predictions at the tree level to determine which trees are dead by a majority vote across all views of it.
- Finally, the masked crops and the matched crowns (now with all information from the field trees and predicted live/dead status) are uploaded to S3.

### Outputs
For each line in the input, a separate training dataset is uploaded. In the following lines, the `pair_name` parameter represents the concatenation of the two columns in the input file. The `S3_TRAINING_OUTPUT_FOLDER` is a workflow-level parameter.
- The geospatial crown delineations can be found at `s3:{S3_TRAINING_OUTPUT_FOLDER}/{pair_name}/{pair_name}_matched-trees.gpkg`. The `unique_ID` field matches to the rendered chips in the next bullet and the `live_dead` field represents whether it was predicted as live or dead based on the multiview crops and provided model. This file contains all the columns from the field reference trees that were matched to the crowns.
- The chips can be found at `s3:{S3_TRAINING_OUTPUT_FOLDER}/{pair_name}/chips/` in a nested folder structure. The folders structure represents the structure of the input images, with the leaf folders corresponding to an individual image (minus the suffix). Within each folder, the individual images are named based on the `unique_ID` from the bullet above, padded to five digits. Using this linking, a model could be trained for any attribute provided in the initial field reference data.

## Ingest under canopy data
This workflow (`ingest-under-canopy-imagery-workflow.yaml`) is designed to standardize undercanopy GoPro imagery. A folder of all the imagery is provided and the first step is to subset the data into individual collects. This is done through a combination of filename prefix matching and date matching. Then, the imagery is reorganized into a standardized format. Per-image metadata is extracted and uploaded to S3. Then, the reorganized images are zipped and uploaded to S3 as well. After both complete, all temporary data is deleted from local storage. This process is repeated independently for each collect.

The input arguments are described in comments in detail in the `arguments -> parameters` section of the workflow file. An important one is `COLLECTS_FILE`. This is a `.csv` that contains the per-collect information required to perform the standardization. As described in the workflow file, this input file should have at least the following four columns (others will be ignored):
- `collect_id` is an integer representing the newly-assigned collect ID. All outputs contain this value.
- `file_prefixes` is a string that contains one or more space-separated file prefix strings to include in this collect.
- `collect_start_datetime` is a `YYYY-MM-DD HH:MM` string (e.g. `2026-08-15 09:30`) specifying the start of the inclusive datetime range of images to include for this collect.
- `collect_end_datetime` is a `YYYY-MM-DD HH:MM` string (e.g. `2026-08-15 11:30`) specifying the end of the inclusive datetime range.
In many cases for internal users, the collects file should be downloaded from Baserow (table `datasets-imagery-under-canopy`) and subset to the appropriate rows. To do this, go to `export view -> Export to CSV -> Download`.

The other important parameter is `INPUT_DATA_FOLDER`. This is a path, relative to the mounted filesystem in `Argo`, where all the images are located. There are no requirements for how this data is organized.

The current testing command is:
```
argo submit -n argo argo-workflows/ingest-under-canopy-workflow.yaml \
  -p COLLECTS_FILE="/data/argo-input/under-canopy-imagery-organization/missions_file_subset.csv" \
  -p S3_OUTPUT_FOLDER="ofo-public/under-canopy-imagery-test" \
  -p INGEST_IMAGE_TAG="feature-DR-ingest-under-canopy" \
  -p INPUT_DATA_FOLDER="/data/argo-input/under-canopy-imagery-organization/0_raw"
```

The processing will fail for a given collect if no images both match the specified file prefixes and the specified time bounds. If there is a gap in image timestamps, this will be logged as a warning, but will not cause the dataset to fail. These warnings can be viewed in the `report-warnings` step in the Argo UI. This step will only be run after all datasets finish.

## Train classification model on pre-chipped imagery
The `Create chips for model training` workflow creates training data consisting of masked views of individual trees. This workflow (`train-classification-model.yaml`) downloads this data from S3 and uses it to train a classificaiton model that can be used to perform species prediction on unseen data. This model is then uploaded to S3 and all intermediate local data is deleted.

This workflow runs by first downloading all the required chipped data and the tree-level metadata saved as a `.gpkg` data format. At this stage, there is the option to filter based on whether the data comes from oblique or nadir views, but only in the cases where the data is generated from paired missions. These datasets are organized into train and test folders based on the user specification, but all files retain their original naming. Then, using the tree-level metadata, these files are reorganzed to be sequentially numbered in class-level folders. The user can optionally specify a class-level remapping to update and optionally merge classes contained in the metadata.

From there, a model is trained using the `MMPretrain` framework. Once trained, this model is uploaded to S3 along with the associated config file and training logs. Finally, the downloaded data is all removed from local storage.

### Parameters

- **`DATASETS_FILE`** (required): Path to a file on the mounted volume specifying what data to train on. This should be a text file with two columns (comma-separated; no column headers). The first column specifies each dataset in the format it appears on S3 — either `<drone_mission_id>_<plot_id>` or `<drone_mission_id_nadir>_<drone_mission_id_oblique>_<plot_id>` for the single or paired mission case. The second column should be either `"train"` or `"val"`.

- **`CLASS_REMAPPING_FILE`** (default: `""`): A `.json` file specifying how to remap input attribute values to final class names, as a flat object, e.g. `{"CADE27": "incense_cedar", "PIPO": "pine", "PILA": "pine"}`. The set of output classes is the set of values. Trees whose attribute value is not a key are dropped. If not provided (empty string), an identity mapping is used and every observed class is kept.

- **`MODEL_UPLOAD_DIR_S3`** (required): Where on S3 the trained model should be uploaded. Should include the bucket name.

- **`ATTRIBUTE_TO_TRAIN_ON`** (default: `"species_code"`): The column of the downloaded geopackages to use as the training class label.

- **`FILTER_DEAD_TREES`** (default: `"true"`): Whether to exclude trees predicted as dead from the training data. Any value other than `"true"` (case-sensitive) is treated as false. Live/dead status is predicted during the chipping workflow and included in the per-tree metadata file downloaded from S3.

- **`MISSION_TYPE`** (default: `"all"`): Which imagery to use for training. Options are `"all"`, `"nadir"`, or `"oblique"`. Only applies to paired datasets; all data is used for single-mission datasets.

- **`TEMP_FOLDER`** (default: `"/data/argo-output/temp-dir"`): Base directory for temporary products. All temp outputs for a run are saved under `TEMP_FOLDER/<workflow-name>`.

- **`TRAINING_DATA_PATH_S3`** (default: `"ofo-public/drone/training-data_01"`): S3 path where the chipped training data is stored. Should include the bucket name and no trailing slash.

- **`MODEL_CONFIG_PATH`** (required): Path to an MMPretrain config file on `/ofo-share`. All fields should be finalized except `data_root`, which is overridden automatically to point to the downloaded training data.

- **`TRAINING_EPOCHS`** (default: `"10"`): Number of epochs to train for.

- **`MMPRETRAIN_IMAGE_TAG`** (default: `"main"`): Version tag for the mmpretrain Docker image.
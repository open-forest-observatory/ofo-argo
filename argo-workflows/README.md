### Tree Detection and Attribute Prediction
The `species-prediction-workflow.yaml` contains code to detect trees and classify their species and live/dead status. This workflow requires that photogrammetry and post-processing have been run on the corresponding datasets.

The workflow performs the follow series of steps
- **Downloading imagery**: Download the zipped mission-level images that were used for photogrammetry and optionally subset to the ones which were actually used.
- **Downloading photogrammetry products**: Download the mesh, cameras, CHM, and DTM.
- **Tree detection**: Using the two-stage geometric detector from TDF, first detect tree tops and then segment the crowns with watershed.
- **Instance ID rendering**: Using geograypher, render the `unique_ID` field of the segmented trees to the perspective of each image. These renders are saved out in a folder structure paralleling the input imagery.
- **Chipping**: Chip out the images corresponding to the view of each tree and mask the background. This structure parallels the structure of the input data, with one folder of chips for each input image. Within that folder, chips are named based on the tree `unique_ID` that generated them.
- **Prediction**: The species and live/dead predictions are generated using `MMPretrain` and the per-chip predictions are saved to a `.json` file.
- **Aggregation and merging**: The final step is to use the per-chip predictions to vote on the class per tree. Then this information is merged into the original geospatial data product as a new column. This step is computationally very fast, and is only distinct from the prediction step because the `MMPretrain` container does not have the required dependencies to load geospatial files.

### Registring Field Trees to Drone Products
There may be a spatial miss-alignment between the field reference data and the drone products. This is primarily driven by differences in the GPS bias between the surveys. The `register-field-trees-to-CHM.yaml` workflow can be used to estimate a shift which best aligns the field data with the drone products, specifically by using the CHM. This approach determines the shift which produces the best correlation between the field trees heights and the corresponding locations on the CHM. This is done in a two-stage coarse-to-fine manner.

The workflow takes as input field trees and field plot bounds from the shared data drive and downloads drone mission metadata and CHM products from `S3`. For each overlapping pair of field plot and drone mission, the output is a `.csv` file containing the shift which would best align the field trees to the corresponding CHM, with associated quality metrics. This file follows the convention `js2s3:ofo-public/drone/{missions dir}/{mission ID}/{photogrammetry ID}/ground-reference-shifts/{mission ID}_{plot ID}_ground-reference-shift.csv`

The workflow contains the following steps
- The drone mission bounds metadata is downloaded from `S3`.
- The overlap is computed between the drone mission bounds and the field plot bounds. In cases where a drone mission has two rows in the bounds metadata (such as an oblique-nadir composite mission) the intersection between the two is used. A drone mission and plot are considered a pair if the field plot is fully within the drone mission bounds or the field plot overlaps the drone mission by greater than 0.25ha.
- For each pair:
    - The CHM file is downloaded from `S3`.
    - Registration is run using the [this](https://github.com/open-forest-observatory/tree-registration-and-matching/blob/main/tree_registration_and_matching/entrypoints/register_trees_to_CHM.py) tree-registration-and-matching entrypoint.
    - The shift file is uploaded to `S3` and the intermediate data products are deleted.

### Tree Detection and Evaluation
The `tree-detection-and-eval.yaml` workflow benchmarks one or more tree detectors against field reference data across a set of drone missions and field plots. It fans out over all `(mission, plot)` pairs in a datasets file and all detector configurations in a detection config file, running each combination in parallel.

The workflow performs the following steps for each `(mission, plot, detector config)` combination:
- **Download**: Pulls the orthomosaic, CHM, and ground-reference shift file from S3.
- **Preprocess**: Applies the spatial shift to field trees and plot bounds, filters by minimum tree height, and crops rasters to the shifted plot boundary.
- **Detect**: Runs the specified detector (geometric on CPU; all others on GPU) to produce raw detections.
- **Postprocess**: Applies the postprocessing chain for the config (or just a height filter for the geometric detector).
- **Evaluate**: Matches predicted tree points to ground truth and computes precision, recall, and F1.
- **Upload**: Writes per-run `eval_results.json` and `detections.gpkg` to S3. After all datasets finish, merges all results into a single summary CSV and uploads it.

#### Input file structure examples

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

# Creating chips for model training
The `species-prediction-training-data-prep.yaml` workflow is used to produce training data for tree-level attribute prediction tasks, such as predicting tree species. Specifically, the model operates (both for training and inference) on each individual view of a given tree, taken from the raw drone images captured by the survey. This process begins with manually collected field reference data and predicted tree crowns detected from drone-derived photogrammetry products. Then, the drone and field trees are matched and the matched drone crowns are rendered to the perspective of each image. These renders are then chipped to provided one image per view of each matched trees. These chips can be linked back to the attributes of the field tree and used to train a model for any attribute which was surveyed. Additionally, this workflow predicts a live/dead status for each view and adds the predicted status to the tree-level metadata. All data is uploaded to `S3` and can be downloaded to train models. A publication summarizing this workflow can be found [here](https://ecoevorxiv.org/repository/view/13675).

## Inputs
### Workflow level-inputs
- **Which datasets to run**
You directly specifies which field-drone pairs to process in a two column csv file. The file should not contain a header. The first field represents which drone dataset to use. This can either be the `ofo_drone_mission_id` (padded to six digits) or a concatenation of two `id`s separated by an `_`, such as when oblique and nadir data is processed together. The second field is the `ofo_plot_id` (padded to four digits). This file is pointed to by the `DATASETS_FILE` workflow parameter. An example row of the file for a paired mission is `001439_001440, 0045` and for a single mission,`001439, 0045`. In almost all cases, the file should only contain one format of missions (either paired or single) since this workflow expects all photogrammetry products to be uploaded to the same `S3_PROCESSED_MISSIONS_FOLDER` folder, which has only one format of mission.
- **Field reference information**: You must provide two files on the `ofo-share` describing the field-surveyed tree points and the corresponding bounds of the surveyed plots. These files should both contain the `plot_id` key, which describes which surveyed plot they correspond to. The workflow parameters that control these inputs are `FIELD_TREES_FILE` and `FIELD_PLOTS_FILE`.
- **Live/dead classification model**: This generates predictions from individual cropped views of each tree of whether it is alive or not. This information can be later used to filter the training data only to live trees. The workflow parameters that control this are `LD_MODEL_PATH` and `LD_CONFIG_PATH`.

### Per-pairing inputs:
- **Photogrammetry products**: The mesh file representing the 3D geometry of the scene and the cameras file representing the location and orientation of each camera is used for rendering and the CHM is used for tree detection. One set of photogrammetry data must be provided per drone mission. The photogrammetry files should be at the following path `s3:{S3_PROCESSED_MISSIONS_FOLDER}/{PROCESSED_DRONE_DATASET_ID}/{PHOTOGRAMMETRY_ID}/full/`. In this path, `PROCESSED_DRONE_DATASET_ID` represents the `ofo_drone_mission_id` or concatenation thereof provided as the first input column and `S3_PROCESSED_MISSIONS_FOLDER` and `PHOTOGRAMMETRY_ID` are workflow-level parameters.
- **Plot-drone spatial registration**: The spatial shift which aligns the photogrammetry data to the field survey data. This is represented as an x-y shift associated with a specific projected CRS. The shift file should be at `s3:{S3_PROCESSED_MISSIONS_FOLDER}/{PROCESSED_DRONE_DATASET_ID}/{PHOTOGRAMMETRY_ID}/ground-reference-shifts/{PAIR_NAME}_ground-reference-shift.csv`. In this path, `PROCESSED_DRONE_DATASET_ID` represents the `ofo_drone_mission_id` or concatenation thereof provided as the first input column and `S3_PROCESSED_MISSIONS_FOLDER` and `PHOTOGRAMMETRY_ID` are workflow-level parameters. The `PAIR_NAME` represents the concatenation of the `PROCESSED_DRONE_DATASET_ID` and `ofo_plot_id`.
- **Raw images**: The multiview drone images. The zipped folders of images should be found at `s3:{S3_IMAGERY_FOLDER}/{ofo_drone_mission_id}/images/{ofo_drone_mission_id}_images.zip`. The `S3_IMAGERY_FOLDER` is a workflow-level parameter and the `ofo_drone_mission_id` is parsed (potentially split) from the input file.

## Steps
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

## Outputs
For each line in the input, a separate training dataset is uploaded. In the following lines, the `pair_name` parameter represents the concatenation of the two columns in the input file. The `S3_TRAINING_OUTPUT_FOLDER` is a workflow-level parameter.
- The geospatial crown delineations can be found at `s3:{S3_TRAINING_OUTPUT_FOLDER}/{pair_name}/{pair_name}_matched-trees.gpkg`. The `unique_ID` field matches to the rendered chips in the next bullet and the `live_dead` field represents whether it was predicted as live or dead based on the multiview crops and provided model. This file contains all the columns from the field reference trees that were matched to the crowns.
- The chips can be found at `s3:{S3_TRAINING_OUTPUT_FOLDER}/{pair_name}/chips/` in a nested folder structure. The folders structure represents the structure of the input images, with the leaf folders corresponding to an individual image (minus the suffix). Within each folder, the individual images are named based on the `unique_ID` from the bullet above, padded to five digits. Using this linking, a model could be trained for any attribute provided in the initial field reference data.

# Ingest under canopy data
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

# TODO add a note about failure conditions and logging within the Argo UI

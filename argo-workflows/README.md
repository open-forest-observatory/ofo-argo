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

The workflow takes as input field trees and field plot bounds from the shared data drive and downloads drone mission metadata and CHM products from `S3`. For each overlapping pair of field plot and drone mission, the output is a `.csv` file containing the shift which would best align the field trees to the corresponding CHM, with associated quality metrics. This file follows the convention `js2s3:ofo-public/drone/{missions dir}/{mission ID}/{photogrammetry ID}/ground-reference-shifts/{plot ID}_{mission ID}_ground-reference-shift.csv`

The workflow contains the following steps
- The drone mission bounds metadata is downloaded from `S3`.
- The overlap is computed between the drone mission bounds and the field plot bounds. In cases where a drone mission has two rows in the bounds metadata (such as an oblique-nadir composite mission) the intersection between the two is used. A drone mission and plot are considered a pair if the field plot is fully within the drone mission bounds or the field plot overlaps the drone mission by greater than 0.25ha.
- For each pair:
    - The CHM file is downloaded from `S3`.
    - Registration is run using the [this](https://github.com/open-forest-observatory/tree-registration-and-matching/blob/main/tree_registration_and_matching/entrypoints/register_trees_to_CHM.py) tree-registration-and-matching entrypoint.
    - The shift file is uploaded to `S3` and the intermediate data products are deleted.
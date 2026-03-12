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
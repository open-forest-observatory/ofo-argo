import json
import geopandas as gpd
import pandas as pd


PREDS = "/ofo-share/repos/david/ofo-argo/scratch/fake_preds.json"
DETECTED_TREES_FILE = (
    "/ofo-share/argo-data/argo-output/david-species/detected_trees.gpkg"
)

with open(PREDS) as file_h:
    data = json.load(file_h)

tree_IDs = [p.split("/")[-1].split(".")[0] for p in data.keys()]
tree_species_preds = list(data.values())

preds_df = pd.DataFrame({"tree_ID": tree_IDs, "tree_species_pred": tree_species_preds})

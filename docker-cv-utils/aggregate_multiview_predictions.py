import json
import geopandas as gpd
import pandas as pd
import numpy as np


PREDS = "/ofo-share/repos/david/ofo-argo/scratch/fake_preds.json"
DETECTED_TREES_FILE = (
    "/ofo-share/argo-data/argo-output/david-species/detected_trees.gpkg"
)

with open(PREDS) as file_h:
    data = json.load(file_h)

tree_IDs = [p.split("/")[-1].split(".")[0] for p in data.keys()]
tree_species_preds = list(data.values())

preds_df = pd.DataFrame({"tree_ID": tree_IDs, "tree_species_pred": tree_species_preds})


def fair_mode(series):
    """Tie break if there are more than two options"""
    modes = series.mode()
    mode = np.random.choice(modes)
    return mode


grouped = preds_df.groupby(["tree_ID"]).apply(
    lambda x: fair_mode(x["tree_species_pred"])
)
grouped = pd.DataFrame(
    {"unique_ID": grouped.index, "species_prediction": grouped.values}
)
grouped["unique_ID"] = grouped["unique_ID"].astype(str)
grouped["unique_ID"] = grouped["unique_ID"].str.pad(5, fillchar="0")
grouped["unique_ID"] = grouped["unique_ID"].astype(str)

detected_trees = gpd.read_file(DETECTED_TREES_FILE)
detected_trees["unique_ID"] = detected_trees["unique_ID"].astype(str)
detected_trees = detected_trees.merge(grouped, on="unique_ID")

import argparse
from pathlib import Path
import pandas as pd
import numpy as np
import geopandas as gpd

from mmpretrain import ImageClassificationInferencer


def main(
    input_folder,
    model_path,
    config_path,
    detected_trees_path,
    output_trees_path,
    batch_size=4,
):
    # Placeholder for the actual prediction logic
    inferencer = ImageClassificationInferencer(
        model=str(config_path), pretrained=str(model_path), device="cuda"
    )

    input_files = [
        str(f)
        for f in Path(input_folder).rglob("*")
        if f.suffix.lower() in [".jpg", ".jpeg", ".png"]
    ]

    preds = inferencer(input_files, batch_size=batch_size)
    labels = [pred["pred_label"] for pred in preds]

    tree_IDs = [Path(f).stem for f in input_files]

    preds_df = pd.DataFrame({"tree_ID": tree_IDs, "tree_species_pred": labels})

    def fair_mode(series):
        """Tie break if there two or more options"""
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

    detected_trees = gpd.read_file(detected_trees_path)
    detected_trees["unique_ID"] = detected_trees["unique_ID"].astype(str)
    detected_trees = detected_trees.merge(grouped, on="unique_ID", how="left")

    # create output folder
    output_trees_path.parent.mkdir(parents=True, exist_ok=True)

    detected_trees.to_file(output_trees_path)


def parse_args():
    parser = argparse.ArgumentParser(description="Predict species from input data")
    parser.add_argument(
        "--input-folder", type=Path, required=True, help="Path to input imagery folder"
    )
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument(
        "--config-path",
        type=Path,
        required=True,
    )
    parser.add_argument("--detected-trees-path", type=Path, required=True)
    parser.add_argument("--output-trees-path", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(
        args.input_folder,
        args.model_path,
        args.config_path,
        args.detected_trees_path,
        args.output_trees_path,
        args.batch_size,
    )

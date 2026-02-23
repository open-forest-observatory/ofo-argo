import argparse
from pathlib import Path

from mmpretrain import ImageClassificationInferencer


def main(input_folder, model_path, config_path):
    # Placeholder for the actual prediction logic
    inferencer = ImageClassificationInferencer(
        model=config_path, pretrained=model_path, device="cuda"
    )

    input_files = [
        f
        for f in Path(input_folder).rglob("*")
        if f.suffix.lower() in [".jpg", ".jpeg", ".png"]
    ]

    preds = [inferencer(str(f)) for f in input_files]
    print(preds)


def parse_args():
    parser = argparse.ArgumentParser(description="Predict species from input data")
    parser.add_argument(
        "--input-folder", type=str, required=True, help="Path to input imagery folder"
    )
    parser.add_argument("--model-path", type=str, required=True)
    parser.add_argument(
        "--config-path",
        type=str,
        required=True,
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(args.input_folder, args.model_path, args.config_path)

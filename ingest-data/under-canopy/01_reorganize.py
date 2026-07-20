from pathlib import Path
import argparse

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_data_folder", default=Path("/ofo-share/under-canopy-imagery-organization/0_raw/"), type=Path)
    parser.add_argument("output_data_folder", default=Path("/ofo-share/under-canopy-imagery-organization/1_manually-cleaned/"), type=Path)
    parser.add_argument("mission_file", type=Path)

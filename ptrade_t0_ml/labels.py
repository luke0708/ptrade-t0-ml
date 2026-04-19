from __future__ import annotations

import argparse

import pandas as pd

from .config import DEFAULT_CONFIG, ProjectConfig
from .io_utils import save_dataframe


def build_labeled_dataset(features_df: pd.DataFrame, config: ProjectConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    df = features_df.copy()
    thresholds = config.label_thresholds
    df["label"] = (
        (df["daily_amplitude"] > thresholds.daily_amplitude)
        & (df["close"] > df["pre_close"] * thresholds.close_floor_ratio)
    ).astype(int)
    df["target"] = df["label"].shift(-1)
    df = df.dropna(subset=["target"]).reset_index(drop=True)
    df["target"] = df["target"].astype(int)
    return df


def run_label_generation(config: ProjectConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    features_df = pd.read_csv(config.features_path)
    labeled_df = build_labeled_dataset(features_df, config=config)
    save_dataframe(labeled_df, config.labeled_data_path)
    print("Saved labeled dataset to:", config.labeled_data_path)
    print("Target distribution:")
    print(labeled_df["target"].value_counts(dropna=False).sort_index().to_string())
    return labeled_df


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Generate next-day binary labels for the T+0 model.")


def main() -> None:
    build_parser().parse_args()
    run_label_generation(DEFAULT_CONFIG)


if __name__ == "__main__":
    main()

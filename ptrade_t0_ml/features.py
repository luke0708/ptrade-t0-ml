from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .config import DEFAULT_CONFIG, ProjectConfig
from .io_utils import save_dataframe


FEATURE_EXCLUDED_COLUMNS = {"date", "label", "target"}


def _get_series_by_prefix(df: pd.DataFrame, prefix: str) -> pd.Series:
    matches = [column for column in df.columns if column.startswith(prefix)]
    if not matches:
        raise ValueError(f"Expected indicator column with prefix {prefix!r} not found.")
    return df[matches[0]]


def load_raw_dataset(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required_columns = {"date", "open", "high", "low", "close", "volume", "amount", "pre_close"}
    missing = required_columns.difference(df.columns)
    if missing:
        raise ValueError(f"Raw dataset is missing required columns: {sorted(missing)}")
    df["date"] = pd.to_datetime(df["date"])
    for column in required_columns.difference({"date"}):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    if "turnover_rate" in df.columns:
        df["turnover_rate"] = pd.to_numeric(df["turnover_rate"], errors="coerce")
    df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    df["pre_close"] = df["pre_close"].fillna(df["close"].shift(1))
    return df


def prepare_features(raw_df: pd.DataFrame) -> pd.DataFrame:
    try:
        import pandas_ta as ta
    except ImportError as exc:
        raise ImportError("pandas-ta is required. Install dependencies with `pip install -r requirements.txt`.") from exc

    df = raw_df.copy()
    df["rsi_14"] = ta.rsi(df["close"], length=14)

    macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
    if macd_df is None or macd_df.empty:
        raise ValueError("Failed to generate MACD indicators.")
    df["macd_hist_12_26_9"] = _get_series_by_prefix(macd_df, "MACDh_")

    df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)

    bbands_df = ta.bbands(df["close"], length=20, std=2)
    if bbands_df is None or bbands_df.empty:
        raise ValueError("Failed to generate Bollinger Bands indicators.")
    df["bb_width_20_2"] = _get_series_by_prefix(bbands_df, "BBB_")

    df["sma_20"] = ta.sma(df["close"], length=20)
    df["sma_60"] = ta.sma(df["close"], length=60)
    df["close_to_sma20"] = (df["close"] - df["sma_20"]) / df["sma_20"]
    df["volume_sma_5"] = ta.sma(df["volume"], length=5)
    df["volume_sma_20"] = ta.sma(df["volume"], length=20)
    df["turnover_proxy"] = df["turnover_rate"] if "turnover_rate" in df.columns else df["amount"]

    df["daily_amplitude"] = (df["high"] - df["low"]) / df["pre_close"]
    df["gap_pct"] = (df["open"] - df["pre_close"]) / df["pre_close"]

    df = df.dropna().reset_index(drop=True)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    excluded = FEATURE_EXCLUDED_COLUMNS.intersection(df.columns)
    return [column for column in df.columns if column not in excluded]


def run_feature_engineering(config: ProjectConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    raw_df = load_raw_dataset(config.raw_data_path)
    features_df = prepare_features(raw_df)
    save_dataframe(features_df, config.features_path)
    print("Saved feature dataset to:", config.features_path)
    print("Feature columns:")
    print(", ".join(features_df.columns))
    return features_df


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Generate technical features from raw daily data.")


def main() -> None:
    build_parser().parse_args()
    run_feature_engineering(DEFAULT_CONFIG)


if __name__ == "__main__":
    main()

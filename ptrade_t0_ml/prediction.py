from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

import pandas as pd

from .config import DEFAULT_CONFIG, ProjectConfig
from .data_source import fetch_akshare_daily_data, load_local_daily_csv
from .features import load_raw_dataset, prepare_features
from .io_utils import atomic_write_json, atomic_write_text


def load_model_and_metadata(config: ProjectConfig):
    try:
        from xgboost import XGBClassifier
    except ImportError as exc:
        raise ImportError("xgboost is required. Install dependencies with `pip install -r requirements.txt`.") from exc

    if not config.model_path.exists():
        raise FileNotFoundError(f"Model file not found: {config.model_path}")
    if not config.model_metadata_path.exists():
        raise FileNotFoundError(f"Model metadata file not found: {config.model_metadata_path}")

    model = XGBClassifier()
    model.load_model(config.model_path)
    metadata = json.loads(config.model_metadata_path.read_text(encoding="utf-8"))
    return model, metadata


def fetch_prediction_window(config: ProjectConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    end_date = date.today()
    start_date = end_date - timedelta(days=config.prediction_fetch_calendar_days)
    try:
        return fetch_akshare_daily_data(
            config=config,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
    except Exception as exc:
        fallback_path = config.local_input_csv_path if config.local_input_csv_path.exists() else config.raw_data_path
        if not fallback_path.exists():
            raise RuntimeError("Failed to fetch latest data and no local CSV/raw dataset is available.") from exc
        print(f"Live fetch failed, falling back to local data source: {fallback_path}")
        if fallback_path == config.local_input_csv_path:
            df = load_local_daily_csv(fallback_path)
        else:
            df = load_raw_dataset(fallback_path)
        return df[df["date"] >= start_date.isoformat()].reset_index(drop=True)


def build_prediction_row(config: ProjectConfig = DEFAULT_CONFIG) -> tuple[pd.DataFrame, pd.Series]:
    raw_df = fetch_prediction_window(config=config)
    raw_df["date"] = pd.to_datetime(raw_df["date"])
    raw_df = raw_df.sort_values("date").reset_index(drop=True)
    if len(raw_df) < config.min_prediction_bars:
        raise ValueError(
            f"Insufficient daily bars for prediction: got {len(raw_df)}, need at least {config.min_prediction_bars}."
        )

    features_df = prepare_features(raw_df)
    if features_df.empty:
        raise ValueError("Feature engineering returned no rows for the prediction window.")
    latest_row = features_df.iloc[-1]
    return features_df, latest_row


def run_daily_prediction(config: ProjectConfig = DEFAULT_CONFIG) -> dict[str, object]:
    model, metadata = load_model_and_metadata(config)
    features_df, latest_row = build_prediction_row(config=config)

    feature_columns = metadata.get("feature_columns", [])
    missing = [column for column in feature_columns if column not in features_df.columns]
    if missing:
        raise ValueError(f"Prediction features are missing model columns: {missing}")

    X_latest = features_df.iloc[[-1]][feature_columns].apply(pd.to_numeric, errors="raise")
    probability = float(model.predict_proba(X_latest)[0, 1])

    signal = {
        "date": str(latest_row["date"]),
        "probability": round(probability, 6),
    }
    csv_content = "date,probability\n{date},{probability}\n".format(**signal)
    atomic_write_text(config.daily_signal_csv_path, csv_content)
    atomic_write_json(config.daily_signal_json_path, signal)

    print("Saved daily signal CSV to:", config.daily_signal_csv_path)
    print("Saved daily signal JSON to:", config.daily_signal_json_path)
    print(json.dumps(signal, ensure_ascii=False))
    return signal


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Generate the latest daily prediction signal for PTrade.")


def main() -> None:
    build_parser().parse_args()
    run_daily_prediction(DEFAULT_CONFIG)


if __name__ == "__main__":
    main()

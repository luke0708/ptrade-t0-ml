from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta

import pandas as pd

from .baseline_models import build_xgb_classifier, build_xgb_regressor, train_baseline_models
from .config import DEFAULT_CONFIG, ProjectConfig
from .feature_engine import run_feature_engine
from .io_utils import atomic_write_json, save_dataframe
from .minute_foundation import configure_logging as configure_foundation_logging

LOGGER = logging.getLogger(__name__)

REGRESSION_HEAD_TO_SIGNAL_FIELD = {
    "upside_regression": "pred_upside_t1",
    "downside_regression": "pred_downside_t1",
    "grid_pnl_regression": "pred_grid_pnl_t1",
}

CLASSIFICATION_HEAD_TO_SIGNAL_FIELD = {
    "positive_grid_day_classifier": "pred_positive_grid_day_t1",
    "tradable_classifier": "pred_tradable_score_t1",
    "trend_break_risk_classifier": "pred_trend_break_risk_t1",
    "vwap_reversion_classifier": "pred_vwap_reversion_score_t1",
}


def _load_baseline_metadata(config: ProjectConfig) -> dict[str, object]:
    if not config.baseline_metadata_path.exists():
        LOGGER.info("Baseline metadata missing. Training baseline models first.")
        train_baseline_models(config)
    return json.loads(config.baseline_metadata_path.read_text(encoding="utf-8"))


def _load_latest_feature_row(config: ProjectConfig, feature_columns: list[str]) -> pd.DataFrame:
    if not config.feature_table_path.exists():
        LOGGER.info("Feature table missing. Rebuilding features first.")
        run_feature_engine(config)
    feature_df = pd.read_csv(config.feature_table_path)
    if feature_df.empty:
        raise ValueError("Feature table is empty; cannot export signal.")
    latest_row = feature_df.sort_values("date").iloc[[-1]].copy()
    missing_columns = [column for column in feature_columns if column not in latest_row.columns]
    if missing_columns:
        raise ValueError(f"Feature table is missing required columns for scoring: {missing_columns}")
    return latest_row


def _next_weekday(signal_date: str) -> str:
    current = date.fromisoformat(signal_date)
    next_day = current + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day.isoformat()


def _load_regressor(config: ProjectConfig):
    model = build_xgb_regressor(config)
    return model


def _load_classifier(config: ProjectConfig):
    model = build_xgb_classifier(config, scale_pos_weight=1.0)
    return model


def _score_latest_row(config: ProjectConfig, metadata: dict[str, object], latest_feature_row: pd.DataFrame) -> dict[str, float]:
    feature_columns = metadata["feature_columns"]
    X_latest = latest_feature_row[feature_columns]
    predictions: dict[str, float] = {}

    for head_name, signal_field in REGRESSION_HEAD_TO_SIGNAL_FIELD.items():
        model = _load_regressor(config)
        model.load_model(metadata["heads"][head_name]["model_path"])
        predictions[signal_field] = float(model.predict(X_latest)[0])

    for head_name, signal_field in CLASSIFICATION_HEAD_TO_SIGNAL_FIELD.items():
        model = _load_classifier(config)
        model.load_model(metadata["heads"][head_name]["model_path"])
        predictions[signal_field] = float(model.predict_proba(X_latest)[0, 1])

    return predictions


def _derive_runtime_controls(
    predictions: dict[str, float],
    thresholds: dict[str, float],
    latest_feature_row: pd.Series,
) -> dict[str, float | bool | str]:
    positive_grid_threshold = thresholds["pred_positive_grid_day_t1"]
    tradable_threshold = thresholds["pred_tradable_score_t1"]
    trend_threshold = thresholds["pred_trend_break_risk_t1"]
    vwap_threshold = thresholds["pred_vwap_reversion_score_t1"]

    positive_grid_on = predictions["pred_positive_grid_day_t1"] >= positive_grid_threshold
    tradable_on = predictions["pred_tradable_score_t1"] >= tradable_threshold
    trend_high = predictions["pred_trend_break_risk_t1"] >= trend_threshold
    vwap_on = predictions["pred_vwap_reversion_score_t1"] >= vwap_threshold

    predicted_upside = predictions["pred_upside_t1"]
    predicted_downside = predictions["pred_downside_t1"]
    predicted_grid_pnl = predictions["pred_grid_pnl_t1"]
    predicted_total_range = max(predicted_upside, 0.0) + abs(min(predicted_downside, 0.0))
    base_grid_width = float(latest_feature_row.get("grid_step_pct_t1", 0.01))

    mode = "NORMAL"
    trend_weak = False
    position_scale = 0.85
    grid_width_scale = 1.0
    dip_buy_enabled = True
    high_sell_enabled = True
    rationale = "baseline_normal_mode"

    if positive_grid_on and tradable_on and vwap_on and not trend_high:
        rationale = "tradable_and_reverting"
        if predicted_upside >= 0.03 and predicted_grid_pnl > 0 and predicted_total_range >= max(0.03, base_grid_width * 2):
            mode = "AGGRESSIVE"
            position_scale = 1.0
            grid_width_scale = 0.92
            rationale = "strong_range_and_positive_grid_edge"
    elif trend_high:
        mode = "SAFE"
        trend_weak = True
        position_scale = 0.55 if (positive_grid_on or tradable_on) else 0.35
        grid_width_scale = 1.20
        dip_buy_enabled = False
        rationale = "trend_break_risk_above_threshold"
    elif not positive_grid_on or not tradable_on:
        mode = "SAFE"
        position_scale = 0.55
        grid_width_scale = 1.10
        dip_buy_enabled = positive_grid_on and vwap_on and predicted_downside > -0.03
        rationale = "positive_grid_or_tradable_below_threshold"

    if trend_high and not positive_grid_on and not tradable_on and not vwap_on and predicted_upside <= 0.012 and predicted_downside <= -0.02:
        mode = "OFF"
        position_scale = 0.20
        grid_width_scale = 1.35
        dip_buy_enabled = False
        high_sell_enabled = False
        rationale = "converging_negative_signals"

    recommended_grid_width = max(base_grid_width * grid_width_scale, 0.005)
    return {
        "recommended_mode": mode,
        "trend_weak": bool(trend_weak),
        "position_scale": float(position_scale),
        "grid_width_scale": float(grid_width_scale),
        "recommended_grid_width_t1": float(recommended_grid_width),
        "dip_buy_enabled": bool(dip_buy_enabled),
        "high_sell_enabled": bool(high_sell_enabled),
        "signal_rationale": rationale,
    }


def build_ml_daily_signal(config: ProjectConfig = DEFAULT_CONFIG) -> dict[str, object]:
    metadata = _load_baseline_metadata(config)
    feature_columns = metadata["feature_columns"]
    latest_feature_row_df = _load_latest_feature_row(config, feature_columns)
    latest_feature_row = latest_feature_row_df.iloc[0]

    predictions = _score_latest_row(config, metadata, latest_feature_row_df)
    thresholds = {
        "pred_positive_grid_day_t1": float(metadata["heads"]["positive_grid_day_classifier"]["recommended_threshold"]),
        "pred_tradable_score_t1": float(metadata["heads"]["tradable_classifier"]["recommended_threshold"]),
        "pred_trend_break_risk_t1": float(metadata["heads"]["trend_break_risk_classifier"]["recommended_threshold"]),
        "pred_vwap_reversion_score_t1": float(metadata["heads"]["vwap_reversion_classifier"]["recommended_threshold"]),
    }
    runtime_controls = _derive_runtime_controls(predictions, thresholds, latest_feature_row)

    feature_date = str(latest_feature_row["date"])
    trained_at = str(metadata["trained_at"])
    model_version = f"baseline_multihead_{trained_at.replace(':', '').replace('-', '').replace('T', '_')}"
    threshold_version = f"calibrated_thresholds_{trained_at[:10]}"
    feature_version = f"feature_table_cols{metadata['feature_column_count']}_asof_{feature_date}"

    signal_payload: dict[str, object] = {
        "date": feature_date,
        "signal_for_date": _next_weekday(feature_date),
        **predictions,
        **runtime_controls,
        "recommended_thresholds": thresholds,
        "feature_source_path": str(config.feature_table_path),
        "model_metadata_path": str(config.baseline_metadata_path),
        "model_version": model_version,
        "feature_version": feature_version,
        "threshold_version": threshold_version,
        "signal_status": "experimental_baseline",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    atomic_write_json(config.ml_daily_signal_json_path, signal_payload)
    save_dataframe(pd.DataFrame([signal_payload]), config.ml_daily_signal_csv_path)
    LOGGER.info("Saved ML daily signal JSON to: %s", config.ml_daily_signal_json_path)
    LOGGER.info("Saved ML daily signal CSV to: %s", config.ml_daily_signal_csv_path)
    return signal_payload


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Export the latest multi-head ML signal for PTrade consumption.")


def main() -> None:
    configure_foundation_logging()
    build_parser().parse_args()
    build_ml_daily_signal(DEFAULT_CONFIG)


if __name__ == "__main__":
    main()

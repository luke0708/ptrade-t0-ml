from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from .baseline_models import build_xgb_classifier, build_xgb_regressor, train_baseline_models
from .config import DEFAULT_CONFIG, ProjectConfig
from .feature_engine import run_feature_engine
from .io_utils import atomic_write_json, save_dataframe
from .minute_foundation import configure_logging as configure_foundation_logging
from .ptrade_strategy_export import export_ptrade_strategy

LOGGER = logging.getLogger(__name__)
MARKET_CLOSE_TIME = time(hour=15, minute=0)

REGRESSION_HEAD_TO_SIGNAL_FIELD = {
    "upside_regression": "pred_upside_t1",
    "downside_regression": "pred_downside_t1",
    "grid_pnl_regression": "pred_grid_pnl_t1",
}

CLASSIFICATION_HEAD_TO_SIGNAL_FIELD = {
    "positive_grid_day_classifier": "pred_positive_grid_day_t1",
    "tradable_classifier": "pred_tradable_score_t1",
    "trend_break_risk_classifier": "pred_trend_break_risk_t1",
    "hostile_selloff_risk_classifier": "pred_hostile_selloff_risk_t1",
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


def _load_trading_calendar_dates() -> set[date]:
    try:
        import akshare as ak

        calendar_df = ak.tool_trade_date_hist_sina()
    except Exception as exc:
        LOGGER.warning("Falling back to weekday-only next-day logic because trading calendar load failed: %s", exc)
        return set()

    if "trade_date" not in calendar_df.columns:
        LOGGER.warning("Falling back to weekday-only next-day logic because trading calendar has no trade_date column.")
        return set()

    trading_dates: set[date] = set()
    for value in calendar_df["trade_date"].tolist():
        try:
            trading_dates.add(pd.Timestamp(value).date())
        except Exception:
            continue
    return trading_dates


def _next_trading_day(signal_date: str, trading_dates: set[date] | None = None) -> str:
    current = date.fromisoformat(signal_date)
    if trading_dates is None:
        trading_dates = _load_trading_calendar_dates()
    if not trading_dates:
        return _next_weekday(signal_date)

    next_day = current + timedelta(days=1)
    safety_limit = current + timedelta(days=30)
    while next_day <= safety_limit:
        if next_day in trading_dates:
            return next_day.isoformat()
        next_day += timedelta(days=1)

    LOGGER.warning(
        "Falling back to weekday-only next-day logic because no future trading day was found within 30 days for %s.",
        signal_date,
    )
    return _next_weekday(signal_date)


def _previous_trading_day(reference_date: date, trading_dates: set[date] | None = None) -> date:
    if trading_dates:
        candidate = reference_date - timedelta(days=1)
        safety_limit = reference_date - timedelta(days=30)
        while candidate >= safety_limit:
            if candidate in trading_dates:
                return candidate
            candidate -= timedelta(days=1)
        raise ValueError(f"Could not find previous trading day within 30 days before {reference_date.isoformat()}.")

    candidate = reference_date - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _expected_feature_date(now_dt: datetime, trading_dates: set[date] | None = None) -> date:
    today = now_dt.date()
    if trading_dates:
        if today in trading_dates and now_dt.time() >= MARKET_CLOSE_TIME:
            return today
        return _previous_trading_day(today, trading_dates)

    if today.weekday() < 5 and now_dt.time() >= MARKET_CLOSE_TIME:
        return today
    return _previous_trading_day(today, trading_dates=None)


def _read_max_date_from_csv(path, column_name: str) -> date | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, usecols=[column_name])
    if df.empty:
        return None
    series = pd.to_datetime(df[column_name], errors="coerce")
    if column_name == "datetime":
        return series.dropna().dt.date.max()
    return series.dropna().dt.date.max()


def _collect_daily_inference_dependency_status(
    config: ProjectConfig,
    latest_feature_date: date,
    now_dt: datetime | None = None,
) -> dict[str, object]:
    if now_dt is None:
        now_dt = datetime.now()

    trading_dates = _load_trading_calendar_dates()
    expected_feature_date = _expected_feature_date(now_dt, trading_dates=trading_dates if trading_dates else None)

    source_dates = {
        "stock_1m": _read_max_date_from_csv(config.stock_ptrade_1m_path, "datetime"),
        "index_daily": _read_max_date_from_csv(config.data_dir / "399006.csv", "date"),
        "sector_daily": _read_max_date_from_csv(config.data_dir / "512480.csv", "date"),
        "feature_table": latest_feature_date,
    }
    hard_dependency_names = {"stock_1m", "feature_table"}
    soft_dependency_names = {"index_daily", "sector_daily"}

    hard_stale_sources = {
        name: value.isoformat() if value else "missing"
        for name, value in source_dates.items()
        if name in hard_dependency_names and (value is None or value < expected_feature_date)
    }
    soft_stale_sources = {
        name: value.isoformat() if value else "missing"
        for name, value in source_dates.items()
        if name in soft_dependency_names and (value is None or value < expected_feature_date)
    }
    return {
        "expected_feature_date": expected_feature_date.isoformat(),
        "source_dates": {name: value.isoformat() if value else "missing" for name, value in source_dates.items()},
        "hard_stale_sources": hard_stale_sources,
        "soft_stale_sources": soft_stale_sources,
        "runtime_data_dir": str(config.data_dir),
        "archive_data_dir": str(config.backup_archive_data_dir) if config.backup_archive_data_dir else None,
    }


def _assert_daily_inference_freshness(
    config: ProjectConfig,
    latest_feature_date: date,
    now_dt: datetime | None = None,
) -> dict[str, object]:
    dependency_status = _collect_daily_inference_dependency_status(config, latest_feature_date, now_dt=now_dt)
    if dependency_status["hard_stale_sources"]:
        raise ValueError(
            "Daily inference hard dependencies are stale. "
            f"Current local time={(now_dt or datetime.now()).isoformat(timespec='seconds')}, "
            f"expected latest feature date={dependency_status['expected_feature_date']}, "
            f"source_dates={dependency_status['source_dates']}. "
            "300661 1m and feature_table are hard dependencies; rebuild local runtime data before exporting the next trading-day signal."
        )
    return dependency_status


def _apply_soft_dependency_safe_downgrade(
    runtime_controls: dict[str, float | bool | str],
    dependency_status: dict[str, object],
) -> dict[str, float | bool | str]:
    soft_stale_sources = dependency_status.get("soft_stale_sources", {})
    if not soft_stale_sources:
        return runtime_controls

    downgraded_controls = dict(runtime_controls)
    if downgraded_controls.get("recommended_mode") != "OFF":
        downgraded_controls["recommended_mode"] = "SAFE"
    downgraded_controls["trend_weak"] = True
    downgraded_controls["position_scale"] = float(min(float(downgraded_controls["position_scale"]), 0.55))
    downgraded_controls["grid_width_scale"] = float(max(float(downgraded_controls["grid_width_scale"]), 1.10))
    downgraded_controls["recommended_grid_width_t1"] = float(
        max(float(downgraded_controls["recommended_grid_width_t1"]), 0.005)
    )
    downgraded_controls["dip_buy_enabled"] = False
    downgraded_controls["signal_rationale"] = "soft_dependency_degraded_to_safe"
    return downgraded_controls


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
    hostile_selloff_threshold = thresholds["pred_hostile_selloff_risk_t1"]
    vwap_threshold = thresholds["pred_vwap_reversion_score_t1"]

    positive_grid_on = predictions["pred_positive_grid_day_t1"] >= positive_grid_threshold
    tradable_on = predictions["pred_tradable_score_t1"] >= tradable_threshold
    trend_high = predictions["pred_trend_break_risk_t1"] >= trend_threshold
    hostile_selloff_high = predictions["pred_hostile_selloff_risk_t1"] >= hostile_selloff_threshold
    vwap_on = predictions["pred_vwap_reversion_score_t1"] >= vwap_threshold

    predicted_upside = predictions["pred_upside_t1"]
    predicted_downside = predictions["pred_downside_t1"]
    predicted_grid_pnl = predictions["pred_grid_pnl_t1"]
    predicted_total_range = max(predicted_upside, 0.0) + abs(min(predicted_downside, 0.0))
    base_grid_width = float(latest_feature_row.get("grid_step_pct_t1", 0.01))
    core_edge = bool(positive_grid_on and tradable_on)
    clean_edge = bool(core_edge and not hostile_selloff_high)
    reversion_edge = bool(clean_edge and vwap_on)
    strong_range = bool(
        predicted_upside >= 0.03
        and predicted_grid_pnl > 0
        and predicted_total_range >= max(0.03, base_grid_width * 2)
    )
    severe_negative_stack = bool(
        hostile_selloff_high
        and not positive_grid_on
        and not tradable_on
        and not vwap_on
        and predicted_upside <= 0.012
        and predicted_grid_pnl <= 0
    )

    mode = "SAFE"
    trend_weak = False
    position_scale = 0.55
    grid_width_scale = 1.10
    dip_buy_enabled = False
    high_sell_enabled = True
    rationale = "insufficient_edge"

    if severe_negative_stack:
        mode = "OFF"
        trend_weak = True
        position_scale = 0.20
        grid_width_scale = 1.35
        dip_buy_enabled = False
        high_sell_enabled = False
        rationale = "negative_stack_with_hostile_selloff"
    elif reversion_edge and strong_range and not trend_high:
        mode = "AGGRESSIVE"
        position_scale = 1.0
        grid_width_scale = 0.92
        dip_buy_enabled = True
        rationale = "clean_reversion_and_strong_range"
    elif clean_edge:
        mode = "NORMAL"
        trend_weak = bool(trend_high)
        position_scale = 0.70 if trend_high else 0.85
        grid_width_scale = 1.08 if trend_high else 1.00
        dip_buy_enabled = bool(vwap_on and predicted_downside > -0.03)
        rationale = "clean_edge_with_trend_damper" if trend_high else "clean_edge_without_hostile_selloff"
    elif core_edge and hostile_selloff_high:
        trend_weak = True
        position_scale = 0.45
        grid_width_scale = 1.20
        dip_buy_enabled = False
        rationale = "hostile_selloff_blocks_execution"
    elif positive_grid_on:
        trend_weak = bool(trend_high or hostile_selloff_high)
        position_scale = 0.45 if hostile_selloff_high else 0.60
        grid_width_scale = 1.22 if hostile_selloff_high else 1.15
        dip_buy_enabled = False
        rationale = "positive_grid_without_tradable_confirmation"
    elif tradable_on:
        trend_weak = bool(trend_high or hostile_selloff_high)
        position_scale = 0.40 if hostile_selloff_high else 0.50
        grid_width_scale = 1.20 if hostile_selloff_high else 1.12
        dip_buy_enabled = False
        rationale = "tradable_without_grid_confirmation"
    else:
        trend_weak = bool(trend_high or hostile_selloff_high)
        position_scale = 0.35 if hostile_selloff_high else 0.45
        grid_width_scale = 1.22 if hostile_selloff_high else 1.12
        dip_buy_enabled = False

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
    feature_date = date.fromisoformat(str(latest_feature_row["date"]))
    dependency_status = _assert_daily_inference_freshness(config, feature_date)

    predictions = _score_latest_row(config, metadata, latest_feature_row_df)
    thresholds = {
        "pred_positive_grid_day_t1": float(metadata["heads"]["positive_grid_day_classifier"]["recommended_threshold"]),
        "pred_tradable_score_t1": float(metadata["heads"]["tradable_classifier"]["recommended_threshold"]),
        "pred_trend_break_risk_t1": float(metadata["heads"]["trend_break_risk_classifier"]["recommended_threshold"]),
        "pred_hostile_selloff_risk_t1": float(
            metadata["heads"]["hostile_selloff_risk_classifier"]["recommended_threshold"]
        ),
        "pred_vwap_reversion_score_t1": float(metadata["heads"]["vwap_reversion_classifier"]["recommended_threshold"]),
    }
    runtime_controls = _derive_runtime_controls(predictions, thresholds, latest_feature_row)
    runtime_controls = _apply_soft_dependency_safe_downgrade(runtime_controls, dependency_status)
    soft_dependency_degraded = bool(dependency_status["soft_stale_sources"])

    feature_date_str = str(latest_feature_row["date"])
    trained_at = str(metadata["trained_at"])
    model_version = f"baseline_multihead_{trained_at.replace(':', '').replace('-', '').replace('T', '_')}"
    threshold_version = f"calibrated_thresholds_{trained_at[:10]}"
    feature_version = f"feature_table_cols{metadata['feature_column_count']}_asof_{feature_date_str}"

    signal_payload: dict[str, object] = {
        "date": feature_date_str,
        "signal_for_date": _next_trading_day(feature_date_str),
        **predictions,
        **runtime_controls,
        "recommended_thresholds": thresholds,
        "feature_source_path": str(config.feature_table_path),
        "model_metadata_path": str(config.baseline_metadata_path),
        "model_version": model_version,
        "feature_version": feature_version,
        "threshold_version": threshold_version,
        "signal_status": "experimental_baseline_soft_degraded" if soft_dependency_degraded else "experimental_baseline",
        "dependency_status": dependency_status,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    if soft_dependency_degraded:
        LOGGER.warning(
            "Soft dependencies are stale; forcing SAFE downgrade. runtime_data_dir=%s source_dates=%s",
            dependency_status["runtime_data_dir"],
            dependency_status["source_dates"],
        )

    atomic_write_json(config.ml_daily_signal_json_path, signal_payload)
    save_dataframe(pd.DataFrame([signal_payload]), config.ml_daily_signal_csv_path)
    ptrade_export_result = export_ptrade_strategy(config, signal_payload)
    LOGGER.info("Saved ML daily signal JSON to: %s", config.ml_daily_signal_json_path)
    LOGGER.info("Saved ML daily signal CSV to: %s", config.ml_daily_signal_csv_path)
    LOGGER.info(
        "Saved dated PTrade strategy for %s to: %s",
        ptrade_export_result["signal_for_date"],
        ptrade_export_result["dated_path"],
    )
    return signal_payload


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Export the latest multi-head ML signal for PTrade consumption.")


def main() -> None:
    configure_foundation_logging()
    build_parser().parse_args()
    build_ml_daily_signal(DEFAULT_CONFIG)


if __name__ == "__main__":
    main()

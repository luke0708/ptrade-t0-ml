from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from .config import DEFAULT_CONFIG, ProjectConfig
from .io_utils import save_dataframe
from .minute_foundation import configure_logging as configure_foundation_logging

LOGGER = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 120
DEFAULT_SWING_THRESHOLD = 0.055
HIGH_SELL_SPACE_THRESHOLD = 0.025
DIP_REPAIR_DRAWDOWN_THRESHOLD = -0.025
DIP_REPAIR_RECOVERY_THRESHOLD = 0.55

PREDICTION_COLUMNS = [
    "date",
    "pred_upside_t1",
    "pred_downside_t1",
    "pred_downside_from_open_t1",
    "pred_grid_pnl_t1",
    "pred_clean_execution_day_t1",
    "pred_positive_grid_day_t1",
    "pred_tradable_score_t1",
    "pred_trend_break_risk_t1",
    "pred_hostile_selloff_risk_t1",
    "pred_vwap_reversion_score_t1",
    "pred_clean_execution_day_t1_threshold",
    "pred_positive_grid_day_t1_threshold",
    "pred_tradable_score_t1_threshold",
    "pred_trend_break_risk_t1_threshold",
    "pred_hostile_selloff_risk_t1_threshold",
    "pred_vwap_reversion_score_t1_threshold",
    "recommended_mode",
    "trend_weak",
    "position_scale",
    "grid_width_scale",
    "dip_buy_enabled",
    "high_sell_enabled",
    "signal_rationale",
]

LABEL_COLUMNS = [
    "date",
    "next_date",
    "next_day_open",
    "next_day_high",
    "next_day_low",
    "next_day_close",
    "target_grid_pnl_t1",
    "target_positive_grid_day_t1",
    "target_tradable_score_t1",
    "target_hostile_selloff_risk_t1",
    "target_vwap_reversion_t1",
    "target_clean_execution_day_t1",
    "next_day_open30_low_return",
    "next_day_open60_low_return",
    "next_day_close_recovery_ratio_from_early_low",
    "next_day_negative_vwap_ratio",
    "next_day_vwap_cross_count_label",
    "next_day_gap_return_t1",
]

FEATURE_COLUMNS = [
    "date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "daily_return",
    "daily_range",
    "gap_pct",
    "close_to_ma20",
    "close_to_ma60",
    "idx_daily_return",
    "sec_daily_return",
    "stk_idx_return_spread",
    "stk_sec_return_spread",
    "stk_m_intraday_range",
    "stk_m_day_return_from_minutes",
    "stk_m_open15_return",
    "stk_m_open30_return",
    "stk_m_open60_return",
    "stk_m_open15_volume_ratio",
    "stk_m_open30_volume_ratio",
    "stk_m_close_vwap_gap",
    "stk_m_max_vwap_gap",
    "stk_m_vwap_cross_count",
    "stk_m_vwap_below_ratio",
    "stk_m_open30_low_return",
    "stk_m_open60_low_return",
    "stk_m_close_recovery_ratio_from_open60_low",
    "stk_m_max_drawdown_intraday",
    "flag_open60_deep_selloff",
    "flag_open60_negative_vwap_persistent",
    "flag_open60_poor_recovery",
    "flag_hostile_selloff_regime",
    "flag_reversion_failure_regime",
    "overnight_us_mean_return",
    "overnight_us_relative_strength_spread",
    "overnight_gap_risk_bucket",
]

OUTPUT_COLUMNS = [
    "date",
    "next_date",
    "path_regime",
    "model_blockers",
    "recommended_mode",
    "signal_rationale",
    "position_scale",
    "grid_width_scale",
    "dip_buy_enabled",
    "high_sell_enabled",
    "daily_range_effective",
    "daily_range",
    "stk_m_intraday_range",
    "gap_pct",
    "open_to_close_return",
    "high_from_open",
    "low_from_open",
    "high_from_prev_close",
    "low_from_prev_close",
    "stk_m_open15_return",
    "stk_m_open60_return",
    "stk_m_open60_low_return",
    "stk_m_close_recovery_ratio_from_open60_low",
    "stk_m_vwap_cross_count",
    "stk_m_vwap_below_ratio",
    "stk_m_close_vwap_gap",
    "high_swing_flag",
    "high_open_fade_flag",
    "early_selloff_flag",
    "same_day_high_sell_window_proxy",
    "same_day_dip_repair_window_proxy",
    "next_day_high_from_open",
    "next_day_low_from_open",
    "next_day_open_to_close_return",
    "next_day_high_sell_window_proxy",
    "next_day_dip_repair_window_proxy",
    "target_grid_pnl_t1",
    "target_positive_grid_day_t1",
    "target_tradable_score_t1",
    "target_hostile_selloff_risk_t1",
    "target_vwap_reversion_t1",
    "pred_positive_grid_day_t1",
    "pred_tradable_score_t1",
    "pred_clean_execution_day_t1",
    "pred_hostile_selloff_risk_t1",
    "pred_vwap_reversion_score_t1",
    "pred_downside_from_open_t1",
    "pred_grid_pnl_t1",
]


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.replace(0, pd.NA)
    return numerator / denominator - 1.0


def _read_optional_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _select_existing_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return df[[column for column in columns if column in df.columns]].copy()


def _latest_signal_prediction_row(config: ProjectConfig) -> pd.DataFrame:
    signal_path = config.data_dir / "ml_daily_signal.json"
    if not signal_path.exists():
        return pd.DataFrame()

    payload = json.loads(signal_path.read_text(encoding="utf-8"))
    if not payload.get("date"):
        return pd.DataFrame()

    row: dict[str, object] = {
        "date": payload.get("date"),
        "recommended_mode": payload.get("recommended_mode"),
        "trend_weak": payload.get("trend_weak"),
        "position_scale": payload.get("position_scale"),
        "grid_width_scale": payload.get("grid_width_scale"),
        "dip_buy_enabled": payload.get("dip_buy_enabled"),
        "high_sell_enabled": payload.get("high_sell_enabled"),
        "signal_rationale": payload.get("signal_rationale"),
    }
    for key, value in payload.items():
        if key.startswith("pred_"):
            row[key] = value
    for key, value in payload.get("recommended_thresholds", {}).items():
        row[f"{key}_threshold"] = value
    return pd.DataFrame([row])


def _load_prediction_frame(config: ProjectConfig) -> pd.DataFrame:
    prediction_df = _read_optional_csv(config.baseline_test_predictions_path)
    if not prediction_df.empty:
        prediction_df = _select_existing_columns(prediction_df, PREDICTION_COLUMNS)

    latest_signal_df = _latest_signal_prediction_row(config)
    if not latest_signal_df.empty:
        prediction_df = pd.concat([prediction_df, latest_signal_df], ignore_index=True)

    if prediction_df.empty:
        return prediction_df
    prediction_df["date"] = pd.to_datetime(prediction_df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return prediction_df.dropna(subset=["date"]).drop_duplicates(subset=["date"], keep="last")


def enrich_high_swing_frame(
    merged_df: pd.DataFrame,
    swing_threshold: float = DEFAULT_SWING_THRESHOLD,
) -> pd.DataFrame:
    df = merged_df.copy()
    for column in [
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "daily_range",
        "stk_m_intraday_range",
        "gap_pct",
        "stk_m_open60_low_return",
        "stk_m_close_recovery_ratio_from_open60_low",
        "stk_m_vwap_cross_count",
        "stk_m_close_vwap_gap",
        "next_day_open",
        "next_day_high",
        "next_day_low",
        "next_day_close",
        "next_day_open60_low_return",
        "next_day_close_recovery_ratio_from_early_low",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    df["open_to_close_return"] = _safe_divide(df["close"], df["open"])
    df["high_from_open"] = _safe_divide(df["high"], df["open"])
    df["low_from_open"] = _safe_divide(df["low"], df["open"])
    df["high_from_prev_close"] = _safe_divide(df["high"], df["pre_close"])
    df["low_from_prev_close"] = _safe_divide(df["low"], df["pre_close"])
    df["daily_range_effective"] = df[["daily_range", "stk_m_intraday_range"]].max(axis=1, skipna=True)

    df["high_swing_flag"] = df["daily_range_effective"] >= float(swing_threshold)
    df["high_open_fade_flag"] = (df["gap_pct"] >= 0.02) & (df["open_to_close_return"] <= -0.015)
    df["early_selloff_flag"] = (
        df[["stk_m_open60_low_return", "low_from_open"]].min(axis=1, skipna=True)
        <= DIP_REPAIR_DRAWDOWN_THRESHOLD
    )
    df["same_day_high_sell_window_proxy"] = (
        (df["high_from_open"] >= HIGH_SELL_SPACE_THRESHOLD)
        | (df["high_from_prev_close"] >= 0.04)
    )
    df["same_day_dip_repair_window_proxy"] = (
        df["early_selloff_flag"]
        & (df["stk_m_close_recovery_ratio_from_open60_low"] >= DIP_REPAIR_RECOVERY_THRESHOLD)
        & (df["open_to_close_return"] >= -0.005)
    )

    df["next_day_high_from_open"] = _safe_divide(df["next_day_high"], df["next_day_open"])
    df["next_day_low_from_open"] = _safe_divide(df["next_day_low"], df["next_day_open"])
    df["next_day_open_to_close_return"] = _safe_divide(df["next_day_close"], df["next_day_open"])
    df["next_day_high_sell_window_proxy"] = df["next_day_high_from_open"] >= HIGH_SELL_SPACE_THRESHOLD
    df["next_day_dip_repair_window_proxy"] = (
        (df["next_day_open60_low_return"] <= DIP_REPAIR_DRAWDOWN_THRESHOLD)
        & (df["next_day_close_recovery_ratio_from_early_low"] >= DIP_REPAIR_RECOVERY_THRESHOLD)
        & (df["next_day_open_to_close_return"] >= -0.005)
    )

    df["path_regime"] = "mixed_high_swing"
    df.loc[df["high_open_fade_flag"], "path_regime"] = "high_open_fade"
    df.loc[df["early_selloff_flag"] & ~df["same_day_dip_repair_window_proxy"], "path_regime"] = (
        "early_selloff_no_repair"
    )
    df.loc[df["same_day_dip_repair_window_proxy"], "path_regime"] = "early_selloff_repaired"
    df.loc[df["same_day_high_sell_window_proxy"] & ~df["early_selloff_flag"], "path_regime"] = (
        "high_sell_window"
    )
    df["model_blockers"] = df.apply(_build_model_blocker_text, axis=1)
    return df


def _build_model_blocker_text(row: pd.Series) -> str:
    blockers: list[str] = []
    checks = [
        ("positive_grid_below", "pred_positive_grid_day_t1", "pred_positive_grid_day_t1_threshold", "<"),
        ("tradable_below", "pred_tradable_score_t1", "pred_tradable_score_t1_threshold", "<"),
        ("hostile_selloff_high", "pred_hostile_selloff_risk_t1", "pred_hostile_selloff_risk_t1_threshold", ">="),
        ("vwap_reversion_below", "pred_vwap_reversion_score_t1", "pred_vwap_reversion_score_t1_threshold", "<"),
        ("trend_break_high", "pred_trend_break_risk_t1", "pred_trend_break_risk_t1_threshold", ">="),
    ]
    for label, pred_col, threshold_col, operator in checks:
        if pred_col not in row or threshold_col not in row:
            continue
        pred = row.get(pred_col)
        threshold = row.get(threshold_col)
        if pd.isna(pred) or pd.isna(threshold):
            continue
        if operator == "<" and float(pred) < float(threshold):
            blockers.append(label)
        if operator == ">=" and float(pred) >= float(threshold):
            blockers.append(label)
    return "|".join(blockers) if blockers else "none"


def build_high_swing_summary(review_df: pd.DataFrame) -> pd.DataFrame:
    segments = {
        "all_high_swing": review_df["high_swing_flag"],
        "safe_high_swing": review_df["high_swing_flag"] & (review_df["recommended_mode"] == "SAFE"),
        "normal_high_swing": review_df["high_swing_flag"] & (review_df["recommended_mode"] == "NORMAL"),
        "high_open_fade": review_df["high_open_fade_flag"],
        "early_selloff": review_df["early_selloff_flag"],
        "same_day_high_sell_window_proxy": review_df["same_day_high_sell_window_proxy"],
        "same_day_dip_repair_window_proxy": review_df["same_day_dip_repair_window_proxy"],
        "next_day_high_sell_window_proxy": review_df["next_day_high_sell_window_proxy"],
        "next_day_dip_repair_window_proxy": review_df["next_day_dip_repair_window_proxy"],
    }
    rows: list[dict[str, object]] = []
    for segment_name, mask in segments.items():
        subset = review_df.loc[mask.fillna(False)].copy()
        rows.append(_summarize_segment(segment_name, subset))
    return pd.DataFrame(rows)


def _summarize_segment(segment_name: str, subset: pd.DataFrame) -> dict[str, object]:
    if subset.empty:
        return {
            "segment_name": segment_name,
            "rows": 0,
            "safe_rows": 0,
            "normal_rows": 0,
            "target_grid_pnl_mean": 0.0,
            "positive_grid_rate": 0.0,
            "tradable_rate": 0.0,
            "hostile_selloff_rate": 0.0,
            "next_day_high_sell_proxy_rate": 0.0,
            "next_day_dip_repair_proxy_rate": 0.0,
        }
    return {
        "segment_name": segment_name,
        "rows": int(len(subset)),
        "safe_rows": int((subset["recommended_mode"] == "SAFE").sum()),
        "normal_rows": int((subset["recommended_mode"] == "NORMAL").sum()),
        "target_grid_pnl_mean": float(subset["target_grid_pnl_t1"].mean()),
        "positive_grid_rate": float(subset["target_positive_grid_day_t1"].mean()),
        "tradable_rate": float(subset["target_tradable_score_t1"].mean()),
        "hostile_selloff_rate": float(subset["target_hostile_selloff_risk_t1"].mean()),
        "next_day_high_sell_proxy_rate": float(subset["next_day_high_sell_window_proxy"].mean()),
        "next_day_dip_repair_proxy_rate": float(subset["next_day_dip_repair_window_proxy"].mean()),
    }


def build_high_swing_report(
    config: ProjectConfig = DEFAULT_CONFIG,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    swing_threshold: float = DEFAULT_SWING_THRESHOLD,
) -> dict[str, Path]:
    if not config.feature_table_path.exists():
        raise FileNotFoundError(f"Feature table missing: {config.feature_table_path}")

    feature_df = pd.read_csv(config.feature_table_path)
    feature_df["date"] = pd.to_datetime(feature_df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    feature_df = feature_df.dropna(subset=["date"]).sort_values("date").tail(lookback_days)
    feature_df = _select_existing_columns(feature_df, FEATURE_COLUMNS)

    label_df = _read_optional_csv(config.label_targets_path)
    if not label_df.empty:
        label_df["date"] = pd.to_datetime(label_df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        label_df = _select_existing_columns(label_df.dropna(subset=["date"]), LABEL_COLUMNS)

    prediction_df = _load_prediction_frame(config)

    merged = feature_df.merge(label_df, on="date", how="left") if not label_df.empty else feature_df
    if not prediction_df.empty:
        merged = merged.merge(prediction_df, on="date", how="left")

    review_df = enrich_high_swing_frame(merged, swing_threshold=swing_threshold)
    review_df = review_df.loc[review_df["high_swing_flag"].fillna(False)].copy()
    review_df = review_df.sort_values("date", ascending=False).reset_index(drop=True)
    review_df = review_df[[column for column in OUTPUT_COLUMNS if column in review_df.columns]]
    summary_df = build_high_swing_summary(review_df)

    save_dataframe(review_df, config.high_swing_recent_review_path)
    save_dataframe(summary_df, config.high_swing_summary_path)

    LOGGER.info("Saved high-swing recent review to: %s", config.high_swing_recent_review_path)
    LOGGER.info("Saved high-swing summary to: %s", config.high_swing_summary_path)
    LOGGER.info(
        "High-swing review rows=%s lookback_days=%s swing_threshold=%.4f",
        len(review_df),
        lookback_days,
        swing_threshold,
    )
    return {
        "high_swing_recent_review": config.high_swing_recent_review_path,
        "high_swing_summary": config.high_swing_summary_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Review recent high-swing 300661 opportunity regimes.")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--swing-threshold", type=float, default=DEFAULT_SWING_THRESHOLD)
    args = parser.parse_args()

    configure_foundation_logging()
    build_high_swing_report(
        DEFAULT_CONFIG,
        lookback_days=args.lookback_days,
        swing_threshold=args.swing_threshold,
    )


if __name__ == "__main__":
    main()

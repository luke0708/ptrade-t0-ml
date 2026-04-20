from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from .config import DEFAULT_CONFIG, ProjectConfig
from .io_utils import save_dataframe
from .minute_foundation import configure_logging as configure_foundation_logging
from .walk_forward_analysis import build_walk_forward_report

LOGGER = logging.getLogger(__name__)

FAILURE_FEATURE_COLUMNS = [
    "pred_positive_grid_day_t1",
    "pred_tradable_score_t1",
    "pred_hostile_selloff_risk_t1",
    "pred_vwap_reversion_score_t1",
    "pred_trend_break_risk_t1",
    "pred_grid_pnl_t1",
    "target_grid_pnl_t1",
    "target_positive_grid_day_t1",
    "target_tradable_score_t1",
    "target_hostile_selloff_risk_t1",
    "target_vwap_reversion_t1",
    "target_trend_break_risk_t1",
    "next_day_open30_low_return",
    "next_day_open60_low_return",
    "next_day_close_recovery_ratio_from_early_low",
    "next_day_negative_vwap_ratio",
    "next_day_hostile_selloff_soft_score",
    "daily_return",
    "gap_pct",
    "atr_pct",
    "grid_step_pct_t1",
    "stk_m_open15_return",
    "stk_m_open15_range",
    "stk_m_trend_efficiency_ratio",
    "stk_m_morning_trend_efficiency_ratio",
    "stk_m_close_vwap_gap",
    "stk_m_vwap_cross_count",
    "stk_m_max_drawdown_intraday",
    "stk_m_open15_volume_ratio",
    "idx_daily_return",
    "sec_daily_return",
]

FAILURE_CASE_COLUMNS = [
    "window_id",
    "date",
    "next_date",
    "recommended_mode",
    "signal_rationale",
    "target_grid_pnl_t1",
    "target_positive_grid_day_t1",
    "target_tradable_score_t1",
    "target_hostile_selloff_risk_t1",
    "target_vwap_reversion_t1",
    "pred_positive_grid_day_t1",
    "pred_tradable_score_t1",
    "pred_hostile_selloff_risk_t1",
    "pred_vwap_reversion_score_t1",
    "pred_trend_break_risk_t1",
    "pred_grid_pnl_t1",
    "next_day_open30_low_return",
    "next_day_open60_low_return",
    "next_day_close_recovery_ratio_from_early_low",
    "next_day_negative_vwap_ratio",
    "next_day_hostile_selloff_soft_score",
    "daily_return",
    "gap_pct",
    "atr_pct",
    "stk_m_open15_return",
    "stk_m_open15_range",
    "stk_m_trend_efficiency_ratio",
    "stk_m_close_vwap_gap",
    "stk_m_max_drawdown_intraday",
    "idx_daily_return",
    "sec_daily_return",
]


def build_walk_forward_failure_report(
    config: ProjectConfig = DEFAULT_CONFIG,
    top_case_count: int = 80,
) -> dict[str, Path]:
    predictions_df, head_metrics_df, window_mode_summary_df = _ensure_walk_forward_inputs(config)
    failure_window_df = build_failure_window_summary(window_mode_summary_df)
    failure_cohort_df = build_failure_cohort_summary(predictions_df, failure_window_df)
    failure_feature_delta_df = build_failure_feature_delta_summary(predictions_df, failure_window_df)
    threshold_drift_df = build_failure_threshold_drift_summary(head_metrics_df, failure_window_df)
    failure_cases_df = select_failure_cases(
        predictions_df=predictions_df,
        failure_window_df=failure_window_df,
        top_case_count=top_case_count,
    )

    save_dataframe(failure_window_df, config.walk_forward_failure_windows_path)
    save_dataframe(failure_cohort_df, config.walk_forward_failure_cohort_summary_path)
    save_dataframe(failure_feature_delta_df, config.walk_forward_failure_feature_delta_path)
    save_dataframe(threshold_drift_df, config.walk_forward_failure_threshold_drift_path)
    save_dataframe(failure_cases_df, config.walk_forward_failure_cases_path)

    LOGGER.info("Saved walk-forward failure windows to: %s", config.walk_forward_failure_windows_path)
    LOGGER.info("Saved walk-forward failure cohort summary to: %s", config.walk_forward_failure_cohort_summary_path)
    LOGGER.info("Saved walk-forward failure feature delta to: %s", config.walk_forward_failure_feature_delta_path)
    LOGGER.info("Saved walk-forward failure threshold drift to: %s", config.walk_forward_failure_threshold_drift_path)
    LOGGER.info("Saved walk-forward failure cases to: %s", config.walk_forward_failure_cases_path)
    LOGGER.info(
        "Walk-forward failure summary: losing_windows=%s winning_windows=%s",
        int((~failure_window_df["normal_beats_safe"]).sum()),
        int(failure_window_df["normal_beats_safe"].sum()),
    )

    return {
        "walk_forward_failure_windows": config.walk_forward_failure_windows_path,
        "walk_forward_failure_cohort_summary": config.walk_forward_failure_cohort_summary_path,
        "walk_forward_failure_feature_delta": config.walk_forward_failure_feature_delta_path,
        "walk_forward_failure_threshold_drift": config.walk_forward_failure_threshold_drift_path,
        "walk_forward_failure_cases": config.walk_forward_failure_cases_path,
    }


def build_failure_window_summary(window_mode_summary_df: pd.DataFrame) -> pd.DataFrame:
    required_modes = {"SAFE", "NORMAL"}
    pivot_source = window_mode_summary_df[
        window_mode_summary_df["segment_name"].isin(["SAFE", "NORMAL", "OFF", "AGGRESSIVE"])
    ].copy()
    metadata_columns = ["window_id", "train_start_date", "train_end_date", "test_start_date", "test_end_date"]
    metric_columns = ["rows", "grid_pnl_mean", "p10_grid_pnl", "worst_day_grid_pnl"]

    mode_tables: list[pd.DataFrame] = []
    for metric_column in metric_columns:
        pivot = pivot_source.pivot_table(
            index=metadata_columns,
            columns="segment_name",
            values=metric_column,
            aggfunc="first",
        )
        pivot = pivot.add_prefix(f"{metric_column}_").reset_index()
        mode_tables.append(pivot)

    summary_df = mode_tables[0]
    for table in mode_tables[1:]:
        summary_df = summary_df.merge(table, on=metadata_columns, how="outer")

    missing_modes = [
        mode for mode in required_modes if f"grid_pnl_mean_{mode}" not in summary_df.columns
    ]
    if missing_modes:
        raise ValueError(f"Window mode summary is missing required segments: {missing_modes}")

    for mode in ["SAFE", "NORMAL", "OFF", "AGGRESSIVE"]:
        for metric_column in metric_columns:
            column = f"{metric_column}_{mode}"
            if column not in summary_df.columns:
                summary_df[column] = 0.0

    summary_df["normal_minus_safe"] = (
        summary_df["grid_pnl_mean_NORMAL"] - summary_df["grid_pnl_mean_SAFE"]
    )
    summary_df["normal_p10_minus_safe"] = (
        summary_df["p10_grid_pnl_NORMAL"] - summary_df["p10_grid_pnl_SAFE"]
    )
    summary_df["normal_worst_minus_safe"] = (
        summary_df["worst_day_grid_pnl_NORMAL"] - summary_df["worst_day_grid_pnl_SAFE"]
    )
    summary_df["normal_rows_share"] = (
        summary_df["rows_NORMAL"] / (summary_df["rows_NORMAL"] + summary_df["rows_SAFE"]).replace(0, pd.NA)
    ).fillna(0.0)
    summary_df["normal_beats_safe"] = summary_df["normal_minus_safe"] > 0
    summary_df["failure_severity_rank"] = (
        summary_df["normal_minus_safe"].rank(method="dense", ascending=True).astype("int64")
    )
    return summary_df.sort_values(["normal_minus_safe", "window_id"]).reset_index(drop=True)


def build_failure_cohort_summary(
    predictions_df: pd.DataFrame,
    failure_window_df: pd.DataFrame,
) -> pd.DataFrame:
    merged_df = predictions_df.merge(
        failure_window_df[["window_id", "normal_beats_safe", "normal_minus_safe"]],
        on="window_id",
        how="left",
        validate="many_to_one",
    )
    rows: list[dict[str, object]] = []
    for mode in ["NORMAL", "SAFE"]:
        mode_df = merged_df[merged_df["recommended_mode"] == mode].copy()
        for cohort_label, cohort_df in mode_df.groupby("normal_beats_safe", dropna=False):
            is_success = bool(cohort_label)
            cohort_name = "good_windows" if is_success else "failure_windows"
            rows.append(
                {
                    "recommended_mode": mode,
                    "cohort_name": cohort_name,
                    "rows": int(len(cohort_df)),
                    "window_count": int(cohort_df["window_id"].nunique()),
                    "grid_pnl_mean": float(cohort_df["target_grid_pnl_t1"].mean()),
                    "grid_pnl_p10": float(cohort_df["target_grid_pnl_t1"].quantile(0.10)),
                    "worst_day_grid_pnl": float(cohort_df["target_grid_pnl_t1"].min()),
                    "positive_grid_day_rate": float(cohort_df["target_positive_grid_day_t1"].mean()),
                    "tradable_rate": float(cohort_df["target_tradable_score_t1"].mean()),
                    "hostile_selloff_rate": float(cohort_df["target_hostile_selloff_risk_t1"].mean()),
                    "vwap_reversion_rate": float(cohort_df["target_vwap_reversion_t1"].mean()),
                    "pred_positive_grid_day_mean": float(cohort_df["pred_positive_grid_day_t1"].mean()),
                    "pred_tradable_mean": float(cohort_df["pred_tradable_score_t1"].mean()),
                    "pred_hostile_selloff_mean": float(cohort_df["pred_hostile_selloff_risk_t1"].mean()),
                    "pred_vwap_reversion_mean": float(cohort_df["pred_vwap_reversion_score_t1"].mean()),
                    "position_scale_mean": float(cohort_df["position_scale"].mean()),
                    "grid_width_scale_mean": float(cohort_df["grid_width_scale"].mean()),
                }
            )
    return pd.DataFrame(rows).sort_values(["recommended_mode", "cohort_name"]).reset_index(drop=True)


def build_failure_feature_delta_summary(
    predictions_df: pd.DataFrame,
    failure_window_df: pd.DataFrame,
) -> pd.DataFrame:
    merged_df = predictions_df.merge(
        failure_window_df[["window_id", "normal_beats_safe"]],
        on="window_id",
        how="left",
        validate="many_to_one",
    )
    normal_df = merged_df[merged_df["recommended_mode"] == "NORMAL"].copy()
    bad_df = normal_df[normal_df["normal_beats_safe"] == False]
    good_df = normal_df[normal_df["normal_beats_safe"] == True]
    rows: list[dict[str, object]] = []

    for column in FAILURE_FEATURE_COLUMNS:
        if column not in normal_df.columns:
            continue
        bad_mean = float(bad_df[column].mean()) if not bad_df.empty else 0.0
        good_mean = float(good_df[column].mean()) if not good_df.empty else 0.0
        rows.append(
            {
                "feature_name": column,
                "bad_normal_mean": bad_mean,
                "good_normal_mean": good_mean,
                "bad_minus_good": bad_mean - good_mean,
                "bad_abs_mean": abs(bad_mean),
            }
        )

    return pd.DataFrame(rows).sort_values(
        by=["bad_minus_good"],
        ascending=True,
    ).reset_index(drop=True)


def build_failure_threshold_drift_summary(
    head_metrics_df: pd.DataFrame,
    failure_window_df: pd.DataFrame,
) -> pd.DataFrame:
    classification_df = head_metrics_df[head_metrics_df["head_type"] == "classification"].copy()
    classification_df = classification_df.merge(
        failure_window_df[["window_id", "normal_beats_safe"]],
        on="window_id",
        how="left",
        validate="many_to_one",
    )
    rows: list[dict[str, object]] = []
    for head_name, head_df in classification_df.groupby("head_name", sort=True):
        bad_df = head_df[head_df["normal_beats_safe"] == False]
        good_df = head_df[head_df["normal_beats_safe"] == True]
        rows.append(
            {
                "head_name": head_name,
                "bad_window_count": int(bad_df["window_id"].nunique()),
                "good_window_count": int(good_df["window_id"].nunique()),
                "bad_threshold_mean": float(bad_df["recommended_threshold"].mean()),
                "good_threshold_mean": float(good_df["recommended_threshold"].mean()),
                "threshold_delta_bad_minus_good": float(bad_df["recommended_threshold"].mean() - good_df["recommended_threshold"].mean()),
                "bad_recall_mean": float(bad_df["recommended_recall"].mean()),
                "good_recall_mean": float(good_df["recommended_recall"].mean()),
                "recall_delta_bad_minus_good": float(bad_df["recommended_recall"].mean() - good_df["recommended_recall"].mean()),
                "bad_precision_mean": float(bad_df["recommended_precision"].mean()),
                "good_precision_mean": float(good_df["recommended_precision"].mean()),
                "precision_delta_bad_minus_good": float(bad_df["recommended_precision"].mean() - good_df["recommended_precision"].mean()),
                "bad_ap_mean": float(bad_df["default_average_precision"].mean()),
                "good_ap_mean": float(good_df["default_average_precision"].mean()),
                "ap_delta_bad_minus_good": float(bad_df["default_average_precision"].mean() - good_df["default_average_precision"].mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("ap_delta_bad_minus_good", ascending=True).reset_index(drop=True)


def select_failure_cases(
    predictions_df: pd.DataFrame,
    failure_window_df: pd.DataFrame,
    top_case_count: int,
) -> pd.DataFrame:
    if top_case_count <= 0:
        raise ValueError("top_case_count must be positive.")

    merged_df = predictions_df.merge(
        failure_window_df[
            [
                "window_id",
                "normal_beats_safe",
                "normal_minus_safe",
                "failure_severity_rank",
            ]
        ],
        on="window_id",
        how="left",
        validate="many_to_one",
    )
    normal_failure_df = merged_df[
        (merged_df["recommended_mode"] == "NORMAL") & (merged_df["normal_beats_safe"] == False)
    ].copy()
    ordered_columns = [
        "window_id",
        "normal_beats_safe",
        "normal_minus_safe",
        "failure_severity_rank",
    ]
    ordered_columns.extend(column for column in FAILURE_CASE_COLUMNS if column in normal_failure_df.columns)
    ordered_columns = list(dict.fromkeys(ordered_columns))
    return normal_failure_df.sort_values(
        by=["target_grid_pnl_t1", "window_id", "pred_hostile_selloff_risk_t1"],
        ascending=[True, True, False],
    ).head(top_case_count)[ordered_columns].reset_index(drop=True)


def _ensure_walk_forward_inputs(
    config: ProjectConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    missing_paths = [
        path
        for path in [
            config.walk_forward_test_predictions_path,
            config.walk_forward_head_metrics_path,
            config.walk_forward_window_mode_summary_path,
        ]
        if not path.exists()
    ]
    if missing_paths:
        LOGGER.info("Walk-forward artifacts missing. Building walk-forward report first.")
        build_walk_forward_report(config)

    predictions_df = pd.read_csv(config.walk_forward_test_predictions_path)
    head_metrics_df = pd.read_csv(config.walk_forward_head_metrics_path)
    window_mode_summary_df = pd.read_csv(config.walk_forward_window_mode_summary_path)
    return predictions_df, head_metrics_df, window_mode_summary_df


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze walk-forward failure windows and unstable NORMAL slices.")
    parser.add_argument("--top-case-count", type=int, default=80)
    return parser


def main() -> None:
    configure_foundation_logging()
    args = build_parser().parse_args()
    build_walk_forward_failure_report(
        config=DEFAULT_CONFIG,
        top_case_count=args.top_case_count,
    )


if __name__ == "__main__":
    main()

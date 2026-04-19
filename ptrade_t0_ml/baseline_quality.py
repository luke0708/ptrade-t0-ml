from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from .baseline_models import (
    build_xgb_classifier,
    build_xgb_regressor,
    split_train_test,
    train_baseline_models,
)
from .config import DEFAULT_CONFIG, ProjectConfig
from .io_utils import save_dataframe
from .minute_foundation import configure_logging as configure_foundation_logging
from .signal_export import (
    CLASSIFICATION_HEAD_TO_SIGNAL_FIELD,
    REGRESSION_HEAD_TO_SIGNAL_FIELD,
    _derive_runtime_controls,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_BUCKET_COUNT = 5
DEFAULT_TOP_N = 50
DEFAULT_IMPORTANCE_LIMIT = 30

HEAD_TO_SIGNAL_FIELD = {
    **REGRESSION_HEAD_TO_SIGNAL_FIELD,
    **CLASSIFICATION_HEAD_TO_SIGNAL_FIELD,
}

DOWNSIDE_CONTEXT_COLUMNS = [
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
    "idx_daily_range",
    "sec_daily_return",
    "sec_daily_range",
]

SUMMARY_MODE_SEGMENTS = (
    "ALL",
    "OFF",
    "SAFE",
    "NORMAL",
    "AGGRESSIVE",
    "SAFE_OR_OFF",
    "NORMAL_OR_AGGRESSIVE",
)


def assign_score_buckets(series: pd.Series, bucket_count: int = DEFAULT_BUCKET_COUNT) -> pd.Series:
    clean_series = pd.Series(series, copy=False)
    bucketed = pd.Series(pd.NA, index=clean_series.index, dtype="Int64")
    valid = clean_series.dropna()
    if valid.empty:
        return bucketed

    effective_bucket_count = min(int(bucket_count), int(len(valid)))
    if effective_bucket_count <= 1:
        bucketed.loc[valid.index] = 1
        return bucketed

    ranked = valid.rank(method="first")
    quantiles = pd.qcut(ranked, q=effective_bucket_count, labels=False, duplicates="drop")
    bucketed.loc[valid.index] = quantiles.astype("int64") + 1
    return bucketed


def build_mode_replay_summary(predictions_df: pd.DataFrame) -> pd.DataFrame:
    segments: list[dict[str, object]] = []
    total_rows = len(predictions_df)

    for segment_name in SUMMARY_MODE_SEGMENTS:
        if segment_name == "ALL":
            subset = predictions_df
        elif segment_name == "SAFE_OR_OFF":
            subset = predictions_df[predictions_df["recommended_mode"].isin(["SAFE", "OFF"])]
        elif segment_name == "NORMAL_OR_AGGRESSIVE":
            subset = predictions_df[predictions_df["recommended_mode"].isin(["NORMAL", "AGGRESSIVE"])]
        else:
            subset = predictions_df[predictions_df["recommended_mode"] == segment_name]

        segments.append(_summarize_mode_segment(segment_name, subset, total_rows))

    return pd.DataFrame(segments)


def select_downside_error_cases(
    predictions_df: pd.DataFrame,
    top_n: int = DEFAULT_TOP_N,
    context_columns: list[str] | None = None,
) -> pd.DataFrame:
    if top_n <= 0:
        raise ValueError("top_n must be positive.")

    context_columns = context_columns or DOWNSIDE_CONTEXT_COLUMNS
    enriched = predictions_df.copy()
    enriched["predicted_downside_rank"] = (
        enriched["pred_downside_t1"].rank(method="first", ascending=True).astype("int64")
    )
    enriched["actual_downside_rank"] = (
        enriched["target_downside_t1"].rank(method="first", ascending=True).astype("int64")
    )
    enriched["downside_abs_error_rank"] = (
        enriched["downside_abs_error"].rank(method="first", ascending=False).astype("int64")
    )
    enriched["downside_rank_gap"] = (
        enriched["predicted_downside_rank"] - enriched["actual_downside_rank"]
    ).astype("int64")

    predicted_worst_index = set(enriched.nsmallest(top_n, "pred_downside_t1").index)
    actual_worst_index = set(enriched.nsmallest(top_n, "target_downside_t1").index)
    largest_error_index = set(enriched.nlargest(top_n, "downside_abs_error").index)
    selected_index = sorted(predicted_worst_index | actual_worst_index | largest_error_index)

    selected = enriched.loc[selected_index].copy()
    selected["in_predicted_worst_top_n"] = selected.index.isin(predicted_worst_index)
    selected["in_actual_worst_top_n"] = selected.index.isin(actual_worst_index)
    selected["in_largest_abs_error_top_n"] = selected.index.isin(largest_error_index)

    ordered_columns = [
        "date",
        "next_date",
        "recommended_mode",
        "signal_rationale",
        "pred_downside_t1",
        "target_downside_t1",
        "downside_prediction_error",
        "downside_abs_error",
        "predicted_downside_rank",
        "actual_downside_rank",
        "downside_abs_error_rank",
        "downside_rank_gap",
        "in_predicted_worst_top_n",
        "in_actual_worst_top_n",
        "in_largest_abs_error_top_n",
        "pred_upside_t1",
        "target_upside_t1",
        "pred_grid_pnl_t1",
        "target_grid_pnl_t1",
        "pred_positive_grid_day_t1",
        "target_positive_grid_day_t1",
        "pred_tradable_score_t1",
        "target_tradable_score_t1",
        "pred_trend_break_risk_t1",
        "target_trend_break_risk_t1",
        "pred_vwap_reversion_score_t1",
        "target_vwap_reversion_t1",
        "position_scale",
        "grid_width_scale",
        "recommended_grid_width_t1",
    ]
    ordered_columns.extend(column for column in context_columns if column in selected.columns)

    return selected[ordered_columns].sort_values(
        by=["in_largest_abs_error_top_n", "downside_abs_error", "target_downside_t1"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def build_baseline_quality_report(
    config: ProjectConfig = DEFAULT_CONFIG,
    bucket_count: int = DEFAULT_BUCKET_COUNT,
    downside_top_n: int = DEFAULT_TOP_N,
    feature_importance_limit: int = DEFAULT_IMPORTANCE_LIMIT,
) -> dict[str, Path]:
    metadata = _ensure_baseline_outputs(config)
    test_df = _load_test_dataset(config, metadata)
    predictions_df = _score_test_dataset(config, metadata, test_df, bucket_count=bucket_count)
    bucket_summary_df = _build_head_bucket_summary(predictions_df, metadata)
    mode_summary_df = build_mode_replay_summary(predictions_df)
    downside_cases_df = select_downside_error_cases(predictions_df, top_n=downside_top_n)
    feature_importance_df = _extract_head_feature_importance(
        config,
        metadata,
        limit_per_head=feature_importance_limit,
    )

    save_dataframe(predictions_df, config.baseline_test_predictions_path)
    save_dataframe(bucket_summary_df, config.head_bucket_summary_path)
    save_dataframe(mode_summary_df, config.safe_mode_replay_summary_path)
    save_dataframe(downside_cases_df, config.downside_error_cases_path)
    save_dataframe(feature_importance_df, config.head_feature_importance_path)

    LOGGER.info("Saved baseline test predictions to: %s", config.baseline_test_predictions_path)
    LOGGER.info("Saved head bucket summary to: %s", config.head_bucket_summary_path)
    LOGGER.info("Saved safe-mode replay summary to: %s", config.safe_mode_replay_summary_path)
    LOGGER.info("Saved downside error cases to: %s", config.downside_error_cases_path)
    LOGGER.info("Saved head feature importance to: %s", config.head_feature_importance_path)

    return {
        "baseline_test_predictions": config.baseline_test_predictions_path,
        "head_bucket_summary": config.head_bucket_summary_path,
        "safe_mode_replay_summary": config.safe_mode_replay_summary_path,
        "downside_error_cases": config.downside_error_cases_path,
        "head_feature_importance": config.head_feature_importance_path,
    }


def _ensure_baseline_outputs(config: ProjectConfig) -> dict[str, object]:
    if not config.baseline_metadata_path.exists() or not config.training_dataset_path.exists():
        LOGGER.info("Baseline artifacts missing. Training baseline models before analysis.")
        train_baseline_models(config)
    return json.loads(config.baseline_metadata_path.read_text(encoding="utf-8"))


def _load_test_dataset(config: ProjectConfig, metadata: dict[str, object]) -> pd.DataFrame:
    training_df = pd.read_csv(config.training_dataset_path)
    missing_feature_columns = [
        column for column in metadata["feature_columns"] if column not in training_df.columns
    ]
    if missing_feature_columns:
        raise ValueError(
            f"Training dataset is missing feature columns required by the baseline metadata: {missing_feature_columns}"
        )
    _, test_df = split_train_test(training_df, config.test_ratio)
    return test_df.reset_index(drop=True)


def _score_test_dataset(
    config: ProjectConfig,
    metadata: dict[str, object],
    test_df: pd.DataFrame,
    bucket_count: int,
) -> pd.DataFrame:
    feature_columns = metadata["feature_columns"]
    X_test = test_df[feature_columns]

    output_columns = [
        "date",
        "next_date",
        "target_upside_t1",
        "target_downside_t1",
        "target_grid_pnl_t1",
        "target_positive_grid_day_t1",
        "target_tradable_score_t1",
        "target_trend_break_risk_t1",
        "target_vwap_reversion_t1",
    ]
    output_columns.extend(column for column in DOWNSIDE_CONTEXT_COLUMNS if column in test_df.columns)
    predictions_df = test_df[output_columns].copy().reset_index(drop=True)

    for head_name, signal_field in REGRESSION_HEAD_TO_SIGNAL_FIELD.items():
        model = build_xgb_regressor(config)
        model.load_model(metadata["heads"][head_name]["model_path"])
        predictions_df[signal_field] = model.predict(X_test)

    for head_name, signal_field in CLASSIFICATION_HEAD_TO_SIGNAL_FIELD.items():
        model = build_xgb_classifier(config, scale_pos_weight=1.0)
        model.load_model(metadata["heads"][head_name]["model_path"])
        predictions_df[signal_field] = model.predict_proba(X_test)[:, 1]

    thresholds = {
        signal_field: float(metadata["heads"][head_name]["recommended_threshold"])
        for head_name, signal_field in CLASSIFICATION_HEAD_TO_SIGNAL_FIELD.items()
    }
    for signal_field, threshold in thresholds.items():
        predictions_df[f"{signal_field}_threshold"] = threshold
        predictions_df[f"{signal_field}_on"] = predictions_df[signal_field] >= threshold

    runtime_controls_records = []
    prediction_fields = list(HEAD_TO_SIGNAL_FIELD.values())
    for row_index in range(len(predictions_df)):
        row_predictions = {
            signal_field: float(predictions_df.iloc[row_index][signal_field])
            for signal_field in prediction_fields
        }
        runtime_controls_records.append(
            _derive_runtime_controls(
                predictions=row_predictions,
                thresholds=thresholds,
                latest_feature_row=test_df.iloc[row_index],
            )
        )
    runtime_controls_df = pd.DataFrame(runtime_controls_records)
    predictions_df = pd.concat([predictions_df, runtime_controls_df], axis=1)

    for signal_field in prediction_fields:
        predictions_df[f"{signal_field}_bucket"] = assign_score_buckets(
            predictions_df[signal_field],
            bucket_count=bucket_count,
        )

    predictions_df["downside_prediction_error"] = (
        predictions_df["pred_downside_t1"] - predictions_df["target_downside_t1"]
    )
    predictions_df["downside_abs_error"] = predictions_df["downside_prediction_error"].abs()
    return predictions_df


def _build_head_bucket_summary(
    predictions_df: pd.DataFrame,
    metadata: dict[str, object],
) -> pd.DataFrame:
    summary_rows: list[dict[str, object]] = []
    total_rows = len(predictions_df)

    for head_name, signal_field in HEAD_TO_SIGNAL_FIELD.items():
        bucket_column = f"{signal_field}_bucket"
        if bucket_column not in predictions_df.columns:
            continue

        target_column = metadata["heads"][head_name]["target_column"]
        grouped = predictions_df.dropna(subset=[bucket_column]).groupby(bucket_column, sort=True)
        for bucket_value, subset in grouped:
            summary_rows.append(
                {
                    "head_name": head_name,
                    "signal_field": signal_field,
                    "target_column": target_column,
                    "bucket": int(bucket_value),
                    "rows": int(len(subset)),
                    "share_of_test_days": float(len(subset) / total_rows) if total_rows else 0.0,
                    "prediction_mean": float(subset[signal_field].mean()),
                    "prediction_min": float(subset[signal_field].min()),
                    "prediction_max": float(subset[signal_field].max()),
                    "target_mean": float(subset[target_column].mean()),
                    "grid_pnl_mean": float(subset["target_grid_pnl_t1"].mean()),
                    "upside_mean": float(subset["target_upside_t1"].mean()),
                    "downside_mean": float(subset["target_downside_t1"].mean()),
                    "positive_grid_day_rate": float(subset["target_positive_grid_day_t1"].mean()),
                    "tradable_rate": float(subset["target_tradable_score_t1"].mean()),
                    "trend_break_risk_rate": float(subset["target_trend_break_risk_t1"].mean()),
                    "vwap_reversion_rate": float(subset["target_vwap_reversion_t1"].mean()),
                }
            )

    return pd.DataFrame(summary_rows).sort_values(["head_name", "bucket"]).reset_index(drop=True)


def _extract_head_feature_importance(
    config: ProjectConfig,
    metadata: dict[str, object],
    limit_per_head: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if limit_per_head <= 0:
        raise ValueError("limit_per_head must be positive.")

    for head_name, head_metadata in metadata["heads"].items():
        if head_name in REGRESSION_HEAD_TO_SIGNAL_FIELD:
            model = build_xgb_regressor(config)
        else:
            model = build_xgb_classifier(config, scale_pos_weight=1.0)
        model.load_model(head_metadata["model_path"])

        importance_by_feature = model.get_booster().get_score(importance_type="gain")
        sorted_items = sorted(
            importance_by_feature.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:limit_per_head]
        total_importance = sum(value for _, value in sorted_items)
        for rank_index, (feature_name, importance_value) in enumerate(sorted_items, start=1):
            rows.append(
                {
                    "head_name": head_name,
                    "target_column": head_metadata["target_column"],
                    "rank": rank_index,
                    "feature_name": feature_name,
                    "importance_gain": float(importance_value),
                    "importance_gain_share": (
                        float(importance_value / total_importance) if total_importance > 0 else 0.0
                    ),
                }
            )

    return pd.DataFrame(rows).sort_values(["head_name", "rank"]).reset_index(drop=True)


def _summarize_mode_segment(
    segment_name: str,
    subset: pd.DataFrame,
    total_rows: int,
) -> dict[str, object]:
    if subset.empty:
        return {
            "segment_name": segment_name,
            "rows": 0,
            "share_of_test_days": 0.0,
            "grid_pnl_total": 0.0,
            "grid_pnl_mean": 0.0,
            "grid_pnl_median": 0.0,
            "grid_pnl_total_position_scaled_proxy": 0.0,
            "grid_pnl_mean_position_scaled_proxy": 0.0,
            "worst_day_grid_pnl": 0.0,
            "p10_grid_pnl": 0.0,
            "positive_grid_day_rate": 0.0,
            "tradable_rate": 0.0,
            "trend_break_risk_rate": 0.0,
            "vwap_reversion_rate": 0.0,
            "upside_mean": 0.0,
            "downside_mean": 0.0,
        }

    scaled_proxy = subset["target_grid_pnl_t1"] * subset["position_scale"]
    return {
        "segment_name": segment_name,
        "rows": int(len(subset)),
        "share_of_test_days": float(len(subset) / total_rows) if total_rows else 0.0,
        "grid_pnl_total": float(subset["target_grid_pnl_t1"].sum()),
        "grid_pnl_mean": float(subset["target_grid_pnl_t1"].mean()),
        "grid_pnl_median": float(subset["target_grid_pnl_t1"].median()),
        "grid_pnl_total_position_scaled_proxy": float(scaled_proxy.sum()),
        "grid_pnl_mean_position_scaled_proxy": float(scaled_proxy.mean()),
        "worst_day_grid_pnl": float(subset["target_grid_pnl_t1"].min()),
        "p10_grid_pnl": float(subset["target_grid_pnl_t1"].quantile(0.10)),
        "positive_grid_day_rate": float(subset["target_positive_grid_day_t1"].mean()),
        "tradable_rate": float(subset["target_tradable_score_t1"].mean()),
        "trend_break_risk_rate": float(subset["target_trend_break_risk_t1"].mean()),
        "vwap_reversion_rate": float(subset["target_vwap_reversion_t1"].mean()),
        "upside_mean": float(subset["target_upside_t1"].mean()),
        "downside_mean": float(subset["target_downside_t1"].mean()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze baseline quality on the current test slice.")
    parser.add_argument("--bucket-count", type=int, default=DEFAULT_BUCKET_COUNT)
    parser.add_argument("--downside-top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--feature-importance-limit", type=int, default=DEFAULT_IMPORTANCE_LIMIT)
    return parser


def main() -> None:
    configure_foundation_logging()
    args = build_parser().parse_args()
    build_baseline_quality_report(
        DEFAULT_CONFIG,
        bucket_count=args.bucket_count,
        downside_top_n=args.downside_top_n,
        feature_importance_limit=args.feature_importance_limit,
    )


if __name__ == "__main__":
    main()

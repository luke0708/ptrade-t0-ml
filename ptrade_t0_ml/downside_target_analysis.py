from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from .baseline_models import (
    _evaluate_regression,
    build_training_dataset,
    build_xgb_regressor,
    get_feature_columns,
    split_train_test,
)
from .baseline_quality import assign_score_buckets
from .config import DEFAULT_CONFIG, ProjectConfig
from .feature_engine import run_feature_engine
from .io_utils import save_dataframe
from .label_engine import run_label_engine
from .minute_foundation import configure_logging as configure_foundation_logging

LOGGER = logging.getLogger(__name__)

DOWNSIDE_TARGET_COLUMNS = (
    "target_downside_t1",
    "target_downside_from_open_t1",
    "target_downside_from_max_anchor_t1",
)

EVALUATION_SCOPES = (
    "all_test_days",
    "filtered_non_suspicious_days",
)


def build_downside_target_comparison(config: ProjectConfig = DEFAULT_CONFIG) -> dict[str, Path]:
    training_df, metadata = _load_training_frame_with_metadata(config)
    feature_columns = get_feature_columns(training_df)
    train_df, test_df = split_train_test(training_df, config.test_ratio)
    X_train = train_df[feature_columns]
    X_test = test_df[feature_columns]

    summary_rows: list[dict[str, object]] = []
    prediction_df = test_df[
        [
            "date",
            "next_date",
            "next_day_gap_return_t1",
            "target_downside_positive_flag_t1",
            "target_downside_large_positive_flag_t1",
            "target_upside_extreme_flag_t1",
            "next_day_large_gap_flag_t1",
            "next_day_suspicious_abnormal_jump_flag_t1",
            "target_grid_pnl_t1",
            "target_positive_grid_day_t1",
            "target_tradable_score_t1",
            "target_trend_break_risk_t1",
        ]
    ].copy()

    for target_column in DOWNSIDE_TARGET_COLUMNS:
        model = build_xgb_regressor(config)
        model.fit(X_train, train_df[target_column])
        predictions = pd.Series(model.predict(X_test), index=test_df.index)
        evaluation = _evaluate_regression(test_df[target_column], predictions.to_numpy())

        bucket_column = f"{target_column}_prediction_bucket"
        prediction_column = f"pred_{target_column}"
        error_column = f"{target_column}_prediction_error"
        prediction_df[target_column] = test_df[target_column].to_numpy()
        prediction_df[prediction_column] = predictions.to_numpy()
        prediction_df[error_column] = prediction_df[prediction_column] - prediction_df[target_column]
        prediction_df[bucket_column] = assign_score_buckets(predictions, bucket_count=5)
        suspicious_flag_column = "next_day_suspicious_abnormal_jump_flag_t1"
        for evaluation_scope in EVALUATION_SCOPES:
            if (
                evaluation_scope == "filtered_non_suspicious_days"
                and suspicious_flag_column in prediction_df.columns
            ):
                scoped_df = prediction_df.loc[prediction_df[suspicious_flag_column] == 0].copy()
            elif evaluation_scope == "filtered_non_suspicious_days":
                scoped_df = prediction_df.copy()
            else:
                scoped_df = prediction_df.copy()

            if scoped_df.empty:
                continue
            top_bucket_mask = scoped_df[bucket_column] == int(scoped_df[bucket_column].max())
            bottom_bucket_mask = scoped_df[bucket_column] == int(scoped_df[bucket_column].min())
            scoped_eval = _evaluate_regression(
                scoped_df[target_column],
                scoped_df[prediction_column].to_numpy(),
            )
            summary_rows.append(
                {
                    "target_column": target_column,
                    "evaluation_scope": evaluation_scope,
                    "train_rows": int(len(train_df)),
                    "test_rows": int(len(scoped_df)),
                    "excluded_suspicious_rows": int(len(prediction_df) - len(scoped_df)),
                    "test_start_date": str(scoped_df.iloc[0]["date"]),
                    "test_end_date": str(scoped_df.iloc[-1]["date"]),
                    "mean": float(scoped_df[target_column].mean()),
                    "median": float(scoped_df[target_column].median()),
                    "positive_day_count": int((scoped_df[target_column] > 0).sum()),
                    "positive_day_ratio": float((scoped_df[target_column] > 0).mean()),
                    "mae": float(scoped_eval["mae"]),
                    "rmse": float(scoped_eval["rmse"]),
                    "r2": float(scoped_eval["r2"]),
                    "spearman_rank_corr": float(scoped_eval["spearman_rank_corr"]),
                    "top_quintile_actual_mean": float(scoped_eval["top_quintile_actual_mean"]),
                    "bottom_quintile_actual_mean": float(scoped_eval["bottom_quintile_actual_mean"]),
                    "top_bucket_grid_pnl_mean": float(scoped_df.loc[top_bucket_mask, "target_grid_pnl_t1"].mean()),
                    "bottom_bucket_grid_pnl_mean": float(
                        scoped_df.loc[bottom_bucket_mask, "target_grid_pnl_t1"].mean()
                    ),
                    "top_bucket_trend_break_risk_rate": float(
                        scoped_df.loc[top_bucket_mask, "target_trend_break_risk_t1"].mean()
                    ),
                    "bottom_bucket_trend_break_risk_rate": float(
                        scoped_df.loc[bottom_bucket_mask, "target_trend_break_risk_t1"].mean()
                    ),
                }
            )

    summary_df = pd.DataFrame(summary_rows).sort_values("target_column").reset_index(drop=True)
    save_dataframe(summary_df, config.downside_target_comparison_path)
    save_dataframe(prediction_df, config.downside_target_predictions_path)
    LOGGER.info("Saved downside target comparison to: %s", config.downside_target_comparison_path)
    LOGGER.info("Saved downside target predictions to: %s", config.downside_target_predictions_path)
    return {
        "comparison": config.downside_target_comparison_path,
        "predictions": config.downside_target_predictions_path,
    }


def _load_training_frame_with_metadata(config: ProjectConfig) -> tuple[pd.DataFrame, dict[str, object]]:
    if not config.feature_table_path.exists():
        LOGGER.info("Feature table missing. Rebuilding feature engine outputs first.")
        run_feature_engine(config)
    if not config.label_targets_path.exists():
        LOGGER.info("Label targets missing. Rebuilding label engine outputs first.")
        run_label_engine(config)

    feature_df = pd.read_csv(config.feature_table_path)
    label_df = pd.read_csv(config.label_targets_path)
    missing_downside_targets = [column for column in DOWNSIDE_TARGET_COLUMNS if column not in label_df.columns]
    if missing_downside_targets:
        LOGGER.info(
            "Label targets are missing downside variants %s. Rebuilding label targets with the updated label engine.",
            missing_downside_targets,
        )
        run_label_engine(config)
        label_df = pd.read_csv(config.label_targets_path)
    training_df = build_training_dataset(feature_df, label_df)
    metadata = {
        "feature_table_path": str(config.feature_table_path),
        "label_targets_path": str(config.label_targets_path),
    }
    return training_df, metadata


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Compare downside target variants on the current baseline split.")


def main() -> None:
    configure_foundation_logging()
    build_parser().parse_args()
    build_downside_target_comparison(DEFAULT_CONFIG)


if __name__ == "__main__":
    main()

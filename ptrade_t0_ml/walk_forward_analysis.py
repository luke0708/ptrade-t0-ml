from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .baseline_models import (
    _compute_scale_pos_weight,
    _ensure_feature_and_label_outputs,
    _evaluate_classification,
    _evaluate_regression,
    _select_decision_threshold,
    build_training_dataset,
    build_xgb_classifier,
    build_xgb_regressor,
    get_feature_columns,
    split_train_test,
)
from .baseline_quality import (
    DOWNSIDE_CONTEXT_COLUMNS,
    build_controller_interaction_summary,
    build_mode_replay_summary,
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

DEFAULT_TRAIN_WINDOW_ROWS = 756
DEFAULT_TEST_WINDOW_ROWS = 63
DEFAULT_STEP_ROWS = 63
DEFAULT_MIN_TEST_ROWS = 21


@dataclass(frozen=True)
class WalkForwardWindow:
    window_id: int
    train_start_index: int
    train_end_index: int
    test_start_index: int
    test_end_index: int


def build_walk_forward_windows(
    total_rows: int,
    train_window_rows: int = DEFAULT_TRAIN_WINDOW_ROWS,
    test_window_rows: int = DEFAULT_TEST_WINDOW_ROWS,
    step_rows: int = DEFAULT_STEP_ROWS,
    min_test_rows: int = DEFAULT_MIN_TEST_ROWS,
) -> list[WalkForwardWindow]:
    if total_rows <= 0:
        raise ValueError("total_rows must be positive.")
    if train_window_rows <= 0 or test_window_rows <= 0 or step_rows <= 0 or min_test_rows <= 0:
        raise ValueError("walk-forward window sizes must be positive.")
    if step_rows < test_window_rows:
        raise ValueError("step_rows must be >= test_window_rows to avoid overlapping test slices.")
    if train_window_rows + min_test_rows > total_rows:
        raise ValueError("Dataset is too small for the configured walk-forward windows.")

    windows: list[WalkForwardWindow] = []
    train_end_index = train_window_rows
    window_id = 1

    while train_end_index < total_rows:
        test_start_index = train_end_index
        test_end_index = min(test_start_index + test_window_rows, total_rows)
        if (test_end_index - test_start_index) < min_test_rows:
            break

        train_start_index = max(0, train_end_index - train_window_rows)
        windows.append(
            WalkForwardWindow(
                window_id=window_id,
                train_start_index=train_start_index,
                train_end_index=train_end_index,
                test_start_index=test_start_index,
                test_end_index=test_end_index,
            )
        )
        window_id += 1
        train_end_index += step_rows

    if not windows:
        raise ValueError("No valid walk-forward windows were generated.")
    return windows


def build_walk_forward_report(
    config: ProjectConfig = DEFAULT_CONFIG,
    train_window_rows: int = DEFAULT_TRAIN_WINDOW_ROWS,
    test_window_rows: int = DEFAULT_TEST_WINDOW_ROWS,
    step_rows: int = DEFAULT_STEP_ROWS,
    min_test_rows: int = DEFAULT_MIN_TEST_ROWS,
) -> dict[str, Path]:
    training_df = _load_or_build_training_dataset(config)
    feature_columns = get_feature_columns(training_df)
    windows = build_walk_forward_windows(
        total_rows=len(training_df),
        train_window_rows=train_window_rows,
        test_window_rows=test_window_rows,
        step_rows=step_rows,
        min_test_rows=min_test_rows,
    )

    predictions_frames: list[pd.DataFrame] = []
    head_metric_rows: list[dict[str, object]] = []
    window_mode_summary_frames: list[pd.DataFrame] = []

    for window in windows:
        train_df = training_df.iloc[window.train_start_index : window.train_end_index].copy().reset_index(drop=True)
        test_df = training_df.iloc[window.test_start_index : window.test_end_index].copy().reset_index(drop=True)
        window_predictions_df, window_head_metric_rows = _score_walk_forward_window(
            config=config,
            feature_columns=feature_columns,
            train_df=train_df,
            test_df=test_df,
            window=window,
        )
        predictions_frames.append(window_predictions_df)
        head_metric_rows.extend(window_head_metric_rows)

        window_mode_summary_df = build_mode_replay_summary(window_predictions_df)
        window_mode_summary_df.insert(0, "window_id", window.window_id)
        window_mode_summary_df.insert(1, "train_start_date", str(train_df.iloc[0]["date"]))
        window_mode_summary_df.insert(2, "train_end_date", str(train_df.iloc[-1]["date"]))
        window_mode_summary_df.insert(3, "test_start_date", str(test_df.iloc[0]["date"]))
        window_mode_summary_df.insert(4, "test_end_date", str(test_df.iloc[-1]["date"]))
        window_mode_summary_frames.append(window_mode_summary_df)

    predictions_df = pd.concat(predictions_frames, ignore_index=True)
    head_metrics_df = pd.DataFrame(head_metric_rows).sort_values(
        ["window_id", "head_name"]
    ).reset_index(drop=True)
    window_mode_summary_df = pd.concat(window_mode_summary_frames, ignore_index=True)
    mode_summary_df = build_mode_replay_summary(predictions_df)
    controller_interaction_df = build_controller_interaction_summary(predictions_df)

    save_dataframe(predictions_df, config.walk_forward_test_predictions_path)
    save_dataframe(head_metrics_df, config.walk_forward_head_metrics_path)
    save_dataframe(window_mode_summary_df, config.walk_forward_window_mode_summary_path)
    save_dataframe(mode_summary_df, config.walk_forward_mode_summary_path)
    save_dataframe(controller_interaction_df, config.walk_forward_controller_interaction_summary_path)

    LOGGER.info(
        "Saved walk-forward test predictions to: %s",
        config.walk_forward_test_predictions_path,
    )
    LOGGER.info(
        "Saved walk-forward head metrics to: %s",
        config.walk_forward_head_metrics_path,
    )
    LOGGER.info(
        "Saved walk-forward window mode summary to: %s",
        config.walk_forward_window_mode_summary_path,
    )
    LOGGER.info(
        "Saved walk-forward mode summary to: %s",
        config.walk_forward_mode_summary_path,
    )
    LOGGER.info(
        "Saved walk-forward controller interaction summary to: %s",
        config.walk_forward_controller_interaction_summary_path,
    )
    LOGGER.info(
        "Walk-forward windows=%s coverage=%s -> %s train_window_rows=%s test_window_rows=%s step_rows=%s",
        len(windows),
        predictions_df.iloc[0]["date"],
        predictions_df.iloc[-1]["date"],
        train_window_rows,
        test_window_rows,
        step_rows,
    )

    return {
        "walk_forward_test_predictions": config.walk_forward_test_predictions_path,
        "walk_forward_head_metrics": config.walk_forward_head_metrics_path,
        "walk_forward_window_mode_summary": config.walk_forward_window_mode_summary_path,
        "walk_forward_mode_summary": config.walk_forward_mode_summary_path,
        "walk_forward_controller_interaction_summary": config.walk_forward_controller_interaction_summary_path,
    }


def _load_or_build_training_dataset(config: ProjectConfig) -> pd.DataFrame:
    if config.training_dataset_path.exists():
        return pd.read_csv(config.training_dataset_path).sort_values("date").reset_index(drop=True)

    feature_df, label_df = _ensure_feature_and_label_outputs(config)
    training_df = build_training_dataset(feature_df, label_df)
    save_dataframe(training_df, config.training_dataset_path)
    return training_df


def _split_classifier_window(train_df: pd.DataFrame, validation_ratio: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if len(train_df) < 4:
        raise ValueError("Classifier walk-forward train window is too small for calibration.")
    try:
        return split_train_test(train_df, validation_ratio)
    except ValueError:
        split_index = max(1, len(train_df) - 1)
        return train_df.iloc[:split_index].copy(), train_df.iloc[split_index:].copy()


def _score_walk_forward_window(
    config: ProjectConfig,
    feature_columns: list[str],
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    window: WalkForwardWindow,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    X_train = train_df[feature_columns]
    X_test = test_df[feature_columns]
    classifier_train_df, classifier_validation_df = _split_classifier_window(
        train_df,
        config.recall_tuning.validation_ratio,
    )
    X_classifier_train = classifier_train_df[feature_columns]
    X_classifier_validation = classifier_validation_df[feature_columns]

    predictions_df = test_df[_build_prediction_output_columns(test_df)].copy().reset_index(drop=True)
    head_metric_rows: list[dict[str, object]] = []
    thresholds: dict[str, float] = {}

    for head_name, signal_field in REGRESSION_HEAD_TO_SIGNAL_FIELD.items():
        target_column = _head_target_column(head_name)
        model = build_xgb_regressor(config)
        model.fit(X_train, train_df[target_column])
        predictions = model.predict(X_test)
        predictions_df[signal_field] = predictions
        metrics = _evaluate_regression(test_df[target_column], predictions)
        head_metric_rows.append(
            {
                "window_id": window.window_id,
                "train_start_date": str(train_df.iloc[0]["date"]),
                "train_end_date": str(train_df.iloc[-1]["date"]),
                "test_start_date": str(test_df.iloc[0]["date"]),
                "test_end_date": str(test_df.iloc[-1]["date"]),
                "head_name": head_name,
                "head_type": "regression",
                "target_column": target_column,
                **metrics,
            }
        )

    for head_name, signal_field in CLASSIFICATION_HEAD_TO_SIGNAL_FIELD.items():
        target_column = _head_target_column(head_name)
        calibration_scale_pos_weight = _compute_scale_pos_weight(classifier_train_df[target_column])
        calibration_classifier = build_xgb_classifier(
            config,
            scale_pos_weight=calibration_scale_pos_weight,
        )
        calibration_classifier.fit(X_classifier_train, classifier_train_df[target_column])
        validation_probabilities = calibration_classifier.predict_proba(X_classifier_validation)[:, 1]
        threshold_calibration = _select_decision_threshold(
            head_name=head_name,
            y_true=classifier_validation_df[target_column],
            probabilities=validation_probabilities,
            config=config,
        )

        scale_pos_weight = _compute_scale_pos_weight(train_df[target_column])
        classifier = build_xgb_classifier(config, scale_pos_weight=scale_pos_weight)
        classifier.fit(X_train, train_df[target_column])
        probabilities = classifier.predict_proba(X_test)[:, 1]
        predictions_df[signal_field] = probabilities

        default_metrics = _evaluate_classification(
            test_df[target_column],
            probabilities,
            beta=float(threshold_calibration["selection_beta"]),
        )
        recommended_threshold = float(threshold_calibration["selected_threshold"])
        recommended_metrics = _evaluate_classification(
            test_df[target_column],
            probabilities,
            threshold=recommended_threshold,
            beta=float(threshold_calibration["selection_beta"]),
        )
        thresholds[signal_field] = recommended_threshold

        head_metric_rows.append(
            {
                "window_id": window.window_id,
                "train_start_date": str(train_df.iloc[0]["date"]),
                "train_end_date": str(train_df.iloc[-1]["date"]),
                "test_start_date": str(test_df.iloc[0]["date"]),
                "test_end_date": str(test_df.iloc[-1]["date"]),
                "head_name": head_name,
                "head_type": "classification",
                "target_column": target_column,
                "recommended_threshold": recommended_threshold,
                "calibration_scale_pos_weight": float(calibration_scale_pos_weight),
                "scale_pos_weight": float(scale_pos_weight),
                **{f"default_{key}": value for key, value in default_metrics.items()},
                **{f"recommended_{key}": value for key, value in recommended_metrics.items()},
            }
        )

    for signal_field, threshold in thresholds.items():
        predictions_df[f"{signal_field}_threshold"] = threshold
        predictions_df[f"{signal_field}_on"] = predictions_df[signal_field] >= threshold

    runtime_controls_records = []
    prediction_fields = list(REGRESSION_HEAD_TO_SIGNAL_FIELD.values()) + list(CLASSIFICATION_HEAD_TO_SIGNAL_FIELD.values())
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
    predictions_df.insert(0, "window_id", window.window_id)
    predictions_df.insert(1, "train_start_date", str(train_df.iloc[0]["date"]))
    predictions_df.insert(2, "train_end_date", str(train_df.iloc[-1]["date"]))
    predictions_df.insert(3, "test_start_date", str(test_df.iloc[0]["date"]))
    predictions_df.insert(4, "test_end_date", str(test_df.iloc[-1]["date"]))
    return predictions_df, head_metric_rows


def _build_prediction_output_columns(test_df: pd.DataFrame) -> list[str]:
    output_columns = [
        "date",
        "next_date",
        "target_upside_t1",
        "target_downside_t1",
        "target_grid_pnl_t1",
        "target_positive_grid_day_t1",
        "target_tradable_score_t1",
        "target_trend_break_risk_t1",
        "target_hostile_selloff_risk_t1",
        "target_vwap_reversion_t1",
    ]
    existing_output_columns = set(output_columns)
    output_columns.extend(
        column
        for column in DOWNSIDE_CONTEXT_COLUMNS
        if column in test_df.columns and column not in existing_output_columns
    )
    return output_columns


def _head_target_column(head_name: str) -> str:
    mapping = {
        "upside_regression": "target_upside_t1",
        "downside_regression": "target_downside_t1",
        "grid_pnl_regression": "target_grid_pnl_t1",
        "positive_grid_day_classifier": "target_positive_grid_day_t1",
        "tradable_classifier": "target_tradable_score_t1",
        "trend_break_risk_classifier": "target_trend_break_risk_t1",
        "hostile_selloff_risk_classifier": "target_hostile_selloff_risk_t1",
        "vwap_reversion_classifier": "target_vwap_reversion_t1",
    }
    return mapping[head_name]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run rolling walk-forward evaluation on the current training dataset.")
    parser.add_argument("--train-window-rows", type=int, default=DEFAULT_TRAIN_WINDOW_ROWS)
    parser.add_argument("--test-window-rows", type=int, default=DEFAULT_TEST_WINDOW_ROWS)
    parser.add_argument("--step-rows", type=int, default=DEFAULT_STEP_ROWS)
    parser.add_argument("--min-test-rows", type=int, default=DEFAULT_MIN_TEST_ROWS)
    return parser


def main() -> None:
    configure_foundation_logging()
    args = build_parser().parse_args()
    build_walk_forward_report(
        config=DEFAULT_CONFIG,
        train_window_rows=args.train_window_rows,
        test_window_rows=args.test_window_rows,
        step_rows=args.step_rows,
        min_test_rows=args.min_test_rows,
    )


if __name__ == "__main__":
    main()

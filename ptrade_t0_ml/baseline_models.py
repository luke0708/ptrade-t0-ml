from __future__ import annotations

import argparse
import logging
import math
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)

from .config import DEFAULT_CONFIG, ProjectConfig
from .feature_engine import run_feature_engine
from .io_utils import atomic_write_json, save_dataframe
from .label_engine import run_label_engine
from .minute_foundation import configure_logging as configure_foundation_logging

LOGGER = logging.getLogger(__name__)

EXCLUDED_FEATURE_COLUMNS = {
    "date",
    "next_date",
}

EXCLUDED_FEATURE_PREFIXES = (
    "next_day_",
    "target_",
    "replay_",
)

CLASSIFICATION_HEAD_RULES = {
    "positive_grid_day_classifier": {
        "beta": 1.5,
        "min_precision_floor": 0.25,
        "max_positive_rate_multiplier": 1.75,
    },
    "tradable_classifier": {
        "beta": 1.5,
        "min_precision_floor": 0.25,
        "max_positive_rate_multiplier": 1.75,
    },
    "trend_break_risk_classifier": {
        "beta": 3.0,
        "min_precision_floor": 0.10,
        "max_positive_rate_multiplier": 3.00,
    },
    "vwap_reversion_classifier": {
        "beta": 1.5,
        "min_precision_floor": 0.20,
        "max_positive_rate_multiplier": 1.80,
    },
}


def split_train_test(df: pd.DataFrame, test_ratio: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not 0 < test_ratio < 1:
        raise ValueError("test_ratio must be between 0 and 1.")
    split_index = int(len(df) * (1 - test_ratio))
    if split_index <= 0 or split_index >= len(df):
        raise ValueError("Dataset is too small for the configured train/test split.")
    return df.iloc[:split_index].copy(), df.iloc[split_index:].copy()


def _ensure_feature_and_label_outputs(config: ProjectConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not config.feature_table_path.exists():
        LOGGER.info("Feature table missing. Rebuilding feature engine outputs first.")
        run_feature_engine(config)
    if not config.label_targets_path.exists():
        LOGGER.info("Label targets missing. Rebuilding label engine outputs first.")
        run_label_engine(config)
    feature_df = pd.read_csv(config.feature_table_path)
    label_df = pd.read_csv(config.label_targets_path)
    return feature_df, label_df


def build_training_dataset(
    feature_df: pd.DataFrame,
    label_df: pd.DataFrame,
) -> pd.DataFrame:
    label_columns = [
        column
        for column in label_df.columns
        if column == "date"
        or column == "next_date"
        or column.startswith("target_")
        or column.startswith("replay_")
        or column.startswith("next_day_")
    ]
    merged_df = feature_df.merge(label_df[label_columns], on="date", how="inner", validate="one_to_one")
    merged_df = merged_df.sort_values("date").reset_index(drop=True)
    return merged_df


def get_feature_columns(training_df: pd.DataFrame) -> list[str]:
    return [
        column
        for column in training_df.columns
        if column not in EXCLUDED_FEATURE_COLUMNS
        and not any(column.startswith(prefix) for prefix in EXCLUDED_FEATURE_PREFIXES)
    ]


def build_xgb_regressor(config: ProjectConfig):
    try:
        from xgboost import XGBRegressor
    except ImportError as exc:
        raise ImportError("xgboost is required. Install dependencies with `pip install -r requirements.txt`.") from exc

    return XGBRegressor(
        max_depth=config.model_params.max_depth,
        learning_rate=config.model_params.learning_rate,
        n_estimators=max(config.model_params.n_estimators, 300),
        subsample=config.model_params.subsample,
        colsample_bytree=config.model_params.colsample_bytree,
        random_state=config.model_params.random_state,
        n_jobs=config.model_params.n_jobs,
        objective="reg:squarederror",
        eval_metric="rmse",
    )


def build_xgb_classifier(config: ProjectConfig, scale_pos_weight: float):
    try:
        from xgboost import XGBClassifier
    except ImportError as exc:
        raise ImportError("xgboost is required. Install dependencies with `pip install -r requirements.txt`.") from exc

    return XGBClassifier(
        max_depth=config.model_params.max_depth,
        learning_rate=config.model_params.learning_rate,
        n_estimators=max(config.model_params.n_estimators, 300),
        subsample=config.model_params.subsample,
        colsample_bytree=config.model_params.colsample_bytree,
        random_state=config.model_params.random_state,
        n_jobs=config.model_params.n_jobs,
        objective="binary:logistic",
        eval_metric=["logloss", "aucpr"],
        scale_pos_weight=scale_pos_weight,
        max_delta_step=1,
    )


def _evaluate_regression(y_true: pd.Series, predictions: np.ndarray) -> dict[str, float]:
    series_true = pd.Series(y_true).reset_index(drop=True)
    series_pred = pd.Series(predictions).reset_index(drop=True)
    top_quintile_threshold = series_pred.quantile(0.8)
    top_quintile_mask = series_pred >= top_quintile_threshold
    bottom_quintile_threshold = series_pred.quantile(0.2)
    bottom_quintile_mask = series_pred <= bottom_quintile_threshold
    return {
        "mae": float(mean_absolute_error(series_true, series_pred)),
        "rmse": float(math.sqrt(mean_squared_error(series_true, series_pred))),
        "r2": float(r2_score(series_true, series_pred)),
        "spearman_rank_corr": float(series_true.corr(series_pred, method="spearman")),
        "top_quintile_actual_mean": float(series_true[top_quintile_mask].mean()),
        "bottom_quintile_actual_mean": float(series_true[bottom_quintile_mask].mean()),
    }


def _compute_f_beta(precision: float, recall: float, beta: float) -> float:
    beta_sq = beta**2
    denominator = (beta_sq * precision) + recall
    if denominator <= 0:
        return 0.0
    return float(((1 + beta_sq) * precision * recall) / denominator)


def _evaluate_classification(
    y_true: pd.Series,
    probabilities: np.ndarray,
    threshold: float = 0.5,
    beta: float = 1.0,
) -> dict[str, float]:
    predictions = (probabilities >= threshold).astype(int)
    precision = float(precision_score(y_true, predictions, zero_division=0))
    recall = float(recall_score(y_true, predictions, zero_division=0))
    label_positive_rate = float(pd.Series(y_true).mean())
    unique_labels = np.unique(y_true)
    metrics = {
        "threshold": float(threshold),
        "accuracy": float(accuracy_score(y_true, predictions)),
        "precision": precision,
        "recall": recall,
        "f1_score": float(f1_score(y_true, predictions, zero_division=0)),
        "f_beta_score": _compute_f_beta(precision, recall, beta=beta),
        "f_beta_beta": float(beta),
        "positive_rate": float(predictions.mean()),
        "label_positive_rate": label_positive_rate,
    }
    if len(unique_labels) > 1:
        metrics["average_precision"] = float(average_precision_score(y_true, probabilities))
        metrics["roc_auc"] = float(roc_auc_score(y_true, probabilities))
    else:
        metrics["average_precision"] = 1.0 if int(unique_labels[0]) == 1 else 0.0
    return metrics


def _compute_scale_pos_weight(y_train: pd.Series) -> float:
    positives = int((y_train == 1).sum())
    negatives = int((y_train == 0).sum())
    if positives == 0:
        return 1.0
    return max(1.0, negatives / positives)


def _select_decision_threshold(
    head_name: str,
    y_true: pd.Series,
    probabilities: np.ndarray,
    config: ProjectConfig,
) -> dict[str, object]:
    label_positive_rate = float(pd.Series(y_true).mean())
    if label_positive_rate <= 0.0 or label_positive_rate >= 1.0:
        fallback_metrics = _evaluate_classification(
            y_true,
            probabilities,
            threshold=0.5,
            beta=float(CLASSIFICATION_HEAD_RULES.get(head_name, {}).get("beta", config.recall_tuning.ranking_beta)),
        )
        return {
            "selection_metric": "degenerate_validation_fallback",
            "selection_beta": float(CLASSIFICATION_HEAD_RULES.get(head_name, {}).get("beta", config.recall_tuning.ranking_beta)),
            "validation_rows": int(len(y_true)),
            "label_positive_rate": label_positive_rate,
            "min_precision_required": 0.0,
            "max_positive_rate_allowed": 1.0,
            "selected_threshold": 0.5,
            "selected_threshold_metrics": {
                **fallback_metrics,
                "meets_constraints": False,
            },
            "threshold_grid_metrics": [
                {
                    **fallback_metrics,
                    "meets_constraints": False,
                }
            ],
            "fallback_reason": "validation_has_single_class",
        }

    rules = CLASSIFICATION_HEAD_RULES.get(head_name, {})
    beta = float(rules.get("beta", config.recall_tuning.ranking_beta))
    min_precision_required = max(float(rules.get("min_precision_floor", 0.0)), label_positive_rate * 0.75)
    max_positive_rate_allowed = max(
        label_positive_rate * float(rules.get("max_positive_rate_multiplier", 2.0)),
        label_positive_rate + 0.05,
    )
    threshold_grid = sorted(set(float(value) for value in config.recall_tuning.decision_thresholds + (0.5,)))
    threshold_metrics: list[dict[str, float | bool]] = []
    best_rank: tuple[float, ...] | None = None
    best_metrics: dict[str, float | bool] | None = None

    for threshold in threshold_grid:
        metrics = _evaluate_classification(y_true, probabilities, threshold=threshold, beta=beta)
        meets_constraints = (
            metrics["precision"] >= min_precision_required
            and metrics["positive_rate"] <= max_positive_rate_allowed
        )
        threshold_record: dict[str, float | bool] = {
            **metrics,
            "meets_constraints": bool(meets_constraints),
        }
        threshold_metrics.append(threshold_record)
        rank = (
            1.0 if meets_constraints else 0.0,
            float(metrics["f_beta_score"]),
            float(metrics["recall"]),
            float(metrics["precision"]),
            -abs(float(metrics["positive_rate"]) - label_positive_rate),
            float(metrics["threshold"]),
        )
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best_metrics = threshold_record

    if best_metrics is None:
        raise ValueError(f"Unable to calibrate threshold for {head_name}.")

    return {
        "selection_metric": "f_beta_score",
        "selection_beta": beta,
        "validation_rows": int(len(y_true)),
        "label_positive_rate": label_positive_rate,
        "min_precision_required": float(min_precision_required),
        "max_positive_rate_allowed": float(max_positive_rate_allowed),
        "selected_threshold": float(best_metrics["threshold"]),
        "selected_threshold_metrics": best_metrics,
        "threshold_grid_metrics": threshold_metrics,
    }


def train_baseline_models(config: ProjectConfig = DEFAULT_CONFIG) -> dict[str, object]:
    feature_df, label_df = _ensure_feature_and_label_outputs(config)
    training_df = build_training_dataset(feature_df, label_df)
    save_dataframe(training_df, config.training_dataset_path)

    feature_columns = get_feature_columns(training_df)
    train_df, test_df = split_train_test(training_df, config.test_ratio)
    classifier_train_df, classifier_validation_df = split_train_test(train_df, config.recall_tuning.validation_ratio)
    X_train = train_df[feature_columns]
    X_test = test_df[feature_columns]
    X_classifier_train = classifier_train_df[feature_columns]
    X_classifier_validation = classifier_validation_df[feature_columns]

    config.baseline_models_dir.mkdir(parents=True, exist_ok=True)
    heads: dict[str, object] = {}

    regression_targets = {
        "upside_regression": "target_upside_t1",
        "downside_regression": "target_downside_t1",
        "grid_pnl_regression": "target_grid_pnl_t1",
    }
    for head_name, target_column in regression_targets.items():
        model = build_xgb_regressor(config)
        model.fit(X_train, train_df[target_column])
        predictions = model.predict(X_test)
        model_path = config.baseline_models_dir / f"{head_name}.json"
        model.save_model(model_path)
        heads[head_name] = {
            "target_column": target_column,
            "model_path": str(model_path),
            "metrics": _evaluate_regression(test_df[target_column], predictions),
        }

    classification_targets = {
        "positive_grid_day_classifier": "target_positive_grid_day_t1",
        "tradable_classifier": "target_tradable_score_t1",
        "trend_break_risk_classifier": "target_trend_break_risk_t1",
        "vwap_reversion_classifier": "target_vwap_reversion_t1",
    }
    for head_name, target_column in classification_targets.items():
        calibration_scale_pos_weight = _compute_scale_pos_weight(classifier_train_df[target_column])
        calibration_classifier = build_xgb_classifier(config, scale_pos_weight=calibration_scale_pos_weight)
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
        classifier_probabilities = classifier.predict_proba(X_test)[:, 1]
        classifier_path = config.baseline_models_dir / f"{head_name}.json"
        classifier.save_model(classifier_path)
        beta = float(threshold_calibration["selection_beta"])
        recommended_threshold = float(threshold_calibration["selected_threshold"])
        heads[head_name] = {
            "target_column": target_column,
            "model_path": str(classifier_path),
            "scale_pos_weight": float(scale_pos_weight),
            "calibration_scale_pos_weight": float(calibration_scale_pos_weight),
            "metrics": _evaluate_classification(test_df[target_column], classifier_probabilities, beta=beta),
            "recommended_threshold": recommended_threshold,
            "recommended_threshold_metrics": _evaluate_classification(
                test_df[target_column],
                classifier_probabilities,
                threshold=recommended_threshold,
                beta=beta,
            ),
            "threshold_calibration": threshold_calibration,
        }

    metadata = {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "training_dataset_path": str(config.training_dataset_path),
        "feature_table_path": str(config.feature_table_path),
        "label_targets_path": str(config.label_targets_path),
        "feature_columns": feature_columns,
        "feature_column_count": int(len(feature_columns)),
        "training_rows": int(len(training_df)),
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "classifier_train_rows": int(len(classifier_train_df)),
        "classifier_validation_rows": int(len(classifier_validation_df)),
        "test_start_date": str(test_df.iloc[0]["date"]),
        "test_end_date": str(test_df.iloc[-1]["date"]),
        "model_params": asdict(config.model_params),
        "heads": heads,
    }
    atomic_write_json(config.baseline_metadata_path, metadata)

    LOGGER.info("Saved merged training dataset to: %s", config.training_dataset_path)
    LOGGER.info("Saved baseline metadata to: %s", config.baseline_metadata_path)
    LOGGER.info(
        "Baseline train/test split: train_rows=%s test_rows=%s test_range=%s -> %s",
        metadata["train_rows"],
        metadata["test_rows"],
        metadata["test_start_date"],
        metadata["test_end_date"],
    )
    return metadata


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Train stock-only baseline models on the current feature/label slice.")


def main() -> None:
    configure_foundation_logging()
    build_parser().parse_args()
    train_baseline_models(DEFAULT_CONFIG)


if __name__ == "__main__":
    main()

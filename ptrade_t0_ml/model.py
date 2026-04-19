from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import matplotlib
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, fbeta_score, precision_score, recall_score

from .config import DEFAULT_CONFIG, ProjectConfig
from .features import get_feature_columns
from .io_utils import atomic_write_json

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def split_train_test(df: pd.DataFrame, test_ratio: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not 0 < test_ratio < 1:
        raise ValueError("test_ratio must be between 0 and 1.")
    split_index = int(len(df) * (1 - test_ratio))
    if split_index <= 0 or split_index >= len(df):
        raise ValueError("Dataset is too small for the configured train/test split.")
    train_df = df.iloc[:split_index].copy()
    test_df = df.iloc[split_index:].copy()
    return train_df, test_df


def compute_scale_pos_weight(y: pd.Series) -> float:
    positives = int((y == 1).sum())
    negatives = int((y == 0).sum())
    if positives == 0:
        raise ValueError("Training set contains no positive samples; cannot train classifier.")
    return negatives / positives if negatives > 0 else 1.0


def build_xgb_classifier(config: ProjectConfig, scale_pos_weight: float):
    try:
        from xgboost import XGBClassifier
    except ImportError as exc:
        raise ImportError("xgboost is required. Install dependencies with `pip install -r requirements.txt`.") from exc

    return XGBClassifier(
        max_depth=config.model_params.max_depth,
        learning_rate=config.model_params.learning_rate,
        n_estimators=config.model_params.n_estimators,
        subsample=config.model_params.subsample,
        colsample_bytree=config.model_params.colsample_bytree,
        random_state=config.model_params.random_state,
        n_jobs=config.model_params.n_jobs,
        objective="binary:logistic",
        eval_metric=["logloss", "aucpr"],
        scale_pos_weight=scale_pos_weight,
        max_delta_step=1,
    )


def train_xgb_classifier(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    config: ProjectConfig,
    scale_pos_weight: float | None = None,
):
    effective_scale_pos_weight = scale_pos_weight or compute_scale_pos_weight(y_train)
    model = build_xgb_classifier(config=config, scale_pos_weight=effective_scale_pos_weight)
    model.fit(X_train, y_train)
    return model


def evaluate_classifier(model, X_test: pd.DataFrame, y_test: pd.Series, threshold: float = 0.5) -> dict[str, object]:
    probabilities = model.predict_proba(X_test)[:, 1]
    predictions = (probabilities >= threshold).astype(int)
    metrics = {
        "threshold": threshold,
        "accuracy": accuracy_score(y_test, predictions),
        "precision": precision_score(y_test, predictions, zero_division=0),
        "recall": recall_score(y_test, predictions, zero_division=0),
        "f1_score": f1_score(y_test, predictions, zero_division=0),
        "f2_score": fbeta_score(y_test, predictions, beta=2.0, zero_division=0),
        "confusion_matrix": confusion_matrix(y_test, predictions).tolist(),
        "test_rows": int(len(y_test)),
        "predicted_positive_count": int(predictions.sum()),
        "average_probability": float(probabilities.mean()),
    }
    return metrics


def choose_recall_focused_strategy(
    train_df: pd.DataFrame,
    feature_columns: list[str],
    config: ProjectConfig,
) -> dict[str, object]:
    tuning = config.recall_tuning
    fit_df, validation_df = split_train_test(train_df, tuning.validation_ratio)
    X_fit = fit_df[feature_columns]
    y_fit = fit_df["target"]
    X_validation = validation_df[feature_columns]
    y_validation = validation_df["target"]

    base_scale_pos_weight = max(1.0, compute_scale_pos_weight(y_fit))
    candidates: list[dict[str, object]] = []
    for multiplier in tuning.positive_weight_multipliers:
        selected_scale_pos_weight = base_scale_pos_weight * multiplier
        model = train_xgb_classifier(
            X_fit,
            y_fit,
            config=config,
            scale_pos_weight=selected_scale_pos_weight,
        )
        probabilities = model.predict_proba(X_validation)[:, 1]
        for threshold in tuning.decision_thresholds:
            predictions = (probabilities >= threshold).astype(int)
            precision = precision_score(y_validation, predictions, zero_division=0)
            recall = recall_score(y_validation, predictions, zero_division=0)
            f1 = f1_score(y_validation, predictions, zero_division=0)
            f2 = fbeta_score(y_validation, predictions, beta=tuning.ranking_beta, zero_division=0)
            candidates.append(
                {
                    "positive_weight_multiplier": float(multiplier),
                    "scale_pos_weight": float(selected_scale_pos_weight),
                    "threshold": float(threshold),
                    "precision": float(precision),
                    "recall": float(recall),
                    "f1_score": float(f1),
                    "f2_score": float(f2),
                    "predicted_positive_count": int(predictions.sum()),
                    "average_probability": float(probabilities.mean()),
                }
            )

    eligible = [candidate for candidate in candidates if candidate["recall"] >= tuning.min_recall_target]
    if eligible:
        ranked_candidates = sorted(
            eligible,
            key=lambda candidate: (
                candidate["f2_score"],
                candidate["f1_score"],
                candidate["precision"],
                -candidate["positive_weight_multiplier"],
            ),
            reverse=True,
        )
    else:
        ranked_candidates = sorted(
            candidates,
            key=lambda candidate: (
                candidate["recall"],
                candidate["f2_score"],
                candidate["precision"],
                -candidate["positive_weight_multiplier"],
            ),
            reverse=True,
        )

    best_candidate = ranked_candidates[0]
    return {
        "base_scale_pos_weight": float(base_scale_pos_weight),
        "selected_positive_weight_multiplier": best_candidate["positive_weight_multiplier"],
        "selected_scale_pos_weight": best_candidate["scale_pos_weight"],
        "selected_threshold": best_candidate["threshold"],
        "validation_metrics": {
            "precision": best_candidate["precision"],
            "recall": best_candidate["recall"],
            "f1_score": best_candidate["f1_score"],
            "f2_score": best_candidate["f2_score"],
            "predicted_positive_count": best_candidate["predicted_positive_count"],
            "average_probability": best_candidate["average_probability"],
        },
    }


def save_feature_importance_plot(model, feature_columns: list[str], output_path: Path) -> None:
    importances = pd.Series(model.feature_importances_, index=feature_columns)
    top_features = importances.sort_values(ascending=False).head(10).sort_values(ascending=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 6))
    top_features.plot(kind="barh", ax=ax, color="#1f77b4")
    ax.set_title("Top 10 Feature Importances")
    ax.set_xlabel("Importance")
    ax.set_ylabel("Feature")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def train_and_evaluate(config: ProjectConfig = DEFAULT_CONFIG) -> dict[str, object]:
    df = pd.read_csv(config.labeled_data_path)
    if "target" not in df.columns:
        raise ValueError("Labeled dataset must include a target column.")

    feature_columns = [column for column in get_feature_columns(df) if column != "date"]
    train_df, test_df = split_train_test(df, test_ratio=config.test_ratio)

    X_train = train_df[feature_columns]
    y_train = train_df["target"]
    X_test = test_df[feature_columns]
    y_test = test_df["target"]

    strategy = choose_recall_focused_strategy(train_df, feature_columns, config=config)
    model = train_xgb_classifier(
        X_train,
        y_train,
        config=config,
        scale_pos_weight=float(strategy["selected_scale_pos_weight"]),
    )
    metrics = evaluate_classifier(
        model,
        X_test,
        y_test,
        threshold=float(strategy["selected_threshold"]),
    )
    baseline_metrics = evaluate_classifier(model, X_test, y_test, threshold=0.5)

    config.models_dir.mkdir(parents=True, exist_ok=True)
    model.save_model(config.model_path)
    save_feature_importance_plot(model, feature_columns, config.feature_importance_plot_path)

    metadata = {
        "stock_code": config.stock_code,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "feature_columns": feature_columns,
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "label_thresholds": asdict(config.label_thresholds),
        "model_params": asdict(config.model_params),
        "recall_tuning": asdict(config.recall_tuning),
        "selected_strategy": strategy,
        "metrics": metrics,
        "baseline_metrics_at_0_5": baseline_metrics,
    }
    atomic_write_json(config.model_metadata_path, metadata)

    print("Saved model to:", config.model_path)
    print("Saved model metadata to:", config.model_metadata_path)
    print("Saved feature importance plot to:", config.feature_importance_plot_path)
    print(
        "Selected recall-focused strategy:",
        {
            "positive_weight_multiplier": strategy["selected_positive_weight_multiplier"],
            "scale_pos_weight": strategy["selected_scale_pos_weight"],
            "threshold": strategy["selected_threshold"],
        },
    )
    print("Accuracy:", f"{metrics['accuracy']:.4f}")
    print("Precision:", f"{metrics['precision']:.4f}")
    print("Recall:", f"{metrics['recall']:.4f}")
    print("F1-Score:", f"{metrics['f1_score']:.4f}")
    print("F2-Score:", f"{metrics['f2_score']:.4f}")
    print("Confusion Matrix:")
    print(metrics["confusion_matrix"])
    return metadata


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Train and evaluate the XGBoost T+0 classifier.")


def main() -> None:
    build_parser().parse_args()
    train_and_evaluate(DEFAULT_CONFIG)


if __name__ == "__main__":
    main()

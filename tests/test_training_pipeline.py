import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ptrade_t0_ml.config import ProjectConfig
from ptrade_t0_ml.model import choose_recall_focused_strategy, evaluate_classifier, train_xgb_classifier


class TrainingPipelineTests(unittest.TestCase):
    def test_train_xgb_classifier_and_evaluate(self) -> None:
        rng = np.random.default_rng(42)
        rows = 80
        X = pd.DataFrame(
            {
                "open": rng.normal(10, 1, rows),
                "high": rng.normal(10.2, 1, rows),
                "low": rng.normal(9.8, 1, rows),
                "close": rng.normal(10, 1, rows),
                "volume": rng.integers(1_000_000, 2_000_000, rows),
                "amount": rng.normal(12_000_000, 500_000, rows),
                "pre_close": rng.normal(10, 1, rows),
                "rsi_14": rng.uniform(20, 80, rows),
                "macd_hist_12_26_9": rng.normal(0, 1, rows),
                "atr_14": rng.uniform(0.1, 0.8, rows),
                "bb_width_20_2": rng.uniform(1.0, 10.0, rows),
                "sma_20": rng.normal(10, 1, rows),
                "sma_60": rng.normal(10, 1, rows),
                "close_to_sma20": rng.normal(0, 0.05, rows),
                "volume_sma_5": rng.normal(1_300_000, 50_000, rows),
                "volume_sma_20": rng.normal(1_250_000, 50_000, rows),
                "turnover_proxy": rng.normal(15_000_000, 1_000_000, rows),
                "daily_amplitude": rng.uniform(0.01, 0.08, rows),
                "gap_pct": rng.normal(0, 0.02, rows),
            }
        )
        y = pd.Series(([0] * 50) + ([1] * 30))

        with tempfile.TemporaryDirectory() as temp_dir:
            config = ProjectConfig(base_dir=Path(temp_dir))
            model = train_xgb_classifier(X.iloc[:60], y.iloc[:60], config=config)
            metrics = evaluate_classifier(model, X.iloc[60:], y.iloc[60:])

        self.assertIn("accuracy", metrics)
        self.assertIn("precision", metrics)
        self.assertIn("recall", metrics)
        self.assertIn("f1_score", metrics)
        self.assertIn("f2_score", metrics)
        self.assertIn("confusion_matrix", metrics)
        self.assertGreaterEqual(metrics["accuracy"], 0.0)
        self.assertLessEqual(metrics["accuracy"], 1.0)

    def test_choose_recall_focused_strategy_returns_threshold_and_weighting(self) -> None:
        rng = np.random.default_rng(7)
        rows = 140
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=rows, freq="B").strftime("%Y-%m-%d"),
                "open": rng.normal(10, 1, rows),
                "high": rng.normal(10.3, 1, rows),
                "low": rng.normal(9.7, 1, rows),
                "close": rng.normal(10, 1, rows),
                "volume": rng.integers(1_000_000, 2_000_000, rows),
                "amount": rng.normal(12_000_000, 500_000, rows),
                "pre_close": rng.normal(10, 1, rows),
                "rsi_14": rng.uniform(20, 80, rows),
                "macd_hist_12_26_9": rng.normal(0, 1, rows),
                "atr_14": rng.uniform(0.1, 0.8, rows),
                "bb_width_20_2": rng.uniform(1.0, 10.0, rows),
                "sma_20": rng.normal(10, 1, rows),
                "sma_60": rng.normal(10, 1, rows),
                "close_to_sma20": rng.normal(0, 0.05, rows),
                "volume_sma_5": rng.normal(1_300_000, 50_000, rows),
                "volume_sma_20": rng.normal(1_250_000, 50_000, rows),
                "turnover_proxy": rng.normal(15_000_000, 1_000_000, rows),
                "daily_amplitude": rng.uniform(0.01, 0.08, rows),
                "gap_pct": rng.normal(0, 0.02, rows),
                "target": ([0] * 70) + ([1] * 70),
            }
        )
        feature_columns = [column for column in df.columns if column not in {"date", "target"}]

        with tempfile.TemporaryDirectory() as temp_dir:
            config = ProjectConfig(base_dir=Path(temp_dir))
            strategy = choose_recall_focused_strategy(df, feature_columns, config=config)

        self.assertIn("selected_threshold", strategy)
        self.assertIn("selected_scale_pos_weight", strategy)
        self.assertIn("validation_metrics", strategy)
        self.assertGreaterEqual(strategy["selected_scale_pos_weight"], 1.0)


if __name__ == "__main__":
    unittest.main()

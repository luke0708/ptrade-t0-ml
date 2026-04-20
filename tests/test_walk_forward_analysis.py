import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from ptrade_t0_ml.config import ProjectConfig
from ptrade_t0_ml.walk_forward_analysis import (
    build_walk_forward_report,
    build_walk_forward_windows,
)


class _FakeRegressor:
    def fit(self, X: pd.DataFrame, y: pd.Series) -> "_FakeRegressor":
        self.bias = float(pd.Series(y).mean())
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        feature = pd.Series(X.iloc[:, 0], dtype="float64").fillna(0.0)
        return (feature * 0.01 + self.bias * 0.1).to_numpy()


class _FakeClassifier:
    def fit(self, X: pd.DataFrame, y: pd.Series) -> "_FakeClassifier":
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        feature = pd.Series(X.iloc[:, 0], dtype="float64").fillna(0.0)
        probabilities = (0.20 + feature * 0.05).clip(0.05, 0.95).to_numpy()
        return np.column_stack([1.0 - probabilities, probabilities])


class WalkForwardAnalysisTests(unittest.TestCase):
    def test_build_walk_forward_windows_uses_non_overlapping_test_slices(self) -> None:
        windows = build_walk_forward_windows(
            total_rows=12,
            train_window_rows=6,
            test_window_rows=2,
            step_rows=2,
            min_test_rows=2,
        )

        self.assertEqual(len(windows), 3)
        self.assertEqual(windows[0].train_start_index, 0)
        self.assertEqual(windows[0].train_end_index, 6)
        self.assertEqual(windows[0].test_start_index, 6)
        self.assertEqual(windows[0].test_end_index, 8)
        self.assertEqual(windows[1].train_start_index, 2)
        self.assertEqual(windows[1].train_end_index, 8)
        self.assertEqual(windows[1].test_start_index, 8)
        self.assertEqual(windows[1].test_end_index, 10)
        self.assertEqual(windows[2].train_start_index, 4)
        self.assertEqual(windows[2].train_end_index, 10)
        self.assertEqual(windows[2].test_start_index, 10)
        self.assertEqual(windows[2].test_end_index, 12)

    def test_build_walk_forward_report_writes_expected_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            foundation_dir = base_dir / "data" / "foundation"
            foundation_dir.mkdir(parents=True, exist_ok=True)

            training_df = pd.DataFrame(
                {
                    "date": pd.date_range("2026-01-01", periods=12, freq="D").strftime("%Y-%m-%d"),
                    "next_date": pd.date_range("2026-01-02", periods=12, freq="D").strftime("%Y-%m-%d"),
                    "feature_a": [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.20],
                    "feature_b": [1.20, 1.10, 1.00, 0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10],
                    "grid_step_pct_t1": [0.012] * 12,
                    "target_upside_t1": [0.01, 0.015, 0.02, 0.01, 0.03, 0.025, 0.02, 0.03, 0.015, 0.01, 0.02, 0.03],
                    "target_downside_t1": [-0.02, -0.03, -0.01, -0.025, -0.015, -0.02, -0.03, -0.01, -0.02, -0.03, -0.015, -0.02],
                    "target_grid_pnl_t1": [-0.01, 0.0, 0.01, -0.02, 0.015, 0.005, -0.01, 0.01, -0.005, 0.0, 0.01, 0.02],
                    "target_positive_grid_day_t1": [0, 1, 0, 1, 1, 0, 1, 1, 0, 0, 1, 1],
                    "target_tradable_score_t1": [0, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1],
                    "target_trend_break_risk_t1": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
                    "target_hostile_selloff_risk_t1": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
                    "target_vwap_reversion_t1": [0, 1, 1, 0, 1, 0, 1, 1, 0, 0, 1, 1],
                }
            )
            training_df.to_csv(foundation_dir / "300661_SZ_training_dataset.csv", index=False)

            config = ProjectConfig(base_dir=base_dir)

            with (
                patch(
                    "ptrade_t0_ml.walk_forward_analysis.build_xgb_regressor",
                    side_effect=lambda _config: _FakeRegressor(),
                ),
                patch(
                    "ptrade_t0_ml.walk_forward_analysis.build_xgb_classifier",
                    side_effect=lambda _config, scale_pos_weight: _FakeClassifier(),
                ),
            ):
                outputs = build_walk_forward_report(
                    config=config,
                    train_window_rows=6,
                    test_window_rows=2,
                    step_rows=2,
                    min_test_rows=2,
                )

            for path in outputs.values():
                self.assertTrue(path.exists(), path)

            predictions_df = pd.read_csv(config.walk_forward_test_predictions_path)
            head_metrics_df = pd.read_csv(config.walk_forward_head_metrics_path)
            window_mode_df = pd.read_csv(config.walk_forward_window_mode_summary_path)
            mode_summary_df = pd.read_csv(config.walk_forward_mode_summary_path)
            controller_summary_df = pd.read_csv(config.walk_forward_controller_interaction_summary_path)

            self.assertEqual(len(predictions_df), 6)
            self.assertEqual(int(predictions_df["window_id"].nunique()), 3)
            self.assertIn("recommended_mode", predictions_df.columns)
            self.assertIn("signal_rationale", predictions_df.columns)
            self.assertEqual(len(head_metrics_df), 24)
            self.assertEqual(int(window_mode_df["window_id"].nunique()), 3)
            self.assertIn("ALL", set(mode_summary_df["segment_name"]))
            self.assertIn("pg_tr_on_hs_off", set(controller_summary_df["segment_name"]))


if __name__ == "__main__":
    unittest.main()

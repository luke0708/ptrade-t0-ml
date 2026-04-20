import unittest

import pandas as pd

from ptrade_t0_ml.baseline_models import (
    _select_decision_threshold,
    build_feature_leakage_audit,
    build_training_dataset,
    get_feature_columns,
    split_train_test,
)
from ptrade_t0_ml.config import DEFAULT_CONFIG


class BaselineModelTests(unittest.TestCase):
    def test_build_training_dataset_merges_on_date(self) -> None:
        feature_df = pd.DataFrame(
            {
                "date": ["2026-04-10", "2026-04-11"],
                "feature_a": [1.0, 2.0],
                "feature_b": [3.0, 4.0],
            }
        )
        label_df = pd.DataFrame(
            {
                "date": ["2026-04-10"],
                "next_date": ["2026-04-11"],
                "target_upside_t1": [0.1],
                "target_downside_t1": [-0.05],
                "target_grid_pnl_t1": [0.02],
                "target_tradable_score_t1": [1],
                "today_close": [10.0],
                "atr": [0.3],
            }
        )

        training_df = build_training_dataset(feature_df, label_df)

        self.assertEqual(len(training_df), 1)
        self.assertEqual(training_df.iloc[0]["date"], "2026-04-10")
        self.assertNotIn("today_close", training_df.columns)
        self.assertNotIn("atr", training_df.columns)

    def test_get_feature_columns_excludes_target_and_metadata_columns(self) -> None:
        training_df = pd.DataFrame(
            {
                "date": ["2026-04-10"],
                "next_date": ["2026-04-11"],
                "feature_a": [1.0],
                "feature_b": [2.0],
                "next_day_open": [10.5],
                "next_day_high": [10.8],
                "target_upside_t1": [0.1],
                "target_vwap_reversion_t1": [1],
                "target_trend_break_risk_t1": [0],
                "target_tradable_score_t1": [1],
                "replay_round_trips_t1": [2],
                "next_day_vwap_reversion_event_count": [3],
            }
        )

        feature_columns = get_feature_columns(training_df)

        self.assertEqual(feature_columns, ["feature_a", "feature_b"])

    def test_build_feature_leakage_audit_reports_excluded_columns_without_allowing_them_into_features(self) -> None:
        training_df = pd.DataFrame(
            {
                "date": ["2026-04-10"],
                "feature_a": [1.0],
                "next_date": ["2026-04-11"],
                "next_day_open": [10.5],
                "target_upside_t1": [0.1],
                "replay_round_trips_t1": [2],
            }
        )

        feature_columns = get_feature_columns(training_df)
        audit = build_feature_leakage_audit(training_df, feature_columns)

        self.assertEqual(feature_columns, ["feature_a"])
        self.assertTrue(audit["leakage_guard_passed"])
        self.assertEqual(audit["selected_feature_violations"], [])
        self.assertIn("next_day_open", audit["excluded_prefixed_columns_present"])
        self.assertIn("target_upside_t1", audit["excluded_prefixed_columns_present"])
        self.assertIn("replay_round_trips_t1", audit["excluded_prefixed_columns_present"])

    def test_split_train_test_keeps_order(self) -> None:
        df = pd.DataFrame({"date": [f"2026-04-{day:02d}" for day in range(1, 11)]})

        train_df, test_df = split_train_test(df, test_ratio=0.2)

        self.assertEqual(len(train_df), 8)
        self.assertEqual(len(test_df), 2)
        self.assertEqual(train_df.iloc[-1]["date"], "2026-04-08")
        self.assertEqual(test_df.iloc[0]["date"], "2026-04-09")

    def test_select_decision_threshold_prefers_recall_friendly_cutoff_for_sparse_head(self) -> None:
        y_true = pd.Series([0, 0, 1, 0, 1, 1, 0, 0])
        probabilities = pd.Series([0.10, 0.14, 0.24, 0.18, 0.31, 0.41, 0.12, 0.09])

        selection = _select_decision_threshold(
            head_name="trend_break_risk_classifier",
            y_true=y_true,
            probabilities=probabilities.to_numpy(),
            config=DEFAULT_CONFIG,
        )

        self.assertLess(selection["selected_threshold"], 0.5)
        self.assertGreaterEqual(selection["selected_threshold_metrics"]["recall"], 0.6)
        self.assertGreaterEqual(len(selection["threshold_grid_metrics"]), 5)

    def test_select_decision_threshold_falls_back_when_validation_has_single_class(self) -> None:
        y_true = pd.Series([0, 0, 0, 0])
        probabilities = pd.Series([0.05, 0.10, 0.12, 0.20])

        selection = _select_decision_threshold(
            head_name="trend_break_risk_classifier",
            y_true=y_true,
            probabilities=probabilities.to_numpy(),
            config=DEFAULT_CONFIG,
        )

        self.assertEqual(selection["selected_threshold"], 0.5)
        self.assertEqual(selection["fallback_reason"], "validation_has_single_class")
        self.assertEqual(selection["selected_threshold_metrics"]["average_precision"], 0.0)


if __name__ == "__main__":
    unittest.main()

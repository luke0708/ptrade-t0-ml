import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ptrade_t0_ml.config import ProjectConfig
from ptrade_t0_ml.walk_forward_failure_analysis import (
    build_failure_cohort_summary,
    build_failure_threshold_drift_summary,
    build_failure_window_summary,
    build_walk_forward_failure_report,
    select_failure_cases,
)


class WalkForwardFailureAnalysisTests(unittest.TestCase):
    def test_build_failure_window_summary_marks_bad_windows(self) -> None:
        window_mode_summary_df = pd.DataFrame(
            {
                "window_id": [1, 1, 2, 2],
                "train_start_date": ["2026-01-01"] * 4,
                "train_end_date": ["2026-03-31"] * 4,
                "test_start_date": ["2026-04-01", "2026-04-01", "2026-06-01", "2026-06-01"],
                "test_end_date": ["2026-04-30", "2026-04-30", "2026-06-30", "2026-06-30"],
                "segment_name": ["SAFE", "NORMAL", "SAFE", "NORMAL"],
                "rows": [20, 10, 20, 10],
                "grid_pnl_mean": [-0.01, -0.02, -0.01, 0.01],
                "p10_grid_pnl": [-0.03, -0.05, -0.03, -0.01],
                "worst_day_grid_pnl": [-0.08, -0.12, -0.08, -0.03],
            }
        )

        summary_df = build_failure_window_summary(window_mode_summary_df)

        self.assertEqual(summary_df.iloc[0]["window_id"], 1)
        self.assertFalse(bool(summary_df.iloc[0]["normal_beats_safe"]))
        self.assertAlmostEqual(float(summary_df.iloc[0]["normal_minus_safe"]), -0.01)
        self.assertTrue(bool(summary_df.iloc[1]["normal_beats_safe"]))

    def test_build_failure_cohort_summary_and_cases_split_by_bad_windows(self) -> None:
        failure_window_df = pd.DataFrame(
            {
                "window_id": [1, 2],
                "normal_beats_safe": [False, True],
                "normal_minus_safe": [-0.01, 0.02],
                "failure_severity_rank": [1, 2],
            }
        )
        predictions_df = pd.DataFrame(
            {
                "window_id": [1, 1, 2, 2],
                "date": ["2026-04-01", "2026-04-02", "2026-06-01", "2026-06-02"],
                "next_date": ["2026-04-02", "2026-04-03", "2026-06-02", "2026-06-03"],
                "recommended_mode": ["NORMAL", "SAFE", "NORMAL", "SAFE"],
                "signal_rationale": ["clean", "safe", "clean", "safe"],
                "target_grid_pnl_t1": [-0.03, -0.01, 0.02, -0.02],
                "target_positive_grid_day_t1": [0, 1, 1, 0],
                "target_tradable_score_t1": [0, 1, 1, 0],
                "target_hostile_selloff_risk_t1": [1, 0, 0, 1],
                "target_vwap_reversion_t1": [0, 1, 1, 0],
                "pred_positive_grid_day_t1": [0.45, 0.30, 0.50, 0.31],
                "pred_tradable_score_t1": [0.40, 0.20, 0.42, 0.18],
                "pred_hostile_selloff_risk_t1": [0.10, 0.25, 0.08, 0.22],
                "pred_vwap_reversion_score_t1": [0.20, 0.10, 0.30, 0.12],
                "pred_trend_break_risk_t1": [0.15, 0.25, 0.10, 0.22],
                "pred_grid_pnl_t1": [-0.01, -0.02, 0.01, -0.01],
                "position_scale": [0.85, 0.45, 0.85, 0.45],
                "grid_width_scale": [1.0, 1.12, 1.0, 1.12],
                "next_day_open30_low_return": [-0.05, -0.02, -0.01, -0.03],
                "next_day_open60_low_return": [-0.06, -0.03, -0.02, -0.04],
                "next_day_close_recovery_ratio_from_early_low": [1.0, 2.0, 4.0, 3.0],
                "next_day_negative_vwap_ratio": [0.70, 0.50, 0.40, 0.60],
                "next_day_hostile_selloff_soft_score": [8, 5, 3, 6],
                "daily_return": [-0.02, 0.01, 0.03, -0.01],
                "gap_pct": [-0.01, 0.0, 0.01, -0.01],
                "atr_pct": [0.05, 0.04, 0.03, 0.04],
                "stk_m_open15_return": [-0.01, 0.0, 0.01, -0.01],
                "stk_m_open15_range": [0.03, 0.02, 0.04, 0.03],
                "stk_m_trend_efficiency_ratio": [0.02, 0.04, 0.10, 0.05],
                "stk_m_close_vwap_gap": [-0.01, -0.002, -0.005, -0.003],
                "stk_m_max_drawdown_intraday": [0.05, 0.03, 0.02, 0.04],
                "idx_daily_return": [-0.01, 0.0, 0.01, -0.005],
                "sec_daily_return": [-0.02, 0.005, 0.02, -0.01],
            }
        )

        cohort_df = build_failure_cohort_summary(predictions_df, failure_window_df)
        cases_df = select_failure_cases(predictions_df, failure_window_df, top_case_count=10)

        normal_failure = cohort_df[
            (cohort_df["recommended_mode"] == "NORMAL") & (cohort_df["cohort_name"] == "failure_windows")
        ].iloc[0]
        self.assertEqual(int(normal_failure["rows"]), 1)
        self.assertAlmostEqual(float(normal_failure["grid_pnl_mean"]), -0.03)
        self.assertEqual(len(cases_df), 1)
        self.assertEqual(int(cases_df.iloc[0]["window_id"]), 1)
        self.assertFalse(bool(cases_df.iloc[0]["normal_beats_safe"]))

    def test_build_walk_forward_failure_report_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            analysis_dir = base_dir / "analysis"
            analysis_dir.mkdir(parents=True, exist_ok=True)

            pd.DataFrame(
                {
                    "window_id": [1, 1, 2, 2],
                    "date": ["2026-04-01", "2026-04-02", "2026-06-01", "2026-06-02"],
                    "next_date": ["2026-04-02", "2026-04-03", "2026-06-02", "2026-06-03"],
                    "recommended_mode": ["NORMAL", "SAFE", "NORMAL", "SAFE"],
                    "signal_rationale": ["clean", "safe", "clean", "safe"],
                    "target_grid_pnl_t1": [-0.03, -0.01, 0.02, -0.02],
                    "target_positive_grid_day_t1": [0, 1, 1, 0],
                    "target_tradable_score_t1": [0, 1, 1, 0],
                    "target_hostile_selloff_risk_t1": [1, 0, 0, 1],
                    "target_vwap_reversion_t1": [0, 1, 1, 0],
                    "pred_positive_grid_day_t1": [0.45, 0.30, 0.50, 0.31],
                    "pred_tradable_score_t1": [0.40, 0.20, 0.42, 0.18],
                    "pred_hostile_selloff_risk_t1": [0.10, 0.25, 0.08, 0.22],
                    "pred_vwap_reversion_score_t1": [0.20, 0.10, 0.30, 0.12],
                    "pred_trend_break_risk_t1": [0.15, 0.25, 0.10, 0.22],
                    "pred_grid_pnl_t1": [-0.01, -0.02, 0.01, -0.01],
                    "position_scale": [0.85, 0.45, 0.85, 0.45],
                    "grid_width_scale": [1.0, 1.12, 1.0, 1.12],
                }
            ).to_csv(analysis_dir / "walk_forward_test_predictions.csv", index=False)

            pd.DataFrame(
                {
                    "window_id": [1, 1, 2, 2],
                    "head_name": [
                        "positive_grid_day_classifier",
                        "hostile_selloff_risk_classifier",
                        "positive_grid_day_classifier",
                        "hostile_selloff_risk_classifier",
                    ],
                    "head_type": ["classification"] * 4,
                    "recommended_threshold": [0.20, 0.15, 0.30, 0.20],
                    "recommended_recall": [0.70, 0.40, 0.60, 0.45],
                    "recommended_precision": [0.35, 0.22, 0.42, 0.24],
                    "default_average_precision": [0.40, 0.25, 0.50, 0.30],
                }
            ).to_csv(analysis_dir / "walk_forward_head_metrics.csv", index=False)

            pd.DataFrame(
                {
                    "window_id": [1, 1, 2, 2],
                    "train_start_date": ["2026-01-01"] * 4,
                    "train_end_date": ["2026-03-31"] * 4,
                    "test_start_date": ["2026-04-01", "2026-04-01", "2026-06-01", "2026-06-01"],
                    "test_end_date": ["2026-04-30", "2026-04-30", "2026-06-30", "2026-06-30"],
                    "segment_name": ["SAFE", "NORMAL", "SAFE", "NORMAL"],
                    "rows": [20, 10, 20, 10],
                    "grid_pnl_mean": [-0.01, -0.02, -0.01, 0.01],
                    "p10_grid_pnl": [-0.03, -0.05, -0.03, -0.01],
                    "worst_day_grid_pnl": [-0.08, -0.12, -0.08, -0.03],
                }
            ).to_csv(analysis_dir / "walk_forward_window_mode_summary.csv", index=False)

            config = ProjectConfig(base_dir=base_dir)
            outputs = build_walk_forward_failure_report(config=config, top_case_count=10)

            for path in outputs.values():
                self.assertTrue(path.exists(), path)

            threshold_drift_df = pd.read_csv(config.walk_forward_failure_threshold_drift_path)
            self.assertIn("positive_grid_day_classifier", set(threshold_drift_df["head_name"]))


if __name__ == "__main__":
    unittest.main()

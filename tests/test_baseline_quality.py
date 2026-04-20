import unittest

import pandas as pd

from ptrade_t0_ml.baseline_quality import (
    assign_score_buckets,
    build_controller_interaction_summary,
    build_mode_replay_summary,
    select_downside_error_cases,
)


class BaselineQualityTests(unittest.TestCase):
    def test_assign_score_buckets_handles_small_series(self) -> None:
        series = pd.Series([0.9, 0.1, 0.5])

        buckets = assign_score_buckets(series, bucket_count=5)

        self.assertEqual(buckets.tolist(), [3, 1, 2])

    def test_build_mode_replay_summary_includes_combined_segments(self) -> None:
        predictions_df = pd.DataFrame(
            {
                "recommended_mode": ["SAFE", "NORMAL", "AGGRESSIVE", "OFF"],
                "position_scale": [0.55, 0.85, 1.0, 0.2],
                "target_grid_pnl_t1": [-0.03, 0.01, 0.02, -0.04],
                "target_positive_grid_day_t1": [0, 1, 1, 0],
                "target_tradable_score_t1": [0, 1, 1, 0],
                "target_trend_break_risk_t1": [1, 0, 0, 1],
                "target_hostile_selloff_risk_t1": [1, 0, 0, 1],
                "target_vwap_reversion_t1": [0, 1, 1, 0],
                "target_upside_t1": [0.01, 0.02, 0.03, -0.01],
                "target_downside_t1": [-0.05, -0.02, -0.01, -0.06],
            }
        )

        summary_df = build_mode_replay_summary(predictions_df)

        self.assertEqual(
            set(summary_df["segment_name"]),
            {"ALL", "OFF", "SAFE", "NORMAL", "AGGRESSIVE", "SAFE_OR_OFF", "NORMAL_OR_AGGRESSIVE"},
        )
        safe_or_off = summary_df.loc[summary_df["segment_name"] == "SAFE_OR_OFF"].iloc[0]
        self.assertEqual(int(safe_or_off["rows"]), 2)
        self.assertAlmostEqual(float(safe_or_off["grid_pnl_total"]), -0.07)

    def test_select_downside_error_cases_marks_union_membership(self) -> None:
        predictions_df = pd.DataFrame(
            {
                "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
                "next_date": ["2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"],
                "recommended_mode": ["SAFE", "NORMAL", "SAFE", "OFF"],
                "signal_rationale": ["a", "b", "c", "d"],
                "pred_downside_t1": [-0.02, -0.08, -0.01, -0.03],
                "target_downside_t1": [-0.07, -0.04, -0.02, -0.09],
                "downside_prediction_error": [0.07, -0.04, 0.01, 0.06],
                "downside_abs_error": [0.07, 0.04, 0.01, 0.06],
                "pred_upside_t1": [0.01, 0.01, 0.01, 0.01],
                "target_upside_t1": [0.01, 0.01, 0.01, 0.01],
                "pred_grid_pnl_t1": [0.0, 0.0, 0.0, 0.0],
                "target_grid_pnl_t1": [0.0, 0.0, 0.0, 0.0],
                "pred_positive_grid_day_t1": [0.1, 0.1, 0.1, 0.1],
                "target_positive_grid_day_t1": [0, 0, 0, 0],
                "pred_tradable_score_t1": [0.1, 0.1, 0.1, 0.1],
                "target_tradable_score_t1": [0, 0, 0, 0],
                "pred_trend_break_risk_t1": [0.1, 0.1, 0.1, 0.1],
                "target_trend_break_risk_t1": [0, 0, 0, 0],
                "pred_hostile_selloff_risk_t1": [0.2, 0.2, 0.2, 0.2],
                "target_hostile_selloff_risk_t1": [1, 0, 0, 1],
                "pred_vwap_reversion_score_t1": [0.1, 0.1, 0.1, 0.1],
                "target_vwap_reversion_t1": [0, 0, 0, 0],
                "position_scale": [0.55, 0.85, 0.55, 0.2],
                "grid_width_scale": [1.1, 1.0, 1.1, 1.35],
                "recommended_grid_width_t1": [0.02, 0.02, 0.02, 0.02],
                "daily_return": [0.0, 0.0, 0.0, 0.0],
            }
        )

        cases_df = select_downside_error_cases(
            predictions_df,
            top_n=1,
            context_columns=["daily_return"],
        )

        self.assertEqual(len(cases_df), 3)
        self.assertTrue(bool(cases_df["in_predicted_worst_top_n"].any()))
        self.assertTrue(bool(cases_df["in_actual_worst_top_n"].any()))
        self.assertTrue(bool(cases_df["in_largest_abs_error_top_n"].any()))

    def test_build_controller_interaction_summary_splits_hostile_and_pg_tr_segments(self) -> None:
        predictions_df = pd.DataFrame(
            {
                "pred_positive_grid_day_t1": [0.40, 0.40, 0.20, 0.20],
                "pred_positive_grid_day_t1_threshold": [0.35] * 4,
                "pred_tradable_score_t1": [0.40, 0.40, 0.20, 0.20],
                "pred_tradable_score_t1_threshold": [0.35] * 4,
                "pred_trend_break_risk_t1": [0.10, 0.35, 0.10, 0.35],
                "pred_trend_break_risk_t1_threshold": [0.30] * 4,
                "pred_hostile_selloff_risk_t1": [0.30, 0.30, 0.10, 0.10],
                "pred_hostile_selloff_risk_t1_threshold": [0.25] * 4,
                "pred_vwap_reversion_score_t1": [0.30, 0.30, 0.20, 0.20],
                "pred_vwap_reversion_score_t1_threshold": [0.25] * 4,
                "target_grid_pnl_t1": [-0.02, -0.01, 0.01, 0.00],
                "target_positive_grid_day_t1": [1, 1, 0, 0],
                "target_tradable_score_t1": [1, 1, 0, 0],
                "target_trend_break_risk_t1": [0, 1, 0, 1],
                "target_hostile_selloff_risk_t1": [1, 1, 0, 0],
                "target_vwap_reversion_t1": [1, 1, 0, 0],
            }
        )

        summary_df = build_controller_interaction_summary(predictions_df)

        segment_rows = {row["segment_name"]: row for _, row in summary_df.iterrows()}
        self.assertEqual(int(segment_rows["pg_tr_on_hs_on"]["rows"]), 2)
        self.assertEqual(int(segment_rows["pg_tr_on_hs_off"]["rows"]), 0)
        self.assertEqual(int(segment_rows["trend_high_hs_high"]["rows"]), 1)
        self.assertAlmostEqual(float(segment_rows["pg_tr_on_hs_on"]["grid_pnl_mean"]), -0.015)
        self.assertAlmostEqual(float(segment_rows["vwap_on_hs_on"]["positive_grid_day_rate"]), 1.0)


if __name__ == "__main__":
    unittest.main()

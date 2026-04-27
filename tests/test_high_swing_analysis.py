import unittest

import pandas as pd

from ptrade_t0_ml.high_swing_analysis import build_high_swing_summary, enrich_high_swing_frame


class HighSwingAnalysisTests(unittest.TestCase):
    def test_enrich_high_swing_frame_identifies_repaired_selloff(self) -> None:
        df = pd.DataFrame(
            {
                "date": ["2026-04-27"],
                "open": [90.0],
                "high": [92.0],
                "low": [85.0],
                "close": [90.5],
                "pre_close": [89.0],
                "daily_range": [0.075],
                "stk_m_intraday_range": [0.076],
                "gap_pct": [0.01],
                "stk_m_open60_low_return": [-0.055],
                "stk_m_close_recovery_ratio_from_open60_low": [0.90],
                "stk_m_vwap_cross_count": [1],
                "stk_m_close_vwap_gap": [0.01],
                "next_day_open": [91.0],
                "next_day_high": [93.5],
                "next_day_low": [88.0],
                "next_day_close": [91.2],
                "next_day_open60_low_return": [-0.033],
                "next_day_close_recovery_ratio_from_early_low": [0.70],
                "pred_positive_grid_day_t1": [0.26],
                "pred_positive_grid_day_t1_threshold": [0.30],
                "pred_tradable_score_t1": [0.32],
                "pred_tradable_score_t1_threshold": [0.35],
                "pred_hostile_selloff_risk_t1": [0.36],
                "pred_hostile_selloff_risk_t1_threshold": [0.25],
                "pred_vwap_reversion_score_t1": [0.12],
                "pred_vwap_reversion_score_t1_threshold": [0.25],
                "pred_trend_break_risk_t1": [0.07],
                "pred_trend_break_risk_t1_threshold": [0.10],
            }
        )

        result = enrich_high_swing_frame(df)
        row = result.iloc[0]

        self.assertTrue(bool(row["high_swing_flag"]))
        self.assertTrue(bool(row["early_selloff_flag"]))
        self.assertTrue(bool(row["same_day_dip_repair_window_proxy"]))
        self.assertEqual(row["path_regime"], "early_selloff_repaired")
        self.assertIn("positive_grid_below", row["model_blockers"])
        self.assertIn("hostile_selloff_high", row["model_blockers"])

    def test_build_high_swing_summary_counts_segments(self) -> None:
        review_df = pd.DataFrame(
            {
                "high_swing_flag": [True, True],
                "recommended_mode": ["SAFE", "NORMAL"],
                "high_open_fade_flag": [True, False],
                "early_selloff_flag": [False, True],
                "same_day_high_sell_window_proxy": [True, False],
                "same_day_dip_repair_window_proxy": [False, True],
                "next_day_high_sell_window_proxy": [True, False],
                "next_day_dip_repair_window_proxy": [False, True],
                "target_grid_pnl_t1": [0.01, -0.02],
                "target_positive_grid_day_t1": [1, 0],
                "target_tradable_score_t1": [1, 0],
                "target_hostile_selloff_risk_t1": [0, 1],
            }
        )

        summary = build_high_swing_summary(review_df)
        all_row = summary[summary["segment_name"] == "all_high_swing"].iloc[0]

        self.assertEqual(int(all_row["rows"]), 2)
        self.assertEqual(int(all_row["safe_rows"]), 1)
        self.assertEqual(int(all_row["normal_rows"]), 1)


if __name__ == "__main__":
    unittest.main()

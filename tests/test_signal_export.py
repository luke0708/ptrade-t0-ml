import unittest

import pandas as pd

from ptrade_t0_ml.signal_export import _derive_runtime_controls, _next_weekday


class SignalExportTests(unittest.TestCase):
    def test_next_weekday_skips_weekend(self) -> None:
        self.assertEqual(_next_weekday("2026-04-17"), "2026-04-20")

    def test_runtime_controls_do_not_treat_trend_risk_as_absolute_veto(self) -> None:
        predictions = {
            "pred_upside_t1": 0.035,
            "pred_downside_t1": -0.015,
            "pred_grid_pnl_t1": 0.004,
            "pred_positive_grid_day_t1": 0.46,
            "pred_tradable_score_t1": 0.42,
            "pred_trend_break_risk_t1": 0.14,
            "pred_vwap_reversion_score_t1": 0.31,
        }
        thresholds = {
            "pred_positive_grid_day_t1": 0.35,
            "pred_tradable_score_t1": 0.35,
            "pred_trend_break_risk_t1": 0.15,
            "pred_vwap_reversion_score_t1": 0.25,
        }
        latest_feature_row = pd.Series({"grid_step_pct_t1": 0.012})

        controls = _derive_runtime_controls(predictions, thresholds, latest_feature_row)

        self.assertNotEqual(controls["recommended_mode"], "OFF")
        self.assertGreaterEqual(controls["position_scale"], 0.85)

    def test_runtime_controls_turn_off_only_on_converging_negative_signals(self) -> None:
        predictions = {
            "pred_upside_t1": 0.008,
            "pred_downside_t1": -0.025,
            "pred_grid_pnl_t1": -0.002,
            "pred_positive_grid_day_t1": 0.18,
            "pred_tradable_score_t1": 0.20,
            "pred_trend_break_risk_t1": 0.22,
            "pred_vwap_reversion_score_t1": 0.10,
        }
        thresholds = {
            "pred_positive_grid_day_t1": 0.35,
            "pred_tradable_score_t1": 0.35,
            "pred_trend_break_risk_t1": 0.15,
            "pred_vwap_reversion_score_t1": 0.25,
        }
        latest_feature_row = pd.Series({"grid_step_pct_t1": 0.012})

        controls = _derive_runtime_controls(predictions, thresholds, latest_feature_row)

        self.assertEqual(controls["recommended_mode"], "OFF")
        self.assertTrue(controls["trend_weak"])
        self.assertFalse(controls["dip_buy_enabled"])


if __name__ == "__main__":
    unittest.main()

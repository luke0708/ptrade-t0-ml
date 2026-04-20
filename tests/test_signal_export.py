import unittest
from datetime import date, datetime
from pathlib import Path
import tempfile

import pandas as pd

from ptrade_t0_ml.config import ProjectConfig
from ptrade_t0_ml.signal_export import (
    _assert_daily_inference_freshness,
    _apply_soft_dependency_safe_downgrade,
    _collect_daily_inference_dependency_status,
    _derive_runtime_controls,
    _expected_feature_date,
    _next_trading_day,
    _next_weekday,
)


class SignalExportTests(unittest.TestCase):
    def test_next_weekday_skips_weekend(self) -> None:
        self.assertEqual(_next_weekday("2026-04-17"), "2026-04-20")

    def test_next_trading_day_uses_explicit_calendar_for_holiday_rollover(self) -> None:
        trading_dates = {
            date(2026, 4, 30),
            date(2026, 5, 6),
        }
        self.assertEqual(_next_trading_day("2026-04-30", trading_dates=trading_dates), "2026-05-06")

    def test_next_trading_day_falls_back_to_weekday_when_calendar_missing(self) -> None:
        self.assertEqual(_next_trading_day("2026-04-17", trading_dates=set()), "2026-04-20")

    def test_expected_feature_date_uses_today_after_close(self) -> None:
        trading_dates = {date(2026, 4, 17), date(2026, 4, 20)}
        now_dt = datetime(2026, 4, 20, 16, 0, 0)
        self.assertEqual(_expected_feature_date(now_dt, trading_dates=trading_dates), date(2026, 4, 20))

    def test_assert_daily_inference_freshness_rejects_stale_feature_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            data_dir = temp_dir / "data"
            foundation_dir = data_dir / "foundation"
            foundation_dir.mkdir(parents=True, exist_ok=True)

            pd.DataFrame({"datetime": ["2026-04-17 15:00:00"]}).to_csv(
                data_dir / "300661_SZ_1m_ptrade.csv",
                index=False,
            )
            pd.DataFrame({"date": ["2026-04-17"]}).to_csv(data_dir / "399006.csv", index=False)
            pd.DataFrame({"date": ["2026-04-17"]}).to_csv(data_dir / "512480.csv", index=False)

            config = ProjectConfig(base_dir=temp_dir)

            with self.assertRaisesRegex(ValueError, "Daily inference hard dependencies are stale"):
                _assert_daily_inference_freshness(
                    config,
                    latest_feature_date=date(2026, 4, 17),
                    now_dt=datetime(2026, 4, 20, 16, 0, 0),
                )

    def test_dependency_status_treats_environment_daily_as_soft_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            data_dir = temp_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)

            pd.DataFrame({"datetime": ["2026-04-20 15:00:00"]}).to_csv(data_dir / "300661_SZ_1m_ptrade.csv", index=False)
            pd.DataFrame({"date": ["2026-04-17"]}).to_csv(data_dir / "399006.csv", index=False)
            pd.DataFrame({"date": ["2026-04-17"]}).to_csv(data_dir / "512480.csv", index=False)

            config = ProjectConfig(base_dir=temp_dir)
            status = _collect_daily_inference_dependency_status(
                config,
                latest_feature_date=date(2026, 4, 20),
                now_dt=datetime(2026, 4, 20, 16, 0, 0),
            )

            self.assertEqual(status["hard_stale_sources"], {})
            self.assertEqual(
                status["soft_stale_sources"],
                {"index_daily": "2026-04-17", "sector_daily": "2026-04-17"},
            )

    def test_soft_dependency_downgrade_forces_safe_mode(self) -> None:
        runtime_controls = {
            "recommended_mode": "NORMAL",
            "trend_weak": False,
            "position_scale": 0.85,
            "grid_width_scale": 1.00,
            "recommended_grid_width_t1": 0.012,
            "dip_buy_enabled": True,
            "high_sell_enabled": True,
            "signal_rationale": "clean_edge_without_hostile_selloff",
        }
        dependency_status = {
            "soft_stale_sources": {"index_daily": "2026-04-17"},
        }

        downgraded = _apply_soft_dependency_safe_downgrade(runtime_controls, dependency_status)

        self.assertEqual(downgraded["recommended_mode"], "SAFE")
        self.assertTrue(downgraded["trend_weak"])
        self.assertFalse(downgraded["dip_buy_enabled"])
        self.assertEqual(downgraded["signal_rationale"], "soft_dependency_degraded_to_safe")

    def test_runtime_controls_do_not_treat_trend_risk_as_absolute_veto(self) -> None:
        predictions = {
            "pred_upside_t1": 0.035,
            "pred_downside_t1": -0.015,
            "pred_grid_pnl_t1": 0.004,
            "pred_positive_grid_day_t1": 0.46,
            "pred_tradable_score_t1": 0.42,
            "pred_trend_break_risk_t1": 0.18,
            "pred_hostile_selloff_risk_t1": 0.12,
            "pred_vwap_reversion_score_t1": 0.31,
        }
        thresholds = {
            "pred_positive_grid_day_t1": 0.35,
            "pred_tradable_score_t1": 0.35,
            "pred_trend_break_risk_t1": 0.15,
            "pred_hostile_selloff_risk_t1": 0.20,
            "pred_vwap_reversion_score_t1": 0.25,
        }
        latest_feature_row = pd.Series({"grid_step_pct_t1": 0.012})

        controls = _derive_runtime_controls(predictions, thresholds, latest_feature_row)

        self.assertEqual(controls["recommended_mode"], "NORMAL")
        self.assertGreaterEqual(controls["position_scale"], 0.70)
        self.assertEqual(controls["signal_rationale"], "clean_edge_with_trend_damper")

    def test_runtime_controls_turn_off_only_on_converging_negative_signals(self) -> None:
        predictions = {
            "pred_upside_t1": 0.008,
            "pred_downside_t1": -0.025,
            "pred_grid_pnl_t1": -0.002,
            "pred_positive_grid_day_t1": 0.18,
            "pred_tradable_score_t1": 0.20,
            "pred_trend_break_risk_t1": 0.22,
            "pred_hostile_selloff_risk_t1": 0.28,
            "pred_vwap_reversion_score_t1": 0.10,
        }
        thresholds = {
            "pred_positive_grid_day_t1": 0.35,
            "pred_tradable_score_t1": 0.35,
            "pred_trend_break_risk_t1": 0.15,
            "pred_hostile_selloff_risk_t1": 0.20,
            "pred_vwap_reversion_score_t1": 0.25,
        }
        latest_feature_row = pd.Series({"grid_step_pct_t1": 0.012})

        controls = _derive_runtime_controls(predictions, thresholds, latest_feature_row)

        self.assertEqual(controls["recommended_mode"], "OFF")
        self.assertTrue(controls["trend_weak"])
        self.assertFalse(controls["dip_buy_enabled"])
        self.assertEqual(controls["signal_rationale"], "negative_stack_with_hostile_selloff")

    def test_runtime_controls_disable_dip_buy_on_hostile_selloff_risk(self) -> None:
        predictions = {
            "pred_upside_t1": 0.020,
            "pred_downside_t1": -0.012,
            "pred_grid_pnl_t1": 0.001,
            "pred_positive_grid_day_t1": 0.41,
            "pred_tradable_score_t1": 0.39,
            "pred_trend_break_risk_t1": 0.09,
            "pred_hostile_selloff_risk_t1": 0.31,
            "pred_vwap_reversion_score_t1": 0.28,
        }
        thresholds = {
            "pred_positive_grid_day_t1": 0.35,
            "pred_tradable_score_t1": 0.35,
            "pred_trend_break_risk_t1": 0.15,
            "pred_hostile_selloff_risk_t1": 0.20,
            "pred_vwap_reversion_score_t1": 0.25,
        }
        latest_feature_row = pd.Series({"grid_step_pct_t1": 0.012})

        controls = _derive_runtime_controls(predictions, thresholds, latest_feature_row)

        self.assertEqual(controls["recommended_mode"], "SAFE")
        self.assertFalse(controls["dip_buy_enabled"])
        self.assertLessEqual(float(controls["position_scale"]), 0.45)
        self.assertEqual(controls["signal_rationale"], "hostile_selloff_blocks_execution")

    def test_runtime_controls_keep_normal_clean_edge_without_hostile_selloff(self) -> None:
        predictions = {
            "pred_upside_t1": 0.024,
            "pred_downside_t1": -0.016,
            "pred_grid_pnl_t1": 0.0005,
            "pred_positive_grid_day_t1": 0.41,
            "pred_tradable_score_t1": 0.37,
            "pred_trend_break_risk_t1": 0.12,
            "pred_hostile_selloff_risk_t1": 0.14,
            "pred_vwap_reversion_score_t1": 0.22,
        }
        thresholds = {
            "pred_positive_grid_day_t1": 0.35,
            "pred_tradable_score_t1": 0.35,
            "pred_trend_break_risk_t1": 0.30,
            "pred_hostile_selloff_risk_t1": 0.25,
            "pred_vwap_reversion_score_t1": 0.25,
        }
        latest_feature_row = pd.Series({"grid_step_pct_t1": 0.012})

        controls = _derive_runtime_controls(predictions, thresholds, latest_feature_row)

        self.assertEqual(controls["recommended_mode"], "NORMAL")
        self.assertTrue(controls["dip_buy_enabled"] is False)
        self.assertEqual(controls["signal_rationale"], "clean_edge_without_hostile_selloff")

    def test_runtime_controls_mark_positive_grid_without_tradable_as_safe(self) -> None:
        predictions = {
            "pred_upside_t1": 0.020,
            "pred_downside_t1": -0.014,
            "pred_grid_pnl_t1": -0.001,
            "pred_positive_grid_day_t1": 0.40,
            "pred_tradable_score_t1": 0.18,
            "pred_trend_break_risk_t1": 0.09,
            "pred_hostile_selloff_risk_t1": 0.14,
            "pred_vwap_reversion_score_t1": 0.21,
        }
        thresholds = {
            "pred_positive_grid_day_t1": 0.35,
            "pred_tradable_score_t1": 0.35,
            "pred_trend_break_risk_t1": 0.30,
            "pred_hostile_selloff_risk_t1": 0.25,
            "pred_vwap_reversion_score_t1": 0.25,
        }
        latest_feature_row = pd.Series({"grid_step_pct_t1": 0.012})

        controls = _derive_runtime_controls(predictions, thresholds, latest_feature_row)

        self.assertEqual(controls["recommended_mode"], "SAFE")
        self.assertEqual(controls["signal_rationale"], "positive_grid_without_tradable_confirmation")
        self.assertFalse(controls["dip_buy_enabled"])


if __name__ == "__main__":
    unittest.main()

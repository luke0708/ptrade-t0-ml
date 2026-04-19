import unittest

import pandas as pd

from ptrade_t0_ml.config import DEFAULT_CONFIG
from ptrade_t0_ml.label_engine import build_label_targets, replay_next_day_grid


class LabelEngineTests(unittest.TestCase):
    def test_replay_next_day_grid_realizes_profitable_long_round_trip(self) -> None:
        next_day_bars = pd.DataFrame(
            {
                "datetime": pd.to_datetime(
                    [
                        "2026-04-11 09:31:00",
                        "2026-04-11 09:32:00",
                    ]
                ),
                "date": ["2026-04-11", "2026-04-11"],
                "high": [100.0, 101.0],
                "low": [97.0, 97.0],
                "close": [97.0, 100.0],
                "volume": [5000.0, 5000.0],
            }
        )

        result = replay_next_day_grid(
            next_day_bars=next_day_bars,
            anchor_close=100.0,
            grid_step_pct=0.02,
            replay_config=DEFAULT_CONFIG.grid_replay,
        )

        self.assertEqual(result.replay_round_trips_t1, 1)
        self.assertEqual(result.replay_long_entries_t1, 1)
        self.assertEqual(result.replay_short_entries_t1, 0)
        self.assertGreater(result.target_grid_pnl_t1, 0.0)

    def test_replay_next_day_grid_uses_conservative_same_bar_side_selection(self) -> None:
        next_day_bars = pd.DataFrame(
            {
                "datetime": pd.to_datetime(
                    [
                        "2026-04-11 09:31:00",
                        "2026-04-11 09:32:00",
                    ]
                ),
                "date": ["2026-04-11", "2026-04-11"],
                "high": [103.0, 100.5],
                "low": [97.0, 99.0],
                "close": [101.0, 100.0],
                "volume": [5000.0, 5000.0],
            }
        )

        result = replay_next_day_grid(
            next_day_bars=next_day_bars,
            anchor_close=100.0,
            grid_step_pct=0.02,
            replay_config=DEFAULT_CONFIG.grid_replay,
        )

        self.assertEqual(result.replay_ambiguous_entries_t1, 1)
        self.assertEqual(result.replay_short_entries_t1, 1)
        self.assertEqual(result.replay_round_trips_t1, 1)

    def test_build_label_targets_generates_expected_next_day_fields(self) -> None:
        canonical_df = pd.DataFrame(
            {
                "datetime": pd.to_datetime(
                    [
                        "2026-04-10 09:31:00",
                        "2026-04-10 09:32:00",
                        "2026-04-11 09:31:00",
                        "2026-04-11 09:32:00",
                    ]
                ),
                "date": ["2026-04-10", "2026-04-10", "2026-04-11", "2026-04-11"],
                "code": ["300661.SZ"] * 4,
                "open": [100.0, 100.0, 100.0, 97.0],
                "high": [100.0, 100.0, 100.0, 101.0],
                "low": [100.0, 100.0, 97.0, 97.0],
                "close": [100.0, 100.0, 97.0, 100.0],
                "volume": [5000.0, 5000.0, 5000.0, 5000.0],
                "amount": [500000.0, 500000.0, 485000.0, 500000.0],
                "price": [100.0, 100.0, 97.0, 100.0],
            }
        )
        daily_summary_df = pd.DataFrame(
            {
                "date": ["2026-04-10", "2026-04-11"],
                "first_datetime": ["2026-04-10 09:31:00", "2026-04-11 09:31:00"],
                "last_datetime": ["2026-04-10 15:00:00", "2026-04-11 15:00:00"],
                "bar_count": [240, 240],
                "open": [100.0, 100.0],
                "high": [100.0, 101.0],
                "low": [100.0, 97.0],
                "close": [100.0, 100.0],
                "volume": [10000.0, 10000.0],
                "amount": [1000000.0, 985000.0],
                "price": [100.0, 100.0],
                "zero_volume_bar_count": [0, 0],
                "zero_amount_bar_count": [0, 0],
                "zero_volume_bar_ratio": [0.0, 0.0],
                "zero_amount_bar_ratio": [0.0, 0.0],
                "frequency_label": ["1m", "1m"],
                "expected_bar_count": [240, 240],
                "is_complete_day": [True, True],
            }
        )

        result = build_label_targets(canonical_df, daily_summary_df, config=DEFAULT_CONFIG)
        labels_df = result.labels_df

        self.assertEqual(len(labels_df), 1)
        self.assertEqual(labels_df.iloc[0]["date"], "2026-04-10")
        self.assertAlmostEqual(labels_df.iloc[0]["target_upside_t1"], 0.01, places=6)
        self.assertAlmostEqual(labels_df.iloc[0]["target_downside_t1"], -0.03, places=6)
        self.assertEqual(int(labels_df.iloc[0]["target_positive_grid_day_t1"]), 1)
        self.assertEqual(int(labels_df.iloc[0]["target_tradable_score_t1"]), 1)
        self.assertIn("target_vwap_reversion_t1", labels_df.columns)
        self.assertIn("target_trend_break_risk_t1", labels_df.columns)

    def test_build_label_targets_marks_vwap_reversion_opportunity(self) -> None:
        canonical_df = pd.DataFrame(
            {
                "datetime": pd.to_datetime(
                    [
                        "2026-04-10 09:31:00",
                        "2026-04-10 09:32:00",
                        "2026-04-11 09:31:00",
                        "2026-04-11 09:32:00",
                        "2026-04-11 09:33:00",
                        "2026-04-11 09:34:00",
                        "2026-04-11 09:35:00",
                        "2026-04-11 09:36:00",
                        "2026-04-11 09:37:00",
                    ]
                ),
                "date": ["2026-04-10", "2026-04-10"] + ["2026-04-11"] * 7,
                "code": ["300661.SZ"] * 9,
                "open": [100.0, 100.0, 100.0, 100.0, 94.0, 100.0, 94.0, 100.0, 94.0],
                "high": [100.0, 100.0, 100.0, 100.1, 100.1, 100.1, 100.1, 100.1, 100.1],
                "low": [100.0, 100.0, 99.9, 93.9, 93.9, 93.9, 93.9, 93.9, 93.9],
                "close": [100.0, 100.0, 100.0, 94.0, 100.0, 94.0, 100.0, 94.0, 100.0],
                "volume": [5000.0, 5000.0, 2000.0, 2000.0, 2000.0, 2000.0, 2000.0, 2000.0, 10000.0],
                "amount": [500000.0, 500000.0, 200000.0, 188000.0, 200000.0, 188000.0, 200000.0, 188000.0, 1000000.0],
                "price": [100.0, 100.0, 100.0, 94.0, 100.0, 94.0, 100.0, 94.0, 100.0],
            }
        )
        daily_summary_df = pd.DataFrame(
            {
                "date": ["2026-04-10", "2026-04-11"],
                "first_datetime": ["2026-04-10 09:31:00", "2026-04-11 09:31:00"],
                "last_datetime": ["2026-04-10 15:00:00", "2026-04-11 15:00:00"],
                "bar_count": [240, 240],
                "open": [100.0, 100.0],
                "high": [100.0, 100.1],
                "low": [100.0, 93.9],
                "close": [100.0, 100.0],
                "volume": [10000.0, 22000.0],
                "amount": [1000000.0, 2164000.0],
                "price": [100.0, 100.0],
                "zero_volume_bar_count": [0, 0],
                "zero_amount_bar_count": [0, 0],
                "zero_volume_bar_ratio": [0.0, 0.0],
                "zero_amount_bar_ratio": [0.0, 0.0],
                "frequency_label": ["1m", "1m"],
                "expected_bar_count": [240, 240],
                "is_complete_day": [True, True],
            }
        )

        result = build_label_targets(canonical_df, daily_summary_df, config=DEFAULT_CONFIG)
        row = result.labels_df.iloc[0]

        self.assertEqual(int(row["target_vwap_reversion_t1"]), 1)
        self.assertGreaterEqual(int(row["next_day_vwap_reversion_event_count"]), 4)
        self.assertGreaterEqual(int(row["next_day_vwap_reversion_success_count"]), 2)
        self.assertGreater(float(row["next_day_vwap_reversion_max_capture"]), 0.011)
        self.assertGreaterEqual(int(row["next_day_vwap_cross_count_label"]), 3)

    def test_build_label_targets_marks_one_sided_trend_break_risk(self) -> None:
        canonical_df = pd.DataFrame(
            {
                "datetime": pd.to_datetime(
                    [
                        "2026-04-10 09:31:00",
                        "2026-04-10 09:32:00",
                        "2026-04-11 09:31:00",
                        "2026-04-11 09:32:00",
                        "2026-04-11 09:33:00",
                        "2026-04-11 09:34:00",
                    ]
                ),
                "date": ["2026-04-10", "2026-04-10", "2026-04-11", "2026-04-11", "2026-04-11", "2026-04-11"],
                "code": ["300661.SZ"] * 6,
                "open": [100.0, 100.0, 100.0, 101.0, 102.0, 103.0],
                "high": [100.0, 100.0, 101.0, 102.0, 103.0, 104.0],
                "low": [100.0, 100.0, 100.0, 101.0, 102.0, 103.0],
                "close": [100.0, 100.0, 101.0, 102.0, 103.0, 104.0],
                "volume": [5000.0] * 6,
                "amount": [500000.0, 500000.0, 505000.0, 510000.0, 515000.0, 520000.0],
                "price": [100.0, 100.0, 101.0, 102.0, 103.0, 104.0],
            }
        )
        daily_summary_df = pd.DataFrame(
            {
                "date": ["2026-04-10", "2026-04-11"],
                "first_datetime": ["2026-04-10 09:31:00", "2026-04-11 09:31:00"],
                "last_datetime": ["2026-04-10 15:00:00", "2026-04-11 15:00:00"],
                "bar_count": [240, 240],
                "open": [100.0, 100.0],
                "high": [100.0, 104.0],
                "low": [100.0, 100.0],
                "close": [100.0, 104.0],
                "volume": [10000.0, 20000.0],
                "amount": [1000000.0, 2050000.0],
                "price": [100.0, 104.0],
                "zero_volume_bar_count": [0, 0],
                "zero_amount_bar_count": [0, 0],
                "zero_volume_bar_ratio": [0.0, 0.0],
                "zero_amount_bar_ratio": [0.0, 0.0],
                "frequency_label": ["1m", "1m"],
                "expected_bar_count": [240, 240],
                "is_complete_day": [True, True],
            }
        )

        result = build_label_targets(canonical_df, daily_summary_df, config=DEFAULT_CONFIG)
        row = result.labels_df.iloc[0]

        self.assertEqual(int(row["target_trend_break_risk_t1"]), 1)
        self.assertEqual(int(row["next_day_trend_break_extreme_t1"]), 1)
        self.assertEqual(int(row["target_positive_grid_day_t1"]), 0)
        self.assertEqual(int(row["target_vwap_reversion_t1"]), 0)
        self.assertEqual(int(row["target_tradable_score_t1"]), 0)
        self.assertGreater(float(row["next_day_open_close_return"]), 0.03)
        self.assertGreaterEqual(float(row["next_day_directional_efficiency"]), 0.9)
        self.assertGreaterEqual(float(row["next_day_trend_efficiency_ratio"]), 0.32)
        self.assertGreaterEqual(float(row["next_day_open15_return"]), 0.008)
        self.assertGreaterEqual(float(row["next_day_open15_volume_ratio"]), 0.14)
        self.assertGreaterEqual(int(row["next_day_trend_break_soft_score"]), 5)


if __name__ == "__main__":
    unittest.main()

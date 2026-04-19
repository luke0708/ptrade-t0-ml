import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from ptrade_t0_ml.config import ProjectConfig
from ptrade_t0_ml.feature_engine import build_feature_table


def _build_day_frame(trade_date: str, start_open: float, end_close: float) -> tuple[pd.DataFrame, dict[str, object]]:
    datetimes = pd.date_range(f"{trade_date} 09:31:00", periods=240, freq="min")
    close_series = pd.Series(
        [start_open + (end_close - start_open) * index / 239 for index in range(240)],
        dtype=float,
    )
    open_series = close_series.shift(1).fillna(start_open)
    high_series = pd.concat([open_series, close_series], axis=1).max(axis=1) + 0.02
    low_series = pd.concat([open_series, close_series], axis=1).min(axis=1) - 0.02
    volume_series = pd.Series([1000.0] * 240)
    amount_series = close_series * volume_series

    canonical_df = pd.DataFrame(
        {
            "datetime": datetimes,
            "date": [trade_date] * 240,
            "code": ["300661.SZ"] * 240,
            "open": open_series.to_numpy(),
            "high": high_series.to_numpy(),
            "low": low_series.to_numpy(),
            "close": close_series.to_numpy(),
            "volume": volume_series.to_numpy(),
            "amount": amount_series.to_numpy(),
            "price": close_series.to_numpy(),
        }
    )
    summary_row = {
        "date": trade_date,
        "first_datetime": datetimes.min().strftime("%Y-%m-%d %H:%M:%S"),
        "last_datetime": datetimes.max().strftime("%Y-%m-%d %H:%M:%S"),
        "bar_count": 240,
        "open": float(open_series.iloc[0]),
        "high": float(high_series.max()),
        "low": float(low_series.min()),
        "close": float(close_series.iloc[-1]),
        "volume": float(volume_series.sum()),
        "amount": float(amount_series.sum()),
        "price": float(close_series.iloc[-1]),
        "zero_volume_bar_count": 0,
        "zero_amount_bar_count": 0,
        "zero_volume_bar_ratio": 0.0,
        "zero_amount_bar_ratio": 0.0,
        "frequency_label": "1m",
        "expected_bar_count": 240,
        "is_complete_day": True,
    }
    return canonical_df, summary_row


class FeatureEngineTests(unittest.TestCase):
    def test_build_feature_table_generates_minute_and_daily_features(self) -> None:
        day_one_df, day_one_summary = _build_day_frame("2026-04-10", 10.0, 10.5)
        day_two_df, day_two_summary = _build_day_frame("2026-04-11", 10.6, 11.0)
        canonical_df = pd.concat([day_one_df, day_two_df], ignore_index=True)
        daily_summary_df = pd.DataFrame([day_one_summary, day_two_summary])
        config = ProjectConfig(base_dir=Path("E:/AI炒股/机器学习/nonexistent_base"))

        result = build_feature_table(canonical_df, daily_summary_df, config=config)
        feature_df = result.feature_df

        self.assertEqual(len(feature_df), 2)
        self.assertIn("stk_m_open30_return", feature_df.columns)
        self.assertIn("stk_m_vwap", feature_df.columns)
        self.assertIn("stk_m_amihud_mean", feature_df.columns)
        self.assertIn("stk_m_trend_efficiency_ratio", feature_df.columns)
        self.assertIn("stk_m_open15_volume_ratio", feature_df.columns)
        self.assertIn("stk_m_open15_volume_shock", feature_df.columns)
        self.assertIn("daily_return", feature_df.columns)
        self.assertIn("true_range", feature_df.columns)
        self.assertIn("atr", feature_df.columns)
        self.assertIn("grid_step_pct_t1", feature_df.columns)
        self.assertIn("stk_m_open30_return_mean_3d", feature_df.columns)
        self.assertEqual(int(feature_df.iloc[0]["stk_m_bar_count"]), 240)
        self.assertGreater(feature_df.iloc[0]["stk_m_vwap"], 0.0)
        self.assertGreaterEqual(feature_df.iloc[0]["stk_m_trend_efficiency_ratio"], 0.0)
        self.assertLessEqual(feature_df.iloc[0]["stk_m_trend_efficiency_ratio"], 1.0)
        self.assertAlmostEqual(feature_df.iloc[0]["stk_m_open15_volume_ratio"], 15.0 / 240.0, places=6)
        self.assertAlmostEqual(feature_df.iloc[0]["stk_m_open15_volume_shock"], 1.0, places=6)
        self.assertAlmostEqual(feature_df.iloc[1]["pre_close"], feature_df.iloc[0]["close"], places=6)
        expected_daily_return = feature_df.iloc[1]["close"] / feature_df.iloc[0]["close"] - 1.0
        self.assertAlmostEqual(feature_df.iloc[1]["daily_return"], expected_daily_return, places=6)
        expected_open30_mean = feature_df["stk_m_open30_return"].iloc[:2].mean()
        self.assertAlmostEqual(feature_df.iloc[1]["stk_m_open30_return_mean_3d"], expected_open30_mean, places=6)
        self.assertGreaterEqual(feature_df.iloc[1]["grid_step_pct_t1"], config.grid_replay.min_grid_step_pct)

    def test_build_feature_table_merges_environment_daily_context(self) -> None:
        day_one_df, day_one_summary = _build_day_frame("2026-04-10", 10.0, 10.5)
        day_two_df, day_two_summary = _build_day_frame("2026-04-11", 10.6, 11.0)
        canonical_df = pd.concat([day_one_df, day_two_df], ignore_index=True)
        daily_summary_df = pd.DataFrame([day_one_summary, day_two_summary])

        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            data_dir = base_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                {
                    "date": ["2026-04-10", "2026-04-11"],
                    "open": [2000.0, 2010.0],
                    "close": [2010.0, 2025.0],
                    "high": [2020.0, 2030.0],
                    "low": [1990.0, 2005.0],
                    "volume": [1.0e10, 1.1e10],
                    "amount": [pd.NA, pd.NA],
                }
            ).to_csv(data_dir / "399006.csv", index=False)
            pd.DataFrame(
                {
                    "date": ["2026-04-10", "2026-04-11"],
                    "open": [1.50, 1.52],
                    "close": [1.52, 1.55],
                    "high": [1.54, 1.56],
                    "low": [1.49, 1.51],
                    "volume": [5.0e7, 5.2e7],
                    "amount": [pd.NA, pd.NA],
                }
            ).to_csv(data_dir / "512480.csv", index=False)

            config = ProjectConfig(base_dir=base_dir)
            result = build_feature_table(canonical_df, daily_summary_df, config=config)
            feature_df = result.feature_df

        self.assertIn("idx_close", feature_df.columns)
        self.assertIn("sec_close", feature_df.columns)
        self.assertAlmostEqual(feature_df.iloc[0]["idx_close"], 2010.0, places=6)
        self.assertAlmostEqual(feature_df.iloc[1]["sec_ma5"], (1.52 + 1.55) / 2.0, places=6)
        self.assertEqual(result.audit_payload["merged_environment_prefixes"], ["idx", "sec"])

    def test_build_feature_table_merges_optional_overnight_factors(self) -> None:
        day_one_df, day_one_summary = _build_day_frame("2026-04-10", 10.0, 10.5)
        day_two_df, day_two_summary = _build_day_frame("2026-04-11", 10.6, 11.0)
        canonical_df = pd.concat([day_one_df, day_two_df], ignore_index=True)
        daily_summary_df = pd.DataFrame([day_one_summary, day_two_summary])

        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            data_dir = base_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                {
                    "date": ["2026-04-10", "2026-04-11"],
                    "overnight_semiconductor_return": [0.012, -0.008],
                    "overnight_nasdaq_return": [0.006, -0.004],
                    "overnight_gap_risk_bucket": [2, 1],
                }
            ).to_csv(data_dir / "overnight_factors.csv", index=False)

            config = ProjectConfig(base_dir=base_dir)
            result = build_feature_table(canonical_df, daily_summary_df, config=config)
            feature_df = result.feature_df

        self.assertIn("overnight_semiconductor_return", feature_df.columns)
        self.assertIn("overnight_nasdaq_return", feature_df.columns)
        self.assertIn("overnight_gap_risk_bucket", feature_df.columns)
        self.assertAlmostEqual(feature_df.iloc[0]["overnight_semiconductor_return"], 0.012, places=6)
        self.assertEqual(
            result.audit_payload["merged_overnight_factor_columns"],
            ["overnight_semiconductor_return", "overnight_nasdaq_return", "overnight_gap_risk_bucket"],
        )


if __name__ == "__main__":
    unittest.main()

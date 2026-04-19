import unittest

import numpy as np
import pandas as pd

from ptrade_t0_ml.config import DEFAULT_CONFIG
from ptrade_t0_ml.features import prepare_features
from ptrade_t0_ml.labels import build_labeled_dataset


def build_sample_raw_df(rows: int = 120) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=rows, freq="B")
    close = np.linspace(10.0, 16.0, rows) + np.sin(np.linspace(0, 10, rows))
    open_ = close * 0.995
    high = close * 1.02
    low = close * 0.98
    volume = np.linspace(1_000_000, 1_500_000, rows)
    amount = volume * close
    pre_close = np.concatenate(([np.nan], close[:-1]))
    return pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
            "pre_close": pre_close,
        }
    )


class FeatureAndLabelTests(unittest.TestCase):
    def test_prepare_features_generates_expected_columns(self) -> None:
        features_df = prepare_features(build_sample_raw_df())
        self.assertFalse(features_df.empty)
        self.assertTrue(features_df["date"].is_monotonic_increasing)
        self.assertFalse(features_df.duplicated(subset=["date"]).any())
        self.assertFalse(features_df.isna().any().any())
        for column in [
            "rsi_14",
            "macd_hist_12_26_9",
            "atr_14",
            "bb_width_20_2",
            "sma_20",
            "sma_60",
            "close_to_sma20",
            "volume_sma_5",
            "volume_sma_20",
            "turnover_proxy",
            "daily_amplitude",
            "gap_pct",
        ]:
            self.assertIn(column, features_df.columns)

    def test_build_labeled_dataset_uses_next_day_target(self) -> None:
        features_df = prepare_features(build_sample_raw_df())
        labeled_df = build_labeled_dataset(features_df, config=DEFAULT_CONFIG)
        self.assertIn("label", labeled_df.columns)
        self.assertIn("target", labeled_df.columns)
        self.assertEqual(len(labeled_df), len(features_df) - 1)
        expected_target = features_df.assign(
            label=(
                (features_df["daily_amplitude"] > DEFAULT_CONFIG.label_thresholds.daily_amplitude)
                & (
                    features_df["close"]
                    > features_df["pre_close"] * DEFAULT_CONFIG.label_thresholds.close_floor_ratio
                )
            ).astype(int)
        )["label"].shift(-1).dropna().astype(int)
        self.assertListEqual(labeled_df["target"].tolist(), expected_target.tolist())


if __name__ == "__main__":
    unittest.main()

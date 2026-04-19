import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from ptrade_t0_ml.config import ProjectConfig
from ptrade_t0_ml.overnight_factors import build_overnight_factor_file


class OvernightFactorTests(unittest.TestCase):
    def test_build_overnight_factor_file_maps_us_sessions_to_next_trade_date(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            foundation_dir = base_dir / "data" / "foundation"
            foundation_dir.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"date": ["2026-04-14", "2026-04-15", "2026-04-16"]}).to_csv(
                foundation_dir / "300661_SZ_1m_daily_summary.csv",
                index=False,
            )
            pd.DataFrame(
                {
                    "date": ["2026-04-13", "2026-04-14", "2026-04-15"],
                    "close": [100.0, 102.0, 99.0],
                }
            ).to_csv(base_dir / "data" / "soxx_daily.csv", index=False)
            pd.DataFrame(
                {
                    "日期": ["2026-04-13", "2026-04-14", "2026-04-15"],
                    "收盘": [15000.0, 15150.0, 14900.0],
                }
            ).to_csv(base_dir / "data" / "nasdaq_daily.csv", index=False)

            result = build_overnight_factor_file(ProjectConfig(base_dir=base_dir))

        factor_df = result.factor_df
        self.assertEqual(list(factor_df.columns), ["date", "overnight_semiconductor_return", "overnight_nasdaq_return", "overnight_gap_risk_bucket"])
        self.assertEqual(factor_df.iloc[0]["date"], "2026-04-15")
        self.assertAlmostEqual(factor_df.iloc[0]["overnight_semiconductor_return"], 0.02, places=6)
        self.assertAlmostEqual(factor_df.iloc[0]["overnight_nasdaq_return"], 0.01, places=6)
        self.assertEqual(int(factor_df.iloc[0]["overnight_gap_risk_bucket"]), 2)


if __name__ == "__main__":
    unittest.main()

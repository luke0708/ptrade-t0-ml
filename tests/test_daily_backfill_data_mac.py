import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from daily_backfill_data_mac import (
    _expected_latest_date,
    _select_preferred_daily_frame,
    validate_backfill_success,
)


class DailyBackfillMacTests(unittest.TestCase):
    def test_select_preferred_daily_frame_keeps_trying_until_expected_date(self) -> None:
        calls: list[str] = []

        def stale_source() -> pd.DataFrame:
            calls.append("stale")
            return pd.DataFrame(
                {
                    "date": ["2026-04-17"],
                    "open": [1.0],
                    "close": [1.0],
                    "high": [1.0],
                    "low": [1.0],
                    "volume": [100.0],
                    "amount": [1000.0],
                }
            )

        def fresh_source() -> pd.DataFrame:
            calls.append("fresh")
            return pd.DataFrame(
                {
                    "date": ["2026-04-20"],
                    "open": [2.0],
                    "close": [2.1],
                    "high": [2.2],
                    "low": [1.9],
                    "volume": [200.0],
                    "amount": [2000.0],
                }
            )

        result = _select_preferred_daily_frame(
            [
                ("stale source", stale_source),
                ("fresh source", fresh_source),
            ],
            expected_date=date(2026, 4, 20),
        )

        self.assertEqual(calls, ["stale", "fresh"])
        self.assertEqual(result["date"].iloc[-1], "2026-04-20")

    def test_select_preferred_daily_frame_returns_freshest_if_all_sources_stale(self) -> None:
        result = _select_preferred_daily_frame(
            [
                (
                    "older source",
                    lambda: pd.DataFrame(
                        {
                            "date": ["2026-04-16"],
                            "open": [1.0],
                            "close": [1.0],
                            "high": [1.0],
                            "low": [1.0],
                            "volume": [100.0],
                            "amount": [1000.0],
                        }
                    ),
                ),
                (
                    "newer source",
                    lambda: pd.DataFrame(
                        {
                            "date": ["2026-04-17"],
                            "open": [2.0],
                            "close": [2.0],
                            "high": [2.0],
                            "low": [2.0],
                            "volume": [200.0],
                            "amount": [2000.0],
                        }
                    ),
                ),
            ],
            expected_date=date(2026, 4, 20),
        )

        self.assertEqual(result["date"].iloc[-1], "2026-04-17")

    def test_expected_latest_date_uses_today_after_close(self) -> None:
        trading_dates = {date(2026, 4, 17), date(2026, 4, 20)}
        now_dt = datetime(2026, 4, 20, 16, 0, 0)

        expected = _expected_latest_date(now_dt, trading_dates=trading_dates)

        self.assertEqual(expected, date(2026, 4, 20))

    def test_validate_backfill_success_accepts_previous_trading_day_before_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            data_dir = Path(temp_dir_str)
            pd.DataFrame({"datetime": ["2026-04-17 15:00:00"]}).to_csv(
                data_dir / "300661_SZ_1m_ptrade.csv",
                index=False,
            )
            pd.DataFrame({"date": ["2026-04-17"]}).to_csv(data_dir / "399006.csv", index=False)
            pd.DataFrame({"date": ["2026-04-17"]}).to_csv(data_dir / "512480.csv", index=False)

            summary = validate_backfill_success(
                data_dir=data_dir,
                now_dt=datetime(2026, 4, 20, 14, 0, 0),
                trading_dates={date(2026, 4, 17), date(2026, 4, 20)},
            )

            self.assertEqual(summary["expected_latest_date"], "2026-04-17")

    def test_validate_backfill_success_rejects_stale_hard_dependency_after_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            data_dir = Path(temp_dir_str)
            pd.DataFrame({"datetime": ["2026-04-17 15:00:00"]}).to_csv(
                data_dir / "300661_SZ_1m_ptrade.csv",
                index=False,
            )
            pd.DataFrame({"date": ["2026-04-17"]}).to_csv(data_dir / "399006.csv", index=False)
            pd.DataFrame({"date": ["2026-04-17"]}).to_csv(data_dir / "512480.csv", index=False)

            with self.assertRaisesRegex(ValueError, "Backfill hard dependency is stale"):
                validate_backfill_success(
                    data_dir=data_dir,
                    now_dt=datetime(2026, 4, 20, 16, 0, 0),
                    trading_dates={date(2026, 4, 17), date(2026, 4, 20)},
                )

    def test_validate_backfill_success_allows_stale_soft_dependencies_after_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            data_dir = Path(temp_dir_str)
            pd.DataFrame({"datetime": ["2026-04-20 15:00:00"]}).to_csv(
                data_dir / "300661_SZ_1m_ptrade.csv",
                index=False,
            )
            pd.DataFrame({"date": ["2026-04-17"]}).to_csv(data_dir / "399006.csv", index=False)
            pd.DataFrame({"date": ["2026-04-17"]}).to_csv(data_dir / "512480.csv", index=False)

            summary = validate_backfill_success(
                data_dir=data_dir,
                now_dt=datetime(2026, 4, 20, 16, 0, 0),
                trading_dates={date(2026, 4, 17), date(2026, 4, 20)},
            )

            self.assertEqual(summary["stock_1m"], "2026-04-20")
            self.assertEqual(
                summary["soft_stale_sources"],
                {"index_daily": "2026-04-17", "sector_daily": "2026-04-17"},
            )

    def test_validate_backfill_success_accepts_fresh_after_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            data_dir = Path(temp_dir_str)
            pd.DataFrame({"datetime": ["2026-04-20 15:00:00"]}).to_csv(
                data_dir / "300661_SZ_1m_ptrade.csv",
                index=False,
            )
            pd.DataFrame({"date": ["2026-04-20"]}).to_csv(data_dir / "399006.csv", index=False)
            pd.DataFrame({"date": ["2026-04-20"]}).to_csv(data_dir / "512480.csv", index=False)

            summary = validate_backfill_success(
                data_dir=data_dir,
                now_dt=datetime(2026, 4, 20, 16, 0, 0),
                trading_dates={date(2026, 4, 17), date(2026, 4, 20)},
            )

            self.assertEqual(summary["expected_latest_date"], "2026-04-20")
            self.assertEqual(summary["stock_1m"], "2026-04-20")


if __name__ == "__main__":
    unittest.main()

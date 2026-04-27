import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from daily_backfill_data_mac import (
    _clip_daily_frame_to_expected_date,
    _clip_minute_frame_to_expected_date,
    _expected_latest_date,
    _normalize_cn_daily_fallback,
    _select_preferred_daily_frame,
    get_daily_with_fallback,
    validate_backfill_success,
)


def _build_full_a_share_minute_session(trading_date: date) -> list[str]:
    morning = pd.date_range(
        datetime.combine(trading_date, datetime.min.time()).replace(hour=9, minute=31),
        datetime.combine(trading_date, datetime.min.time()).replace(hour=11, minute=30),
        freq="1min",
    )
    afternoon = pd.date_range(
        datetime.combine(trading_date, datetime.min.time()).replace(hour=13, minute=1),
        datetime.combine(trading_date, datetime.min.time()).replace(hour=15, minute=0),
        freq="1min",
    )
    return [*morning.strftime("%Y-%m-%d %H:%M:%S").tolist(), *afternoon.strftime("%Y-%m-%d %H:%M:%S").tolist()]


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

    def test_normalize_cn_daily_fallback_maps_chinese_columns(self) -> None:
        raw = pd.DataFrame(
            {
                "日期": ["2026-04-27"],
                "开盘": ["3700.0"],
                "收盘": ["3710.5"],
                "最高": ["3720.0"],
                "最低": ["3690.0"],
                "成交量": ["123456"],
                "成交额": ["987654321"],
            }
        )

        result = _normalize_cn_daily_fallback(raw)

        self.assertEqual(
            result.columns.tolist(),
            ["date", "open", "close", "high", "low", "volume", "amount"],
        )
        self.assertEqual(result["date"].iloc[0], "2026-04-27")
        self.assertEqual(float(result["close"].iloc[0]), 3710.5)

    def test_get_daily_with_fallback_uses_tencent_index_source_for_399006(self) -> None:
        stale = pd.DataFrame(
            {
                "date": ["2026-04-24"],
                "open": [1.0],
                "close": [1.0],
                "high": [1.0],
                "low": [1.0],
                "volume": [100.0],
                "amount": [1000.0],
            }
        )
        fresh_tencent = pd.DataFrame(
            {
                "date": ["2026-04-27"],
                "open": [3700.0],
                "close": [3710.0],
                "high": [3720.0],
                "low": [3690.0],
                "amount": [123456789.0],
            }
        )

        with (
            patch("daily_backfill_data_mac.get_em_daily", return_value=stale),
            patch("daily_backfill_data_mac.ak.stock_zh_index_daily", return_value=stale),
            patch("daily_backfill_data_mac.ak.stock_zh_a_hist_tx", return_value=fresh_tencent) as tx_mock,
            patch("daily_backfill_data_mac.ak.stock_zh_index_daily_tx") as tx_index_mock,
            patch("daily_backfill_data_mac.ak.stock_zh_index_daily_em") as em_index_mock,
            patch("daily_backfill_data_mac.ak.index_zh_a_hist") as hist_mock,
            patch("daily_backfill_data_mac._fetch_index_spot_snapshot") as spot_mock,
        ):
            result = get_daily_with_fallback(
                "0.399006",
                fallback_symbol="sz399006",
                expected_date=date(2026, 4, 27),
            )

        self.assertEqual(result["date"].iloc[-1], "2026-04-27")
        self.assertEqual(float(result["close"].iloc[-1]), 3710.0)
        tx_mock.assert_called_once_with(symbol="sz399006")
        tx_index_mock.assert_not_called()
        em_index_mock.assert_not_called()
        hist_mock.assert_not_called()
        spot_mock.assert_not_called()

    def test_expected_latest_date_uses_today_after_close(self) -> None:
        trading_dates = {date(2026, 4, 17), date(2026, 4, 20)}
        now_dt = datetime(2026, 4, 20, 16, 0, 0)

        expected = _expected_latest_date(now_dt, trading_dates=trading_dates)

        self.assertEqual(expected, date(2026, 4, 20))

    def test_expected_latest_date_uses_previous_trading_day_before_complete_day_cutoff(self) -> None:
        trading_dates = {date(2026, 4, 17), date(2026, 4, 20)}
        now_dt = datetime(2026, 4, 20, 15, 5, 0)

        expected = _expected_latest_date(now_dt, trading_dates=trading_dates)

        self.assertEqual(expected, date(2026, 4, 17))

    def test_clip_daily_frame_to_expected_date_drops_incomplete_today_rows(self) -> None:
        df = pd.DataFrame(
            {
                "date": ["2026-04-17", "2026-04-20"],
                "open": [1.0, 2.0],
            }
        )

        clipped = _clip_daily_frame_to_expected_date(df, expected_date=date(2026, 4, 17))

        self.assertEqual(clipped["date"].tolist(), ["2026-04-17"])

    def test_clip_minute_frame_to_expected_date_drops_incomplete_today_rows(self) -> None:
        df = pd.DataFrame(
            {
                "datetime": ["2026-04-17 15:00:00", "2026-04-20 09:31:00"],
                "close": [1.0, 2.0],
            }
        )

        clipped = _clip_minute_frame_to_expected_date(df, expected_date=date(2026, 4, 17))

        self.assertEqual(clipped["datetime"].tolist(), ["2026-04-17 15:00:00"])

    def test_validate_backfill_success_accepts_previous_trading_day_before_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            data_dir = Path(temp_dir_str)
            pd.DataFrame({"datetime": _build_full_a_share_minute_session(date(2026, 4, 17))}).to_csv(
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
            pd.DataFrame({"datetime": _build_full_a_share_minute_session(date(2026, 4, 20))}).to_csv(
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
            pd.DataFrame({"datetime": _build_full_a_share_minute_session(date(2026, 4, 20))}).to_csv(
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

    def test_validate_backfill_success_tolerates_two_missing_latest_minute_bars(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            data_dir = Path(temp_dir_str)
            incomplete_session = _build_full_a_share_minute_session(date(2026, 4, 20))
            incomplete_session.remove("2026-04-20 14:58:00")
            incomplete_session.remove("2026-04-20 14:59:00")
            pd.DataFrame({"datetime": incomplete_session}).to_csv(
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

            self.assertEqual(summary["stock_1m"], "2026-04-20")
            self.assertEqual(summary["stock_1m_missing_count"], 2)

    def test_validate_backfill_success_rejects_more_than_tolerance_latest_minute_bars(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            data_dir = Path(temp_dir_str)
            incomplete_session = _build_full_a_share_minute_session(date(2026, 4, 20))
            for missing_value in [
                "2026-04-20 14:57:00",
                "2026-04-20 14:58:00",
                "2026-04-20 14:59:00",
            ]:
                incomplete_session.remove(missing_value)
            pd.DataFrame({"datetime": incomplete_session}).to_csv(
                data_dir / "300661_SZ_1m_ptrade.csv",
                index=False,
            )
            pd.DataFrame({"date": ["2026-04-20"]}).to_csv(data_dir / "399006.csv", index=False)
            pd.DataFrame({"date": ["2026-04-20"]}).to_csv(data_dir / "512480.csv", index=False)

            with self.assertRaisesRegex(ValueError, "latest_day_minute_completeness"):
                validate_backfill_success(
                    data_dir=data_dir,
                    now_dt=datetime(2026, 4, 20, 16, 0, 0),
                    trading_dates={date(2026, 4, 17), date(2026, 4, 20)},
                )


if __name__ == "__main__":
    unittest.main()

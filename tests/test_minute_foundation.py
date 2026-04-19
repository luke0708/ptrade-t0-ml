import unittest

import pandas as pd

from ptrade_t0_ml.minute_foundation import (
    build_daily_minute_summary,
    infer_frequency_seconds,
    standardize_stock_minute_frame,
)


class MinuteFoundationTests(unittest.TestCase):
    def test_infer_frequency_seconds_detects_one_minute_data(self) -> None:
        series = pd.to_datetime(
            pd.Series(
                [
                    "2026-04-14 09:31:00",
                    "2026-04-14 09:32:00",
                    "2026-04-14 09:33:00",
                ]
            )
        )
        self.assertEqual(infer_frequency_seconds(series), 60)

    def test_standardize_stock_minute_frame_repairs_and_filters_expected_rows(self) -> None:
        raw_df = pd.DataFrame(
            {
                "datetime": [
                    "2026-04-14 09:31:00",
                    "2026-04-14 09:32:00",
                    "2026-04-14 09:33:00",
                    "2026-04-14 09:34:00",
                    "2026-04-14 09:35:00",
                    "2026-04-14 09:35:00",
                    "2026-04-14 09:00:00",
                ],
                "code": ["300661.SZ"] * 7,
                "open": [10.0, 0.0, 10.3, 10.4, 10.5, 10.6, 9.9],
                "high": [10.1, 10.4, -1.0, 10.5, 10.6, 10.7, 10.0],
                "low": [9.9, 10.1, 10.2, 10.3, 10.4, 10.5, 9.8],
                "close": [10.0, 10.3, 10.4, 10.5, 10.6, 10.65, 9.95],
                "volume": [100, 120, 130, 140, 150, 160, 100],
                "amount": [1000, 1200, 1300, 1400, 1500, 1600, 990],
                "price": [10.0, 10.3, 10.4, 10.5, 10.6, 10.65, 9.95],
            }
        )

        result = standardize_stock_minute_frame(raw_df, expected_code="300661.SZ")
        canonical_df = result.canonical_df

        self.assertEqual(len(canonical_df), 4)
        self.assertTrue((canonical_df["open"] > 0).all())
        self.assertEqual(result.audit_payload["duplicate_datetime_rows_dropped"], 1)
        self.assertEqual(result.audit_payload["invalid_hlc_rows_dropped"], 1)
        self.assertEqual(result.audit_payload["off_session_rows_dropped"], 1)
        self.assertGreaterEqual(result.audit_payload["repaired_open_rows"], 1)

    def test_build_daily_minute_summary_marks_complete_days(self) -> None:
        canonical_df = pd.DataFrame(
            {
                "datetime": pd.to_datetime(
                    [
                        "2026-04-14 09:31:00",
                        "2026-04-14 09:32:00",
                        "2026-04-14 09:33:00",
                    ]
                ),
                "date": ["2026-04-14"] * 3,
                "code": ["300661.SZ"] * 3,
                "open": [10.0, 10.1, 10.2],
                "high": [10.1, 10.2, 10.3],
                "low": [9.9, 10.0, 10.1],
                "close": [10.0, 10.1, 10.2],
                "volume": [100, 110, 120],
                "amount": [1000, 1100, 1200],
                "price": [10.0, 10.1, 10.2],
            }
        )
        summary = build_daily_minute_summary(canonical_df, detected_frequency_seconds=60)
        self.assertEqual(summary.iloc[0]["bar_count"], 3)
        self.assertFalse(bool(summary.iloc[0]["is_complete_day"]))


if __name__ == "__main__":
    unittest.main()

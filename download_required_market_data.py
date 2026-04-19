from __future__ import annotations

import logging
import sys
from pathlib import Path

import akshare as ak
import pandas as pd

from build_regression_dataset import (
    configure_logging,
    fetch_etf_daily,
    fetch_etf_minute,
    fetch_index_daily,
    fetch_index_minute,
    fetch_stock_daily,
    fetch_stock_minute,
    save_csv,
)


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DAILY_START = "2020-01-01"
MINUTE_START = "1979-09-01"
END_DATE = "2026-04-13"
RETRIES = 6
TIMEOUT = 15.0


def load_existing_csv(path: Path, time_column: str) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if df.empty or time_column not in df.columns:
        return None
    return df


def normalize_daily_fallback(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    result = df.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result = result.dropna(subset=["date"])
    result = result[(result["date"] >= pd.Timestamp(start_date)) & (result["date"] <= pd.Timestamp(end_date))]
    for column in ["open", "close", "high", "low", "volume"]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if "amount" not in result.columns:
        result["amount"] = pd.NA
    result["date"] = result["date"].dt.strftime("%Y-%m-%d")
    result = result[["date", "open", "close", "high", "low", "volume", "amount"]]
    result = result.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    return result


def normalize_minute_fallback(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["datetime"] = pd.to_datetime(result["datetime"], errors="coerce")
    result = result.dropna(subset=["datetime"])
    for column in ["open", "close", "high", "low", "volume"]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if "amount" not in result.columns:
        result["amount"] = pd.NA
    result["datetime"] = result["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    result = result[["datetime", "open", "close", "high", "low", "volume", "amount"]]
    result = result.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last").reset_index(drop=True)
    return result


def fetch_index_daily_fallback() -> pd.DataFrame:
    logging.warning("using Sina fallback for 399006 daily; amount is not provided by this source and will be left blank")
    raw = ak.stock_zh_index_daily(symbol="sz399006")
    raw = raw.rename(columns={"high": "high", "low": "low", "open": "open", "close": "close", "volume": "volume"})
    return normalize_daily_fallback(raw, DAILY_START, END_DATE)


def fetch_index_minute_fallback() -> pd.DataFrame:
    logging.warning("using Sina fallback for 399006 5m; amount is not provided by this source and will be left blank")
    raw = ak.stock_zh_a_minute(symbol="sz399006", period="5", adjust="")
    raw = raw.rename(columns={"day": "datetime", "high": "high", "low": "low", "open": "open", "close": "close", "volume": "volume"})
    return normalize_minute_fallback(raw)


def fetch_etf_daily_fallback() -> pd.DataFrame:
    logging.warning("using Sina fallback for 512480 daily; amount is not provided by this source and will be left blank")
    raw = ak.fund_etf_hist_sina(symbol="sh512480")
    return normalize_daily_fallback(raw, DAILY_START, END_DATE)


def fetch_etf_minute_fallback() -> pd.DataFrame:
    logging.warning("using Sina fallback for 512480 5m; amount is not provided by this source and will be left blank")
    raw = ak.stock_zh_a_minute(symbol="sh512480", period="5", adjust="qfq")
    raw = raw.rename(columns={"day": "datetime", "high": "high", "low": "low", "open": "open", "close": "close", "volume": "volume"})
    return normalize_minute_fallback(raw)


def main() -> int:
    configure_logging()
    logging.info("downloading required market bundle into %s", DATA_DIR)

    try:
        stock_daily_path = DATA_DIR / "300661.csv"
        stock_minute_path = DATA_DIR / "300661_5m.csv"

        stock_daily_existing = load_existing_csv(stock_daily_path, "date")
        stock_minute_existing = load_existing_csv(stock_minute_path, "datetime")

        if stock_daily_existing is None:
            stock_daily = fetch_stock_daily("300661", DAILY_START, END_DATE, TIMEOUT, RETRIES)
            save_csv(stock_daily.frame, stock_daily_path)
        else:
            logging.info("reusing existing %s", stock_daily_path)

        if stock_minute_path.exists() and stock_minute_existing is not None:
            logging.info("reusing existing %s", stock_minute_path)
        else:
            stock_minute = fetch_stock_minute("300661", MINUTE_START, END_DATE, RETRIES)
            save_csv(stock_minute.frame, stock_minute_path)

        try:
            index_daily = fetch_index_daily("399006", DAILY_START, END_DATE, RETRIES).frame
        except Exception as exc:  # noqa: BLE001
            logging.warning("primary 399006 daily source failed, switching to fallback: %s", exc)
            index_daily = fetch_index_daily_fallback()

        try:
            index_minute = fetch_index_minute("399006", "创业板指", MINUTE_START, END_DATE, RETRIES).frame
        except Exception as exc:  # noqa: BLE001
            logging.warning("primary 399006 5m source failed, switching to fallback: %s", exc)
            index_minute = fetch_index_minute_fallback()

        try:
            sector_daily = fetch_etf_daily("512480", "半导体ETF", DAILY_START, END_DATE, RETRIES).frame
        except Exception as exc:  # noqa: BLE001
            logging.warning("primary 512480 daily source failed, switching to fallback: %s", exc)
            sector_daily = fetch_etf_daily_fallback()

        try:
            sector_minute = fetch_etf_minute("512480", "半导体ETF", MINUTE_START, END_DATE, RETRIES).frame
        except Exception as exc:  # noqa: BLE001
            logging.warning("primary 512480 5m source failed, switching to fallback: %s", exc)
            sector_minute = fetch_etf_minute_fallback()
    except Exception as exc:  # noqa: BLE001
        logging.error("download failed: %s", exc)
        return 1

    save_csv(index_daily, DATA_DIR / "399006.csv")
    save_csv(index_minute, DATA_DIR / "399006_5m.csv")
    save_csv(sector_daily, DATA_DIR / "512480.csv")
    save_csv(sector_minute, DATA_DIR / "512480_5m.csv")

    logging.info(
        "saved daily files: %s, %s, %s",
        stock_daily_path,
        DATA_DIR / "399006.csv",
        DATA_DIR / "512480.csv",
    )
    logging.info(
        "saved minute files: %s, %s, %s",
        stock_minute_path,
        DATA_DIR / "399006_5m.csv",
        DATA_DIR / "512480_5m.csv",
    )
    logging.info(
        "minute coverage | 300661=%s->%s | 399006=%s->%s | 512480=%s->%s",
        stock_minute_existing.iloc[0]["datetime"] if stock_minute_existing is not None else stock_minute.available_start,
        stock_minute_existing.iloc[-1]["datetime"] if stock_minute_existing is not None else stock_minute.available_end,
        index_minute.iloc[0]["datetime"],
        index_minute.iloc[-1]["datetime"],
        sector_minute.iloc[0]["datetime"],
        sector_minute.iloc[-1]["datetime"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

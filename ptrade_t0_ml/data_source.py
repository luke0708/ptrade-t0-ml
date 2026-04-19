from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

from .config import DEFAULT_CONFIG, ProjectConfig
from .io_utils import save_dataframe


EXPECTED_COLUMNS = {
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "pre_close",
}


def _format_akshare_date(value: str) -> str:
    return value.replace("-", "")


def _ensure_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def fetch_akshare_daily_data(
    config: ProjectConfig,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError as exc:
        raise ImportError("AkShare is required. Install dependencies with `pip install -r requirements.txt`.") from exc

    query_end_date = end_date or date.today().isoformat()
    query_start_date = start_date or config.start_date
    raw_df = ak.stock_zh_a_hist(
        symbol=config.stock_symbol,
        period="daily",
        start_date=_format_akshare_date(query_start_date),
        end_date=_format_akshare_date(query_end_date),
        adjust="qfq",
    )
    if raw_df.empty:
        raise ValueError(f"No market data returned for {config.stock_symbol}.")
    return normalize_akshare_daily_data(raw_df)


def normalize_akshare_daily_data(raw_df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
        "换手率": "turnover_rate",
    }
    df = raw_df.rename(columns=rename_map).copy()
    _ensure_columns(df, ["date", "open", "high", "low", "close", "volume", "amount"])

    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    numeric_columns = ["open", "high", "low", "close", "volume", "amount"]
    if "turnover_rate" in df.columns:
        numeric_columns.append("turnover_rate")
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.sort_values("date").reset_index(drop=True)
    df["pre_close"] = df["close"].shift(1)

    core_columns = ["date", "open", "high", "low", "close", "volume", "amount", "pre_close"]
    if "turnover_rate" in df.columns:
        core_columns.append("turnover_rate")
    df = df.loc[:, core_columns]

    if df[["open", "high", "low", "close", "volume", "amount"]].isna().any().any():
        raise ValueError("Core price or volume fields contain NaN values after normalization.")

    return df


def normalize_local_daily_data(raw_df: pd.DataFrame) -> pd.DataFrame:
    _ensure_columns(raw_df, ["date", "open", "high", "low", "close", "volume", "amount"])

    df = raw_df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    numeric_columns = ["open", "high", "low", "close", "volume", "amount"]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    if "turnover_rate" in df.columns:
        df["turnover_rate"] = pd.to_numeric(df["turnover_rate"], errors="coerce")
    if "pre_close" in df.columns:
        df["pre_close"] = pd.to_numeric(df["pre_close"], errors="coerce")
    else:
        df["pre_close"] = pd.NA

    df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    df["pre_close"] = df["pre_close"].fillna(df["close"].shift(1))

    output_columns = ["date", "open", "high", "low", "close", "volume", "amount", "pre_close"]
    if "turnover_rate" in df.columns:
        output_columns.append("turnover_rate")
    df = df.loc[:, output_columns]

    if df[["open", "high", "low", "close", "volume", "amount"]].isna().any().any():
        raise ValueError("Local CSV contains NaN values in core OHLCV fields.")

    return df


def load_local_daily_csv(input_path: Path) -> pd.DataFrame:
    if not input_path.exists():
        raise FileNotFoundError(f"Local market data CSV not found: {input_path}")
    raw_df = pd.read_csv(input_path)
    if raw_df.empty:
        raise ValueError(f"Local market data CSV is empty: {input_path}")
    return normalize_local_daily_data(raw_df)


def run_fetch_data(config: ProjectConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    if config.data_source.lower() != "akshare":
        raise ValueError(f"Unsupported data source: {config.data_source}")
    if config.local_input_csv_path.exists():
        print("Using local CSV market data source:", config.local_input_csv_path)
        df = load_local_daily_csv(config.local_input_csv_path)
    else:
        df = fetch_akshare_daily_data(config)
    save_dataframe(df, config.raw_data_path)
    print("Saved raw daily data to:", config.raw_data_path)
    print("First 5 rows:")
    print(df.head().to_string(index=False))
    print("Last 5 rows:")
    print(df.tail().to_string(index=False))
    return df


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch daily OHLCV data for 300661 using AkShare.")
    parser.add_argument("--input-csv", default=None, help="Optional local CSV path to normalize instead of downloading.")
    parser.add_argument("--start-date", default=None, help="Override start date in YYYY-MM-DD format.")
    parser.add_argument("--end-date", default=None, help="Override end date in YYYY-MM-DD format.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = DEFAULT_CONFIG
    if args.input_csv:
        df = load_local_daily_csv(Path(args.input_csv))
        save_dataframe(df, config.raw_data_path)
        print("Saved raw daily data to:", config.raw_data_path)
        print("First 5 rows:")
        print(df.head().to_string(index=False))
        print("Last 5 rows:")
        print(df.tail().to_string(index=False))
        return
    if args.start_date or args.end_date:
        df = fetch_akshare_daily_data(config=config, start_date=args.start_date, end_date=args.end_date)
        save_dataframe(df, config.raw_data_path)
        print("Saved raw daily data to:", config.raw_data_path)
        print("First 5 rows:")
        print(df.head().to_string(index=False))
        print("Last 5 rows:")
        print(df.tail().to_string(index=False))
        return
    run_fetch_data(config)


if __name__ == "__main__":
    main()

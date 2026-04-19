from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd


STANDARD_COLUMNS = ["date", "open", "close", "high", "low", "volume", "amount"]
RAW_TO_STANDARD = {
    "日期": "date",
    "date": "date",
    "开盘": "open",
    "open": "open",
    "收盘": "close",
    "close": "close",
    "最高": "high",
    "high": "high",
    "最低": "low",
    "low": "low",
    "成交量": "volume",
    "volume": "volume",
    "成交额": "amount",
    "amount": "amount",
}


@dataclass(frozen=True)
class UpdateResult:
    symbol: str
    file_path: Path
    mode: str
    row_count: int


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def normalize_symbol(symbol: str) -> str:
    if symbol is None:
        raise ValueError("stock symbol is required")

    raw = str(symbol).strip().upper()
    if not raw:
        raise ValueError("stock symbol is empty")

    six_digit_matches = re.findall(r"(?<!\d)(\d{6})(?!\d)", raw)
    if len(six_digit_matches) == 1:
        return six_digit_matches[0]
    if len(six_digit_matches) > 1:
        raise ValueError(f"ambiguous stock symbol: {symbol}")

    digits_only = "".join(re.findall(r"\d", raw))
    if not digits_only:
        raise ValueError(f"no digits found in stock symbol: {symbol}")
    if len(digits_only) > 6:
        raise ValueError(f"expected at most 6 digits after cleanup, got {digits_only}")

    return digits_only.zfill(6)


def symbol_to_csv_path(symbol: str, data_dir: Path) -> Path:
    return data_dir / f"{symbol}.csv"


def ensure_standard_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed = df.rename(columns=RAW_TO_STANDARD).copy()
    missing_columns = [column for column in STANDARD_COLUMNS if column not in renamed.columns]
    if missing_columns:
        raise ValueError(
            f"missing required columns after standardization: {', '.join(missing_columns)}"
        )

    standardized = renamed.loc[:, STANDARD_COLUMNS].copy()
    standardized["date"] = pd.to_datetime(standardized["date"], errors="coerce")
    standardized = standardized.dropna(subset=["date"])
    standardized["date"] = standardized["date"].dt.strftime("%Y-%m-%d")

    numeric_columns = [column for column in STANDARD_COLUMNS if column != "date"]
    for column in numeric_columns:
        standardized[column] = pd.to_numeric(standardized[column], errors="coerce")

    standardized = standardized.dropna(subset=["open", "close", "high", "low"])
    standardized = standardized.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    standardized.reset_index(drop=True, inplace=True)
    return standardized


def read_local_history(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    try:
        local_df = pd.read_csv(csv_path)
        if local_df.empty:
            return pd.DataFrame(columns=STANDARD_COLUMNS)
        return ensure_standard_columns(local_df)
    except Exception as exc:  # noqa: BLE001
        logging.error("failed to read local csv %s: %s", csv_path, exc)
        logging.warning("falling back to full download for %s", csv_path.stem)
        return pd.DataFrame(columns=STANDARD_COLUMNS)


def fetch_history(
    symbol: str,
    start_dt: date,
    end_dt: date,
    adjust: str,
    timeout: float,
) -> pd.DataFrame:
    if start_dt > end_dt:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    start_date = start_dt.strftime("%Y%m%d")
    end_date = end_dt.strftime("%Y%m%d")
    logging.info(
        "requesting %s from AkShare: %s -> %s, adjust=%s",
        symbol,
        start_date,
        end_date,
        adjust or "none",
    )

    try:
        raw_df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        logging.error("AkShare request failed for %s: %s", symbol, exc)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    if raw_df is None or raw_df.empty:
        logging.warning("AkShare returned no rows for %s", symbol)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    try:
        return ensure_standard_columns(raw_df)
    except Exception as exc:  # noqa: BLE001
        logging.error("failed to standardize AkShare response for %s: %s", symbol, exc)
        return pd.DataFrame(columns=STANDARD_COLUMNS)


def save_history(df: pd.DataFrame, csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")


def update_symbol(
    symbol_input: str,
    data_dir: Path,
    default_start_date: str,
    adjust: str,
    timeout: float,
) -> UpdateResult | None:
    try:
        symbol = normalize_symbol(symbol_input)
    except ValueError as exc:
        logging.error("invalid stock symbol %r: %s", symbol_input, exc)
        return None

    csv_path = symbol_to_csv_path(symbol, data_dir)
    local_df = read_local_history(csv_path)
    today = date.today()

    if local_df.empty:
        mode = "full"
        start_dt = datetime.strptime(default_start_date, "%Y-%m-%d").date()
        logging.info("local csv not found or empty, running full download for %s", symbol)
    else:
        mode = "incremental"
        last_date = datetime.strptime(str(local_df.iloc[-1]["date"]), "%Y-%m-%d").date()
        start_dt = last_date + timedelta(days=1)
        logging.info("latest local date for %s is %s", symbol, last_date.isoformat())

    if start_dt > today:
        logging.info("%s is already up to date, no download needed", symbol)
        return UpdateResult(symbol=symbol, file_path=csv_path, mode="skip", row_count=len(local_df))

    fetched_df = fetch_history(
        symbol=symbol,
        start_dt=start_dt,
        end_dt=today,
        adjust=adjust,
        timeout=timeout,
    )

    if fetched_df.empty and not local_df.empty:
        logging.info("no new rows returned for %s", symbol)
        return UpdateResult(symbol=symbol, file_path=csv_path, mode="skip", row_count=len(local_df))
    if fetched_df.empty and local_df.empty:
        logging.warning("no data saved for %s because nothing was downloaded", symbol)
        return None

    if local_df.empty:
        merged_df = fetched_df.copy()
    else:
        merged_df = pd.concat([local_df, fetched_df], ignore_index=True)
        merged_df = ensure_standard_columns(merged_df)
    save_history(merged_df, csv_path)
    added_rows = max(len(merged_df) - len(local_df), 0)

    logging.info(
        "%s update finished: mode=%s, added_rows=%s, total_rows=%s, file=%s",
        symbol,
        mode,
        added_rows,
        len(merged_df),
        csv_path,
    )
    return UpdateResult(symbol=symbol, file_path=csv_path, mode=mode, row_count=len(merged_df))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download or incrementally update A-share daily history to local CSV files."
    )
    parser.add_argument(
        "symbols",
        nargs="+",
        help="Stock symbols such as 300661, 300661.SZ, or SZ300661",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Directory for storing CSV files, default is ./data",
    )
    parser.add_argument(
        "--start-date",
        default="2020-01-01",
        help="Full download start date in YYYY-MM-DD, default is 2020-01-01",
    )
    parser.add_argument(
        "--adjust",
        default="qfq",
        choices=["", "qfq", "hfq"],
        help="Price adjustment type: qfq (default), hfq, or empty string",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Request timeout in seconds passed to AkShare",
    )
    return parser


def main() -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    try:
        datetime.strptime(args.start_date, "%Y-%m-%d")
    except ValueError:
        logging.error("invalid --start-date: %s, expected YYYY-MM-DD", args.start_date)
        return 1

    data_dir = Path(args.data_dir).resolve()
    results: list[UpdateResult] = []

    for symbol_input in args.symbols:
        result = update_symbol(
            symbol_input=symbol_input,
            data_dir=data_dir,
            default_start_date=args.start_date,
            adjust=args.adjust,
            timeout=args.timeout,
        )
        if result is not None:
            results.append(result)

    if not results:
        logging.error("no symbol was updated successfully")
        return 1

    logging.info("finished updating %s symbol(s)", len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())

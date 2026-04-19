from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import akshare as ak
import pandas as pd


STANDARD_COLUMNS = ["date", "open", "close", "high", "low", "volume", "amount"]
STOCK_REQUIRED_COLUMNS = ["date", "open", "close", "high", "low", "volume", "amount"]
RAW_TO_STANDARD = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
}


@dataclass(frozen=True)
class DatasetSource:
    name: str
    raw_rows: int
    frame: pd.DataFrame


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def normalize_symbol(raw_symbol: str) -> str:
    if raw_symbol is None:
        raise ValueError("symbol is required")

    cleaned = str(raw_symbol).strip().upper()
    if not cleaned:
        raise ValueError("symbol is empty")

    six_digit_matches = re.findall(r"(?<!\d)(\d{6})(?!\d)", cleaned)
    if len(six_digit_matches) == 1:
        return six_digit_matches[0]
    if len(six_digit_matches) > 1:
        raise ValueError(f"ambiguous symbol: {raw_symbol}")

    digits_only = "".join(re.findall(r"\d", cleaned))
    if not digits_only:
        raise ValueError(f"no digits found in symbol: {raw_symbol}")
    if len(digits_only) > 6:
        raise ValueError(f"too many digits in symbol after cleanup: {digits_only}")

    return digits_only.zfill(6)


def normalize_date_text(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r}, expected YYYY-MM-DD") from exc
    return parsed.strftime("%Y%m%d")


def standardize_ohlcva(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError(f"{source_name} returned empty data")

    renamed = df.rename(columns=RAW_TO_STANDARD).copy()
    missing_columns = [column for column in STANDARD_COLUMNS if column not in renamed.columns]
    if missing_columns:
        raise ValueError(
            f"{source_name} missing required columns after rename: {', '.join(missing_columns)}"
        )

    standardized = renamed.loc[:, STANDARD_COLUMNS].copy()
    standardized["date"] = pd.to_datetime(standardized["date"], errors="coerce")
    standardized = standardized.dropna(subset=["date"])
    standardized["date"] = standardized["date"].dt.strftime("%Y-%m-%d")

    for column in STANDARD_COLUMNS:
        if column == "date":
            continue
        standardized[column] = pd.to_numeric(standardized[column], errors="coerce")

    standardized = standardized.sort_values("date")
    standardized = standardized.drop_duplicates(subset=["date"], keep="last")
    standardized.reset_index(drop=True, inplace=True)
    return standardized


def validate_stock_core_columns(stock_df: pd.DataFrame) -> pd.DataFrame:
    before_rows = len(stock_df)
    filtered = stock_df.dropna(subset=STOCK_REQUIRED_COLUMNS)
    dropped_rows = before_rows - len(filtered)
    if dropped_rows > 0:
        logging.warning("dropped %s stock rows with null core fields", dropped_rows)
    if filtered.empty:
        raise ValueError("stock data became empty after removing rows with null core fields")
    return filtered


def add_prefix(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    rename_map = {column: f"{prefix}{column}" for column in df.columns if column != "date"}
    return df.rename(columns=rename_map)


def run_with_retries(label: str, func, retries: int = 3, sleep_seconds: float = 2.0):
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == retries:
                break
            logging.warning(
                "%s failed on attempt %s/%s: %s; retrying in %.1f seconds",
                label,
                attempt,
                retries,
                exc,
                sleep_seconds,
            )
            time.sleep(sleep_seconds)

    assert last_error is not None
    raise last_error


def score_board_name(board_name: str, keyword: str) -> tuple[int, int, str]:
    if board_name == keyword:
        return (4, -len(board_name), board_name)
    if board_name.startswith(keyword) or board_name.endswith(keyword):
        return (3, -len(board_name), board_name)
    if keyword in board_name:
        return (2, -len(board_name), board_name)
    return (0, -len(board_name), board_name)


def fetch_stock_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
    timeout: float,
    retries: int,
) -> DatasetSource:
    try:
        raw_df = run_with_retries(
            label=f"stock_zh_a_hist({symbol})",
            retries=retries,
            func=lambda: ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=normalize_date_text(start_date),
                end_date=normalize_date_text(end_date),
                adjust=adjust,
                timeout=timeout,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"failed to fetch stock_zh_a_hist for {symbol}: {exc}") from exc

    raw_rows = 0 if raw_df is None else len(raw_df)
    standardized = standardize_ohlcva(raw_df, f"stock_zh_a_hist({symbol})")
    standardized = validate_stock_core_columns(standardized)
    return DatasetSource(name=f"stock_{symbol}", raw_rows=raw_rows, frame=standardized)


def fetch_index_daily(symbol: str, start_date: str, end_date: str, retries: int) -> DatasetSource:
    try:
        raw_df = run_with_retries(
            label=f"index_zh_a_hist({symbol})",
            retries=retries,
            func=lambda: ak.index_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=normalize_date_text(start_date),
                end_date=normalize_date_text(end_date),
            ),
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"failed to fetch index_zh_a_hist for {symbol}: {exc}") from exc

    raw_rows = 0 if raw_df is None else len(raw_df)
    standardized = standardize_ohlcva(raw_df, f"index_zh_a_hist({symbol})")
    return DatasetSource(name=f"index_{symbol}", raw_rows=raw_rows, frame=standardized)


def choose_industry_board(keyword: str, retries: int) -> tuple[str, pd.DataFrame]:
    try:
        board_df = run_with_retries(
            label="stock_board_industry_name_em()",
            retries=retries,
            func=lambda: ak.stock_board_industry_name_em(),
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"failed to fetch industry board list: {exc}") from exc

    if board_df is None or board_df.empty:
        raise RuntimeError("industry board list is empty")
    if "板块名称" not in board_df.columns or "板块代码" not in board_df.columns:
        raise RuntimeError("industry board list missing 板块名称 or 板块代码")

    candidates = board_df[board_df["板块名称"].astype(str).str.contains(keyword, na=False)].copy()
    if candidates.empty:
        raise RuntimeError(f"no industry board matched keyword {keyword!r}")

    candidates["__match_score"] = candidates["板块名称"].astype(str).map(
        lambda name: score_board_name(name, keyword)
    )
    candidates = candidates.sort_values("__match_score", ascending=False).drop(columns="__match_score")
    candidates.reset_index(drop=True, inplace=True)
    chosen_board = str(candidates.iloc[0]["板块名称"])
    return chosen_board, candidates


def fetch_industry_board_daily(
    board_name: str,
    start_date: str,
    end_date: str,
    retries: int,
) -> DatasetSource:
    try:
        raw_df = run_with_retries(
            label=f"stock_board_industry_hist_em({board_name})",
            retries=retries,
            func=lambda: ak.stock_board_industry_hist_em(
                symbol=board_name,
                start_date=normalize_date_text(start_date),
                end_date=normalize_date_text(end_date),
                period="日k",
                adjust="",
            ),
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"failed to fetch stock_board_industry_hist_em for {board_name}: {exc}"
        ) from exc

    raw_rows = 0 if raw_df is None else len(raw_df)
    standardized = standardize_ohlcva(raw_df, f"stock_board_industry_hist_em({board_name})")
    return DatasetSource(name=f"sector_{board_name}", raw_rows=raw_rows, frame=standardized)


def build_enriched_dataset(
    stock_source: DatasetSource,
    index_source: DatasetSource,
    sector_source: DatasetSource,
) -> pd.DataFrame:
    merged = stock_source.frame.copy()
    merged = merged.merge(add_prefix(index_source.frame, "idx_"), on="date", how="left")
    merged = merged.merge(add_prefix(sector_source.frame, "sec_"), on="date", how="left")
    merged = merged.sort_values("date").drop_duplicates(subset=["date"], keep="last")

    fill_columns = [column for column in merged.columns if column.startswith(("idx_", "sec_"))]
    if fill_columns:
        merged.loc[:, fill_columns] = merged.loc[:, fill_columns].ffill()

    merged = validate_stock_core_columns(merged)
    merged.reset_index(drop=True, inplace=True)
    return merged


def print_summary(
    stock_source: DatasetSource,
    index_source: DatasetSource,
    sector_source: DatasetSource,
    merged_df: pd.DataFrame,
    board_keyword: str,
    board_name: str,
    board_candidates: pd.DataFrame,
    output_path: Path,
) -> None:
    print("\n=== Data Source Summary ===")
    print(f"stock raw rows: {stock_source.raw_rows}")
    print(f"index raw rows: {index_source.raw_rows}")
    print(f"sector raw rows: {sector_source.raw_rows}")
    print(f"merge rows: {len(merged_df)}")
    print(f"chosen sector board for keyword {board_keyword!r}: {board_name}")
    print("matched board candidates:")
    print(board_candidates.loc[:, [col for col in ["板块名称", "板块代码"] if col in board_candidates.columns]].to_string(index=False))

    print("\n=== Final Columns ===")
    print(merged_df.columns.tolist())

    print("\n=== Missing Value Summary ===")
    missing_summary = merged_df.isna().sum().sort_values(ascending=False)
    missing_summary = missing_summary[missing_summary > 0]
    if missing_summary.empty:
        print("no missing values")
    else:
        print(missing_summary.to_string())

    print("\n=== Head (5 rows) ===")
    print(merged_df.head(5).to_string(index=False))

    print("\n=== Tail (5 rows) ===")
    print(merged_df.tail(5).to_string(index=False))

    print("\n=== Output ===")
    print(output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an enriched daily dataset for A-share regression modeling."
    )
    parser.add_argument("--symbol", default="300661", help="Target stock symbol, default 300661")
    parser.add_argument("--index-symbol", default="399006", help="Broad index symbol, default 399006")
    parser.add_argument(
        "--board-keyword",
        default="半导体",
        help="Keyword used to auto-match an industry board, default 半导体",
    )
    parser.add_argument(
        "--start-date",
        default="2020-01-01",
        help="Dataset start date in YYYY-MM-DD, default 2020-01-01",
    )
    parser.add_argument(
        "--end-date",
        default=date.today().strftime("%Y-%m-%d"),
        help="Dataset end date in YYYY-MM-DD, default today",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Timeout in seconds for stock_zh_a_hist",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retry count for AkShare requests, default 3",
    )
    parser.add_argument(
        "--output",
        default="data/300661_enriched_daily.csv",
        help="Output CSV path, default data/300661_enriched_daily.csv",
    )
    return parser


def main() -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    try:
        stock_symbol = normalize_symbol(args.symbol)
        index_symbol = normalize_symbol(args.index_symbol)
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").strftime("%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").strftime("%Y-%m-%d")
        output_path = Path(args.output).resolve()
    except ValueError as exc:
        logging.error("%s", exc)
        return 1

    if start_date > end_date:
        logging.error("start date %s is later than end date %s", start_date, end_date)
        return 1

    logging.info("building enriched dataset for stock=%s, index=%s", stock_symbol, index_symbol)
    logging.info("date range: %s -> %s", start_date, end_date)

    try:
        stock_source = fetch_stock_daily(
            symbol=stock_symbol,
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
            timeout=args.timeout,
            retries=args.retries,
        )
        index_source = fetch_index_daily(
            symbol=index_symbol,
            start_date=start_date,
            end_date=end_date,
            retries=args.retries,
        )
        board_name, board_candidates = choose_industry_board(args.board_keyword, retries=args.retries)
        logging.info("matched industry board %s for keyword %s", board_name, args.board_keyword)
        sector_source = fetch_industry_board_daily(
            board_name=board_name,
            start_date=start_date,
            end_date=end_date,
            retries=args.retries,
        )
        merged_df = build_enriched_dataset(stock_source, index_source, sector_source)
    except Exception as exc:  # noqa: BLE001
        logging.error("dataset build failed: %s", exc)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    logging.info("saved enriched dataset to %s", output_path)

    print_summary(
        stock_source=stock_source,
        index_source=index_source,
        sector_source=sector_source,
        merged_df=merged_df,
        board_keyword=args.board_keyword,
        board_name=board_name,
        board_candidates=board_candidates,
        output_path=output_path,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

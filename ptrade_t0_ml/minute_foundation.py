from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import numpy as np
import pandas as pd

from .config import DEFAULT_CONFIG, ProjectConfig
from .io_utils import atomic_write_json, save_dataframe

LOGGER = logging.getLogger(__name__)

CHINESE_TO_ENGLISH = {
    "时间": "datetime",
    "日期": "date",
    "代码": "code",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
    "最新价": "price",
}

CANONICAL_COLUMNS = [
    "datetime",
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "price",
]


@dataclass(frozen=True)
class MinuteFoundationResult:
    canonical_df: pd.DataFrame
    daily_summary_df: pd.DataFrame
    audit_payload: dict[str, object]


def configure_logging() -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def infer_frequency_seconds(datetime_series: pd.Series) -> int | None:
    diffs = datetime_series.sort_values().diff().dropna().dt.total_seconds()
    if diffs.empty:
        return None
    positive_diffs = diffs[diffs > 0]
    if positive_diffs.empty:
        return None
    mode = positive_diffs.mode()
    if mode.empty:
        return None
    return int(mode.iloc[0])


def frequency_label(seconds: int | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds == 60:
        return "1m"
    if seconds == 300:
        return "5m"
    return f"{seconds}s"


def expected_bars_per_day(seconds: int | None) -> int | None:
    if seconds is None or seconds <= 0:
        return None
    session_minutes = 240
    if session_minutes * 60 % seconds != 0:
        return None
    return int(session_minutes * 60 / seconds)


def _generate_allowed_session_times(seconds: int) -> set[str]:
    morning = pd.date_range("2000-01-01 09:31:00", "2000-01-01 11:30:00", freq=f"{seconds}s")
    afternoon = pd.date_range("2000-01-01 13:01:00", "2000-01-01 15:00:00", freq=f"{seconds}s")
    return {timestamp.strftime("%H:%M:%S") for timestamp in morning.union(afternoon)}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed = df.rename(columns=lambda column: CHINESE_TO_ENGLISH.get(column, column)).copy()
    return renamed


def _safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def standardize_stock_minute_frame(raw_df: pd.DataFrame, expected_code: str) -> MinuteFoundationResult:
    original_rows = len(raw_df)
    df = _normalize_columns(raw_df)

    missing_columns = [column for column in ["datetime", "open", "high", "low", "close", "volume", "amount"] if column not in df.columns]
    if missing_columns:
        raise ValueError(f"Minute source is missing required columns: {missing_columns}")

    if "code" not in df.columns:
        df["code"] = expected_code
    if "price" not in df.columns:
        df["price"] = np.nan

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    invalid_datetime_rows = int(df["datetime"].isna().sum())
    df = df.dropna(subset=["datetime"]).copy()

    for column in ["open", "high", "low", "close", "volume", "amount", "price"]:
        df[column] = _safe_numeric(df[column])

    df["code"] = df["code"].astype(str).str.strip()
    wrong_code_rows = int((df["code"] != expected_code).sum())
    if wrong_code_rows:
        LOGGER.warning("Found %s rows with unexpected code values; keeping only %s.", wrong_code_rows, expected_code)
        df = df[df["code"] == expected_code].copy()

    df = df.sort_values("datetime").reset_index(drop=True)
    duplicate_datetime_rows = int(df.duplicated(subset=["datetime"], keep="last").sum())
    df = df.drop_duplicates(subset=["datetime"], keep="last").reset_index(drop=True)

    negative_volume_rows = int((df["volume"] < 0).sum())
    if negative_volume_rows:
        df = df[df["volume"] >= 0].copy()

    negative_amount_rows = int((df["amount"] < 0).sum())
    if negative_amount_rows:
        df = df[df["amount"] >= 0].copy()

    invalid_hlc_rows = int(((df["high"] <= 0) | (df["low"] <= 0) | (df["close"] <= 0)).sum())
    if invalid_hlc_rows:
        df = df[(df["high"] > 0) & (df["low"] > 0) & (df["close"] > 0)].copy()

    df["date"] = df["datetime"].dt.strftime("%Y-%m-%d")

    open_repair_source = df.groupby("date")["close"].shift(1)
    repairable_open_mask = df["open"] <= 0
    repaired_open_rows = int(repairable_open_mask.sum())
    if repaired_open_rows:
        df.loc[repairable_open_mask, "open"] = open_repair_source[repairable_open_mask]
        df["open"] = df["open"].fillna(df["close"])

    invalid_open_rows = int((df["open"] <= 0).sum())
    if invalid_open_rows:
        df = df[df["open"] > 0].copy()

    repaired_price_rows = int(((df["price"].isna()) | (df["price"] <= 0)).sum())
    if repaired_price_rows:
        df["price"] = df["price"].where(df["price"] > 0, df["close"])

    detected_frequency_seconds = infer_frequency_seconds(df["datetime"])
    allowed_time_rows_dropped = 0
    allowed_times = None
    if detected_frequency_seconds in {60, 300}:
        allowed_times = _generate_allowed_session_times(detected_frequency_seconds)
        time_strings = df["datetime"].dt.strftime("%H:%M:%S")
        invalid_session_mask = ~time_strings.isin(allowed_times)
        allowed_time_rows_dropped = int(invalid_session_mask.sum())
        if allowed_time_rows_dropped:
            LOGGER.warning(
                "Dropping %s rows outside regular A-share session times for %s data.",
                allowed_time_rows_dropped,
                frequency_label(detected_frequency_seconds),
            )
            df = df[~invalid_session_mask].copy()

    df = df.sort_values("datetime").reset_index(drop=True)
    df["date"] = df["datetime"].dt.strftime("%Y-%m-%d")
    df = df.loc[:, CANONICAL_COLUMNS]

    daily_summary_df = build_daily_minute_summary(df, detected_frequency_seconds)
    expected_daily_bars = expected_bars_per_day(detected_frequency_seconds)
    incomplete_days = []
    if expected_daily_bars is not None:
        incomplete_days = daily_summary_df.loc[
            daily_summary_df["bar_count"] != expected_daily_bars,
            "date",
        ].tolist()

    bar_counts = daily_summary_df["bar_count"].tolist()
    audit_payload: dict[str, object] = {
        "raw_row_count": int(original_rows),
        "canonical_row_count": int(len(df)),
        "trade_day_count": int(daily_summary_df.shape[0]),
        "coverage_start": df["datetime"].min().strftime("%Y-%m-%d %H:%M:%S"),
        "coverage_end": df["datetime"].max().strftime("%Y-%m-%d %H:%M:%S"),
        "detected_frequency_seconds": detected_frequency_seconds,
        "detected_frequency_label": frequency_label(detected_frequency_seconds),
        "expected_bars_per_day": expected_daily_bars,
        "invalid_datetime_rows_dropped": invalid_datetime_rows,
        "wrong_code_rows_filtered": wrong_code_rows,
        "duplicate_datetime_rows_dropped": duplicate_datetime_rows,
        "negative_volume_rows_dropped": negative_volume_rows,
        "negative_amount_rows_dropped": negative_amount_rows,
        "invalid_hlc_rows_dropped": invalid_hlc_rows,
        "repaired_open_rows": repaired_open_rows,
        "repaired_price_rows": repaired_price_rows,
        "off_session_rows_dropped": allowed_time_rows_dropped,
        "zero_volume_bar_count": int((df["volume"] == 0).sum()),
        "zero_amount_bar_count": int((df["amount"] == 0).sum()),
        "unique_codes": sorted(df["code"].dropna().astype(str).unique().tolist()),
        "bar_count_summary": {
            "min": int(min(bar_counts)),
            "max": int(max(bar_counts)),
            "median": float(median(bar_counts)),
            "mean": float(daily_summary_df["bar_count"].mean()),
        },
        "complete_day_count": int((daily_summary_df["is_complete_day"]).sum()),
        "incomplete_day_count": int((~daily_summary_df["is_complete_day"]).sum()),
        "incomplete_day_samples": incomplete_days[:20],
    }
    return MinuteFoundationResult(canonical_df=df, daily_summary_df=daily_summary_df, audit_payload=audit_payload)


def build_daily_minute_summary(canonical_df: pd.DataFrame, detected_frequency_seconds: int | None) -> pd.DataFrame:
    expected_daily_bars = expected_bars_per_day(detected_frequency_seconds)
    grouped = canonical_df.groupby("date", sort=True)
    summary = grouped.agg(
        first_datetime=("datetime", "min"),
        last_datetime=("datetime", "max"),
        bar_count=("datetime", "size"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        amount=("amount", "sum"),
        price=("price", "last"),
    ).reset_index()
    summary["zero_volume_bar_count"] = grouped["volume"].apply(lambda series: int((series == 0).sum())).to_numpy()
    summary["zero_amount_bar_count"] = grouped["amount"].apply(lambda series: int((series == 0).sum())).to_numpy()
    summary["zero_volume_bar_ratio"] = summary["zero_volume_bar_count"] / summary["bar_count"]
    summary["zero_amount_bar_ratio"] = summary["zero_amount_bar_count"] / summary["bar_count"]
    summary["frequency_label"] = frequency_label(detected_frequency_seconds)
    summary["expected_bar_count"] = expected_daily_bars
    summary["is_complete_day"] = summary["bar_count"] == expected_daily_bars if expected_daily_bars is not None else False
    summary["first_datetime"] = summary["first_datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    summary["last_datetime"] = summary["last_datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return summary


def run_minute_foundation(config: ProjectConfig = DEFAULT_CONFIG) -> MinuteFoundationResult:
    source_path = config.stock_ptrade_1m_path
    if not source_path.exists():
        raise FileNotFoundError(f"Primary minute source not found: {source_path}")

    LOGGER.info("Reading primary minute source: %s", source_path)
    raw_df = pd.read_csv(source_path)
    result = standardize_stock_minute_frame(raw_df, expected_code=config.stock_code)

    save_dataframe(result.canonical_df, config.canonical_1m_path)
    save_dataframe(result.daily_summary_df, config.canonical_1m_daily_summary_path)
    audit_payload = {
        "source_path": str(source_path),
        "canonical_output_path": str(config.canonical_1m_path),
        "daily_summary_output_path": str(config.canonical_1m_daily_summary_path),
        **result.audit_payload,
    }
    atomic_write_json(config.canonical_1m_audit_path, audit_payload)

    LOGGER.info("Saved canonical minute table to: %s", config.canonical_1m_path)
    LOGGER.info("Saved daily minute summary to: %s", config.canonical_1m_daily_summary_path)
    LOGGER.info("Saved audit summary to: %s", config.canonical_1m_audit_path)
    LOGGER.info(
        "Canonical minute coverage: %s -> %s | trade_days=%s | frequency=%s",
        audit_payload["coverage_start"],
        audit_payload["coverage_end"],
        audit_payload["trade_day_count"],
        audit_payload["detected_frequency_label"],
    )
    LOGGER.info(
        "Bar-count summary: min=%s max=%s median=%.1f mean=%.1f",
        audit_payload["bar_count_summary"]["min"],
        audit_payload["bar_count_summary"]["max"],
        audit_payload["bar_count_summary"]["median"],
        audit_payload["bar_count_summary"]["mean"],
    )
    LOGGER.info(
        "Dropped rows | invalid_datetime=%s duplicate_datetime=%s invalid_hlc=%s negative_volume=%s negative_amount=%s off_session=%s",
        audit_payload["invalid_datetime_rows_dropped"],
        audit_payload["duplicate_datetime_rows_dropped"],
        audit_payload["invalid_hlc_rows_dropped"],
        audit_payload["negative_volume_rows_dropped"],
        audit_payload["negative_amount_rows_dropped"],
        audit_payload["off_session_rows_dropped"],
    )
    return MinuteFoundationResult(
        canonical_df=result.canonical_df,
        daily_summary_df=result.daily_summary_df,
        audit_payload=audit_payload,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Canonicalize and audit the long-history 300661 1m source.")
    return parser


def main() -> None:
    configure_logging()
    build_parser().parse_args()
    run_minute_foundation(DEFAULT_CONFIG)


if __name__ == "__main__":
    main()

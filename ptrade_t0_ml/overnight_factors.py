from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DEFAULT_CONFIG, ProjectConfig
from .io_utils import save_dataframe
from .minute_foundation import configure_logging as configure_foundation_logging
from .minute_foundation import run_minute_foundation

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OvernightFactorBuildResult:
    factor_df: pd.DataFrame
    source_summary: dict[str, object]


def _load_trade_dates(config: ProjectConfig) -> pd.Series:
    if not config.canonical_1m_daily_summary_path.exists():
        run_minute_foundation(config)
    daily_summary_df = pd.read_csv(config.canonical_1m_daily_summary_path, usecols=["date"])
    trade_dates = pd.to_datetime(daily_summary_df["date"], errors="coerce").dropna().drop_duplicates().sort_values()
    if trade_dates.empty:
        raise ValueError("No valid China trade dates are available for overnight factor alignment.")
    return trade_dates.reset_index(drop=True)


def _standardize_source_frame(path: Path, source_name: str) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 32:
        raise FileNotFoundError(f"Missing overnight factor source file for {source_name}: {path}")

    raw_df = pd.read_csv(path)
    column_map = {
        "date": ["date", "Date", "日期"],
        "close": ["close", "Close", "收盘", "收盘价", "close_price"],
    }
    resolved_columns: dict[str, str] = {}
    for normalized_name, candidates in column_map.items():
        for candidate in candidates:
            if candidate in raw_df.columns:
                resolved_columns[normalized_name] = candidate
                break
        if normalized_name not in resolved_columns:
            raise ValueError(f"Source file for {source_name} is missing required column '{normalized_name}': {path}")

    standardized_df = raw_df.loc[:, [resolved_columns["date"], resolved_columns["close"]]].copy()
    standardized_df.columns = ["source_date", "close"]
    standardized_df["source_date"] = pd.to_datetime(standardized_df["source_date"], errors="coerce")
    standardized_df["close"] = pd.to_numeric(standardized_df["close"], errors="coerce")
    standardized_df = standardized_df.dropna(subset=["source_date", "close"]).sort_values("source_date").drop_duplicates(
        subset=["source_date"], keep="last"
    )
    if standardized_df.empty:
        raise ValueError(f"Source file for {source_name} contains no usable rows: {path}")

    standardized_df["return"] = standardized_df["close"].pct_change()
    standardized_df = standardized_df.dropna(subset=["return"]).reset_index(drop=True)
    return standardized_df


def _map_session_to_next_trade_date(source_df: pd.DataFrame, trade_dates: pd.Series) -> pd.DataFrame:
    trade_date_values = trade_dates.to_numpy(dtype="datetime64[ns]")
    mapped_dates: list[pd.Timestamp | pd.NaT] = []
    for session_date in source_df["source_date"]:
        search_value = np.datetime64((session_date + pd.Timedelta(days=1)).normalize())
        position = int(np.searchsorted(trade_date_values, search_value, side="left"))
        mapped_dates.append(pd.NaT if position >= len(trade_date_values) else pd.Timestamp(trade_date_values[position]))

    mapped_df = source_df.copy()
    mapped_df["date"] = mapped_dates
    mapped_df = mapped_df.dropna(subset=["date"]).reset_index(drop=True)
    mapped_df["date"] = mapped_df["date"].dt.strftime("%Y-%m-%d")
    return mapped_df


def _gap_risk_bucket(semiconductor_return: float, nasdaq_return: float) -> int:
    max_abs_return = max(abs(float(semiconductor_return)), abs(float(nasdaq_return)))
    if max_abs_return < 0.01:
        return 0
    if max_abs_return < 0.02:
        return 1
    if max_abs_return < 0.035:
        return 2
    return 3


def build_overnight_factor_file(config: ProjectConfig = DEFAULT_CONFIG) -> OvernightFactorBuildResult:
    trade_dates = _load_trade_dates(config)
    semiconductor_df = _standardize_source_frame(config.overnight_semiconductor_source_path, "semiconductor")
    nasdaq_df = _standardize_source_frame(config.overnight_nasdaq_source_path, "nasdaq")

    semiconductor_mapped = _map_session_to_next_trade_date(semiconductor_df, trade_dates)
    nasdaq_mapped = _map_session_to_next_trade_date(nasdaq_df, trade_dates)

    factor_df = semiconductor_mapped.loc[:, ["date", "return"]].rename(
        columns={"return": "overnight_semiconductor_return"}
    )
    factor_df = factor_df.merge(
        nasdaq_mapped.loc[:, ["date", "return"]].rename(columns={"return": "overnight_nasdaq_return"}),
        on="date",
        how="inner",
        validate="one_to_one",
    )
    if factor_df.empty:
        raise ValueError("Overnight factor merge produced no aligned rows. Check source coverage and date mapping.")

    factor_df["overnight_gap_risk_bucket"] = factor_df.apply(
        lambda row: _gap_risk_bucket(row["overnight_semiconductor_return"], row["overnight_nasdaq_return"]),
        axis=1,
    )
    factor_df = factor_df.sort_values("date").reset_index(drop=True)
    save_dataframe(factor_df, config.overnight_factors_path)

    source_summary = {
        "semiconductor_source_path": str(config.overnight_semiconductor_source_path),
        "nasdaq_source_path": str(config.overnight_nasdaq_source_path),
        "output_path": str(config.overnight_factors_path),
        "row_count": int(len(factor_df)),
        "coverage_start": str(factor_df.iloc[0]["date"]),
        "coverage_end": str(factor_df.iloc[-1]["date"]),
    }
    LOGGER.info("Saved overnight factors to: %s", config.overnight_factors_path)
    LOGGER.info(
        "Overnight factor coverage: %s -> %s | rows=%s",
        source_summary["coverage_start"],
        source_summary["coverage_end"],
        source_summary["row_count"],
    )
    return OvernightFactorBuildResult(factor_df=factor_df, source_summary=source_summary)


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Build overnight factor CSV from user-supplied SOXX and Nasdaq daily sources."
    )


def main() -> None:
    configure_foundation_logging()
    build_parser().parse_args()
    build_overnight_factor_file(DEFAULT_CONFIG)


if __name__ == "__main__":
    main()

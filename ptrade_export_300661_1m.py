from __future__ import annotations

import builtins
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd


SECURITY_INPUT = "300661"
FREQUENCY = "1m"
FQ = "pre"
FIELDS = ["open", "high", "low", "close", "volume", "money", "price"]
START_DATE = "2005-01-01 09:30"
CHUNK_MONTHS = 1
RECENT_COUNT_CANDIDATES = [200000, 100000, 50000, 20000, 10000, 5000, 1000]

_HAS_RUN = False


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def emit(message: str) -> None:
    logger = globals().get("log")
    if logger is not None and hasattr(logger, "info"):
        try:
            logger.info(message)
            return
        except Exception:  # noqa: BLE001
            pass
    logging.info(message)


def normalize_security(symbol: str) -> str:
    raw = "".join(ch for ch in str(symbol).strip().upper() if ch.isalnum() or ch in "._")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 6:
        raise ValueError(f"expected 6-digit security code, got {symbol!r}")

    if raw.endswith((".SZ", ".XSHE")) or digits.startswith(("0", "1", "2", "3")):
        return f"{digits}.SZ"
    if raw.endswith((".SS", ".XSHG")) or digits.startswith(("5", "6", "9")):
        return f"{digits}.SS"
    if raw.endswith(".BJ") or digits.startswith(("4", "8")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def resolve_api(name: str) -> Callable[..., Any] | None:
    candidate = globals().get(name)
    if callable(candidate):
        return candidate

    builtin_candidate = getattr(builtins, name, None)
    if callable(builtin_candidate):
        return builtin_candidate

    return None


def get_output_path(security: str) -> Path:
    research_path_fn = resolve_api("get_research_path")
    if callable(research_path_fn):
        try:
            base_dir = Path(research_path_fn())
        except Exception:  # noqa: BLE001
            base_dir = Path.cwd()
    else:
        try:
            base_dir = Path(__file__).resolve().parent
        except NameError:
            base_dir = Path.cwd()

    output_dir = base_dir / "data" / "ptrade"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{security.replace('.', '_')}_1m_ptrade.csv"


def month_end(ts: pd.Timestamp) -> pd.Timestamp:
    if ts.month == 12:
        next_month = pd.Timestamp(year=ts.year + 1, month=1, day=1)
    else:
        next_month = pd.Timestamp(year=ts.year, month=ts.month + 1, day=1)
    return next_month - pd.Timedelta(minutes=1)


def add_months(ts: pd.Timestamp, months: int) -> pd.Timestamp:
    year = ts.year + (ts.month - 1 + months) // 12
    month = (ts.month - 1 + months) % 12 + 1
    day = 1
    return pd.Timestamp(year=year, month=month, day=day, hour=ts.hour, minute=ts.minute)


def iter_month_ranges(start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    ranges: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    current = start_ts
    while current <= end_ts:
        next_anchor = add_months(current.replace(day=1), CHUNK_MONTHS)
        current_end = min(end_ts, next_anchor - pd.Timedelta(minutes=1))
        ranges.append((current, current_end))
        current = current_end + pd.Timedelta(minutes=1)
    return ranges


def standardize_price_frame(df: pd.DataFrame, security: str) -> pd.DataFrame:
    if isinstance(df, dict):
        if security in df:
            df = df[security]
        elif len(df) == 1:
            df = next(iter(df.values()))
        else:
            raise ValueError(f"unsupported dict result keys: {list(df.keys())}")

    if df is None or df.empty:
        return pd.DataFrame(columns=["datetime", "code", "open", "high", "low", "close", "volume", "amount", "price"])

    result = df.copy()
    if "code" not in result.columns:
        result["code"] = security

    if result.index.name is not None or not isinstance(result.index, pd.RangeIndex):
        result = result.reset_index()

    first_col = result.columns[0]
    if first_col != "datetime":
        result = result.rename(columns={first_col: "datetime"})

    rename_map = {"money": "amount"}
    result = result.rename(columns=rename_map)

    required_columns = ["datetime", "code", "open", "high", "low", "close", "volume"]
    missing = [column for column in required_columns if column not in result.columns]
    if missing:
        raise ValueError(f"missing expected columns from get_price/get_history: {missing}")

    if "amount" not in result.columns:
        result["amount"] = pd.NA
    if "price" not in result.columns:
        result["price"] = result["close"]

    result["datetime"] = pd.to_datetime(result["datetime"], errors="coerce")
    result = result.dropna(subset=["datetime"])

    numeric_columns = ["open", "high", "low", "close", "volume", "amount", "price"]
    for column in numeric_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    result = result[
        ["datetime", "code", "open", "high", "low", "close", "volume", "amount", "price"]
    ].sort_values("datetime")
    result = result.drop_duplicates(subset=["datetime", "code"], keep="last").reset_index(drop=True)
    return result


def export_via_get_price(security: str, output_path: Path) -> pd.DataFrame:
    get_price_fn = resolve_api("get_price")
    if get_price_fn is None:
        raise RuntimeError("get_price is not available in the current runtime")

    start_ts = pd.Timestamp(START_DATE)
    end_ts = pd.Timestamp(datetime.now().date()) - pd.Timedelta(minutes=1)
    end_ts = end_ts.replace(hour=15, minute=0)

    emit(
        f"[get_price] start export for {security}, frequency={FREQUENCY}, fq={FQ}, "
        f"range={start_ts.strftime('%Y-%m-%d %H:%M')} -> {end_ts.strftime('%Y-%m-%d %H:%M')}"
    )
    emit("[get_price] note: according to PTrade docs, returned data does not include current day")

    frames: list[pd.DataFrame] = []
    for chunk_start, chunk_end in iter_month_ranges(start_ts, end_ts):
        emit(
            f"[get_price] requesting chunk {chunk_start.strftime('%Y-%m-%d %H:%M')} -> "
            f"{chunk_end.strftime('%Y-%m-%d %H:%M')}"
        )
        chunk = get_price_fn(
            security=security,
            start_date=chunk_start.strftime("%Y-%m-%d %H:%M"),
            end_date=chunk_end.strftime("%Y-%m-%d %H:%M"),
            frequency=FREQUENCY,
            fields=FIELDS,
            fq=FQ,
        )
        chunk_df = standardize_price_frame(chunk, security)
        emit(f"[get_price] chunk rows={len(chunk_df)}")
        if not chunk_df.empty:
            frames.append(chunk_df)

    if not frames:
        raise RuntimeError("get_price returned no rows across all chunks")

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["datetime", "code"], keep="last").sort_values("datetime")
    merged.reset_index(drop=True, inplace=True)
    merged.to_csv(output_path, index=False, encoding="utf-8-sig")

    emit(
        f"[get_price] export done, rows={len(merged)}, start={merged.iloc[0]['datetime']}, "
        f"end={merged.iloc[-1]['datetime']}, output={output_path}"
    )
    return merged


def call_get_history(get_history_fn: Callable[..., Any], security: str, count: int) -> Any:
    try:
        return get_history_fn(
            count,
            frequency=FREQUENCY,
            field=FIELDS,
            security_list=security,
            fq=FQ,
            is_dict=False,
        )
    except TypeError:
        return get_history_fn(
            count,
            frequency=FREQUENCY,
            field=FIELDS,
            security_list=security,
        )


def export_via_get_history(security: str, output_path: Path) -> pd.DataFrame:
    get_history_fn = resolve_api("get_history")
    if get_history_fn is None:
        raise RuntimeError("get_history is not available in the current runtime")

    emit("[get_history] get_price unavailable, fallback to recent-bar export mode")
    last_error: Exception | None = None

    for count in RECENT_COUNT_CANDIDATES:
        try:
            emit(f"[get_history] trying count={count}")
            history = call_get_history(get_history_fn, security, count)
            history_df = standardize_price_frame(history, security)
            if history_df.empty:
                continue
            history_df.to_csv(output_path, index=False, encoding="utf-8-sig")
            emit(
                f"[get_history] export done, rows={len(history_df)}, "
                f"start={history_df.iloc[0]['datetime']}, end={history_df.iloc[-1]['datetime']}, output={output_path}"
            )
            return history_df
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            emit(f"[get_history] count={count} failed: {exc}")

    raise RuntimeError(f"get_history fallback failed: {last_error}") from last_error


def run_export() -> pd.DataFrame:
    configure_logging()
    security = normalize_security(SECURITY_INPUT)
    output_path = get_output_path(security)

    try:
        return export_via_get_price(security, output_path)
    except Exception as price_error:  # noqa: BLE001
        emit(f"[get_price] failed: {price_error}")
        emit("[fallback] switching to get_history recent-bar mode")
        return export_via_get_history(security, output_path)


def initialize(context=None) -> None:
    global _HAS_RUN
    if _HAS_RUN:
        return
    _HAS_RUN = True
    try:
        run_export()
    except Exception as exc:  # noqa: BLE001
        emit(f"[initialize] export failed: {exc}")


def handle_data(context=None, data=None) -> None:
    return None


def main() -> int:
    try:
        run_export()
        return 0
    except Exception as exc:  # noqa: BLE001
        configure_logging()
        logging.error("ptrade export failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

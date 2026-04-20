import json
import logging
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlencode

# 添加 vendor 目录到 sys.path 以便导入下载的依赖
vendor_dir = str(Path(__file__).parent / "vendor")
if vendor_dir not in sys.path:
    sys.path.insert(0, vendor_dir)

import akshare as ak
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
LOGGER = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
MARKET_CLOSE_TIME = time(hour=15, minute=0)
EM_BASE_URL = "https://push2his.eastmoney.com/api/qt/stock"


def _safe_read_csv(csv_path: Path, required_column: str) -> pd.DataFrame:
    if not csv_path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:
        LOGGER.warning("Read %s failed, fallback to empty frame: %s", csv_path.name, exc)
        return pd.DataFrame()
    if df.empty or required_column not in df.columns:
        return pd.DataFrame()
    return df


def _curl_json(url: str, params: dict[str, str], timeout_seconds: int = 20) -> dict:
    full_url = f"{url}?{urlencode(params)}"
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--http1.1",
        "--retry",
        "2",
        "--retry-all-errors",
        "--max-time",
        str(timeout_seconds),
        "--header",
        "User-Agent: Mozilla/5.0",
        "--header",
        "Accept: application/json, text/plain, */*",
        "--header",
        "Referer: https://quote.eastmoney.com/",
        full_url,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"curl failed with exit code {result.returncode}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON response from Eastmoney: {exc}") from exc


def _get_em_klines(secid: str, klt: str, fqt: str = "1", beg: str = "19700101", end: str = "20500101") -> list[str]:
    data = _curl_json(
        f"{EM_BASE_URL}/kline/get",
        params={
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "klt": klt,
            "fqt": fqt,
            "secid": secid,
            "beg": beg,
            "end": end,
        },
    )
    if not data.get("data") or not data["data"].get("klines"):
        return []
    return data["data"]["klines"]


def _get_em_trends(secid: str, ndays: str = "5") -> list[str]:
    data = _curl_json(
        f"{EM_BASE_URL}/trends2/get",
        params={
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "ndays": ndays,
            "iscr": "0",
            "secid": secid,
        },
    )
    if not data.get("data") or not data["data"].get("trends"):
        return []
    return data["data"]["trends"]


def _load_trading_calendar_dates() -> set[date]:
    try:
        calendar_df = ak.tool_trade_date_hist_sina()
    except Exception as exc:
        LOGGER.warning("Falling back to weekday-only freshness check because trading calendar load failed: %s", exc)
        return set()

    if "trade_date" not in calendar_df.columns:
        LOGGER.warning(
            "Falling back to weekday-only freshness check because trading calendar has no trade_date column."
        )
        return set()

    trading_dates: set[date] = set()
    for value in calendar_df["trade_date"].tolist():
        try:
            trading_dates.add(pd.Timestamp(value).date())
        except Exception:
            continue
    return trading_dates


def _previous_trading_day(reference_date: date, trading_dates: set[date] | None = None) -> date:
    if trading_dates:
        candidate = reference_date - timedelta(days=1)
        safety_limit = reference_date - timedelta(days=30)
        while candidate >= safety_limit:
            if candidate in trading_dates:
                return candidate
            candidate -= timedelta(days=1)
        raise ValueError(f"Could not find previous trading day within 30 days before {reference_date.isoformat()}.")

    candidate = reference_date - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _expected_latest_date(now_dt: datetime, trading_dates: set[date] | None = None) -> date:
    today = now_dt.date()
    if trading_dates:
        if today in trading_dates and now_dt.time() >= MARKET_CLOSE_TIME:
            return today
        return _previous_trading_day(today, trading_dates)

    if today.weekday() < 5 and now_dt.time() >= MARKET_CLOSE_TIME:
        return today
    return _previous_trading_day(today, trading_dates=None)


def _extract_latest_date(df: pd.DataFrame, column_name: str) -> date | None:
    if df.empty or column_name not in df.columns:
        return None
    series = pd.to_datetime(df[column_name], errors="coerce").dropna()
    if series.empty:
        return None
    return series.dt.date.max()


def get_em_daily(secid: str) -> pd.DataFrame:
    """直接使用东方财富接口获取日线数据。"""
    try:
        klines = _get_em_klines(secid=secid, klt="101", fqt="1")
        if not klines:
            return pd.DataFrame()
        parsed_rows = []
        for item in klines:
            parts = item.split(",")
            if len(parts) < 7:
                continue
            parsed_rows.append(
                {
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                    "amount": float(parts[6]),
                }
            )
        df = pd.DataFrame(parsed_rows)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        return df[["date", "open", "close", "high", "low", "volume", "amount"]]
    except Exception as exc:
        LOGGER.error("Fetch %s failed: %s", secid, exc)
        return pd.DataFrame()


def _normalize_daily_fallback(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.copy()
    if "date" not in result.columns:
        return pd.DataFrame()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result = result.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")
    for column in ["open", "close", "high", "low", "volume"]:
        if column not in result.columns:
            result[column] = pd.NA
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if "amount" not in result.columns:
        result["amount"] = pd.NA
    result["amount"] = pd.to_numeric(result["amount"], errors="coerce")
    result["date"] = result["date"].dt.strftime("%Y-%m-%d")
    return result[["date", "open", "close", "high", "low", "volume", "amount"]].reset_index(drop=True)


def _normalize_tx_daily(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.copy()
    if "date" not in result.columns:
        return pd.DataFrame()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result = result.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")
    for column in ["open", "close", "high", "low", "amount"]:
        if column not in result.columns:
            result[column] = pd.NA
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if "volume" not in result.columns:
        result["volume"] = pd.NA
    result["volume"] = pd.to_numeric(result["volume"], errors="coerce")
    result["date"] = result["date"].dt.strftime("%Y-%m-%d")
    return result[["date", "open", "close", "high", "low", "volume", "amount"]].reset_index(drop=True)


def _build_daily_snapshot_row(
    *,
    trading_date: date,
    open_price: object,
    close_price: object,
    high_price: object,
    low_price: object,
    volume: object,
    amount: object,
) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "date": trading_date.isoformat(),
                "open": open_price,
                "close": close_price,
                "high": high_price,
                "low": low_price,
                "volume": volume,
                "amount": amount,
            }
        ]
    )
    return _normalize_daily_fallback(frame)


def _fetch_index_spot_snapshot(symbol: str, trading_date: date) -> pd.DataFrame:
    LOGGER.warning("Historical index daily is stale, trying Sina index spot snapshot for %s", symbol)
    df = ak.stock_zh_index_spot_sina()
    if df is None or df.empty:
        return pd.DataFrame()
    matched = df[df["代码"].astype(str) == symbol.replace("sz", "")]
    if matched.empty:
        return pd.DataFrame()
    row = matched.iloc[0]
    return _build_daily_snapshot_row(
        trading_date=trading_date,
        open_price=row.get("今开"),
        close_price=row.get("最新价"),
        high_price=row.get("最高"),
        low_price=row.get("最低"),
        volume=row.get("成交量"),
        amount=row.get("成交额"),
    )


def _fetch_etf_spot_snapshot(symbol: str, trading_date: date) -> pd.DataFrame:
    LOGGER.warning("Historical ETF daily is stale, trying Eastmoney ETF spot snapshot for %s", symbol)
    df = ak.fund_etf_spot_em()
    if df is None or df.empty:
        return pd.DataFrame()
    matched = df[df["代码"].astype(str) == symbol.replace("sh", "").replace("sz", "")]
    if matched.empty:
        return pd.DataFrame()
    row = matched.iloc[0]
    return _build_daily_snapshot_row(
        trading_date=trading_date,
        open_price=row.get("开盘价"),
        close_price=row.get("最新价"),
        high_price=row.get("最高价"),
        low_price=row.get("最低价"),
        volume=row.get("成交量"),
        amount=row.get("成交额"),
    )


def _select_preferred_daily_frame(
    candidate_fetchers: list[tuple[str, Callable[[], pd.DataFrame]]],
    expected_date: date | None = None,
) -> pd.DataFrame:
    freshest_df = pd.DataFrame()
    freshest_date: date | None = None

    for label, fetcher in candidate_fetchers:
        try:
            candidate_df = fetcher()
        except Exception as exc:
            LOGGER.error("%s failed: %s", label, exc)
            continue

        if candidate_df is None or candidate_df.empty:
            LOGGER.warning("%s returned empty data", label)
            continue

        latest_date = _extract_latest_date(candidate_df, "date")
        if latest_date is None:
            LOGGER.warning("%s returned data without a valid latest date", label)
            continue

        if freshest_date is None or latest_date > freshest_date:
            freshest_df = candidate_df
            freshest_date = latest_date

        if expected_date is None or latest_date >= expected_date:
            LOGGER.info("%s reached expected daily freshness: latest=%s", label, latest_date.isoformat())
            return candidate_df

        LOGGER.warning(
            "%s is still stale after fetch: latest=%s expected=%s; trying next source",
            label,
            latest_date.isoformat(),
            expected_date.isoformat(),
        )

    return freshest_df


def get_daily_with_fallback(secid: str, fallback_symbol: str, expected_date: date | None = None) -> pd.DataFrame:
    if fallback_symbol.startswith("sz399"):
        candidate_fetchers: list[tuple[str, Callable[[], pd.DataFrame]]] = [
            (f"Eastmoney daily {secid}", lambda: get_em_daily(secid)),
            (
                f"Sina index daily {fallback_symbol}",
                lambda: _normalize_daily_fallback(ak.stock_zh_index_daily(symbol=fallback_symbol)),
            ),
            (
                f"Sina index spot snapshot {fallback_symbol}",
                lambda: _fetch_index_spot_snapshot(fallback_symbol, expected_date or datetime.now().date()),
            ),
        ]
    else:
        candidate_fetchers = [
            (f"Eastmoney daily {secid}", lambda: get_em_daily(secid)),
            (
                f"Sina ETF daily {fallback_symbol}",
                lambda: _normalize_daily_fallback(ak.fund_etf_hist_sina(symbol=fallback_symbol)),
            ),
            (
                f"Sina stock daily {fallback_symbol}",
                lambda: _normalize_daily_fallback(ak.stock_zh_a_daily(symbol=fallback_symbol)),
            ),
            (
                f"Tencent stock daily {fallback_symbol}",
                lambda: _normalize_tx_daily(ak.stock_zh_a_hist_tx(symbol=fallback_symbol)),
            ),
            (
                f"Eastmoney ETF spot snapshot {fallback_symbol}",
                lambda: _fetch_etf_spot_snapshot(fallback_symbol, expected_date or datetime.now().date()),
            ),
        ]

    return _select_preferred_daily_frame(candidate_fetchers, expected_date=expected_date)


def update_daily_file(
    secid: str,
    csv_filename: str,
    fallback_symbol: str,
    data_dir: Path = DATA_DIR,
    expected_date: date | None = None,
) -> date | None:
    csv_path = data_dir / csv_filename
    LOGGER.info("--- 更新 %s (日线数据) ---", csv_filename)

    df_old = _safe_read_csv(csv_path, "date")
    df_new = get_daily_with_fallback(secid, fallback_symbol=fallback_symbol, expected_date=expected_date)
    if df_new.empty:
        LOGGER.warning("新数据 %s 获取为空，保留现有文件", secid)
        return _extract_latest_date(df_old, "date")

    if not df_old.empty:
        df_old["date"] = pd.to_datetime(df_old["date"]).dt.strftime("%Y-%m-%d")
        df_merged = pd.concat([df_old, df_new], ignore_index=True)
        df_merged = df_merged.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    else:
        df_merged = df_new

    cols = ["date", "open", "close", "high", "low", "volume", "amount"]
    df_merged = df_merged[cols]
    df_merged.to_csv(csv_path, index=False)
    latest_date = _extract_latest_date(df_merged, "date")
    LOGGER.info("%s 更新完成! 最新的日期: %s, 总行数: %s", csv_filename, df_merged["date"].iloc[-1], len(df_merged))
    return latest_date


def update_300661_1m(data_dir: Path = DATA_DIR) -> date | None:
    csv_path = data_dir / "300661_SZ_1m_ptrade.csv"
    LOGGER.info("--- 更新 300661_SZ_1m_ptrade.csv (1分钟数据) ---")

    df_old = _safe_read_csv(csv_path, "datetime")

    try:
        trends = _get_em_trends(secid="0.300661", ndays="5")
    except Exception as exc:
        LOGGER.error("东方财富获取分钟线失败: %s", exc)
        trends = []

    if not trends:
        LOGGER.warning("东方财富分钟线为空，切换到新浪 minute fallback")
        try:
            fallback_df = ak.stock_zh_a_minute(symbol="sz300661", period="1", adjust="qfq")
        except Exception as exc:
            LOGGER.error("新浪分钟线 fallback 失败: %s", exc)
            return _extract_latest_date(df_old, "datetime")

        if fallback_df is None or fallback_df.empty:
            LOGGER.warning("新浪分钟线 fallback 为空，保留现有文件")
            return _extract_latest_date(df_old, "datetime")

        rename_map = {
            "day": "datetime",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
            "volume": "volume",
        }
        df_new = fallback_df.rename(columns=rename_map).copy()
        if "amount" not in df_new.columns:
            df_new["amount"] = pd.NA
        if "price" not in df_new.columns:
            df_new["price"] = pd.to_numeric(df_new["close"], errors="coerce")
    else:
        parsed_rows = []
        for item in trends:
            parts = item.split(",")
            if len(parts) < 8:
                continue
            parsed_rows.append(
                {
                    "datetime": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                    "amount": float(parts[6]),
                    "price": float(parts[7]),
                }
            )
        df_new = pd.DataFrame(parsed_rows)

    if df_new.empty:
        LOGGER.warning("新拉取的分钟线解析为空，保留现有文件")
        return _extract_latest_date(df_old, "datetime")

    if "open" in df_new.columns and "close" in df_new.columns:
        df_new["open"] = df_new.apply(lambda row: row["close"] if row["open"] == 0.0 else row["open"], axis=1)

    df_new["code"] = "300661.SZ"
    cols = ["datetime", "code", "open", "high", "low", "close", "volume", "amount", "price"]
    for column in cols:
        if column not in df_new.columns:
            df_new[column] = pd.NA
    df_new = df_new[cols]
    df_new["datetime"] = pd.to_datetime(df_new["datetime"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    if not df_old.empty:
        df_old["datetime"] = pd.to_datetime(df_old["datetime"]).dt.strftime("%Y-%m-%d %H:%M:%S")
        df_merged = pd.concat([df_old, df_new], ignore_index=True)
        df_merged = (
            df_merged.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last").reset_index(drop=True)
        )
    else:
        df_merged = df_new

    df_merged.to_csv(csv_path, index=False)
    latest_date = _extract_latest_date(df_merged, "datetime")
    LOGGER.info(
        "300661 1分钟线更新完成! 最新一分钟时间: %s, 总行数: %s",
        df_merged["datetime"].iloc[-1],
        len(df_merged),
    )
    return latest_date


def validate_backfill_success(
    data_dir: Path = DATA_DIR,
    now_dt: datetime | None = None,
    trading_dates: set[date] | None = None,
) -> dict[str, object]:
    if now_dt is None:
        now_dt = datetime.now()
    if trading_dates is None:
        trading_dates = _load_trading_calendar_dates()

    expected_date = _expected_latest_date(now_dt, trading_dates=trading_dates if trading_dates else None)
    source_dates = {
        "stock_1m": _extract_latest_date(_safe_read_csv(data_dir / "300661_SZ_1m_ptrade.csv", "datetime"), "datetime"),
        "index_daily": _extract_latest_date(_safe_read_csv(data_dir / "399006.csv", "date"), "date"),
        "sector_daily": _extract_latest_date(_safe_read_csv(data_dir / "512480.csv", "date"), "date"),
    }
    hard_stale_sources = {
        name: value.isoformat() if value else "missing"
        for name, value in source_dates.items()
        if name == "stock_1m" and (value is None or value < expected_date)
    }
    soft_stale_sources = {
        name: value.isoformat() if value else "missing"
        for name, value in source_dates.items()
        if name in {"index_daily", "sector_daily"} and (value is None or value < expected_date)
    }
    if hard_stale_sources:
        raise ValueError(
            "Backfill hard dependency is stale. "
            f"current_local_time={now_dt.isoformat(timespec='seconds')}, "
            f"expected_latest_date={expected_date.isoformat()}, "
            "source_dates={"
            + ", ".join(f"{name}:{value.isoformat() if value else 'missing'}" for name, value in source_dates.items())
            + "}. "
            "300661 1m is a hard dependency; confirm the local minute backfill reached the latest trading day before continuing."
        )

    summary = {
        "expected_latest_date": expected_date.isoformat(),
        **{name: value.isoformat() for name, value in source_dates.items() if value is not None},
        "soft_stale_sources": soft_stale_sources,
    }
    if soft_stale_sources:
        LOGGER.warning(
            "Backfill soft dependencies are stale, but continuing. expected_latest_date=%s soft_stale_sources=%s",
            expected_date.isoformat(),
            soft_stale_sources,
        )
    LOGGER.info("Backfill freshness check passed: %s", summary)
    return summary


def run_daily_backfill(data_dir: Path = DATA_DIR, now_dt: datetime | None = None) -> dict[str, str]:
    if now_dt is None:
        now_dt = datetime.now()
    trading_dates = _load_trading_calendar_dates()
    expected_date = _expected_latest_date(now_dt, trading_dates=trading_dates if trading_dates else None)

    update_daily_file(
        "1.512480",
        "512480.csv",
        fallback_symbol="sh512480",
        data_dir=data_dir,
        expected_date=expected_date,
    )
    update_daily_file(
        "0.399006",
        "399006.csv",
        fallback_symbol="sz399006",
        data_dir=data_dir,
        expected_date=expected_date,
    )
    update_300661_1m(data_dir=data_dir)
    return validate_backfill_success(data_dir=data_dir, now_dt=now_dt, trading_dates=trading_dates)


def main() -> int:
    try:
        run_daily_backfill()
    except Exception as exc:
        LOGGER.error("Daily backfill failed validation: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

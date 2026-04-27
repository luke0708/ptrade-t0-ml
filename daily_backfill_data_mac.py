from __future__ import annotations

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

try:
    import yfinance as yf

    _YFINANCE_AVAILABLE = True
except Exception:
    # Python 3.9 上 yfinance 新版会因 `list[A] | list[B]` 语法抛 TypeError，
    # 统一捕获所有导入异常，退化到 AkShare fallback
    _YFINANCE_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
LOGGER = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
COMPLETE_DAY_CUTOFF_TIME = time(hour=15, minute=10)
EM_BASE_URL = "https://push2his.eastmoney.com/api/qt/stock"

# 分钟线完整性容忍阈值：末尾 ≤ N 根缺失视为 soft warning，不阻断流程
# 新浪/东方财富 fallback 收盘前最后 1~2 根常缺，属正常数据源噪声
MAX_MISSING_BARS_TOLERATED = 2


def _expected_a_share_minute_timestamps(trading_date: date) -> list[datetime]:
    morning = pd.date_range(
        datetime.combine(trading_date, time(hour=9, minute=31)),
        datetime.combine(trading_date, time(hour=11, minute=30)),
        freq="1min",
    )
    afternoon = pd.date_range(
        datetime.combine(trading_date, time(hour=13, minute=1)),
        datetime.combine(trading_date, time(hour=15, minute=0)),
        freq="1min",
    )
    return [*morning.to_pydatetime(), *afternoon.to_pydatetime()]


def _assess_minute_day_completeness(
    df: pd.DataFrame,
    target_date: date,
) -> dict[str, object]:
    if df.empty or "datetime" not in df.columns:
        return {
            "target_date": target_date.isoformat(),
            "observed_rows": 0,
            "expected_rows": 240,
            "missing_timestamps": [],
            "missing_count": 240,
            "is_complete": False,
        }

    dt_series = pd.to_datetime(df["datetime"], errors="coerce")
    session_df = df.loc[dt_series.dt.date == target_date].copy()
    if session_df.empty:
        return {
            "target_date": target_date.isoformat(),
            "observed_rows": 0,
            "expected_rows": 240,
            "missing_timestamps": [],
            "missing_count": 240,
            "is_complete": False,
        }

    session_df["datetime"] = pd.to_datetime(session_df["datetime"], errors="coerce")
    observed = {
        ts.to_pydatetime().replace(tzinfo=None)
        for ts in session_df["datetime"].dropna().drop_duplicates().tolist()
    }
    expected = _expected_a_share_minute_timestamps(target_date)
    missing_timestamps = [ts.strftime("%Y-%m-%d %H:%M:%S") for ts in expected if ts not in observed]
    return {
        "target_date": target_date.isoformat(),
        "observed_rows": len(observed),
        "expected_rows": len(expected),
        "missing_timestamps": missing_timestamps,
        "missing_count": len(missing_timestamps),
        "is_complete": not missing_timestamps,
    }


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
        if today in trading_dates and now_dt.time() >= COMPLETE_DAY_CUTOFF_TIME:
            return today
        return _previous_trading_day(today, trading_dates)

    if today.weekday() < 5 and now_dt.time() >= COMPLETE_DAY_CUTOFF_TIME:
        return today
    return _previous_trading_day(today, trading_dates=None)


def _clip_daily_frame_to_expected_date(df: pd.DataFrame, expected_date: date | None) -> pd.DataFrame:
    if expected_date is None or df.empty or "date" not in df.columns:
        return df
    result = df.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result = result.dropna(subset=["date"])
    result = result.loc[result["date"].dt.date <= expected_date].copy()
    if result.empty:
        return result
    result["date"] = result["date"].dt.strftime("%Y-%m-%d")
    return result.reset_index(drop=True)


def _clip_minute_frame_to_expected_date(df: pd.DataFrame, expected_date: date | None) -> pd.DataFrame:
    if expected_date is None or df.empty or "datetime" not in df.columns:
        return df
    result = df.copy()
    result["datetime"] = pd.to_datetime(result["datetime"], errors="coerce")
    result = result.dropna(subset=["datetime"])
    result = result.loc[result["datetime"].dt.date <= expected_date].copy()
    if result.empty:
        return result
    result["datetime"] = result["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return result.reset_index(drop=True)


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


def _normalize_cn_daily_fallback(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize AkShare Chinese-column daily frames into the project daily schema."""
    if df is None or df.empty:
        return pd.DataFrame()
    rename_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
    }
    return _normalize_daily_fallback(df.rename(columns=rename_map))


def _strip_market_prefix(symbol: str) -> str:
    return symbol.replace("sh", "").replace("sz", "")


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
        index_code = _strip_market_prefix(fallback_symbol)
        candidate_fetchers: list[tuple[str, Callable[[], pd.DataFrame]]] = [
            (f"Eastmoney daily {secid}", lambda: get_em_daily(secid)),
            (
                f"Sina index daily {fallback_symbol}",
                lambda: _normalize_daily_fallback(ak.stock_zh_index_daily(symbol=fallback_symbol)),
            ),
            (
                f"Tencent index daily {fallback_symbol}",
                lambda: _normalize_tx_daily(ak.stock_zh_a_hist_tx(symbol=fallback_symbol)),
            ),
            (
                f"Tencent index daily tx {fallback_symbol}",
                lambda: _normalize_tx_daily(ak.stock_zh_index_daily_tx(symbol=fallback_symbol)),
            ),
            (
                f"Eastmoney index daily em {fallback_symbol}",
                lambda: _normalize_daily_fallback(
                    ak.stock_zh_index_daily_em(
                        symbol=fallback_symbol,
                        start_date="19700101",
                        end_date="20500101",
                    )
                ),
            ),
            (
                f"Eastmoney index daily hist {index_code}",
                lambda: _normalize_cn_daily_fallback(
                    ak.index_zh_a_hist(
                        symbol=index_code,
                        period="daily",
                        start_date="19700101",
                        end_date="20500101",
                    )
                ),
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
    df_old = _clip_daily_frame_to_expected_date(df_old, expected_date)
    df_new = _clip_daily_frame_to_expected_date(df_new, expected_date)
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


# ---------------------------------------------------------------------------
# 美股指数日线（^SOX 费城半导体 / ^IXIC 纳斯达克）
# ---------------------------------------------------------------------------


def get_us_index_daily(ticker: str) -> pd.DataFrame:
    """拉取美股指数日线数据，优先使用 yfinance，失败则 fallback 到 AkShare。

    输出列：date, open, close, high, low, volume, amount
    amount 字段对美股指数没有成交额，填 pd.NA 保持格式一致。
    """
    # --- 主力：yfinance ---
    if _YFINANCE_AVAILABLE:
        try:
            LOGGER.info("[yfinance] 拉取 %s 日线数据...", ticker)
            raw = yf.download(ticker, period="max", auto_adjust=True, progress=False)
            if raw is not None and not raw.empty:
                df = raw.reset_index()
                # yfinance 列名可能是 MultiIndex，先 flatten
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                df = df.rename(
                    columns={
                        "Date": "date",
                        "Open": "open",
                        "Close": "close",
                        "High": "high",
                        "Low": "low",
                        "Volume": "volume",
                    }
                )
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                df["amount"] = pd.NA
                cols = ["date", "open", "close", "high", "low", "volume", "amount"]
                for col in cols:
                    if col not in df.columns:
                        df[col] = pd.NA
                df = df[cols].copy()
                for col in ["open", "close", "high", "low", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")
                LOGGER.info("[yfinance] %s 拉取成功，共 %d 行", ticker, len(df))
                return df.reset_index(drop=True)
        except Exception as exc:
            LOGGER.warning("[yfinance] %s 拉取失败，尝试 AkShare fallback: %s", ticker, exc)

    # --- Fallback：AkShare stock_us_hist ---
    # AkShare 用 symbol 格式如 ".SOX" / ".IXIC"（去掉 ^）
    ak_symbol = ticker.lstrip("^").lstrip(".")
    try:
        LOGGER.info("[AkShare] 拉取美股指数 %s 日线数据...", ak_symbol)
        raw = ak.stock_us_hist(symbol=ak_symbol, period="daily", adjust="")
        if raw is not None and not raw.empty:
            df = raw.rename(
                columns={
                    "日期": "date",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume",
                    "成交额": "amount",
                }
            ).copy()
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            if "amount" not in df.columns:
                df["amount"] = pd.NA
            cols = ["date", "open", "close", "high", "low", "volume", "amount"]
            for col in cols:
                if col not in df.columns:
                    df[col] = pd.NA
            df = df[cols]
            for col in ["open", "close", "high", "low", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")
            LOGGER.info("[AkShare] %s 拉取成功，共 %d 行", ak_symbol, len(df))
            return df.reset_index(drop=True)
    except Exception as exc:
        LOGGER.error("[AkShare] %s 拉取失败: %s", ak_symbol, exc)

    return pd.DataFrame()


def update_us_index_file(
    ticker: str,
    csv_filename: str,
    data_dir: Path = DATA_DIR,
) -> date | None:
    """拉取指定美股指数日线，增量合并后落盘。"""
    csv_path = data_dir / csv_filename
    LOGGER.info("--- 更新 %s (%s 日线数据) ---", csv_filename, ticker)

    df_old = _safe_read_csv(csv_path, "date")
    df_new = get_us_index_daily(ticker)

    if df_new.empty:
        LOGGER.warning("%s 新数据获取为空，保留现有文件", ticker)
        return _extract_latest_date(df_old, "date")

    if not df_old.empty:
        df_old["date"] = pd.to_datetime(df_old["date"]).dt.strftime("%Y-%m-%d")
        df_merged = pd.concat([df_old, df_new], ignore_index=True)
        df_merged = (
            df_merged.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
        )
    else:
        df_merged = df_new

    cols = ["date", "open", "close", "high", "low", "volume", "amount"]
    df_merged = df_merged[cols]
    df_merged.to_csv(csv_path, index=False)
    latest_date = _extract_latest_date(df_merged, "date")
    LOGGER.info("%s 更新完成! 最新日期: %s, 总行数: %d", csv_filename, df_merged["date"].iloc[-1], len(df_merged))
    return latest_date


def update_300661_1m(
    data_dir: Path = DATA_DIR,
    expected_date: date | None = None,
) -> date | None:
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
    df_old = _clip_minute_frame_to_expected_date(df_old, expected_date)
    df_new = _clip_minute_frame_to_expected_date(df_new, expected_date)

    if df_new.empty:
        LOGGER.warning("新拉取的分钟线在完整交易日 cutoff 过滤后为空，保留现有完整数据")
        return _extract_latest_date(df_old, "datetime")

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
    latest_session_completeness: dict[str, object] | None = None
    if latest_date is not None:
        latest_session_completeness = _assess_minute_day_completeness(df_merged, latest_date)
    LOGGER.info(
        "300661 1分钟线更新完成! 最新一分钟时间: %s, 总行数: %s",
        df_merged["datetime"].iloc[-1],
        len(df_merged),
    )
    if latest_session_completeness and not latest_session_completeness["is_complete"]:
        LOGGER.warning(
            "300661 最新交易日分钟线不完整: target_date=%s observed_rows=%s expected_rows=%s missing_timestamps=%s",
            latest_session_completeness["target_date"],
            latest_session_completeness["observed_rows"],
            latest_session_completeness["expected_rows"],
            latest_session_completeness["missing_timestamps"][:10],
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
    stock_1m_df = _safe_read_csv(data_dir / "300661_SZ_1m_ptrade.csv", "datetime")
    source_dates = {
        "stock_1m": _extract_latest_date(stock_1m_df, "datetime"),
        "index_daily": _extract_latest_date(_safe_read_csv(data_dir / "399006.csv", "date"), "date"),
        "sector_daily": _extract_latest_date(_safe_read_csv(data_dir / "512480.csv", "date"), "date"),
    }
    stock_minute_completeness = _assess_minute_day_completeness(stock_1m_df, expected_date)
    _n_missing = len(stock_minute_completeness["missing_timestamps"])
    # 缺失 > MAX_MISSING_BARS_TOLERATED 才视为 hard incomplete，否则降级为 warning
    stock_1m_incomplete = (
        source_dates["stock_1m"] == expected_date
        and not stock_minute_completeness["is_complete"]
        and _n_missing > MAX_MISSING_BARS_TOLERATED
    )
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
    if hard_stale_sources or stock_1m_incomplete:
        minute_completeness_message = ""
        if stock_1m_incomplete:
            minute_completeness_message = (
                " latest_day_minute_completeness={"
                f"target_date:{stock_minute_completeness['target_date']}, "
                f"observed_rows:{stock_minute_completeness['observed_rows']}, "
                f"expected_rows:{stock_minute_completeness['expected_rows']}, "
                f"missing_count:{stock_minute_completeness['missing_count']}, "
                f"missing_timestamps:{stock_minute_completeness['missing_timestamps'][:10]}"
                "}."
            )
        raise ValueError(
            "Backfill hard dependency is stale. "
            f"current_local_time={now_dt.isoformat(timespec='seconds')}, "
            f"expected_latest_date={expected_date.isoformat()}, "
            "source_dates={"
            + ", ".join(f"{name}:{value.isoformat() if value else 'missing'}" for name, value in source_dates.items())
            + "}. "
            + minute_completeness_message
            + " "
            "300661 1m is a hard dependency; confirm the local minute backfill reached the latest trading day before continuing."
        )

    summary = {
        "expected_latest_date": expected_date.isoformat(),
        **{name: value.isoformat() for name, value in source_dates.items() if value is not None},
        "stock_1m_observed_rows": stock_minute_completeness["observed_rows"],
        "stock_1m_expected_rows": stock_minute_completeness["expected_rows"],
        "stock_1m_missing_count": stock_minute_completeness["missing_count"],
        "soft_stale_sources": soft_stale_sources,
    }
    if soft_stale_sources:
        LOGGER.warning(
            "Backfill soft dependencies are stale, but continuing. expected_latest_date=%s soft_stale_sources=%s",
            expected_date.isoformat(),
            soft_stale_sources,
        )
    # 分钟线轻度缺失（≤ MAX_MISSING_BARS_TOLERATED）：容忍放行，但仍 WARNING 提示
    if 0 < _n_missing <= MAX_MISSING_BARS_TOLERATED:
        LOGGER.warning(
            "300661 1m 分钟线轻度缺失（容忍放行）: target_date=%s missing=%d/%d missing_timestamps=%s",
            stock_minute_completeness["target_date"],
            _n_missing,
            stock_minute_completeness["expected_rows"],
            stock_minute_completeness["missing_timestamps"],
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
    update_300661_1m(data_dir=data_dir, expected_date=expected_date)

    # 美股指数：^SOX 费城半导体 / ^IXIC 纳斯达克
    update_us_index_file("^SOX", "soxx_daily.csv", data_dir=data_dir)
    update_us_index_file("^IXIC", "nasdaq_daily.csv", data_dir=data_dir)

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

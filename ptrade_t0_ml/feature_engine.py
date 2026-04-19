from __future__ import annotations

import argparse
import logging
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DEFAULT_CONFIG, MinuteFeatureConfig, ProjectConfig
from .io_utils import atomic_write_json, save_dataframe
from .minute_foundation import configure_logging as configure_foundation_logging
from .minute_foundation import run_minute_foundation

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeatureEngineResult:
    feature_df: pd.DataFrame
    audit_payload: dict[str, object]


def _to_python_scalar(value: object) -> object:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _to_python_scalar(inner_value) for key, inner_value in value.items()}
    if isinstance(value, list):
        return [_to_python_scalar(item) for item in value]
    return value


def _load_feature_inputs(config: ProjectConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not config.canonical_1m_path.exists() or not config.canonical_1m_daily_summary_path.exists():
        LOGGER.info("Minute foundation outputs missing. Rebuilding foundation first.")
        run_minute_foundation(config)
    canonical_df = pd.read_csv(config.canonical_1m_path, parse_dates=["datetime"])
    daily_summary_df = pd.read_csv(config.canonical_1m_daily_summary_path)
    return canonical_df, daily_summary_df


def _safe_ratio(numerator: float, denominator: float) -> float:
    if pd.isna(denominator) or denominator == 0:
        return np.nan
    return float(numerator / denominator)


def _return_from_open(open_price: float, close_price: float) -> float:
    return _safe_ratio(close_price - open_price, open_price)


def _range_ratio(high_price: float, low_price: float) -> float:
    if pd.isna(low_price) or low_price <= 0:
        return np.nan
    return float(high_price / low_price - 1.0)


def _segment_frame(day_df: pd.DataFrame, count: int, mode: str = "head") -> pd.DataFrame:
    if len(day_df) < count or count <= 0:
        return pd.DataFrame(columns=day_df.columns)
    return day_df.head(count) if mode == "head" else day_df.tail(count)


def _compute_window_return_range(day_df: pd.DataFrame, window: int) -> tuple[float, float]:
    window_df = _segment_frame(day_df, window, mode="head")
    if window_df.empty:
        return np.nan, np.nan
    open_price = float(window_df.iloc[0]["open"])
    close_price = float(window_df.iloc[-1]["close"])
    high_price = float(window_df["high"].max())
    low_price = float(window_df["low"].min())
    return _return_from_open(open_price, close_price), _range_ratio(high_price, low_price)


def _trend_efficiency_ratio(frame: pd.DataFrame) -> float:
    if frame.empty:
        return np.nan
    first_open = float(frame.iloc[0]["open"])
    last_close = float(frame.iloc[-1]["close"])
    if first_open <= 0:
        return np.nan
    close_series = frame["close"].astype(float)
    prev_price_series = close_series.shift(1).fillna(first_open)
    path_distance = (close_series - prev_price_series).abs().replace([np.inf, -np.inf], np.nan)
    total_absolute_path = float(path_distance.fillna(0.0).sum())
    if total_absolute_path <= 0:
        return 0.0
    net_distance = abs(last_close - first_open)
    return float(net_distance / total_absolute_path)


def _directional_consistency_ratio(frame: pd.DataFrame) -> float:
    if frame.empty:
        return np.nan
    first_open = float(frame.iloc[0]["open"])
    last_close = float(frame.iloc[-1]["close"])
    if first_open <= 0:
        return np.nan
    net_return = last_close / first_open - 1.0
    day_direction = float(np.sign(net_return))
    if day_direction == 0:
        return 0.0

    close_series = frame["close"].astype(float)
    prev_close_series = close_series.shift(1).fillna(first_open)
    minute_returns = (close_series / prev_close_series.replace(0, np.nan) - 1.0).replace([np.inf, -np.inf], np.nan).dropna()
    nonzero_returns = minute_returns[minute_returns != 0]
    if nonzero_returns.empty:
        return 0.0
    return float((np.sign(nonzero_returns) == day_direction).mean())


def _time_bucket_for_index(index: int, total: int, bucket_count: int) -> float:
    if total <= 0 or bucket_count <= 0:
        return np.nan
    bucket = int(math.floor(index / total * bucket_count)) + 1
    return float(min(bucket, bucket_count))


def _weighted_skew_kurt(values: np.ndarray, weights: np.ndarray) -> tuple[float, float]:
    positive_mask = weights > 0
    if positive_mask.sum() < 2:
        return np.nan, np.nan
    x = values[positive_mask]
    w = weights[positive_mask].astype(float)
    weight_sum = w.sum()
    if weight_sum <= 0:
        return np.nan, np.nan
    mean = np.sum(w * x) / weight_sum
    variance = np.sum(w * np.square(x - mean)) / weight_sum
    if variance <= 0:
        return 0.0, 0.0
    std = math.sqrt(variance)
    skew = np.sum(w * np.power(x - mean, 3)) / (weight_sum * std**3)
    kurt = np.sum(w * np.power(x - mean, 4)) / (weight_sum * std**4) - 3.0
    return float(skew), float(kurt)


def _volume_profile_stats(day_df: pd.DataFrame, config: MinuteFeatureConfig) -> tuple[float, float]:
    day_low = float(day_df["low"].min())
    day_high = float(day_df["high"].max())
    total_volume = float(day_df["volume"].sum())
    if day_high <= day_low or total_volume <= 0:
        return np.nan, np.nan

    bin_edges = np.linspace(day_low, day_high, config.volume_profile_bins + 1)
    if np.unique(bin_edges).size < 3:
        return np.nan, np.nan
    bucket_ids = pd.cut(
        day_df["close"],
        bins=bin_edges,
        include_lowest=True,
        labels=False,
        duplicates="drop",
    )
    bucket_volume = day_df.groupby(bucket_ids, dropna=True)["volume"].sum()
    if bucket_volume.empty:
        return np.nan, np.nan
    centers = []
    weights = []
    for bucket_id, volume in bucket_volume.items():
        bucket_index = int(bucket_id)
        left_edge = bin_edges[bucket_index]
        right_edge = bin_edges[bucket_index + 1]
        centers.append((left_edge + right_edge) / 2.0)
        weights.append(volume)
    return _weighted_skew_kurt(np.asarray(centers), np.asarray(weights))


def _compute_vwap_features(day_df: pd.DataFrame, config: MinuteFeatureConfig) -> dict[str, float]:
    result = {
        "stk_m_vwap": np.nan,
        "stk_m_close_vwap_gap": np.nan,
        "stk_m_max_vwap_gap": np.nan,
        "stk_m_mean_abs_vwap_gap": np.nan,
        "stk_m_vwap_cross_count": 0.0,
        "stk_m_vwap_above_ratio": np.nan,
        "stk_m_vwap_below_ratio": np.nan,
        "stk_m_reversion_count_after_large_deviation": 0.0,
    }

    volume_sum = float(day_df["volume"].sum())
    if volume_sum <= 0:
        return result

    cumulative_volume = day_df["volume"].cumsum()
    price_volume = day_df["close"] * day_df["volume"]
    cumulative_price_volume = price_volume.cumsum()
    running_vwap = cumulative_price_volume.where(cumulative_volume > 0, np.nan) / cumulative_volume.where(cumulative_volume > 0, np.nan)
    gap_series = day_df["close"] / running_vwap - 1.0
    valid_gap = gap_series.replace([np.inf, -np.inf], np.nan).dropna()
    if valid_gap.empty:
        return result

    sign_series = np.sign(valid_gap)
    sign_changes = ((sign_series != sign_series.shift(1)) & (sign_series != 0) & (sign_series.shift(1) != 0)).sum()

    reversion_count = 0
    gap_values = valid_gap.to_numpy()
    threshold = config.vwap_large_deviation_threshold
    lookahead = config.vwap_reversion_lookahead_bars
    for index, current_gap in enumerate(gap_values[:-1]):
        if abs(current_gap) < threshold:
            continue
        if index > 0 and abs(gap_values[index - 1]) >= threshold:
            continue
        future_slice = gap_values[index + 1 : index + 1 + lookahead]
        if future_slice.size == 0:
            continue
        if current_gap > 0 and np.any(future_slice <= 0):
            reversion_count += 1
        elif current_gap < 0 and np.any(future_slice >= 0):
            reversion_count += 1

    day_vwap = float(price_volume.sum() / volume_sum)
    result.update(
        {
            "stk_m_vwap": float(day_vwap),
            "stk_m_close_vwap_gap": float(day_df.iloc[-1]["close"] / day_vwap - 1.0),
            "stk_m_max_vwap_gap": float(valid_gap.abs().max()),
            "stk_m_mean_abs_vwap_gap": float(valid_gap.abs().mean()),
            "stk_m_vwap_cross_count": float(sign_changes),
            "stk_m_vwap_above_ratio": float((valid_gap > 0).mean()),
            "stk_m_vwap_below_ratio": float((valid_gap < 0).mean()),
            "stk_m_reversion_count_after_large_deviation": float(reversion_count),
        }
    )
    return result


def _compute_intraday_features_for_day(
    day_df: pd.DataFrame,
    day_summary_row: pd.Series,
    config: MinuteFeatureConfig,
) -> dict[str, float | str]:
    day_df = day_df.sort_values("datetime").reset_index(drop=True).copy()
    first_open = float(day_df.iloc[0]["open"])
    last_close = float(day_df.iloc[-1]["close"])
    day_high = float(day_df["high"].max())
    day_low = float(day_df["low"].min())
    total_volume = float(day_df["volume"].sum())
    total_amount = float(day_df["amount"].sum())
    total_bars = len(day_df)
    morning_count = min(config.morning_bar_count, total_bars)
    half_index = total_bars // 2

    feature_row: dict[str, float | str] = {
        "date": str(day_summary_row["date"]),
        "open": float(day_summary_row["open"]),
        "high": float(day_summary_row["high"]),
        "low": float(day_summary_row["low"]),
        "close": float(day_summary_row["close"]),
        "volume": float(day_summary_row["volume"]),
        "amount": float(day_summary_row["amount"]),
        "stk_m_bar_count": float(total_bars),
    }

    for window in config.open_windows:
        window_return, window_range = _compute_window_return_range(day_df, window)
        feature_row[f"stk_m_open{window}_return"] = window_return
        feature_row[f"stk_m_open{window}_range"] = window_range

    morning_df = day_df.head(morning_count)
    afternoon_df = day_df.tail(total_bars - morning_count) if total_bars > morning_count else pd.DataFrame(columns=day_df.columns)
    last_window_df = _segment_frame(day_df, config.last_window_bars, mode="tail")
    open15_df = _segment_frame(day_df, 15, mode="head")
    first_half_df = day_df.head(half_index)
    second_half_df = day_df.tail(total_bars - half_index)

    feature_row["stk_m_am_return"] = (
        _return_from_open(first_open, float(morning_df.iloc[-1]["close"])) if not morning_df.empty else np.nan
    )
    feature_row["stk_m_pm_return"] = (
        _return_from_open(float(afternoon_df.iloc[0]["open"]), last_close) if not afternoon_df.empty else np.nan
    )
    feature_row["stk_m_last30_return"] = (
        _return_from_open(float(last_window_df.iloc[0]["open"]), last_close) if not last_window_df.empty else np.nan
    )
    feature_row["stk_m_intraday_range"] = _range_ratio(day_high, day_low)
    feature_row["stk_m_day_return_from_minutes"] = _return_from_open(first_open, last_close)
    feature_row["stk_m_close_location_in_range"] = _safe_ratio(last_close - day_low, day_high - day_low)
    feature_row["stk_m_trend_efficiency_ratio"] = _trend_efficiency_ratio(day_df)
    feature_row["stk_m_morning_trend_efficiency_ratio"] = _trend_efficiency_ratio(morning_df)
    feature_row["stk_m_directional_consistency"] = _directional_consistency_ratio(day_df)

    high_index = int(day_df["high"].idxmax())
    low_index = int(day_df["low"].idxmin())
    feature_row["stk_m_high_time_bucket"] = _time_bucket_for_index(high_index, total_bars, config.high_low_time_buckets)
    feature_row["stk_m_low_time_bucket"] = _time_bucket_for_index(low_index, total_bars, config.high_low_time_buckets)
    feature_row["stk_m_high_before_low_flag"] = float(high_index < low_index)

    vwap_features = _compute_vwap_features(day_df, config)
    feature_row.update(vwap_features)

    close_series = day_df["close"].astype(float)
    prev_close_series = close_series.shift(1).fillna(float(day_df.iloc[0]["open"]))
    log_returns = np.log(close_series / prev_close_series.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    cumulative_max = close_series.cummax()
    cumulative_min = close_series.cummin()
    drawdown_series = 1.0 - close_series / cumulative_max.replace(0, np.nan)
    runup_series = close_series / cumulative_min.replace(0, np.nan) - 1.0
    feature_row["stk_m_realized_volatility"] = float(np.sqrt(np.square(log_returns).sum()))
    feature_row["stk_m_max_drawdown_intraday"] = float(drawdown_series.max())
    feature_row["stk_m_max_runup_intraday"] = float(runup_series.max())
    feature_row["stk_m_range_first_half"] = (
        _range_ratio(float(first_half_df["high"].max()), float(first_half_df["low"].min())) if not first_half_df.empty else np.nan
    )
    feature_row["stk_m_range_second_half"] = (
        _range_ratio(float(second_half_df["high"].max()), float(second_half_df["low"].min())) if not second_half_df.empty else np.nan
    )
    tail_returns = log_returns.tail(config.last_window_bars)
    feature_row["stk_m_tail_volatility"] = (
        float(tail_returns.std(ddof=0) * math.sqrt(len(tail_returns))) if len(tail_returns) > 0 else np.nan
    )

    open30_df = _segment_frame(day_df, 30, mode="head")
    last30_df = _segment_frame(day_df, 30, mode="tail")
    middle_df = day_df.iloc[30:-30] if total_bars > 60 else pd.DataFrame(columns=day_df.columns)
    open15_volume = float(open15_df["volume"].sum()) if not open15_df.empty else np.nan
    open15_bar_count = len(open15_df)
    average_bar_volume = _safe_ratio(total_volume, total_bars)
    open15_average_volume = _safe_ratio(open15_volume, open15_bar_count) if open15_bar_count > 0 else np.nan
    open15_close = float(open15_df.iloc[-1]["close"]) if not open15_df.empty else np.nan
    feature_row["stk_m_open30_volume_ratio"] = _safe_ratio(float(open30_df["volume"].sum()), total_volume)
    feature_row["stk_m_open15_volume_ratio"] = _safe_ratio(open15_volume, total_volume)
    feature_row["stk_m_open15_volume_shock"] = _safe_ratio(open15_average_volume, average_bar_volume)
    feature_row["stk_m_open15_breakout_strength"] = (
        _safe_ratio(open15_close - first_open, day_high - day_low) if not open15_df.empty else np.nan
    )
    feature_row["stk_m_midday_volume_ratio"] = _safe_ratio(float(middle_df["volume"].sum()), total_volume)
    feature_row["stk_m_last30_volume_ratio"] = _safe_ratio(float(last30_df["volume"].sum()), total_volume)

    positive_volumes = day_df.loc[day_df["volume"] > 0, "volume"].astype(float)
    volume_spike_threshold = (
        positive_volumes.median() * config.volume_spike_multiplier if not positive_volumes.empty else np.nan
    )
    if positive_volumes.empty or pd.isna(volume_spike_threshold):
        feature_row["stk_m_volume_spike_count"] = 0.0
        feature_row["stk_m_volume_zscore_close"] = np.nan
    else:
        feature_row["stk_m_volume_spike_count"] = float((day_df["volume"] > volume_spike_threshold).sum())
        volume_std = positive_volumes.std(ddof=0)
        feature_row["stk_m_volume_zscore_close"] = (
            float((float(day_df.iloc[-1]["volume"]) - positive_volumes.mean()) / volume_std) if volume_std > 0 else 0.0
        )

    minute_abs_return = close_series.pct_change().abs().fillna(abs(_return_from_open(first_open, float(day_df.iloc[0]["close"]))))
    valid_amount_mask = day_df["amount"] > 0
    amihud_series = minute_abs_return.where(valid_amount_mask, np.nan) / day_df["amount"].where(valid_amount_mask, np.nan)
    feature_row["stk_m_amihud_mean"] = float(amihud_series.mean()) if amihud_series.notna().any() else np.nan
    feature_row["stk_m_amihud_p90"] = float(amihud_series.quantile(0.9)) if amihud_series.notna().any() else np.nan
    feature_row["stk_m_zero_volume_bar_ratio"] = _safe_ratio(float((day_df["volume"] == 0).sum()), total_bars)

    vol_profile_skew, vol_profile_kurt = _volume_profile_stats(day_df, config)
    feature_row["stk_m_volume_profile_skewness"] = vol_profile_skew
    feature_row["stk_m_volume_profile_kurtosis"] = vol_profile_kurt

    hl_range = day_df["high"] - day_df["low"]
    clv = ((2 * day_df["close"]) - day_df["high"] - day_df["low"]) / hl_range.replace(0, np.nan)
    clv = clv.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    proxy_ofi = clv * day_df["volume"]
    daily_sign = np.sign(proxy_ofi.sum())
    nonzero_proxy = proxy_ofi[proxy_ofi != 0]
    feature_row["stk_m_proxy_ofi_sum"] = float(proxy_ofi.sum())
    feature_row["stk_m_proxy_ofi_mean"] = float(proxy_ofi.mean())
    feature_row["stk_m_proxy_ofi_persistence"] = (
        float((np.sign(nonzero_proxy) == daily_sign).mean()) if daily_sign != 0 and not nonzero_proxy.empty else np.nan
    )

    return feature_row


def _apply_stock_daily_features(feature_df: pd.DataFrame, config: ProjectConfig) -> pd.DataFrame:
    df = feature_df.sort_values("date").reset_index(drop=True).copy()
    df["pre_close"] = df["close"].shift(1)
    df["daily_return"] = df["close"] / df["pre_close"] - 1.0
    df["daily_range"] = (df["high"] - df["low"]) / df["pre_close"]
    df["gap_pct"] = df["open"] / df["pre_close"] - 1.0
    high_low_range = df["high"] - df["low"]
    high_prev_close = (df["high"] - df["pre_close"]).abs()
    low_prev_close = (df["low"] - df["pre_close"]).abs()
    df["true_range"] = pd.concat([high_low_range, high_prev_close, low_prev_close], axis=1).max(axis=1)
    atr_rolling = df["true_range"].rolling(
        window=config.grid_replay.atr_window,
        min_periods=config.grid_replay.atr_min_periods,
    ).mean()
    atr_fallback = df["true_range"].expanding(min_periods=1).mean()
    df["atr"] = atr_rolling.fillna(atr_fallback)
    df["atr_pct"] = df["atr"] / df["close"]
    raw_grid_step = df["atr_pct"] * config.grid_replay.atr_multiplier
    df["grid_step_pct_t1"] = raw_grid_step.clip(
        lower=config.grid_replay.min_grid_step_pct,
        upper=config.grid_replay.max_grid_step_pct,
    )
    df["ma5"] = df["close"].rolling(window=5, min_periods=1).mean()
    df["ma10"] = df["close"].rolling(window=10, min_periods=1).mean()
    df["ma20"] = df["close"].rolling(window=20, min_periods=1).mean()
    df["ma60"] = df["close"].rolling(window=60, min_periods=1).mean()
    df["vol_ma5"] = df["volume"].rolling(window=5, min_periods=1).mean()
    df["vol_ma20"] = df["volume"].rolling(window=20, min_periods=1).mean()
    df["close_to_ma20"] = df["close"] / df["ma20"] - 1.0
    df["close_to_ma60"] = df["close"] / df["ma60"] - 1.0
    return df


def _apply_rolling_feature_block(feature_df: pd.DataFrame, config: MinuteFeatureConfig) -> pd.DataFrame:
    df = feature_df.copy()
    rolling_targets = [
        "stk_m_open30_return",
        "stk_m_intraday_range",
        "stk_m_close_vwap_gap",
        "stk_m_max_drawdown_intraday",
        "stk_m_last30_return",
        "stk_m_realized_volatility",
        "stk_m_amihud_mean",
        "stk_m_proxy_ofi_sum",
        "stk_m_trend_efficiency_ratio",
        "stk_m_directional_consistency",
        "stk_m_open15_volume_shock",
    ]
    for column in rolling_targets:
        if column not in df.columns:
            continue
        for window in config.rolling_windows:
            df[f"{column}_mean_{window}d"] = df[column].rolling(window=window, min_periods=1).mean()
            df[f"{column}_std_{window}d"] = df[column].rolling(window=window, min_periods=2).std(ddof=0)

    df["flag_large_vwap_deviation"] = (df["stk_m_max_vwap_gap"] >= config.vwap_large_deviation_threshold).astype(float)
    df["flag_large_intraday_drawdown"] = (df["stk_m_max_drawdown_intraday"] >= config.large_drawdown_threshold).astype(float)
    df["flag_strong_afternoon_reversal"] = (
        (df["stk_m_am_return"] <= -config.strong_afternoon_reversal_threshold)
        & (df["stk_m_pm_return"] >= config.strong_afternoon_reversal_threshold)
    ).astype(float)
    df["flag_strong_tail_close"] = (df["stk_m_last30_return"] >= config.strong_tail_close_threshold).astype(float)

    flag_columns = [
        "flag_large_vwap_deviation",
        "flag_large_intraday_drawdown",
        "flag_strong_afternoon_reversal",
        "flag_strong_tail_close",
    ]
    for column in flag_columns:
        for window in config.rolling_windows:
            df[f"{column}_rate_{window}d"] = df[column].rolling(window=window, min_periods=1).mean()
    return df


def _environment_daily_status(config: ProjectConfig) -> dict[str, object]:
    status: dict[str, object] = {}
    for path_name, path_value in {
        "stock_daily": config.local_input_csv_path,
        "index_daily": config.data_dir / "399006.csv",
        "sector_daily": config.data_dir / "512480.csv",
        "overnight_factors": config.overnight_factors_path,
    }.items():
        exists = path_value.exists()
        size = path_value.stat().st_size if exists else 0
        status[path_name] = {
            "path": str(path_value),
            "exists": exists,
            "size_bytes": int(size),
            "usable": bool(exists and size > 32),
        }
    return status


def _load_environment_daily_frame(path: Path, prefix: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    required_columns = ["date", "open", "close", "high", "low", "volume", "amount"]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise ValueError(f"Environment daily file is missing required columns {missing_columns}: {path}")

    normalized_df = df.loc[:, required_columns].copy()
    normalized_df["date"] = pd.to_datetime(normalized_df["date"], errors="coerce")
    normalized_df = normalized_df.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    for column in required_columns[1:]:
        normalized_df[column] = pd.to_numeric(normalized_df[column], errors="coerce")

    normalized_df[f"{prefix}_open"] = normalized_df["open"]
    normalized_df[f"{prefix}_close"] = normalized_df["close"]
    normalized_df[f"{prefix}_high"] = normalized_df["high"]
    normalized_df[f"{prefix}_low"] = normalized_df["low"]
    normalized_df[f"{prefix}_volume"] = normalized_df["volume"]
    normalized_df[f"{prefix}_amount"] = normalized_df["amount"]

    previous_close = normalized_df["close"].shift(1)
    normalized_df[f"{prefix}_daily_return"] = normalized_df["close"] / previous_close - 1.0
    normalized_df[f"{prefix}_daily_range"] = (normalized_df["high"] - normalized_df["low"]) / previous_close
    normalized_df[f"{prefix}_ma5"] = normalized_df["close"].rolling(window=5, min_periods=1).mean()
    normalized_df[f"{prefix}_ma20"] = normalized_df["close"].rolling(window=20, min_periods=1).mean()
    normalized_df[f"{prefix}_close_to_ma20"] = normalized_df["close"] / normalized_df[f"{prefix}_ma20"] - 1.0

    output_columns = [
        "date",
        f"{prefix}_open",
        f"{prefix}_close",
        f"{prefix}_high",
        f"{prefix}_low",
        f"{prefix}_volume",
        f"{prefix}_amount",
        f"{prefix}_daily_return",
        f"{prefix}_daily_range",
        f"{prefix}_ma5",
        f"{prefix}_ma20",
        f"{prefix}_close_to_ma20",
    ]
    normalized_df["date"] = normalized_df["date"].dt.strftime("%Y-%m-%d")
    return normalized_df.loc[:, output_columns]


def _merge_environment_daily_features(feature_df: pd.DataFrame, config: ProjectConfig) -> tuple[pd.DataFrame, list[str]]:
    merged_df = feature_df.copy()
    merged_prefixes: list[str] = []
    environment_paths = {
        "idx": config.data_dir / "399006.csv",
        "sec": config.data_dir / "512480.csv",
    }
    for prefix, path in environment_paths.items():
        if not path.exists() or path.stat().st_size <= 32:
            continue
        environment_df = _load_environment_daily_frame(path, prefix)
        merged_df = merged_df.merge(environment_df, on="date", how="left", validate="one_to_one")
        merged_prefixes.append(prefix)
    return merged_df, merged_prefixes


def _load_overnight_factor_frame(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required_columns = [
        "date",
        "overnight_semiconductor_return",
        "overnight_nasdaq_return",
        "overnight_gap_risk_bucket",
    ]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise ValueError(f"Overnight factor file is missing required columns {missing_columns}: {path}")

    normalized_df = df.loc[:, required_columns].copy()
    normalized_df["date"] = pd.to_datetime(normalized_df["date"], errors="coerce")
    normalized_df = normalized_df.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    for column in required_columns[1:]:
        normalized_df[column] = pd.to_numeric(normalized_df[column], errors="coerce")
    normalized_df["date"] = normalized_df["date"].dt.strftime("%Y-%m-%d")
    return normalized_df


def _merge_overnight_factor_features(feature_df: pd.DataFrame, config: ProjectConfig) -> tuple[pd.DataFrame, list[str]]:
    path = config.overnight_factors_path
    if not path.exists() or path.stat().st_size <= 32:
        return feature_df.copy(), []

    overnight_df = _load_overnight_factor_frame(path)
    merged_df = feature_df.merge(overnight_df, on="date", how="left", validate="one_to_one")
    merged_columns = [column for column in overnight_df.columns if column != "date"]
    return merged_df, merged_columns


def build_feature_table(
    canonical_df: pd.DataFrame,
    daily_summary_df: pd.DataFrame,
    config: ProjectConfig = DEFAULT_CONFIG,
) -> FeatureEngineResult:
    minute_config = config.minute_features
    grouped_bars = {
        trade_date: group.sort_values("datetime").reset_index(drop=True)
        for trade_date, group in canonical_df.groupby("date", sort=True)
    }

    feature_rows: list[dict[str, float | str]] = []
    for _, summary_row in daily_summary_df.sort_values("date").iterrows():
        trade_date = str(summary_row["date"])
        day_df = grouped_bars.get(trade_date)
        if day_df is None or day_df.empty:
            continue
        feature_rows.append(_compute_intraday_features_for_day(day_df, summary_row, minute_config))

    feature_df = pd.DataFrame(feature_rows)
    if feature_df.empty:
        raise ValueError("Feature engine produced no rows. Check the canonical minute source and daily summary inputs.")

    feature_df = _apply_stock_daily_features(feature_df, config)
    feature_df = _apply_rolling_feature_block(feature_df, minute_config)
    feature_df, merged_environment_prefixes = _merge_environment_daily_features(feature_df, config)
    feature_df, merged_overnight_factor_columns = _merge_overnight_factor_features(feature_df, config)

    label_match_count = 0
    if config.label_targets_path.exists():
        label_df = pd.read_csv(config.label_targets_path, usecols=["date"])
        label_match_count = int(feature_df["date"].isin(label_df["date"]).sum())

    missing_ratio = (feature_df.isna().mean().sort_values(ascending=False).head(20)).to_dict()
    base_feature_columns = [
        column
        for column in feature_df.columns
        if column.startswith("stk_m_")
        or column
        in {
            "pre_close",
            "daily_return",
            "daily_range",
            "gap_pct",
            "true_range",
            "atr",
            "atr_pct",
            "grid_step_pct_t1",
            "ma5",
            "ma10",
            "ma20",
            "ma60",
            "vol_ma5",
            "vol_ma20",
            "close_to_ma20",
            "close_to_ma60",
        }
    ]
    audit_payload: dict[str, object] = {
        "source_canonical_path": str(config.canonical_1m_path),
        "source_daily_summary_path": str(config.canonical_1m_daily_summary_path),
        "output_feature_table_path": str(config.feature_table_path),
        "row_count": int(len(feature_df)),
        "coverage_start": str(feature_df.iloc[0]["date"]),
        "coverage_end": str(feature_df.iloc[-1]["date"]),
        "column_count": int(feature_df.shape[1]),
        "stock_feature_column_count": int(len(base_feature_columns)),
        "label_match_count": int(label_match_count),
        "merged_environment_prefixes": merged_environment_prefixes,
        "merged_overnight_factor_columns": merged_overnight_factor_columns,
        "top_missing_ratio": missing_ratio,
        "environment_daily_status": _environment_daily_status(config),
        "minute_feature_config": asdict(minute_config),
    }
    return FeatureEngineResult(feature_df=feature_df, audit_payload=_to_python_scalar(audit_payload))


def run_feature_engine(config: ProjectConfig = DEFAULT_CONFIG) -> FeatureEngineResult:
    canonical_df, daily_summary_df = _load_feature_inputs(config)
    result = build_feature_table(canonical_df, daily_summary_df, config=config)
    save_dataframe(result.feature_df, config.feature_table_path)
    atomic_write_json(config.feature_audit_path, result.audit_payload)

    LOGGER.info("Saved feature table to: %s", config.feature_table_path)
    LOGGER.info("Saved feature audit to: %s", config.feature_audit_path)
    LOGGER.info(
        "Feature coverage: %s -> %s | rows=%s | columns=%s | label_match_count=%s",
        result.audit_payload["coverage_start"],
        result.audit_payload["coverage_end"],
        result.audit_payload["row_count"],
        result.audit_payload["column_count"],
        result.audit_payload["label_match_count"],
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Build the production daily feature table from the canonical 300661 minute source."
    )


def main() -> None:
    configure_foundation_logging()
    build_parser().parse_args()
    run_feature_engine(DEFAULT_CONFIG)


if __name__ == "__main__":
    main()

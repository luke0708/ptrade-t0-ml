from __future__ import annotations

import argparse
import logging
import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .config import DEFAULT_CONFIG, GridReplayConfig, ProjectConfig
from .io_utils import atomic_write_json, save_dataframe
from .minute_foundation import configure_logging as configure_foundation_logging
from .minute_foundation import run_minute_foundation

LOGGER = logging.getLogger(__name__)

ANOMALY_SAMPLE_LIMIT = 20


@dataclass(frozen=True)
class GridReplayResult:
    target_grid_pnl_t1: float
    replay_grid_pnl_cash_t1: float
    replay_round_trips_t1: int
    replay_long_entries_t1: int
    replay_short_entries_t1: int
    replay_ambiguous_entries_t1: int
    replay_skipped_unfillable_touches_t1: int
    replay_total_filled_shares_t1: int
    replay_forced_close_t1: int


@dataclass
class OpenCycle:
    side: str
    entry_price: float
    quantity: int
    entry_cost_cash: float


@dataclass(frozen=True)
class LabelEngineResult:
    labels_df: pd.DataFrame
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


def _load_foundation_inputs(config: ProjectConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not config.canonical_1m_path.exists() or not config.canonical_1m_daily_summary_path.exists():
        LOGGER.info("Minute foundation outputs missing. Rebuilding foundation first.")
        run_minute_foundation(config)

    canonical_df = pd.read_csv(config.canonical_1m_path, parse_dates=["datetime"])
    daily_summary_df = pd.read_csv(config.canonical_1m_daily_summary_path)
    return canonical_df, daily_summary_df


def _prepare_daily_reference_frame(
    daily_summary_df: pd.DataFrame,
    replay_config: GridReplayConfig,
) -> pd.DataFrame:
    df = daily_summary_df.copy()
    df = df.sort_values("date").reset_index(drop=True)

    numeric_columns = ["open", "high", "low", "close", "volume", "amount", "bar_count"]
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    df["pre_close"] = df["close"].shift(1)
    true_range_parts = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - df["pre_close"]).abs(),
            (df["low"] - df["pre_close"]).abs(),
        ],
        axis=1,
    )
    df["true_range"] = true_range_parts.max(axis=1)
    df["daily_range_pct"] = np.where(df["close"] > 0, (df["high"] - df["low"]) / df["close"], np.nan)
    df["atr"] = df["true_range"].rolling(
        window=replay_config.atr_window,
        min_periods=replay_config.atr_min_periods,
    ).mean()
    df["atr_pct"] = np.where(df["close"] > 0, df["atr"] / df["close"], np.nan)

    fallback_step_pct = (
        df["daily_range_pct"]
        .rolling(window=5, min_periods=1)
        .mean()
        .mul(replay_config.atr_multiplier)
        .clip(
            lower=replay_config.min_grid_step_pct,
            upper=replay_config.max_grid_step_pct,
        )
    )
    df["grid_step_pct"] = (
        df["atr_pct"]
        .mul(replay_config.atr_multiplier)
        .clip(
            lower=replay_config.min_grid_step_pct,
            upper=replay_config.max_grid_step_pct,
        )
        .fillna(fallback_step_pct)
        .fillna(replay_config.min_grid_step_pct)
    )
    return df


def _safe_return(anchor_price: float, realized_price: float) -> float:
    if pd.isna(anchor_price) or pd.isna(realized_price) or float(anchor_price) <= 0:
        return np.nan
    return float(realized_price / anchor_price - 1.0)


def _safe_fraction(numerator: float, denominator: float) -> float:
    if pd.isna(numerator) or pd.isna(denominator) or float(denominator) == 0:
        return np.nan
    return float(numerator / denominator)


def _build_price_target_bundle(
    today_close: float,
    next_day_open: float,
    next_day_high: float,
    next_day_low: float,
) -> dict[str, float]:
    max_anchor = max(float(today_close), float(next_day_open))
    return {
        "next_day_gap_return_t1": _safe_return(today_close, next_day_open),
        "target_upside_t1": _safe_return(today_close, next_day_high),
        "target_downside_t1": _safe_return(today_close, next_day_low),
        "target_downside_from_open_t1": _safe_return(next_day_open, next_day_low),
        "target_downside_from_max_anchor_t1": _safe_return(max_anchor, next_day_low),
    }


def _build_target_anomaly_audit(labels_df: pd.DataFrame) -> dict[str, object]:
    downside_positive_mask = labels_df["target_downside_t1"] > 0.0
    downside_large_positive_mask = labels_df["target_downside_t1"] > 0.03
    upside_extreme_mask = labels_df["target_upside_t1"] > 0.10
    large_gap_mask = labels_df["next_day_gap_return_t1"].abs() > 0.08
    suspicious_abnormal_jump_mask = downside_large_positive_mask & upside_extreme_mask
    combined_suspicious_mask = suspicious_abnormal_jump_mask | large_gap_mask

    suspicious_columns = [
        "date",
        "next_date",
        "next_day_gap_return_t1",
        "target_upside_t1",
        "target_downside_t1",
        "target_downside_from_open_t1",
        "target_downside_from_max_anchor_t1",
        "next_day_open",
        "next_day_high",
        "next_day_low",
        "today_close",
    ]
    suspicious_samples = (
        labels_df.loc[combined_suspicious_mask, suspicious_columns]
        .head(ANOMALY_SAMPLE_LIMIT)
        .to_dict(orient="records")
    )

    return {
        "downside_positive_day_count": int(downside_positive_mask.sum()),
        "downside_positive_day_ratio": float(downside_positive_mask.mean()),
        "downside_large_positive_day_count": int(downside_large_positive_mask.sum()),
        "downside_large_positive_day_ratio": float(downside_large_positive_mask.mean()),
        "upside_extreme_day_count": int(upside_extreme_mask.sum()),
        "upside_extreme_day_ratio": float(upside_extreme_mask.mean()),
        "large_gap_day_count": int(large_gap_mask.sum()),
        "large_gap_day_ratio": float(large_gap_mask.mean()),
        "suspicious_abnormal_jump_day_count": int(suspicious_abnormal_jump_mask.sum()),
        "suspicious_abnormal_jump_day_ratio": float(suspicious_abnormal_jump_mask.mean()),
        "suspicious_abnormal_jump_samples": suspicious_samples,
    }


def _build_target_anomaly_flags(price_target_bundle: dict[str, float]) -> dict[str, int]:
    target_downside_t1 = float(price_target_bundle["target_downside_t1"])
    target_upside_t1 = float(price_target_bundle["target_upside_t1"])
    next_day_gap_return_t1 = float(price_target_bundle["next_day_gap_return_t1"])

    downside_positive_flag = int(target_downside_t1 > 0.0)
    downside_large_positive_flag = int(target_downside_t1 > 0.03)
    upside_extreme_flag = int(target_upside_t1 > 0.10)
    large_gap_flag = int(abs(next_day_gap_return_t1) > 0.08)
    suspicious_abnormal_jump_flag = int(
        (downside_large_positive_flag == 1 and upside_extreme_flag == 1)
        or large_gap_flag == 1
    )
    return {
        "target_downside_positive_flag_t1": downside_positive_flag,
        "target_downside_large_positive_flag_t1": downside_large_positive_flag,
        "target_upside_extreme_flag_t1": upside_extreme_flag,
        "next_day_large_gap_flag_t1": large_gap_flag,
        "next_day_suspicious_abnormal_jump_flag_t1": suspicious_abnormal_jump_flag,
    }


def _fillable_quantity(bar_volume: float, replay_config: GridReplayConfig) -> int:
    if pd.isna(bar_volume) or bar_volume <= 0:
        return 0
    max_participation_shares = int(math.floor(bar_volume * replay_config.participation_rate))
    lot_fill = (max_participation_shares // 100) * 100
    if replay_config.order_size_shares <= 0:
        return 0
    return int(min(replay_config.order_size_shares, lot_fill))


def _choose_worse_entry_side(
    bar: pd.Series,
    buy_trigger: float,
    sell_trigger: float,
    replay_config: GridReplayConfig,
) -> str:
    buy_fill = buy_trigger * (1.0 + replay_config.one_way_slippage)
    sell_fill = sell_trigger * (1.0 - replay_config.one_way_slippage)
    long_mark_to_market = float(bar["close"]) - buy_fill
    short_mark_to_market = sell_fill - float(bar["close"])
    return "long" if long_mark_to_market <= short_mark_to_market else "short"


def _open_long_cycle(
    buy_trigger: float,
    quantity: int,
    replay_config: GridReplayConfig,
) -> OpenCycle:
    entry_price = buy_trigger * (1.0 + replay_config.one_way_slippage)
    entry_cost_cash = entry_price * quantity * replay_config.commission_rate
    return OpenCycle(
        side="long",
        entry_price=entry_price,
        quantity=quantity,
        entry_cost_cash=entry_cost_cash,
    )


def _open_short_cycle(
    sell_trigger: float,
    quantity: int,
    replay_config: GridReplayConfig,
) -> OpenCycle:
    entry_price = sell_trigger * (1.0 - replay_config.one_way_slippage)
    entry_cost_cash = entry_price * quantity * (
        replay_config.commission_rate + replay_config.stamp_tax_rate
    )
    return OpenCycle(
        side="short",
        entry_price=entry_price,
        quantity=quantity,
        entry_cost_cash=entry_cost_cash,
    )


def _close_cycle(
    open_cycle: OpenCycle,
    exit_price: float,
    replay_config: GridReplayConfig,
) -> float:
    if open_cycle.side == "long":
        sell_fill = exit_price * (1.0 - replay_config.one_way_slippage)
        exit_cost_cash = sell_fill * open_cycle.quantity * (
            replay_config.commission_rate + replay_config.stamp_tax_rate
        )
        gross_pnl_cash = (sell_fill - open_cycle.entry_price) * open_cycle.quantity
    else:
        buy_fill = exit_price * (1.0 + replay_config.one_way_slippage)
        exit_cost_cash = buy_fill * open_cycle.quantity * replay_config.commission_rate
        gross_pnl_cash = (open_cycle.entry_price - buy_fill) * open_cycle.quantity
    return gross_pnl_cash - open_cycle.entry_cost_cash - exit_cost_cash


def _build_running_vwap_gap(next_day_bars: pd.DataFrame) -> pd.Series:
    close_series = pd.to_numeric(next_day_bars["close"], errors="coerce")
    volume_series = pd.to_numeric(next_day_bars["volume"], errors="coerce").fillna(0.0)
    cumulative_volume = volume_series.cumsum()
    price_volume = close_series * volume_series
    running_vwap = price_volume.cumsum().where(cumulative_volume > 0, np.nan) / cumulative_volume.where(
        cumulative_volume > 0, np.nan
    )
    gap_series = close_series / running_vwap - 1.0
    return gap_series.replace([np.inf, -np.inf], np.nan)


def _count_vwap_crosses(valid_gap: pd.Series) -> int:
    if valid_gap.empty:
        return 0
    sign_series = np.sign(valid_gap)
    sign_changes = (
        (sign_series != sign_series.shift(1))
        & (sign_series != 0)
        & (sign_series.shift(1) != 0)
    ).sum()
    return int(sign_changes)


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
    return float(abs(last_close - first_open) / total_absolute_path)


def _open_window_stats(next_day_bars: pd.DataFrame, bar_count: int) -> tuple[float, float]:
    window_df = next_day_bars.head(bar_count)
    if window_df.empty:
        return np.nan, np.nan
    total_volume = float(next_day_bars["volume"].sum())
    first_open = float(window_df.iloc[0]["open"])
    last_close = float(window_df.iloc[-1]["close"])
    open_window_return = (last_close / first_open - 1.0) if first_open > 0 else np.nan
    open_window_volume_ratio = float(window_df["volume"].sum() / total_volume) if total_volume > 0 else np.nan
    return open_window_return, open_window_volume_ratio


def _compute_vwap_reversion_label(
    next_day_bars: pd.DataFrame,
    config: ProjectConfig,
) -> dict[str, float | int]:
    label_config = config.strategy_labels
    replay_config = config.grid_replay
    round_trip_cost_floor = (
        2.0 * replay_config.one_way_slippage
        + 2.0 * replay_config.commission_rate
        + replay_config.stamp_tax_rate
    )
    min_capture_abs = max(label_config.vwap_reversion_min_capture_abs, round_trip_cost_floor * 1.25)
    gap_series = _build_running_vwap_gap(next_day_bars)
    valid_gap = gap_series.dropna()

    if valid_gap.empty:
        return {
            "target_vwap_reversion_t1": 0,
            "next_day_vwap_reversion_event_count": 0,
            "next_day_vwap_reversion_success_count": 0,
            "next_day_vwap_reversion_max_capture": 0.0,
            "next_day_vwap_reversion_max_event_gap": 0.0,
            "next_day_vwap_cross_count_label": 0,
            "next_day_vwap_dominant_side_ratio": 0.0,
        }

    gap_values = valid_gap.to_numpy(dtype=float)
    threshold = label_config.vwap_reversion_threshold
    lookahead = label_config.vwap_reversion_lookahead_bars
    success_residual_factor = 1.0 - label_config.vwap_reversion_min_capture_ratio

    event_count = 0
    success_count = 0
    max_capture = 0.0
    max_event_gap = 0.0

    for index in range(len(gap_values) - 1):
        current_gap = float(gap_values[index])
        if abs(current_gap) < threshold:
            continue

        if index > 0:
            previous_gap = float(gap_values[index - 1])
            if abs(previous_gap) >= threshold and np.sign(previous_gap) == np.sign(current_gap):
                continue

        future_slice = gap_values[index + 1 : index + 1 + lookahead]
        if future_slice.size == 0:
            continue

        event_count += 1
        max_event_gap = max(max_event_gap, abs(current_gap))
        future_abs = np.abs(future_slice)
        min_abs_future = float(np.nanmin(future_abs))
        capture = float(abs(current_gap) - min_abs_future)
        max_capture = max(max_capture, capture)
        sign_crossed = bool(np.any(np.sign(future_slice) == -np.sign(current_gap)))
        residual_threshold = max(
            label_config.vwap_reversion_residual_threshold,
            abs(current_gap) * success_residual_factor,
        )
        sufficiently_resolved = sign_crossed or min_abs_future <= residual_threshold

        if capture >= min_capture_abs and sufficiently_resolved:
            success_count += 1

    dominant_side_ratio = float(max((valid_gap > 0).mean(), (valid_gap < 0).mean()))
    cross_count = _count_vwap_crosses(valid_gap)
    label_hit = bool(
        success_count >= label_config.vwap_reversion_label_min_success_count
        and max_capture >= label_config.vwap_reversion_label_min_capture_abs
        and cross_count >= label_config.vwap_reversion_label_min_cross_count
        and dominant_side_ratio <= label_config.vwap_reversion_label_max_dominant_side_ratio
    )
    return {
        "target_vwap_reversion_t1": int(label_hit),
        "next_day_vwap_reversion_event_count": int(event_count),
        "next_day_vwap_reversion_success_count": int(success_count),
        "next_day_vwap_reversion_max_capture": float(max_capture),
        "next_day_vwap_reversion_max_event_gap": float(max_event_gap),
        "next_day_vwap_cross_count_label": cross_count,
        "next_day_vwap_dominant_side_ratio": dominant_side_ratio,
    }


def _compute_trend_break_risk_label(
    next_day_bars: pd.DataFrame,
    grid_step_pct: float,
    target_tradable_score_t1: int,
    target_vwap_reversion_t1: int,
    next_day_vwap_cross_count: int,
    next_day_vwap_dominant_side_ratio: float,
    config: ProjectConfig,
) -> dict[str, float | int]:
    label_config = config.strategy_labels
    first_open = float(next_day_bars.iloc[0]["open"])
    last_close = float(next_day_bars.iloc[-1]["close"])
    day_high = float(next_day_bars["high"].max())
    day_low = float(next_day_bars["low"].min())
    price_range = day_high - day_low
    open_close_return = (last_close / first_open - 1.0) if first_open > 0 else np.nan
    open15_return, open15_volume_ratio = _open_window_stats(next_day_bars, bar_count=15)
    close_location = ((last_close - day_low) / price_range) if price_range > 0 else 0.5
    directional_efficiency = (abs(last_close - first_open) / price_range) if price_range > 0 else 0.0
    trend_efficiency_ratio = _trend_efficiency_ratio(next_day_bars)
    min_directional_move = max(
        label_config.trend_break_min_open_close_return,
        grid_step_pct * label_config.trend_break_grid_step_multiplier,
    )

    is_extreme_close = False
    trend_direction = 0
    if pd.notna(open_close_return) and open_close_return > 0:
        trend_direction = 1
        is_extreme_close = close_location >= label_config.trend_break_close_location_threshold
    elif pd.notna(open_close_return) and open_close_return < 0:
        trend_direction = -1
        is_extreme_close = close_location <= 1.0 - label_config.trend_break_close_location_threshold

    open15_aligned = bool(
        pd.notna(open15_return)
        and abs(open15_return) >= label_config.trend_break_soft_open15_return_min
        and np.sign(open15_return) == trend_direction
    )
    soft_score = 0
    soft_score += int(trend_direction != 0)
    soft_score += int(pd.notna(open_close_return) and abs(open_close_return) >= min_directional_move)
    soft_score += int(directional_efficiency >= label_config.trend_break_soft_directional_efficiency_min)
    soft_score += int(trend_efficiency_ratio >= label_config.trend_break_soft_trend_efficiency_ratio_min)
    soft_score += int(open15_aligned)
    soft_score += int(pd.notna(open15_volume_ratio) and open15_volume_ratio >= label_config.trend_break_soft_open15_volume_ratio_min)
    soft_score += int(next_day_vwap_dominant_side_ratio >= label_config.trend_break_soft_vwap_side_ratio_min)
    soft_score += int(next_day_vwap_cross_count <= label_config.trend_break_soft_max_vwap_cross_count)
    soft_score += int(is_extreme_close)

    one_sided_trend_signature = bool(
        trend_direction != 0
        and abs(open_close_return) >= min_directional_move
        and directional_efficiency >= label_config.trend_break_directional_efficiency_min
        and trend_efficiency_ratio >= label_config.trend_break_trend_efficiency_ratio_min
        and pd.notna(open15_return)
        and abs(open15_return) >= label_config.trend_break_open15_return_min
        and np.sign(open15_return) == trend_direction
        and pd.notna(open15_volume_ratio)
        and open15_volume_ratio >= label_config.trend_break_open15_volume_ratio_min
        and next_day_vwap_dominant_side_ratio >= label_config.trend_break_vwap_side_ratio_min
        and next_day_vwap_cross_count <= label_config.trend_break_max_vwap_cross_count
        and is_extreme_close
    )
    hostile_to_mean_reversion = target_tradable_score_t1 == 0 or target_vwap_reversion_t1 == 0
    strong_one_sided_signature = bool(
        trend_direction != 0
        and next_day_vwap_dominant_side_ratio >= label_config.trend_break_label_vwap_side_ratio_min
        and next_day_vwap_cross_count <= label_config.trend_break_label_max_vwap_cross_count
        and (
            trend_efficiency_ratio >= label_config.trend_break_label_trend_efficiency_ratio_min
            or soft_score >= label_config.trend_break_label_soft_score_min
        )
    )
    soft_risk_signature = bool(hostile_to_mean_reversion and strong_one_sided_signature)
    trend_break_target = bool((one_sided_trend_signature and hostile_to_mean_reversion) or soft_risk_signature)

    return {
        "target_trend_break_risk_t1": int(trend_break_target),
        "next_day_trend_break_extreme_t1": int(one_sided_trend_signature and hostile_to_mean_reversion),
        "next_day_trend_break_soft_score": int(soft_score),
        "next_day_trend_break_hostile_flag": int(hostile_to_mean_reversion),
        "next_day_trend_break_soft_signature_t1": int(soft_risk_signature),
        "next_day_open_close_return": float(open_close_return) if pd.notna(open_close_return) else np.nan,
        "next_day_directional_efficiency": float(directional_efficiency),
        "next_day_trend_efficiency_ratio": float(trend_efficiency_ratio) if pd.notna(trend_efficiency_ratio) else np.nan,
        "next_day_open15_return": float(open15_return) if pd.notna(open15_return) else np.nan,
        "next_day_open15_volume_ratio": float(open15_volume_ratio) if pd.notna(open15_volume_ratio) else np.nan,
        "next_day_close_location_in_range": float(close_location),
        "next_day_trend_direction": int(trend_direction),
    }


def _compute_hostile_selloff_risk_label(
    next_day_bars: pd.DataFrame,
    today_close: float,
    grid_step_pct: float,
    target_tradable_score_t1: int,
    target_vwap_reversion_t1: int,
    target_trend_break_risk_t1: int,
    next_day_trend_direction: int,
    config: ProjectConfig,
) -> dict[str, float | int]:
    label_config = config.strategy_labels
    anchor_price = max(float(today_close), float(next_day_bars.iloc[0]["open"]))
    early_bar_limit = max(1, min(int(label_config.hostile_selloff_early_bar_limit), len(next_day_bars)))
    open30_df = next_day_bars.head(min(30, len(next_day_bars)))
    open60_df = next_day_bars.head(early_bar_limit)
    first_open = float(next_day_bars.iloc[0]["open"])
    last_close = float(next_day_bars.iloc[-1]["close"])
    open15_return, open15_volume_ratio = _open_window_stats(next_day_bars, bar_count=15)

    open30_low = float(open30_df["low"].min()) if not open30_df.empty else np.nan
    open60_low = float(open60_df["low"].min()) if not open60_df.empty else np.nan
    open30_low_return = _safe_return(anchor_price, open30_low)
    open60_low_return = _safe_return(anchor_price, open60_low)

    low_time_index = int(pd.to_numeric(next_day_bars["low"], errors="coerce").idxmin())
    low_in_first_hour = low_time_index < early_bar_limit
    close_vs_anchor_return = _safe_return(anchor_price, last_close)
    early_drawdown_cash = anchor_price - open60_low if pd.notna(open60_low) else np.nan
    close_recovery_ratio = (
        _safe_fraction(last_close - open60_low, early_drawdown_cash)
        if pd.notna(early_drawdown_cash) and float(early_drawdown_cash) > 0
        else 1.0
    )

    vwap_gap = _build_running_vwap_gap(next_day_bars).dropna()
    negative_vwap_ratio = float((vwap_gap < 0).mean()) if not vwap_gap.empty else 0.0
    negative_day_return = _safe_return(first_open, last_close)
    min_drawdown = max(
        label_config.hostile_selloff_min_drawdown,
        grid_step_pct * label_config.hostile_selloff_grid_step_multiplier,
    )

    open30_drawdown_hit = bool(pd.notna(open30_low_return) and open30_low_return <= -min_drawdown)
    open60_drawdown_hit = bool(pd.notna(open60_low_return) and open60_low_return <= -min_drawdown)
    weak_recovery = bool(
        pd.notna(close_recovery_ratio)
        and close_recovery_ratio <= label_config.hostile_selloff_recovery_ratio_max
    )
    weak_close = bool(
        pd.notna(close_vs_anchor_return)
        and close_vs_anchor_return <= label_config.hostile_selloff_close_return_max
    )
    early_pressure = bool(
        pd.notna(open15_return)
        and open15_return <= label_config.hostile_selloff_open15_return_max
    )
    opening_volume_shock = bool(
        pd.notna(open15_volume_ratio)
        and open15_volume_ratio >= label_config.hostile_selloff_open15_volume_ratio_min
    )
    negative_vwap_persistent = negative_vwap_ratio >= label_config.hostile_selloff_negative_vwap_ratio_min
    negative_trend_break = bool(
        target_trend_break_risk_t1 == 1 and int(next_day_trend_direction) < 0
    )

    soft_score = 0
    soft_score += int(open30_drawdown_hit)
    soft_score += int(open60_drawdown_hit)
    soft_score += int(low_in_first_hour)
    soft_score += int(early_pressure)
    soft_score += int(opening_volume_shock)
    soft_score += int(negative_vwap_persistent)
    soft_score += int(weak_recovery)
    soft_score += int(weak_close)
    soft_score += int(target_tradable_score_t1 == 0)
    soft_score += int(target_vwap_reversion_t1 == 0)
    soft_score += int(negative_trend_break)

    extreme_signature = bool(
        open30_drawdown_hit
        and low_in_first_hour
        and negative_vwap_persistent
        and weak_recovery
        and negative_trend_break
    )
    hostile_context = bool(target_tradable_score_t1 == 0 or target_vwap_reversion_t1 == 0)
    soft_signature = bool(
        hostile_context
        and (open30_drawdown_hit or open60_drawdown_hit)
        and soft_score >= label_config.hostile_selloff_soft_score_min
        and (early_pressure or weak_close or negative_trend_break)
    )
    hostile_selloff_target = bool(extreme_signature or soft_signature)

    return {
        "target_hostile_selloff_risk_t1": int(hostile_selloff_target),
        "next_day_open30_low_return": float(open30_low_return) if pd.notna(open30_low_return) else np.nan,
        "next_day_open60_low_return": float(open60_low_return) if pd.notna(open60_low_return) else np.nan,
        "next_day_low_time_index": int(low_time_index),
        "next_day_low_in_first_hour_flag": int(low_in_first_hour),
        "next_day_close_vs_anchor_return": float(close_vs_anchor_return) if pd.notna(close_vs_anchor_return) else np.nan,
        "next_day_close_recovery_ratio_from_early_low": (
            float(close_recovery_ratio) if pd.notna(close_recovery_ratio) else np.nan
        ),
        "next_day_negative_vwap_ratio": float(negative_vwap_ratio),
        "next_day_hostile_selloff_soft_score": int(soft_score),
        "next_day_hostile_selloff_extreme_t1": int(extreme_signature),
        "next_day_hostile_selloff_negative_trend_flag": int(negative_trend_break),
        "next_day_hostile_selloff_hostile_context_flag": int(hostile_context),
        "next_day_hostile_selloff_open15_return": float(open15_return) if pd.notna(open15_return) else np.nan,
        "next_day_hostile_selloff_open15_volume_ratio": (
            float(open15_volume_ratio) if pd.notna(open15_volume_ratio) else np.nan
        ),
        "next_day_hostile_selloff_open_close_return": (
            float(negative_day_return) if pd.notna(negative_day_return) else np.nan
        ),
    }


def replay_next_day_grid(
    next_day_bars: pd.DataFrame,
    anchor_close: float,
    grid_step_pct: float,
    replay_config: GridReplayConfig,
) -> GridReplayResult:
    if next_day_bars.empty or anchor_close <= 0 or grid_step_pct <= 0:
        return GridReplayResult(
            target_grid_pnl_t1=0.0,
            replay_grid_pnl_cash_t1=0.0,
            replay_round_trips_t1=0,
            replay_long_entries_t1=0,
            replay_short_entries_t1=0,
            replay_ambiguous_entries_t1=0,
            replay_skipped_unfillable_touches_t1=0,
            replay_total_filled_shares_t1=0,
            replay_forced_close_t1=0,
        )

    buy_trigger = anchor_close * (1.0 - grid_step_pct)
    sell_trigger = anchor_close * (1.0 + grid_step_pct)

    total_pnl_cash = 0.0
    round_trips = 0
    long_entries = 0
    short_entries = 0
    ambiguous_entries = 0
    skipped_unfillable_touches = 0
    total_filled_shares = 0
    forced_close = 0
    open_cycle: OpenCycle | None = None

    for _, bar in next_day_bars.iterrows():
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])

        if open_cycle is None:
            buy_touched = bar_low <= buy_trigger
            sell_touched = bar_high >= sell_trigger
            if not buy_touched and not sell_touched:
                continue

            fill_quantity = _fillable_quantity(float(bar["volume"]), replay_config)
            if fill_quantity <= 0:
                skipped_unfillable_touches += int(buy_touched or sell_touched)
                continue

            total_filled_shares += fill_quantity
            if buy_touched and sell_touched:
                ambiguous_entries += 1
                chosen_side = _choose_worse_entry_side(bar, buy_trigger, sell_trigger, replay_config)
                if chosen_side == "long":
                    open_cycle = _open_long_cycle(buy_trigger, fill_quantity, replay_config)
                    long_entries += 1
                else:
                    open_cycle = _open_short_cycle(sell_trigger, fill_quantity, replay_config)
                    short_entries += 1
                continue

            if buy_touched:
                open_cycle = _open_long_cycle(buy_trigger, fill_quantity, replay_config)
                long_entries += 1
            elif sell_touched:
                open_cycle = _open_short_cycle(sell_trigger, fill_quantity, replay_config)
                short_entries += 1
            continue

        if open_cycle.side == "long" and bar_high >= anchor_close:
            total_pnl_cash += _close_cycle(open_cycle, anchor_close, replay_config)
            round_trips += 1
            open_cycle = None
            continue

        if open_cycle.side == "short" and bar_low <= anchor_close:
            total_pnl_cash += _close_cycle(open_cycle, anchor_close, replay_config)
            round_trips += 1
            open_cycle = None
            continue

    if open_cycle is not None:
        forced_close = 1
        last_close = float(next_day_bars.iloc[-1]["close"])
        total_pnl_cash += _close_cycle(open_cycle, last_close, replay_config)

    notional_cash = anchor_close * replay_config.order_size_shares
    target_grid_pnl = total_pnl_cash / notional_cash if notional_cash > 0 else 0.0
    return GridReplayResult(
        target_grid_pnl_t1=float(target_grid_pnl),
        replay_grid_pnl_cash_t1=float(total_pnl_cash),
        replay_round_trips_t1=int(round_trips),
        replay_long_entries_t1=int(long_entries),
        replay_short_entries_t1=int(short_entries),
        replay_ambiguous_entries_t1=int(ambiguous_entries),
        replay_skipped_unfillable_touches_t1=int(skipped_unfillable_touches),
        replay_total_filled_shares_t1=int(total_filled_shares),
        replay_forced_close_t1=int(forced_close),
    )


def build_label_targets(
    canonical_df: pd.DataFrame,
    daily_summary_df: pd.DataFrame,
    config: ProjectConfig = DEFAULT_CONFIG,
) -> LabelEngineResult:
    replay_config = config.grid_replay
    daily_reference_df = _prepare_daily_reference_frame(daily_summary_df, replay_config)
    grouped_bars = {
        trade_date: group.sort_values("datetime").reset_index(drop=True)
        for trade_date, group in canonical_df.groupby("date", sort=True)
    }

    rows: list[dict[str, object]] = []
    for row_index in range(len(daily_reference_df) - 1):
        today_row = daily_reference_df.iloc[row_index]
        next_day_row = daily_reference_df.iloc[row_index + 1]
        next_date = str(next_day_row["date"])
        next_day_bars = grouped_bars.get(next_date)
        if next_day_bars is None or next_day_bars.empty:
            continue

        anchor_close = float(today_row["close"])
        grid_step_pct = float(today_row["grid_step_pct"])
        replay_result = replay_next_day_grid(next_day_bars, anchor_close, grid_step_pct, replay_config)
        positive_grid_day = int(replay_result.target_grid_pnl_t1 > 0)
        tradable_score = int(
            positive_grid_day == 1
            and replay_result.replay_round_trips_t1 >= replay_config.min_round_trips_for_tradable
        )
        vwap_reversion_label = _compute_vwap_reversion_label(next_day_bars, config)
        trend_break_risk_label = _compute_trend_break_risk_label(
            next_day_bars=next_day_bars,
            grid_step_pct=grid_step_pct,
            target_tradable_score_t1=tradable_score,
            target_vwap_reversion_t1=int(vwap_reversion_label["target_vwap_reversion_t1"]),
            next_day_vwap_cross_count=int(vwap_reversion_label["next_day_vwap_cross_count_label"]),
            next_day_vwap_dominant_side_ratio=float(vwap_reversion_label["next_day_vwap_dominant_side_ratio"]),
            config=config,
        )
        hostile_selloff_label = _compute_hostile_selloff_risk_label(
            next_day_bars=next_day_bars,
            today_close=anchor_close,
            grid_step_pct=grid_step_pct,
            target_tradable_score_t1=tradable_score,
            target_vwap_reversion_t1=int(vwap_reversion_label["target_vwap_reversion_t1"]),
            target_trend_break_risk_t1=int(trend_break_risk_label["target_trend_break_risk_t1"]),
            next_day_trend_direction=int(trend_break_risk_label["next_day_trend_direction"]),
            config=config,
        )
        price_target_bundle = _build_price_target_bundle(
            today_close=anchor_close,
            next_day_open=float(next_day_row["open"]),
            next_day_high=float(next_day_row["high"]),
            next_day_low=float(next_day_row["low"]),
        )
        target_anomaly_flags = _build_target_anomaly_flags(price_target_bundle)

        rows.append(
            {
                "date": str(today_row["date"]),
                "next_date": next_date,
                "today_close": anchor_close,
                "today_high": float(today_row["high"]),
                "today_low": float(today_row["low"]),
                "today_volume": float(today_row["volume"]),
                "pre_close": float(today_row["pre_close"]) if pd.notna(today_row["pre_close"]) else np.nan,
                "true_range": float(today_row["true_range"]) if pd.notna(today_row["true_range"]) else np.nan,
                "atr": float(today_row["atr"]) if pd.notna(today_row["atr"]) else np.nan,
                "atr_pct": float(today_row["atr_pct"]) if pd.notna(today_row["atr_pct"]) else np.nan,
                "grid_step_pct_t1": grid_step_pct,
                "next_day_open": float(next_day_row["open"]),
                "next_day_high": float(next_day_row["high"]),
                "next_day_low": float(next_day_row["low"]),
                "next_day_close": float(next_day_row["close"]),
                **price_target_bundle,
                **target_anomaly_flags,
                "target_grid_pnl_t1": replay_result.target_grid_pnl_t1,
                "target_positive_grid_day_t1": positive_grid_day,
                "target_tradable_score_t1": tradable_score,
                **vwap_reversion_label,
                **trend_break_risk_label,
                **hostile_selloff_label,
                "replay_grid_pnl_cash_t1": replay_result.replay_grid_pnl_cash_t1,
                "replay_round_trips_t1": replay_result.replay_round_trips_t1,
                "replay_long_entries_t1": replay_result.replay_long_entries_t1,
                "replay_short_entries_t1": replay_result.replay_short_entries_t1,
                "replay_ambiguous_entries_t1": replay_result.replay_ambiguous_entries_t1,
                "replay_skipped_unfillable_touches_t1": replay_result.replay_skipped_unfillable_touches_t1,
                "replay_total_filled_shares_t1": replay_result.replay_total_filled_shares_t1,
                "replay_forced_close_t1": replay_result.replay_forced_close_t1,
            }
        )

    labels_df = pd.DataFrame(rows)
    if labels_df.empty:
        raise ValueError("Label engine produced no rows. Check the canonical minute source and daily summary inputs.")

    grid_stats = labels_df["target_grid_pnl_t1"].describe(percentiles=[0.1, 0.5, 0.9]).to_dict()
    upside_stats = labels_df["target_upside_t1"].describe(percentiles=[0.1, 0.5, 0.9]).to_dict()
    downside_stats = labels_df["target_downside_t1"].describe(percentiles=[0.1, 0.5, 0.9]).to_dict()
    downside_from_open_stats = labels_df["target_downside_from_open_t1"].describe(percentiles=[0.1, 0.5, 0.9]).to_dict()
    downside_from_max_anchor_stats = labels_df["target_downside_from_max_anchor_t1"].describe(
        percentiles=[0.1, 0.5, 0.9]
    ).to_dict()
    gap_stats = labels_df["next_day_gap_return_t1"].describe(percentiles=[0.1, 0.5, 0.9]).to_dict()
    target_anomaly_audit = _build_target_anomaly_audit(labels_df)
    audit_payload: dict[str, object] = {
        "source_canonical_path": str(config.canonical_1m_path),
        "source_daily_summary_path": str(config.canonical_1m_daily_summary_path),
        "output_label_targets_path": str(config.label_targets_path),
        "row_count": int(len(labels_df)),
        "coverage_start": str(labels_df.iloc[0]["date"]),
        "coverage_end": str(labels_df.iloc[-1]["date"]),
        "positive_grid_day_positive_ratio": float(labels_df["target_positive_grid_day_t1"].mean()),
        "tradable_positive_ratio": float(labels_df["target_tradable_score_t1"].mean()),
        "vwap_reversion_positive_ratio": float(labels_df["target_vwap_reversion_t1"].mean()),
        "trend_break_risk_positive_ratio": float(labels_df["target_trend_break_risk_t1"].mean()),
        "hostile_selloff_risk_positive_ratio": float(labels_df["target_hostile_selloff_risk_t1"].mean()),
        "target_grid_pnl_t1_summary": grid_stats,
        "target_upside_t1_summary": upside_stats,
        "target_downside_t1_summary": downside_stats,
        "target_downside_from_open_t1_summary": downside_from_open_stats,
        "target_downside_from_max_anchor_t1_summary": downside_from_max_anchor_stats,
        "next_day_gap_return_t1_summary": gap_stats,
        "target_anomaly_audit": target_anomaly_audit,
        "vwap_reversion_event_summary": labels_df["next_day_vwap_reversion_event_count"].describe().to_dict(),
        "vwap_reversion_success_summary": labels_df["next_day_vwap_reversion_success_count"].describe().to_dict(),
        "trend_break_open_close_return_summary": labels_df["next_day_open_close_return"].describe(percentiles=[0.1, 0.5, 0.9]).to_dict(),
        "trend_break_efficiency_ratio_summary": labels_df["next_day_trend_efficiency_ratio"].describe(percentiles=[0.1, 0.5, 0.9]).to_dict(),
        "trend_break_soft_score_summary": labels_df["next_day_trend_break_soft_score"].describe(percentiles=[0.1, 0.5, 0.9]).to_dict(),
        "trend_break_extreme_positive_ratio": float(labels_df["next_day_trend_break_extreme_t1"].mean()),
        "trend_break_soft_signature_positive_ratio": float(labels_df["next_day_trend_break_soft_signature_t1"].mean()),
        "hostile_selloff_open30_low_return_summary": labels_df["next_day_open30_low_return"].describe(percentiles=[0.1, 0.5, 0.9]).to_dict(),
        "hostile_selloff_negative_vwap_ratio_summary": labels_df["next_day_negative_vwap_ratio"].describe(percentiles=[0.1, 0.5, 0.9]).to_dict(),
        "hostile_selloff_soft_score_summary": labels_df["next_day_hostile_selloff_soft_score"].describe(percentiles=[0.1, 0.5, 0.9]).to_dict(),
        "hostile_selloff_extreme_positive_ratio": float(labels_df["next_day_hostile_selloff_extreme_t1"].mean()),
        "round_trip_summary": labels_df["replay_round_trips_t1"].describe().to_dict(),
        "forced_close_count": int(labels_df["replay_forced_close_t1"].sum()),
        "ambiguous_entry_count": int(labels_df["replay_ambiguous_entries_t1"].sum()),
        "skipped_unfillable_touch_count": int(labels_df["replay_skipped_unfillable_touches_t1"].sum()),
        "replay_config": asdict(replay_config),
        "strategy_label_config": asdict(config.strategy_labels),
    }
    return LabelEngineResult(labels_df=labels_df, audit_payload=_to_python_scalar(audit_payload))


def run_label_engine(config: ProjectConfig = DEFAULT_CONFIG) -> LabelEngineResult:
    canonical_df, daily_summary_df = _load_foundation_inputs(config)
    result = build_label_targets(canonical_df, daily_summary_df, config=config)
    save_dataframe(result.labels_df, config.label_targets_path)
    atomic_write_json(config.label_targets_audit_path, result.audit_payload)

    LOGGER.info("Saved label targets to: %s", config.label_targets_path)
    LOGGER.info("Saved label audit to: %s", config.label_targets_audit_path)
    LOGGER.info(
        "Label coverage: %s -> %s | rows=%s | positive_grid_day_positive_ratio=%.4f | tradable_positive_ratio=%.4f | vwap_reversion_positive_ratio=%.4f | trend_break_risk_positive_ratio=%.4f",
        result.audit_payload["coverage_start"],
        result.audit_payload["coverage_end"],
        result.audit_payload["row_count"],
        result.audit_payload["positive_grid_day_positive_ratio"],
        result.audit_payload["tradable_positive_ratio"],
        result.audit_payload["vwap_reversion_positive_ratio"],
        result.audit_payload["trend_break_risk_positive_ratio"],
    )
    LOGGER.info(
        "Grid PnL summary: mean=%.6f median=%.6f p90=%.6f",
        result.audit_payload["target_grid_pnl_t1_summary"]["mean"],
        result.audit_payload["target_grid_pnl_t1_summary"]["50%"],
        result.audit_payload["target_grid_pnl_t1_summary"]["90%"],
    )
    LOGGER.info(
        "Hostile selloff ratio: %.4f | extreme ratio: %.4f",
        result.audit_payload["hostile_selloff_risk_positive_ratio"],
        result.audit_payload["hostile_selloff_extreme_positive_ratio"],
    )
    LOGGER.info(
        "Target anomaly audit: downside_positive_days=%s suspicious_abnormal_jump_days=%s large_gap_days=%s",
        result.audit_payload["target_anomaly_audit"]["downside_positive_day_count"],
        result.audit_payload["target_anomaly_audit"]["suspicious_abnormal_jump_day_count"],
        result.audit_payload["target_anomaly_audit"]["large_gap_day_count"],
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Build pessimistic next-day label targets from the canonical 300661 minute source."
    )


def main() -> None:
    configure_foundation_logging()
    build_parser().parse_args()
    run_label_engine(DEFAULT_CONFIG)


if __name__ == "__main__":
    main()

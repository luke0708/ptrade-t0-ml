# Minute Feature Schema

## Purpose

This document defines the daily feature schema generated from `300661` long-history `1m` data and supporting daily environment data. It is the source of truth for feature names, meanings, and minimum quality rules.

The modeling unit is one row per trading day `t`. All minute features must be computed using only intraday data from day `t`, and then used to predict day `t+1`.

## Core Inputs

- Primary minute source: `data/300661_SZ_1m_ptrade.csv`
- Primary daily source: `data/300661.csv`
- Environment daily sources:
  - `data/399006.csv`
  - `data/512480.csv`
- Optional environment minute sources:
  - `data/399006_5m.csv`
  - `data/512480_5m.csv`

## Feature Groups

### A. Intraday Structure

- `stk_m_open5_return`, `stk_m_open15_return`, `stk_m_open30_return`, `stk_m_open60_return`
- `stk_m_open5_range`, `stk_m_open15_range`, `stk_m_open30_range`, `stk_m_open60_range`
- `stk_m_am_return`, `stk_m_pm_return`, `stk_m_last30_return`
- `stk_m_intraday_range`
- `stk_m_day_return_from_minutes`
- `stk_m_close_location_in_range`
- `stk_m_high_time_bucket`, `stk_m_low_time_bucket`
- `stk_m_high_before_low_flag`
- `stk_m_trend_efficiency_ratio`
- `stk_m_morning_trend_efficiency_ratio`
- `stk_m_directional_consistency`
- `stk_m_open15_volume_ratio`
- `stk_m_open15_volume_shock`
- `stk_m_open15_breakout_strength`

### B. VWAP And Reversion

- `stk_m_vwap`
- `stk_m_close_vwap_gap`
- `stk_m_max_vwap_gap`
- `stk_m_mean_abs_vwap_gap`
- `stk_m_vwap_cross_count`
- `stk_m_vwap_above_ratio`
- `stk_m_vwap_below_ratio`
- `stk_m_reversion_count_after_large_deviation`

### C. Early Failure-Regime Context

These features are intended to help the model distinguish:

- apparently clean reversion days
- from early-path structures that often turn into failed `VWAP` reversion or weak tradability on the next day

- `stk_m_open30_low_return`
- `stk_m_open60_low_return`
- `stk_m_low_in_first_hour_flag`
- `stk_m_close_recovery_ratio_from_open60_low`
- `stk_m_open30_negative_vwap_ratio`
- `stk_m_open60_negative_vwap_ratio`
- `stk_m_open30_vwap_cross_count`
- `stk_m_open60_vwap_cross_count`
- `stk_m_open30_vwap_dominant_side_ratio`
- `stk_m_open60_vwap_dominant_side_ratio`
- `stk_m_hostile_selloff_soft_score`
- `flag_open60_deep_selloff`
- `flag_open60_negative_vwap_persistent`
- `flag_open60_poor_recovery`
- `flag_hostile_selloff_regime`
- `flag_reversion_failure_regime`

### D. Volatility And Path Risk

- `stk_m_realized_volatility`
- `stk_m_max_drawdown_intraday`
- `stk_m_max_runup_intraday`
- `stk_m_range_first_half`
- `stk_m_range_second_half`
- `stk_m_tail_volatility`

### E. Volume And Flow

- `stk_m_bar_count`
- `stk_m_open30_volume_ratio`
- `stk_m_midday_volume_ratio`
- `stk_m_last30_volume_ratio`
- `stk_m_volume_spike_count`
- `stk_m_volume_zscore_close`

### F. Liquidity And Micro Friction

These are mandatory additions for the production spec.

- `stk_m_amihud_mean`
  Daily mean of minute-level `abs(return) / amount`
- `stk_m_amihud_p90`
  90th percentile of minute-level illiquidity
- `stk_m_zero_volume_bar_ratio`
  Ratio of zero-volume minute bars
- `stk_m_volume_profile_skewness`
  Skewness of volume distribution across intraday price buckets
- `stk_m_volume_profile_kurtosis`
  Kurtosis of volume distribution across intraday price buckets
- `stk_m_proxy_ofi_sum`
  Sum of `CLV * volume`, where `CLV = (2*close - high - low) / (high - low)`
- `stk_m_proxy_ofi_mean`
  Mean of `CLV * volume`
- `stk_m_proxy_ofi_persistence`
  Fraction of bars where the sign of `CLV * volume` matches the daily sign

### G. Rolling Cross-Day Statistics

Compute rolling statistics on the daily minute-derived features above:

- 3-day, 5-day, 10-day, 20-day mean
- 3-day, 5-day, 10-day, 20-day std
- recent occurrence rates for:
  - large VWAP deviation
  - large intraday drawdown
  - strong afternoon reversal
  - strong tail close

The current production slice also rolls:

- `stk_m_trend_efficiency_ratio`
- `stk_m_directional_consistency`
- `stk_m_open15_volume_shock`
- `stk_m_open30_low_return`
- `stk_m_open60_low_return`
- `stk_m_close_recovery_ratio_from_open60_low`
- `stk_m_open30_negative_vwap_ratio`
- `stk_m_open60_negative_vwap_ratio`
- `stk_m_open30_vwap_cross_count`
- `stk_m_open60_vwap_cross_count`
- `stk_m_open60_vwap_dominant_side_ratio`
- `stk_m_hostile_selloff_soft_score`
- recent occurrence rates for:
  - `flag_open60_deep_selloff`
  - `flag_open60_negative_vwap_persistent`
  - `flag_open60_poor_recovery`
  - `flag_hostile_selloff_regime`
  - `flag_reversion_failure_regime`

### H. Daily Environment Features

Keep and derive from daily data:

- Stock daily features:
  - `pre_close`
  - `daily_return`
  - `daily_range`
  - `gap_pct`
  - `ma5`, `ma10`, `ma20`, `ma60`
  - `vol_ma5`, `vol_ma20`
  - `close_to_ma20`, `close_to_ma60`
- Index daily features:
  - `idx_daily_return`
  - `idx_daily_range`
  - `idx_ma5`, `idx_ma20`
  - `idx_close_to_ma20`
- Sector daily features:
  - `sec_daily_return`
  - `sec_daily_range`
  - `sec_ma5`, `sec_ma20`
  - `sec_close_to_ma20`

### I. Relative Environment Regime

These features describe whether `300661` is moving with, against, or weaker than the broader environment:

- `stk_idx_return_spread`
- `stk_sec_return_spread`
- `stk_idx_gap_spread`
- `stk_sec_gap_spread`
- `stk_idx_close_to_ma20_spread`
- `stk_sec_close_to_ma20_spread`
- `idx_sec_return_spread`
- `flag_relative_weak_vs_idx`
- `flag_relative_weak_vs_sec`
- `flag_gap_up_without_index_confirmation`
- `flag_gap_up_without_sector_confirmation`

### J. Overnight Sentiment Factor Group

This group is optional in engineering, but mandatory in the final design.

- `overnight_semiconductor_return`
- `overnight_nasdaq_return`
- `overnight_gap_risk_bucket`

Use SOXX first when available, but the spec must not hard-code SOXX as the only acceptable factor.

## Data Quality Rules

- Never infer minute frequency from filename. Detect it from timestamp differences.
- Bars with invalid `datetime` are dropped.
- Bars with `high <= 0`, `low <= 0`, or `close <= 0` are invalid.
- `open == 0` alone must not trigger unconditional row deletion without inspection; handle it with a repair or fallback rule if other fields are valid.
- `amount` may be missing for external data. In that case, VWAP-amount-derived features must remain `NaN` and be explicitly logged.
- All features must be computed with information available by the end of day `t`.

## How This Guides ML

- This schema determines exactly what the feature builder is allowed to emit.
- `model_spec.md` can only reference features defined here.
- Any feature not listed here is considered experimental and must be versioned before use in production.

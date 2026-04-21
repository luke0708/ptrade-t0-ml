# Label Definition

## Purpose

This document defines the supervised targets for the `300661` ML system. Labels are derived from day `t+1`, while features come strictly from day `t`.

## Primary Regression Targets

- `target_upside_t1 = next_day_high / today_close - 1`
- `target_downside_t1 = next_day_low / today_close - 1`

These are computed from the primary stock path, using next-day realized highs and lows.
For `300661`, the raw downside regression target now remains primarily a research / comparison target rather than the preferred live downside controller.

## Downside Diagnostic Variants

To diagnose whether the main downside target is being distorted by gap-up days, abnormal jumps, or corporate-action-like discontinuities, the label table also carries research-only downside variants:

- `target_downside_from_open_t1 = next_day_low / next_day_open - 1`
- `target_downside_from_max_anchor_t1 = next_day_low / max(today_close, next_day_open) - 1`
- `next_day_gap_return_t1 = next_day_open / today_close - 1`

These are not automatically the production downside head. They exist so we can compare:

- close-anchored downside
- open-anchored downside
- gap-adjusted downside

before choosing which definition best reflects real next-day hostile selloff risk for `300661`.

Current implementation note:

- `target_downside_from_open_t1` is now also trained as a research-only regression head
- this head is intended for candidate analysis and walk-forward comparison
- it must not directly replace the live downside controller unless later evidence clearly shows it is better

## Primary Strategy Labels

### A. Tradability

`target_tradable_score_t1`

Meaning:
- whether day `t+1` contains enough realizable intraday round-trip opportunity for the grid/VWAP strategy after costs

Recommended implementation:
- binary version: `0/1`
- optional regression version: net tradable opportunity score

Current production interpretation:

- `target_tradable_score_t1 = 1` only when the pessimistic replay produces a positive net grid day **and** at least one completed round trip
- this is stricter than merely surviving costs

### A1. Positive Grid Day

`target_positive_grid_day_t1`

Meaning:
- whether the pessimistic next-day grid replay survives all modeled costs and closes with `PnL > 0`

Role:

- this is now the primary classifier replacement for directly regressing `target_grid_pnl_t1`
- it should be treated as the first executable filter before `target_tradable_score_t1`

### B. VWAP Reversion

`target_vwap_reversion_t1`

Meaning:
- whether large intraday deviations from VWAP on day `t+1` revert with enough magnitude and time to be exploitable

### C. Trend Break Risk

`target_trend_break_risk_t1`

Meaning:
- whether day `t+1` behaves like a one-sided trend day that is hostile to mean reversion and grid trading

Current production-facing definition:
- a positive label is assigned when either:
  - the day satisfies the strict hostile one-sided extreme signature, or
  - the day satisfies a softer but still hostile signature with:
    - high VWAP side dominance
    - low VWAP cross count
    - sufficiently high trend-efficiency or soft trend-break score

Deployment note:
- this label exists to warn the strategy about “mean reversion is likely to fail today”
- it should remain a soft-constraint / damping signal unless its ranking quality improves materially

### C1. Hostile Selloff Risk

`target_hostile_selloff_risk_t1`

Meaning:
- whether day `t+1` contains an early hostile selloff pattern that is specifically unfriendly to dip-buy and grid activation

Current production-facing definition:
- anchor the downside to `max(today_close, next_day_open)` to avoid positive downside artifacts from gap-up days
- require a sufficiently large early drawdown in the first `30-60` minutes
- require hostile execution context such as:
  - weak tradability
  - missing VWAP reversion
  - persistent trading below running VWAP
  - weak close recovery from the early low
  - or a negative trend-break signature

Diagnostic fields emitted together with this label include:

- `next_day_open30_low_return`
- `next_day_open60_low_return`
- `next_day_low_in_first_hour_flag`
- `next_day_close_vs_anchor_return`
- `next_day_close_recovery_ratio_from_early_low`
- `next_day_negative_vwap_ratio`
- `next_day_hostile_selloff_soft_score`
- `next_day_hostile_selloff_extreme_t1`

Deployment note:
- this is the preferred production-facing downside risk head for `300661`
- `target_downside_t1` should remain exported for research, ranking comparison, and post-mortem diagnostics

### D. Grid PnL

`target_grid_pnl_t1`

Meaning:
- next-day offline replay PnL under a simplified but pessimistic version of the V3.2 strategy

Role:

- keep as an auxiliary research / ranking head
- do **not** make it the main production control head
- the production decision path should prefer `target_positive_grid_day_t1` and `target_tradable_score_t1`

## Pessimistic Replay Rules

These rules are mandatory. Without them, `target_grid_pnl_t1` is too optimistic and leaks unrealizable execution quality.

### Same-Bar Penalty

If one 1-minute bar touches both the buy grid and the sell grid:
- never assume the favorable execution sequence
- always apply the worst-case sequence
- if ambiguity remains, choose the outcome with lower PnL

### Slippage And Fees

Each simulated fill must include:

- broker commission
- stamp tax where applicable
- at least `0.1%` one-way slippage

If the net result after fees and slippage is negative:

- `target_grid_pnl_t1 <= 0`
- `target_tradable_score_t1 = 0`

### Participation Constraint

Each simulated order must obey a conservative participation cap:

- maximum fill quantity per bar is capped to a configured fraction of that bar's traded volume

### Close-Out Rule

Any residual temporary position must be flattened using the same pessimistic fill logic near the session close.

## Anti Look-Ahead Rules

- No label may use information from day `t+1` to build day `t` features.
- Replay logic must use only bar-level information available at each replay step.
- If OHLC ambiguity remains, choose the less favorable path.

## Required Label Audit

Every label build should explicitly audit abnormal next-day price jumps, especially for downside targets.

At minimum, the audit should report:

- days where `target_downside_t1 > 0`
- days where `target_downside_t1` is strongly positive
- days where `target_upside_t1` is abnormally large
- large next-day gap days
- sample dates that look suspicious enough to review manually

This is important because these days can weaken downside ranking quality without being a classic feature-leakage bug.

## How This Guides ML

- These labels define what the model is trying to predict.
- `target_positive_grid_day_t1` should be the main production classifier for grid survivability.
- `model_spec.md` must map each model head to one or more of these labels.
- `ptrade_signal_contract.md` may only consume outputs derived from labels defined here.

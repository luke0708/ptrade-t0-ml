# Label Definition

## Purpose

This document defines the supervised targets for the `300661` ML system. Labels are derived from day `t+1`, while features come strictly from day `t`.

## Primary Regression Targets

- `target_upside_t1 = next_day_high / today_close - 1`
- `target_downside_t1 = next_day_low / today_close - 1`

These are computed from the primary stock path, using next-day realized highs and lows.

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

## How This Guides ML

- These labels define what the model is trying to predict.
- `target_positive_grid_day_t1` should be the main production classifier for grid survivability.
- `model_spec.md` must map each model head to one or more of these labels.
- `ptrade_signal_contract.md` may only consume outputs derived from labels defined here.

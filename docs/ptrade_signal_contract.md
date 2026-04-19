# PTrade Signal Contract

## Purpose

This document defines how the ML system communicates with the PTrade strategy and how separate workflows or LLM conversations must coordinate.

The ML system and the PTrade strategy are allowed to be developed in separate conversations, but they must communicate through files and this contract, not through chat memory.

PTrade is assumed to be a closed sandbox with strict runtime limits.
Therefore:

- heavy model training stays offline
- daily scoring stays offline
- PTrade intraday logic only consumes a compact signal file and executes lightweight rules

## Daily Output Contract

The ML side must generate a daily artifact after the close and before the next trading day starts.

Recommended files:

- `data/ml_daily_signal.json`
- optional mirror: `data/ml_daily_signal.csv`

## Required Fields

- `date`
  feature date `t`
- `signal_for_date`
  target trading date `t+1`
- `pred_upside_t1`
- `pred_downside_t1`
- `pred_grid_pnl_t1`
- `pred_positive_grid_day_t1`
- `pred_tradable_score_t1`
- `pred_trend_break_risk_t1`
- `pred_vwap_reversion_score_t1`
- `recommended_grid_width_t1`
- `recommended_mode`
- `model_version`
- `feature_version`
- `threshold_version`

## Recommended Modes

- `OFF`
- `SAFE`
- `NORMAL`
- `AGGRESSIVE`

## PTrade Mapping Rules

### No Intraday ML Inference Inside PTrade

PTrade should **not**:

- load large training tables
- regenerate large minute-level feature sets intraday
- run XGBoost / LightGBM scoring on every tick or Level2 callback

PTrade should instead:

- read the offline daily signal before the session
- treat that signal as the day-level playbook
- apply only hard intraday execution rules based on live market state

### Trend Risk Is Not A Veto

`pred_trend_break_risk_t1` must not have absolute veto power.

Instead, PTrade should combine it with current position state:

- high risk + heavy base position:
  reduce activity hard
- high risk + light base position:
  allow a small trial size, for example one-third of normal size
- medium risk:
  widen grid and reduce trade frequency
- low risk:
  normal mode

This prevents the model from fully hibernating the strategy for long stretches.

### Suggested Runtime Controls

The strategy may map ML output to:

- `trend_weak`
- `position_scale`
- `grid_width_scale`
- `dip_buy_enabled`
- `high_sell_enabled`
- `forced_safe_mode`

Suggested production priority:

1. `pred_positive_grid_day_t1`
2. `pred_tradable_score_t1`
3. `pred_vwap_reversion_score_t1`
4. `pred_trend_break_risk_t1`

`pred_grid_pnl_t1` may still be exported, but it should be treated as an auxiliary diagnostic rather than the primary live gating signal.

### Level2 Usage Boundary

Level2 can be used intraday, but only for lightweight control logic such as:

- canceling a planned dip-buy
- reducing position size
- widening the grid
- switching from `NORMAL` to `SAFE`

Level2 should not be treated as a trigger to run a second ML model stack inside PTrade.

## Cross-Conversation Workflow

If the ML work and PTrade work live in separate LLM chats, they must coordinate like this:

1. Shared source of truth:
   all chats read the same files under `docs/`

2. Shared data artifacts:
   ML chat writes training and signal outputs under `data/`

3. Stable interface:
   PTrade chat only reads `ml_daily_signal.json/csv` and does not depend on hidden chat context

4. Version fields:
   every signal file carries `model_version`, `feature_version`, and `threshold_version`

5. Change discipline:
   if the signal format changes, update this contract first, then update the strategy reader

## How This Integrates Into PTrade

Recommended daily flow:

1. after market close, ML pipeline builds features and scores day `t`
2. ML pipeline writes `ml_daily_signal.json`
3. before `before_trading_start`, PTrade reads the signal file
4. strategy maps model outputs to mode and risk parameters
5. intraday strategy executes with ML-adjusted controls and lightweight Level2 hard rules
6. if needed, intraday execution facts are summarized after the close and fed back into the next offline ML cycle

## Minimal Reader Rule

PTrade must degrade safely when the signal file is missing or stale:

- log the issue
- fall back to predefined safe defaults
- never crash or trade using partially parsed ML outputs

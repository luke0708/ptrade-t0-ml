# Model Spec

## Purpose

This document defines the final ML system architecture for `300661`, using long-history `1m` data as the core source of edge.

The system is not a single on/off classifier. It is a multi-head decision engine serving daily trading-mode control, risk control, and parameter adaptation.

Important runtime constraint:

- model training and scoring happen offline on the local machine
- PTrade is treated as a closed execution sandbox
- intraday PTrade code must not rely on real-time XGBoost / LightGBM inference
- Level2 belongs either in:
  - intraday hard-rule execution controls
  - post-close summary features for the next offline training cycle

## Modeling Unit

- one sample per trading day `t`
- features built from day `t`
- targets derived from day `t+1`

## Model Heads

### A. Regression Heads

1. `pred_upside_t1`
- predicts `target_upside_t1`

2. `pred_downside_t1`
- predicts `target_downside_t1`
- keep as a research-only regression head for ranking comparison and diagnostics

3. `pred_grid_pnl_t1`
- predicts `target_grid_pnl_t1`
- research-only auxiliary head; not the preferred production controller

### B. Classification / Score Heads

4. `pred_positive_grid_day_t1`
- predicts whether next-day pessimistic grid replay survives costs with positive net PnL

5. `pred_tradable_score_t1`
- predicts whether next day is worth running the grid/VWAP strategy

6. `pred_trend_break_risk_t1`
- predicts whether next day is hostile to mean reversion

7. `pred_hostile_selloff_risk_t1`
- predicts whether next day is likely to produce an early hostile selloff that is unfriendly to dip-buy / grid activation

8. `pred_vwap_reversion_score_t1`
- predicts the quality of next-day VWAP reversion opportunities

### C. Parameter Suggestion Head

9. `recommended_grid_width_t1`
- predicts or maps to the next-day grid-width multiplier

## First Production Version

Use gradient-boosted tree models first:

- `LightGBM` or `XGBoost`

Reasons:

- daily sample count is in the thousands, not millions
- features are structured and heterogeneous
- tree models are easier to validate and interpret
- easier to integrate into the current PTrade workflow

This does **not** mean the tree model is loaded and rescored on every intraday event inside PTrade.
The production contract is:

1. score offline after the close
2. export a compact daily signal
3. let PTrade consume that signal and apply lightweight intraday rules

## Feature Inputs

Allowed features come only from:

- `minute_feature_schema.md`
- stable daily environment features

No undeclared feature may enter production training.

## Validation

Must use rolling time-series validation.

Recommended protocol:

- rolling train window: 2-4 years
- rolling validation window: 3-6 months
- monthly or quarterly walk-forward retrain

## Evaluation

### Regression

- MAE
- RMSE
- rank correlation
- top-decile realized outcome lift

### Classification

- Precision
- Recall
- F1
- PR AUC
- top-score tradability hit rate

### Strategy-Level

The final acceptance criterion is strategy improvement, not just ML score quality:

- higher next-day replay PnL in top-score groups
- lower drawdown on high-risk flagged days
- lower wasted activation rate
- meaningful separation between `SAFE` and `NORMAL`
- no obvious contamination from ex-rights / abnormal event days in critical targets

## Intraday Level2 Role

Level2 is explicitly separated from the daily model:

- allowed intraday role:
  - cancel or delay entries
  - widen grid
  - reduce position size
  - disable dip-buy / aggressive execution
- disallowed intraday role:
  - rebuild large feature sets
  - run a second complex ML scoring stack inside PTrade

Recommended future integration:

1. use Level2 hard rules intraday
2. summarize those observations after the close
3. merge the summary into the next offline feature table

## Current Production Preference

- keep `pred_grid_pnl_t1` as a diagnostic / research head
- prefer `pred_positive_grid_day_t1` as the main production classifier for grid survivability
- use `pred_tradable_score_t1` as the stricter executable filter
- use `pred_hostile_selloff_risk_t1` as the preferred downside / dip-buy risk damper
- treat `pred_trend_break_risk_t1` as a soft constraint, never an absolute veto

## How The 4 Documents Guide ML

- `minute_feature_schema.md`
  defines what can be used as inputs
- `label_definition.md`
  defines what can be predicted
- `model_spec.md`
  defines how models are trained, validated, and combined
- `ptrade_signal_contract.md`
  defines how outputs are consumed by the trading strategy

Together, these four files form the ML system's source of truth. A separate LLM conversation should not invent targets, features, or deployment rules outside these files.

# ML Implementation Plan

## Purpose

This document is the execution plan for the `300661` ML workstream. It translates the design docs into an implementation order, with concrete deliverables and acceptance criteria.

This plan assumes:

- primary minute source is `data/300661_SZ_1m_ptrade.csv`
- environment daily sources are `data/399006.csv` and `data/512480.csv`
- external minute data is optional for v1, not a blocker
- the first production goal is a usable daily decision engine for PTrade, not a research-only notebook

## Success Criteria

The ML workstream is considered successful only if all of the following are true:

- we can build a stable daily training table from long-history `1m` data
- we can generate pessimistic, strategy-aligned labels
- we can train at least one useful first-pass multi-head tree-model stack
- we can write a stable daily signal artifact that PTrade can consume
- walk-forward evaluation shows strategy-level lift, not just ML metric lift

## Workstreams

### Phase 0. Freeze Specs

Goal:

- use `docs/minute_feature_schema.md`
- use `docs/label_definition.md`
- use `docs/model_spec.md`
- use `docs/ptrade_signal_contract.md`

Deliverables:

- no undocumented features in production
- no undocumented labels in production
- stable signal contract for PTrade

Exit criteria:

- all later code references only declared features, labels, and outputs

### Phase 1. Data Foundation

Goal:

- establish canonical data sources and normalized outputs

Tasks:

- normalize `300661_SZ_1m_ptrade.csv`
- detect and repair or safely filter bad minute bars
- derive canonical daily minute-feature input from `1m`
- normalize `300661.csv`, `399006.csv`, `512480.csv`
- keep `399006_5m.csv` and `512480_5m.csv` as optional enhancement sources
- write a repeatable audit summary for coverage, nulls, and anomalies

Deliverables:

- canonical normalized stock minute table
- canonical normalized daily environment tables
- data audit summary

Exit criteria:

- no blocking quality issues remain in the primary stock minute source
- daily sample index is stable and reproducible

### Phase 2. Label Engine

Goal:

- build a strategy-aligned label pipeline

Tasks:

- generate `target_upside_t1`
- generate `target_downside_t1`
- generate `target_tradable_score_t1`
- generate `target_vwap_reversion_t1`
- generate `target_trend_break_risk_t1`
- generate `target_grid_pnl_t1`
- enforce pessimistic replay rules
- enforce same-bar worst-case execution rules
- enforce slippage, fees, and participation caps

Deliverables:

- repeatable label-generation code
- label QA summary

Exit criteria:

- labels are free of look-ahead leakage by construction
- strategy labels reflect pessimistic executable reality

### Phase 3. Feature Engine

Goal:

- build the full daily feature table from `1m` microstructure and daily context

Tasks:

- implement all core intraday structure features
- implement VWAP/reversion features
- implement liquidity and micro-friction features
- implement rolling cross-day summary features
- merge daily environment features
- keep feature versioning stable

Deliverables:

- final training feature table builder
- feature QA and missingness summary

Exit criteria:

- feature builder is deterministic
- feature names match the schema docs

### Phase 4. Baseline Models

Goal:

- train the first production-grade baseline model stack

Tasks:

- regression model for `pred_upside_t1`
- regression model for `pred_downside_t1`
- regression or classification model for `pred_grid_pnl_t1`
- classifier for `pred_tradable_score_t1`
- classifier for `pred_trend_break_risk_t1`
- score model for `pred_vwap_reversion_score_t1`
- parameter suggestion model or mapping for `recommended_grid_width_t1`

Deliverables:

- baseline training scripts
- model artifacts
- walk-forward evaluation reports

Exit criteria:

- at least one model stack shows strategy-level separation between top and bottom score groups

### Phase 5. Signal Export And PTrade Integration

Goal:

- turn model outputs into a stable daily artifact for PTrade

Tasks:

- generate `data/ml_daily_signal.json`
- include `model_version`, `feature_version`, and `threshold_version`
- define fallback behavior for stale or missing files
- map outputs to `trend_weak`, `position_scale`, `grid_width_scale`, and runtime mode

Deliverables:

- daily signal writer
- signal validation checks
- documented PTrade reader expectations

Exit criteria:

- PTrade can consume the signal file without relying on hidden chat context

## First Production Slice

To avoid overbuilding, the first delivery should focus on:

- Phase 1 complete
- Phase 2 complete for `upside`, `downside`, `grid_pnl`, `tradable_score`, `trend_break_risk`, and `vwap_reversion`
- Phase 3 complete for stock-minute plus environment-daily features
- Phase 4 baseline on tree models
- Phase 5 signal export contract

This means external minute data is enhancement work, not a launch blocker.

## Out Of Scope For V1

- minute-sequence deep learning models
- level-2 order book features
- cross-sectional multi-stock training
- intraday live-updating models before a solid end-of-day system exists

## Current Priority Order

1. Canonicalize and audit `300661` long-history `1m`
2. Build pessimistic label engine
3. Build full daily minute-feature table
4. Train baseline multi-head tree models
5. Export stable daily signal for PTrade

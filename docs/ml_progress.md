# ML Progress

## Status Legend

- `done`: completed and accepted as current truth
- `in_progress`: actively being worked on
- `pending`: not started yet
- `blocked`: cannot advance until a dependency is resolved

## Snapshot

- Date: `2026-04-16`
- Workstream: `300661` long-history minute-data ML system
- Overall status: `in_progress`

## What Is Already Settled

### Strategy Understanding

Status: `done`

We have aligned that the live strategy is best described as:

- dynamic grid as the core execution style
- VWAP mean-reversion behavior as a major execution layer
- `trend_weak` as an outer risk-control control, not the whole strategy

### ML Design Direction

Status: `done`

We have aligned that the ML system should not be reduced to a single T+0 switch. The target design is a multi-head daily decision engine with:

- upside prediction
- downside prediction
- tradability score
- trend-break risk
- VWAP reversion score
- grid-width recommendation

### Spec Documents

Status: `done`

The following design docs now exist and are the source of truth:

- [minute_feature_schema.md](</E:/AI炒股/机器学习/docs/minute_feature_schema.md>)
- [label_definition.md](</E:/AI炒股/机器学习/docs/label_definition.md>)
- [model_spec.md](</E:/AI炒股/机器学习/docs/model_spec.md>)
- [ptrade_signal_contract.md](</E:/AI炒股/机器学习/docs/ptrade_signal_contract.md>)

### Long-History Primary Minute Source

Status: `done`

Primary stock minute source is now:

- [300661_SZ_1m_ptrade.csv](</E:/AI炒股/机器学习/data/300661_SZ_1m_ptrade.csv>)

Known facts:

- coverage: `2017-06-06 09:31:00` to `2026-04-14 15:00:00`
- rows: `516240`
- fields: `datetime, code, open, high, low, close, volume, amount, price`

This is now the canonical minute source for `300661`.

### Environment Data

Status: `done`

Reserved daily environment paths:

- [300661.csv](</E:/AI炒股/机器学习/data/300661.csv>)
- [399006.csv](</E:/AI炒股/机器学习/data/399006.csv>)
- [512480.csv](</E:/AI炒股/机器学习/data/512480.csv>)

Available optional external minute enhancement files:

- [300661_5m.csv](</E:/AI炒股/机器学习/data/300661_5m.csv>)
- [399006_5m.csv](</E:/AI炒股/机器学习/data/399006_5m.csv>)
- [512480_5m.csv](</E:/AI炒股/机器学习/data/512480_5m.csv>)

Important caveat:

- `300661.csv` is still a placeholder-like empty file and must **not** be treated as a production-ready daily truth source
- `399006.csv` and `512480.csv` have been restored as usable real daily environment files
- external `399006` and `512480` minute/daily files still lack reliable `amount`
- this means v1 can now merge daily environment context directly, while still treating external minute data as optional enhancement

### Old Regression Dataset Status

Status: `done`

Existing files:

- [300661_regression_dataset.csv](</E:/AI炒股/机器学习/data/300661_regression_dataset.csv>)
- [300661_regression_dataset_with_minute_intersection.csv](</E:/AI炒股/机器学习/data/300661_regression_dataset_with_minute_intersection.csv>)

These are useful historical artifacts, but they are **not yet the final production-grade training base**, because they were built before the long-history `1m` source became the primary minute source.

## What Still Needs To Be Built

### 1. Canonical Minute Normalization Pipeline

Status: `done`

Needed deliverables:

- normalize `300661_SZ_1m_ptrade.csv`
- define bad-bar handling rules
- derive stable day index from minute history
- produce a reproducible quality report

Completed outputs:

- [300661_SZ_1m_canonical.csv](</E:/AI炒股/机器学习/data/foundation/300661_SZ_1m_canonical.csv>)
- [300661_SZ_1m_daily_summary.csv](</E:/AI炒股/机器学习/data/foundation/300661_SZ_1m_daily_summary.csv>)
- [300661_SZ_1m_audit.json](</E:/AI炒股/机器学习/data/foundation/300661_SZ_1m_audit.json>)

Validated facts from the audit:

- canonical rows: `516240`
- trade days: `2151`
- coverage: `2017-06-06 09:31:00` to `2026-04-14 15:00:00`
- detected frequency: `1m`
- expected bars per day: `240`
- complete trading days: `2151`
- incomplete trading days: `0`
- invalid datetime rows dropped: `0`
- duplicate datetime rows dropped: `0`
- invalid H/L/C rows dropped: `0`
- negative volume rows dropped: `0`
- negative amount rows dropped: `0`
- repaired open rows: `0`

This means the primary stock minute source is now confirmed clean enough to act as the production minute foundation for the next phases.

### 2. Production Label Engine

Status: `done`

Needed deliverables:

- `target_upside_t1`
- `target_downside_t1`
- `target_positive_grid_day_t1`
- pessimistic `target_grid_pnl_t1`
- `target_tradable_score_t1`
- `target_trend_break_risk_t1`
- `target_vwap_reversion_t1`

Completed first-slice outputs:

- [build_label_engine.py](</E:/AI炒股/机器学习/build_label_engine.py>)
- [label_engine.py](</E:/AI炒股/机器学习/ptrade_t0_ml/label_engine.py>)
- [300661_SZ_label_targets.csv](</E:/AI炒股/机器学习/data/foundation/300661_SZ_label_targets.csv>)
- [300661_SZ_label_audit.json](</E:/AI炒股/机器学习/data/foundation/300661_SZ_label_audit.json>)

Completed first-slice labels:

- `target_upside_t1`
- `target_downside_t1`
- `target_positive_grid_day_t1`
- `target_tradable_score_t1`
- `target_vwap_reversion_t1`
- `target_trend_break_risk_t1`
- pessimistic `target_grid_pnl_t1`

Validated facts from the label audit:

- label rows: `2150`
- coverage: `2017-06-06` to `2026-04-13`
- `positive_grid_day_positive_ratio`: `0.4135`
- `tradable_positive_ratio`: `0.3121`
- `vwap_reversion_positive_ratio`: `0.3363`
- `trend_break_risk_positive_ratio`: `0.0981`
- `target_grid_pnl_t1` mean: `-0.004495`
- `target_grid_pnl_t1` median: `0.0`
- `target_grid_pnl_t1` p90: `0.022488`
- `replay_round_trips_t1` max: `7`
- `forced_close_count`: `1458`

Interpretation:

- `target_vwap_reversion_t1` has been tightened from the earlier overly-positive version and now behaves more like a quality filter for mean-reversion days
- `target_positive_grid_day_t1` is now the preferred production classifier for “grid survives costs”
- `target_trend_break_risk_t1` has been reworked into a two-stage label:
  - extreme one-sided hostile trend days remain positive
  - a second “soft signature” branch now captures strong one-sided, hostile-to-mean-reversion days with high VWAP side dominance and low cross count
- this makes the trend-break slice trainable again, but it is still not strong enough for production control

Phase 2 is now complete for the current spec slice.

### 3. Production Feature Builder

Status: `done`

Needed deliverables:

- stock-minute intraday structure features
- VWAP and reversion features
- liquidity and micro-friction features
- rolling statistics
- merge with daily environment features

Completed first-slice outputs:

- [build_feature_engine.py](</E:/AI炒股/机器学习/build_feature_engine.py>)
- [feature_engine.py](</E:/AI炒股/机器学习/ptrade_t0_ml/feature_engine.py>)
- [300661_SZ_feature_table.csv](</E:/AI炒股/机器学习/data/foundation/300661_SZ_feature_table.csv>)
- [300661_SZ_feature_audit.json](</E:/AI炒股/机器学习/data/foundation/300661_SZ_feature_audit.json>)

Completed first-slice feature groups:

- stock-minute intraday structure features
- VWAP and reversion features
- volatility and path-risk features
- volume and micro-friction features
- stock-derived daily features
- 3/5/10/20 day rolling summary features

Validated facts from the feature audit:

- feature rows: `2151`
- coverage: `2017-06-06` to `2026-04-14`
- feature columns: `204`
- stock feature column count: `155`
- label match count: `2150`
- merged environment prefixes: `["idx", "sec"]`
- merged overnight factor columns: `[]`
- current environment daily status:
  - `300661.csv`: `unusable`
  - `399006.csv`: `usable`
  - `512480.csv`: `usable`
  - `overnight_factors.csv`: `unusable`

Still pending inside Phase 3:

- add any approved overnight factor group inputs
- expected raw overnight source files:
  - `data/soxx_daily.csv`
  - `data/nasdaq_daily.csv`

### 4. Baseline Model Stack

Status: `in_progress`

Needed deliverables:

- tree-model baselines
- walk-forward training and evaluation
- model artifact versioning

Completed first-slice outputs:

- [train_baseline_models.py](</E:/AI炒股/机器学习/train_baseline_models.py>)
- [baseline_models.py](</E:/AI炒股/机器学习/ptrade_t0_ml/baseline_models.py>)
- [analyze_baseline_quality.py](</E:/AI炒股/机器学习/analyze_baseline_quality.py>)
- [baseline_quality.py](</E:/AI炒股/机器学习/ptrade_t0_ml/baseline_quality.py>)
- [300661_SZ_training_dataset.csv](</E:/AI炒股/机器学习/data/foundation/300661_SZ_training_dataset.csv>)
- [baseline_stock_only_metadata.json](</E:/AI炒股/机器学习/models/baseline_stock_only/baseline_stock_only_metadata.json>)
- baseline model files under [baseline_stock_only](</E:/AI炒股/机器学习/models/baseline_stock_only>)
- baseline quality analysis outputs under [analysis](</E:/AI炒股/机器学习/analysis>)

Completed first-slice heads:

- `upside_regression`
- `downside_regression`
- `grid_pnl_regression`
- `positive_grid_day_classifier`
- `tradable_classifier`
- `trend_break_risk_classifier`
- `vwap_reversion_classifier`

Validated facts from the baseline metadata:

- training rows: `2153`
- train/test split: `1722 / 431`
- classifier calibration split inside train: `1463 / 259`
- test range: `2024-07-05` to `2026-04-16`
- model feature column count: `203`
- the baseline stack was retrained after removing `next_day_*` leakage columns from model inputs
- the latest run now includes `399006 / 512480` daily environment features
- the latest run also calibrates classifier thresholds on a time-ordered validation slice before final retraining
- a first dedicated quality-analysis pass can now export:
  - per-day test predictions
  - per-head score-bucket summaries
  - `SAFE/NORMAL` replay summaries
  - downside error cases
  - per-head feature importance

Current baseline quality read:

- stock-only first slice reference:
  - `upside_regression` spearman rank corr: `0.0138`
  - `downside_regression` spearman rank corr: `0.0464`
  - `grid_pnl_regression` spearman rank corr: `-0.0122`
  - `tradable_classifier` average precision: `0.2924`
  - `tradable_classifier` ROC AUC: `0.5151`
- current second baseline with environment daily context:
  - `upside_regression` spearman rank corr: `0.0715`
  - `downside_regression` spearman rank corr: `-0.0109`
  - `grid_pnl_regression` spearman rank corr: `-0.0439`
  - `positive_grid_day_classifier` average precision: `0.3764`
  - `positive_grid_day_classifier` ROC AUC: `0.4765`
  - `tradable_classifier` average precision: `0.3171`
  - `tradable_classifier` ROC AUC: `0.5310`
  - `trend_break_risk_classifier` average precision: `0.1464`
  - `trend_break_risk_classifier` ROC AUC: `0.5112`
  - `vwap_reversion_classifier` average precision: `0.3184`
  - `vwap_reversion_classifier` ROC AUC: `0.5939`
  - calibrated threshold recommendations:
    - `positive_grid_day_classifier`: `0.35`
    - `tradable_classifier`: `0.35`
    - `trend_break_risk_classifier`: `0.30`
    - `vwap_reversion_classifier`: `0.25`
  - calibrated test-set behavior:
    - `positive_grid_day_classifier` precision / recall: `0.3456 / 0.5839`
    - `tradable_classifier` precision / recall: `0.3404 / 0.2602`
    - `trend_break_risk_classifier` precision / recall: `0.1333 / 0.0351`
    - `vwap_reversion_classifier` precision / recall: `0.2324 / 0.5244`

Validated facts from the first baseline quality analysis pass:

- `SAFE` currently covers `352 / 431` test days (`81.67%`)
- `NORMAL` currently covers `79 / 431` test days (`18.33%`)
- `AGGRESSIVE` and `OFF` were not triggered on the current test slice
- `SAFE` replay mean is `-0.00618`
- `NORMAL` replay mean is `-0.00532`
- this means current mode gating is still too weak to create strong strategy-level separation
- current `downside_regression` importance is concentrated in:
  - `ma20`
  - `ma60`
  - `stk_m_realized_volatility`
  - recent volatility / large-vwap-deviation rolling features
- this suggests the current downside head is leaning more on medium-horizon volatility regime context than on a sharp next-day hostile selloff signature

Interpretation:

- the training pipeline is now real and reproducible
- `positive_grid_day_classifier` is now the better primary production gate for grid survivability
- daily environment context plus threshold calibration still provide useful lift for `tradable_classifier` and `vwap_reversion_classifier`
- `trend_break_risk_classifier` is no longer broken by an ultra-sparse label slice, but its discrimination is still weak and it should stay a research / soft-constraint head
- `grid_pnl_regression` remains unsuitable for direct live parameter control
- `downside_regression` has materially weakened in the latest rerun and now requires explicit target / feature diagnosis before further live use
- the system is **not ready for direct live deployment**
- next gains will likely require stronger labels, richer context, and a better explanation of why the current `SAFE` vs `NORMAL` split is not separating replay quality enough

### 5. Daily Signal Export

Status: `in_progress`

Needed deliverables:

- `data/ml_daily_signal.json`
- versioned output fields
- PTrade-safe fallback behavior

Completed first-slice outputs:

- [export_ml_daily_signal.py](</E:/AI炒股/机器学习/export_ml_daily_signal.py>)
- [signal_export.py](</E:/AI炒股/机器学习/ptrade_t0_ml/signal_export.py>)
- [ml_daily_signal.json](</E:/AI炒股/机器学习/data/ml_daily_signal.json>)
- [ml_daily_signal.csv](</E:/AI炒股/机器学习/data/ml_daily_signal.csv>)

Validated facts from the latest signal export:

- feature date: `2026-04-17`
- signal for date: `2026-04-20`
- `pred_upside_t1`: `0.0280`
- `pred_downside_t1`: `-0.0415`
- `pred_positive_grid_day_t1`: `0.3200`
- `pred_tradable_score_t1`: `0.0793`
- `pred_trend_break_risk_t1`: `0.0235`
- `pred_vwap_reversion_score_t1`: `0.1520`
- `pred_grid_pnl_t1`: `-0.0381`
- `recommended_mode`: `SAFE`
- `position_scale`: `0.55`
- `grid_width_scale`: `1.10`
- `signal_rationale`: `positive_grid_or_tradable_below_threshold`

Interpretation:

- the ML side can now emit a stable, versioned daily artifact for PTrade consumption
- the signal writer is still **experimental**, but it now uses `positive_grid_day` rather than `grid_pnl_regression` as the primary survivability gate
- `trend_break_risk` is currently better treated as a research head than a live control signal, even after the label redesign

## Current Risks

### Risk 1. Spec Drift Across Chats

Status: `active`

Mitigation:

- all future ML and PTrade work should anchor to the docs under `docs/`
- no feature, label, or signal format should be invented only inside a chat

### Risk 2. External Minute `amount` Missing

Status: `active`

Impact:

- external VWAP/amount-derived features are limited

Mitigation:

- rely primarily on `300661` long-history `1m`
- keep external daily features as stable context
- treat external minute features as optional enhancement in v1

### Risk 4. Stock Daily Truth File Is Still Missing

Status: `active`

Impact:

- any chat or script that blindly reads `data/300661.csv` will still get invalid input in the current workspace snapshot

Mitigation:

- keep Phase 1 and Phase 2 fully anchored to:
- keep Phase 3 first slice anchored to:
  - [300661_SZ_1m_canonical.csv](</E:/AI炒股/机器学习/data/foundation/300661_SZ_1m_canonical.csv>)
  - [300661_SZ_1m_daily_summary.csv](</E:/AI炒股/机器学习/data/foundation/300661_SZ_1m_daily_summary.csv>)
  - [300661_SZ_label_targets.csv](</E:/AI炒股/机器学习/data/foundation/300661_SZ_label_targets.csv>)
  - [300661_SZ_feature_table.csv](</E:/AI炒股/机器学习/data/foundation/300661_SZ_feature_table.csv>)
- continue treating `300661.csv` as non-authoritative until it is rebuilt from a trusted source

### Risk 3. Overbuilding Before Baseline

Status: `active`

Mitigation:

- finish the first production slice before adding advanced models

## Immediate Next Steps

1. Read `analysis/safe_mode_replay_summary.csv` and confirm whether `SAFE` days are truly worse enough to justify live gating
2. Read `analysis/downside_error_cases.csv` and inspect why the worst `downside` misses include multiple positive next-day downside values
3. Use `analysis/head_feature_importance.csv` to check whether `downside_regression` is overweighting slow regime features versus next-day hostile selloff precursors
4. Keep `grid_pnl_regression` as a research head and let `positive_grid_day_classifier` remain the main production gate
5. Only after the baseline quality diagnosis is understood, decide whether the next gain should come from overnight factors, label redesign, or Level2-derived post-close summary features

## Coordination Rule

If ML work and PTrade work continue in separate chats, both sides must treat:

- `docs/*.md`
- `data/*.csv`
- `data/ml_daily_signal.json`

as the only shared communication layer.

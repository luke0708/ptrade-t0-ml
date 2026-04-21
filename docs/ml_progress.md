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

## Recent Updates

### Daily / Weekly Runbook Unified

Status: `done`

The daily and weekly operating docs have been fully unified across:

- `README.md`
- `Project Plan.md`
- `docs/mac_daily_weekly_runbook.md`

Current fixed truth:

- daily production uses:
  - `python daily_backfill_data_mac.py`
  - `python build_minute_foundation.py`
  - `python build_feature_engine.py`
  - `python export_ml_daily_signal.py`
- weekend research uses:
  - `python build_label_engine.py`
  - `python train_baseline_models.py`
  - `python analyze_baseline_quality.py`
  - `python analyze_walk_forward.py`
  - `python analyze_walk_forward_failures.py`
- model adoption is a separate, explicit step:
  - `python promote_baseline_candidate.py`
  - `python export_ml_daily_signal.py`

Clarified dependency rules:

- `300661 1m` and `feature_table` are hard dependencies for daily inference
- `399006` and `512480` are soft dependencies for daily inference
- stale soft dependencies do not block export, but force the exported signal down to `SAFE`

### Overnight Factors And Downside Research Head

Status: `done`

We completed two model-quality plumbing changes:

- `build_feature_engine.py` now auto-refreshes `overnight_factors.csv` when local
  `data/soxx_daily.csv` and `data/nasdaq_daily.csv` are present
- the merged overnight factor group now includes:
  - `overnight_us_mean_return`
  - `overnight_us_relative_strength_spread`
  - `overnight_us_direction_agreement_flag`
- environment gap context now explicitly includes:
  - `idx_gap_pct`
  - `sec_gap_pct`
  - `stk_idx_gap_spread`
  - `stk_sec_gap_spread`
  - `idx_sec_gap_spread`

We also promoted `target_downside_from_open_t1` from a passive diagnostic label into a research-only regression head:

- head name: `downside_from_open_regression`
- purpose:
  - compare open-anchored downside ranking against the legacy close-anchored downside
  - keep production control unchanged while research continues
- production control still prioritizes `target_hostile_selloff_risk_t1`

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
- [analyze_walk_forward.py](</E:/AI炒股/机器学习/analyze_walk_forward.py>)
- [analyze_downside_targets.py](</E:/AI炒股/机器学习/analyze_downside_targets.py>)
- [baseline_quality.py](</E:/AI炒股/机器学习/ptrade_t0_ml/baseline_quality.py>)
- [walk_forward_analysis.py](</E:/AI炒股/机器学习/ptrade_t0_ml/walk_forward_analysis.py>)
- [downside_target_analysis.py](</E:/AI炒股/机器学习/ptrade_t0_ml/downside_target_analysis.py>)
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

Validated facts from the downside target audit:

- current close-anchored `target_downside_t1` has `158` positive days (`7.34%`)
- `target_downside_t1 > 3%` occurs on `14` days
- `target_upside_t1 > 10%` occurs on `80` days
- large next-day gap days currently count `10`
- suspicious abnormal-jump days currently count `12`
- many suspicious days are concentrated around:
  - early post-listing limit-up style sequences
  - holiday / reopening gaps
  - abrupt large upward discontinuities
- the current training-frame leakage audit now explicitly records:
  - excluded reference columns present in the merged frame
  - excluded `next_day_ / target_ / replay_` columns present in the merged frame
  - zero selected feature violations
  - `leakage_guard_passed = true`

First in-memory downside target comparison:

- `target_downside_t1`
  - positive ratio: `9.51%`
  - test spearman: `-0.0109`
- `target_downside_from_open_t1`
  - positive ratio: `0.00%`
  - test spearman: `-0.0791`
- `target_downside_from_max_anchor_t1`
  - positive ratio: `0.00%`
  - test spearman: `-0.0050`

First in-memory abnormal-jump filtering check on the current test slice:

- only `4` suspicious abnormal-jump rows fall inside the current test window
- filtering those rows does **not** materially improve downside ranking:
  - `target_downside_t1`: `-0.0109 -> -0.0135`
  - `target_downside_from_open_t1`: `-0.0791 -> -0.0783`
  - `target_downside_from_max_anchor_t1`: `-0.0050 -> -0.0101`

Interpretation:

- simply switching to `next_day_open` anchor does remove positive downside days
- but the first rerun does **not** automatically improve ranking quality
- simply filtering suspicious jump rows inside the current test slice also does **not** solve the ranking problem
- this means the next downside repair step should treat:
  - target definition
  - abnormal-event filtering
  - and feature alignment
as a combined diagnosis problem rather than assuming one anchor change will solve it

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

1. Run `analyze_walk_forward.py` and read:
   - `analysis/walk_forward_mode_summary.csv`
   - `analysis/walk_forward_window_mode_summary.csv`
   - `analysis/walk_forward_head_metrics.csv`
2. Confirm whether the refactored `NORMAL` slice still keeps a materially cleaner left tail across rolling windows, not just the single latest holdout split
3. If overnight factors are still desired, first provide:
   - `data/soxx_daily.csv`
   - `data/nasdaq_daily.csv`
4. Only after walk-forward quality is understood, decide whether the next gain should come from overnight context, abnormal-event filtering, or Level2-derived post-close summary features

## Latest Update: Hostile Selloff Risk Head

Implemented a new production-facing downside risk label and head:

- `target_hostile_selloff_risk_t1`
- `hostile_selloff_risk_classifier`
- `pred_hostile_selloff_risk_t1`

Current definition summary:

- anchor downside to `max(today_close, next_day_open)`
- focus on the first `30-60` minutes instead of raw full-day low only
- require an early hostile drawdown signature plus hostile execution context:
  - weak tradability
  - failed VWAP reversion
  - persistent trading below running VWAP
  - weak close recovery from the early low
  - or negative trend-break confirmation

New label diagnostics now emitted by `label_engine.py`:

- `next_day_open30_low_return`
- `next_day_open60_low_return`
- `next_day_low_in_first_hour_flag`
- `next_day_close_vs_anchor_return`
- `next_day_close_recovery_ratio_from_early_low`
- `next_day_negative_vwap_ratio`
- `next_day_hostile_selloff_soft_score`
- `next_day_hostile_selloff_extreme_t1`

Validated facts from the first real-data in-memory check:

- total rows: `2153`
- `target_hostile_selloff_risk_t1` positive ratio: `17.56%`
- `next_day_hostile_selloff_extreme_t1` positive ratio: `0.14%`
- current test-slice positive ratio: `17.87%`
- first baseline classifier pass:
  - average precision: `0.2231`
  - ROC AUC: `0.6048`
  - default threshold `0.50` recall: `0.1429`
  - calibrated threshold `0.25` recall: `0.5065`

Interpretation:

- this looks materially more aligned with the real `300661` strategy problem than the current raw `downside_regression`
- the head is not yet a strong standalone alpha source, but it is already usable as a production-side dip-buy / mode-damping signal
- `pred_downside_t1` should remain exported for diagnostics, while `pred_hostile_selloff_risk_t1` becomes the preferred live downside controller

Latest controller interaction summary:

- added [controller_interaction_summary.csv](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/analysis/controller_interaction_summary.csv)
- key combined segments on the current test slice:
  - `pg_tr_on_hs_on`: `45` rows, `grid_pnl_mean = -0.008786`, `p10 = -0.036325`, worst day `-0.187665`
  - `pg_tr_on_hs_off`: `38` rows, `grid_pnl_mean = -0.000205`, `p10 = -0.012609`, worst day `-0.026786`
  - `trend_low_hs_high`: `165` rows, `grid_pnl_mean = -0.009072`
  - `vwap_on_hs_on`: `75` rows, `grid_pnl_mean = -0.013971`
  - `vwap_on_hs_off`: `110` rows, `grid_pnl_mean = -0.002340`

Interpretation:

- hostile selloff high-risk days materially worsen left-tail outcomes even when `positive_grid` and `tradable` are both on
- this means `hostile_selloff` should stay as a real production dampener
- the next tuning step should not weaken this head; it should refine how PTrade maps this signal into:
  - dip-buy veto
  - position scaling
  - grid-width widening

Latest signal-controller refactor:

- rewrote the daily controller in [signal_export.py](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/ptrade_t0_ml/signal_export.py) around explicit states:
  - `core_edge = positive_grid_on and tradable_on`
  - `clean_edge = core_edge and not hostile_selloff_high`
  - `reversion_edge = clean_edge and vwap_on`
- `trend_break_risk` is no longer treated as an automatic `SAFE` veto
- `hostile_selloff` remains the primary downside execution blocker
- branch rationales are now explicit:
  - `clean_edge_without_hostile_selloff`
  - `clean_edge_with_trend_damper`
  - `hostile_selloff_blocks_execution`
  - `positive_grid_without_tradable_confirmation`
  - `tradable_without_grid_confirmation`
  - `negative_stack_with_hostile_selloff`

Validated facts after rerunning `analyze_baseline_quality.py` with the refactored controller:

- mode distribution:
  - `SAFE = 388`
  - `NORMAL = 38`
  - `OFF = 5`
  - `AGGRESSIVE = 0`
- updated segment quality:
  - `NORMAL` replay mean: `-0.000205`
  - `NORMAL` p10: `-0.012609`
  - `SAFE` replay mean: `-0.006657`
  - `SAFE` p10: `-0.032002`
- current `NORMAL` now maps almost exactly to `pg_tr_on_hs_off`, which is the cleanest executable slice seen so far

Interpretation:

- the controller is now closer to the real empirical split implied by the test slice
- `trend_break_risk` should stay a dampener inside `NORMAL`, not a top-level veto
- the next ML-side gain is more likely to come from better features / context for `positive_grid`, `tradable`, and `hostile_selloff` than from further controller reshuffling alone

Latest walk-forward evaluation tooling:

- added [analyze_walk_forward.py](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/analyze_walk_forward.py)
- added [walk_forward_analysis.py](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/ptrade_t0_ml/walk_forward_analysis.py)
- rolling defaults:
  - train window: `756` rows
  - test window: `63` rows
  - step: `63` rows
- exported analysis files:
  - `analysis/walk_forward_test_predictions.csv`
  - `analysis/walk_forward_head_metrics.csv`
  - `analysis/walk_forward_window_mode_summary.csv`
  - `analysis/walk_forward_mode_summary.csv`
  - `analysis/walk_forward_controller_interaction_summary.csv`
- purpose:
  - validate whether `SAFE/NORMAL/OFF` separation survives rolling windows
  - validate whether `hostile_selloff` remains a stable left-tail blocker outside one fixed holdout slice
  - keep ML optimization moving even when `overnight_factors.csv` is blocked by missing raw source files

Validated facts after the first real-data `walk-forward` run:

- default window setup:
  - train window: `756` rows
  - test window: `63` rows
  - step: `63` rows
- total walk-forward windows: `22`
- prediction coverage: `2020-07-13` to `2026-03-31`
- total evaluated days: `1386`
- mode distribution across all rolling windows:
  - `SAFE = 1045`
  - `NORMAL = 312`
  - `AGGRESSIVE = 27`
  - `OFF = 2`
- overall mode summary:
  - `SAFE` replay mean: `-0.003926`
  - `NORMAL` replay mean: `-0.004249`
  - `AGGRESSIVE` replay mean: `-0.004979`
  - `SAFE` p10: `-0.030402`
  - `NORMAL` p10: `-0.029410`
- per-window comparison:
  - windows with both `SAFE` and `NORMAL`: `22`
  - `NORMAL` beat `SAFE` on replay mean in only `12 / 22` windows
- rolling head metric means:
  - `hostile_selloff_risk_classifier` average precision: `0.3112`
  - `hostile_selloff_risk_classifier` ROC AUC: `0.5992`
  - `positive_grid_day_classifier` average precision: `0.4580`
  - `tradable_classifier` average precision: `0.3911`
  - `vwap_reversion_classifier` average precision: `0.3736`
  - `downside_regression` spearman rank corr: `0.0487`
  - `grid_pnl_regression` spearman rank corr: `0.0023`
  - `upside_regression` spearman rank corr: `0.0052`

Interpretation:

- the controller refactor improved explainability, but the single latest holdout split overstated its stability
- `NORMAL` is not yet a robust rolling-window executable slice
- `hostile_selloff` remains the most stable downside-oriented classification head, but it is not sufficient by itself to create clean strategy-level separation
- the next ML gain should come from better context features or label refinement, not more controller-only reshuffling

Latest walk-forward failure diagnosis:

- added [analyze_walk_forward_failures.py](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/analyze_walk_forward_failures.py)
- added [walk_forward_failure_analysis.py](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/ptrade_t0_ml/walk_forward_failure_analysis.py)
- exported analysis files:
  - `analysis/walk_forward_failure_windows.csv`
  - `analysis/walk_forward_failure_cohort_summary.csv`
  - `analysis/walk_forward_failure_feature_delta.csv`
  - `analysis/walk_forward_failure_threshold_drift.csv`
  - `analysis/walk_forward_failure_cases.csv`

Validated facts from the first real-data failure pass:

- losing windows where `NORMAL <= SAFE`: `10`
- winning windows where `NORMAL > SAFE`: `12`
- worst failure windows:
  - window `17`: `2024-09-03 -> 2024-12-09`, `SAFE = -0.005210`, `NORMAL = -0.050938`
  - window `13`: `2023-08-21 -> 2023-11-23`, `SAFE = 0.000483`, `NORMAL = -0.008793`
  - window `9`: `2022-08-08 -> 2022-11-10`, `SAFE = -0.000902`, `NORMAL = -0.006013`
- cohort comparison for `NORMAL` days:
  - failure windows:
    - `grid_pnl_mean = -0.007872`
    - `target_positive_grid_day_rate = 0.3129`
    - `target_tradable_rate = 0.2393`
    - `pred_positive_grid_day_mean = 0.4922`
    - `pred_tradable_mean = 0.4372`
  - good windows:
    - `grid_pnl_mean = -0.000285`
    - `target_positive_grid_day_rate = 0.4430`
    - `target_tradable_rate = 0.3289`
    - `pred_positive_grid_day_mean = 0.4969`
    - `pred_tradable_mean = 0.4155`
- largest negative feature deltas on failure `NORMAL` days:
  - `next_day_close_recovery_ratio_from_early_low`
  - `target_positive_grid_day_t1`
  - `pred_vwap_reversion_score_t1`
  - `target_tradable_score_t1`
  - `target_vwap_reversion_t1`
- threshold drift:
  - failure windows use lower mean thresholds on:
    - `hostile_selloff_risk_classifier`
    - `positive_grid_day_classifier`
    - `vwap_reversion_classifier`
  - `vwap_reversion_classifier` AP is materially weaker in failure windows (`0.3100` vs `0.4266`)
- worst failure cases are still mostly tagged as `clean_edge_without_hostile_selloff`, but many of them realize:
  - `target_positive_grid_day_t1 = 0`
  - `target_tradable_score_t1 = 0`
  - sharp early drawdown or poor early-low recovery

Interpretation:

- the main failure mode is not “hostile risk was obviously high but missed”; it is “the stack overestimated clean reversion/tradability when the day later proved non-tradable”
- this points more strongly to missing regime/context features than to controller mapping defects
- the next feature priority should bias toward:
  - overnight gap / external risk context
  - early hostile selloff precursors
  - VWAP reversion failure regime context

Latest feature-engine extension for failure-regime context:

- extended [feature_engine.py](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/ptrade_t0_ml/feature_engine.py) with new same-day regime features:
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
- added regime flags and rolling rates:
  - `flag_open60_deep_selloff`
  - `flag_open60_negative_vwap_persistent`
  - `flag_open60_poor_recovery`
  - `flag_hostile_selloff_regime`
  - `flag_reversion_failure_regime`

Validated facts from the real-data in-memory feature build:

- row count: `2154`
- column count after the new regime block: `315`
- new feature summaries:
  - `stk_m_open60_low_return` mean: `-0.0161`
  - `stk_m_open60_negative_vwap_ratio` mean: `0.5012`
  - `stk_m_open60_vwap_cross_count` mean: `5.86`
  - `stk_m_hostile_selloff_soft_score` mean: `3.06`
  - `flag_hostile_selloff_regime` positive ratio: `8.82%`
  - `flag_reversion_failure_regime` positive ratio: `17.41%`

Interpretation:

- this adds the exact kind of context the failure diagnosis was missing: early drawdown depth, early VWAP pressure, early-path choppiness, and same-day close recovery quality
- the next required step is not more feature design discussion; it is to rebuild the on-disk feature table and rerun baseline plus walk-forward with this new block

Latest feature-engine extension for relative environment regime:

- extended [feature_engine.py](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/ptrade_t0_ml/feature_engine.py) with:
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
- the rolling feature block was also rewritten to append columns via `pd.concat`, so the old pandas fragmentation warning no longer reproduces in the in-memory real-data build

Validated facts from the real-data in-memory build after this change:

- row count: `2154`
- column count after relative-environment extension: `382`
- new feature summaries:
  - `stk_idx_return_spread` mean: `0.0016`
  - `stk_sec_return_spread` mean: `-0.0139`
  - `stk_idx_close_to_ma20_spread` mean: `0.0104`
  - `stk_sec_close_to_ma20_spread` mean: `0.0043`
  - `flag_relative_weak_vs_idx` positive ratio: `20.71%`
  - `flag_relative_weak_vs_sec` positive ratio: `14.16%`
  - `flag_gap_up_without_sector_confirmation_rate_5d` mean: `0.1275`

Interpretation:

- the failure diagnostics pointed to weaker `daily_return / sec_daily_return / atr_pct` on bad `NORMAL` windows, so relative-environment context is a more justified next addition than more path-only microstructure features
- the next execution step is to rebuild the on-disk feature table again and rerun `baseline + walk-forward + failure analysis` on top of this `382`-column slice

Validated facts after the first real rerun on the `382`-column slice:

- on-disk feature table:
  - rows: `2154`
  - columns: `382`
  - label matches: `2153`
- baseline holdout metrics:
  - `downside_regression` spearman: `0.0780`
  - `grid_pnl_regression` spearman: `-0.0099`
  - `positive_grid_day_classifier` AP: `0.4151`
  - `tradable_classifier` AP: `0.3463`
  - `hostile_selloff_risk_classifier` AP: `0.2484`
  - `vwap_reversion_classifier` AP: `0.3597`
- walk-forward rolling means:
  - `downside_regression` spearman: `0.0907`
  - `positive_grid_day_classifier` AP: `0.4726`
  - `tradable_classifier` AP: `0.3782`
  - `hostile_selloff_risk_classifier` AP: `0.3121`
  - `vwap_reversion_classifier` AP: `0.3781`
- walk-forward mode summary:
  - `SAFE` mean: `-0.004003`
  - `NORMAL` mean: `-0.004191`
  - `AGGRESSIVE` mean: `-0.000951`
  - losing windows where `NORMAL <= SAFE`: `11`
  - winning windows where `NORMAL > SAFE`: `11`

Updated interpretation:

- the new relative-environment block improved several heads, especially:
  - `downside_regression`
  - `positive_grid_day_classifier`
  - `vwap_reversion_classifier`
- but the main controller problem remains:
  - `NORMAL` still does not stably beat `SAFE` across rolling windows
- this means the next gain is more likely to come from:
  - target/decision redesign for `NORMAL`
  - or richer context features that explain failed tradability/reversion
  - not from continuing to widen the same feature family without changing the downstream decision logic

## Coordination Rule

If ML work and PTrade work continue in separate chats, both sides must treat:

- `docs/*.md`
- `data/*.csv`
- `data/ml_daily_signal.json`

as the only shared communication layer.

## PTrade Daily Render Integration

Added a dedicated PTrade strategy rendering layer so the daily production chain no longer stops at `ml_daily_signal.json`.

Code changes:

- added [ptrade_strategy_export.py](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/ptrade_t0_ml/ptrade_strategy_export.py)
- added [export_ptrade_strategy.py](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/export_ptrade_strategy.py)
- extended [config.py](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/ptrade_t0_ml/config.py) with:
  - `ptrade_strategy_template_path`
  - `ptrade_strategy_output_dir`
  - `ptrade_strategy_latest_path`
  - `ptrade_strategy_dated_path(signal_for_date)`
- extended [signal_export.py](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/ptrade_t0_ml/signal_export.py) so `python export_ml_daily_signal.py` now also writes a dated PTrade script

Operational contract:

- template source remains:
  - `data/ptrade_300661.py`
- daily generated local artifacts now include:
  - `generated/ptrade/ptrade_300661_latest.py`
  - `generated/ptrade/ptrade_300661_YYYYMMDD.py`
- `YYYYMMDD` uses `signal_for_date`, so the filename itself tells which trading day the script is for

Reasoning:

- the user wants a directly copyable PTrade script each day, not just `ml_daily_signal.json`
- keeping the template separate from dated rendered outputs avoids daily manual payload replacement
- writing generated scripts under local `generated/` avoids coupling daily operational artifacts to the `data/` symlink target

## Daily / Weekly Runbook Clarification

The operating cadence has now been made explicit in project docs:

- [README.md](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/README.md)
- [Project Plan.md](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/Project%20Plan.md)
- [mac_daily_weekly_runbook.md](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/docs/mac_daily_weekly_runbook.md)

Confirmed operating rules:

- `1m` raw data is daily-critical and should be backfilled after every close
- daily production flow is:
  - `daily_backfill_data_mac.py`
  - `build_minute_foundation.py`
  - `build_feature_engine.py`
  - `export_ml_daily_signal.py`
- weekly training / model acceptance flow is:
  - `build_label_engine.py`
  - `train_baseline_models.py`
  - `analyze_walk_forward.py`
  - `analyze_walk_forward_failures.py`
  - `export_ml_daily_signal.py`
- `data/ptrade_300661.py` is now treated as a template source that may continue to evolve and may be copied back from external PTrade
- `generated/ptrade/ptrade_300661_YYYYMMDD.py` is the operational artifact actually copied into PTrade

Signal-date improvement:

- `signal_for_date` is no longer documented as a simple “next weekday” concept
- the export path now prefers the A-share trading calendar and only falls back to the weekend-only rule if calendar lookup fails
- this keeps both:
  - `ml_daily_signal.json`
  - `ptrade_300661_YYYYMMDD.py`
aligned with the next actual trading day across holiday gaps

## Candidate / Production Model Split

The repo now separates research training from daily production inference:

- production model directory:
  - `models/baseline_stock_only/`
- candidate model directory:
  - `models/baseline_candidate/`

Current behavior:

- `train_baseline_models.py`
  - trains into candidate
- `analyze_baseline_quality.py`
  - reads / builds candidate
- `analyze_walk_forward.py`
  - reads / builds candidate
- `analyze_walk_forward_failures.py`
  - reads / builds candidate
- `export_ml_daily_signal.py`
  - reads production only
- `promote_baseline_candidate.py`
  - is now the explicit acceptance step from candidate -> production

Reasoning:

- daily inference should stay stable across weekdays
- weekly research retrains should not silently replace the production model
- model acceptance is now a distinct operational action instead of an accidental side-effect of training

## Mac Backfill Freshness Guard

Updated [daily_backfill_data_mac.py](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/daily_backfill_data_mac.py) so the script no longer treats “fetched nothing new” as silent success.

Current behavior:

- after updating:
  - `300661_SZ_1m_ptrade.csv`
  - `399006.csv`
  - `512480.csv`
- the script now checks whether these files have reached the expected latest trading date
- if the local time is already after market close but the files are still stale, the script exits non-zero

Purpose:

- prevent the downstream chain from exporting a next-day signal off stale inputs
- make “daily inference correctness” observable from the backfill stage instead of only noticing it at `export_ml_daily_signal.py`

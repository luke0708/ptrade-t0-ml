from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import os
from pathlib import Path


@dataclass(frozen=True)
class LabelThresholds:
    daily_amplitude: float = 0.035
    close_floor_ratio: float = 0.98


@dataclass(frozen=True)
class ModelHyperparameters:
    max_depth: int = 4
    learning_rate: float = 0.05
    n_estimators: int = 200
    subsample: float = 0.9
    colsample_bytree: float = 0.9
    random_state: int = 42
    n_jobs: int = 1


@dataclass(frozen=True)
class RecallTuningConfig:
    validation_ratio: float = 0.15
    positive_weight_multipliers: tuple[float, ...] = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
    decision_thresholds: tuple[float, ...] = (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60)
    min_recall_target: float = 0.60
    ranking_beta: float = 2.0


@dataclass(frozen=True)
class GridReplayConfig:
    atr_window: int = 20
    atr_min_periods: int = 5
    atr_multiplier: float = 0.4
    min_grid_step_pct: float = 0.008
    max_grid_step_pct: float = 0.035
    one_way_slippage: float = 0.001
    commission_rate: float = 0.0002
    stamp_tax_rate: float = 0.0005
    participation_rate: float = 0.05
    order_size_shares: int = 100
    min_round_trips_for_tradable: int = 1


@dataclass(frozen=True)
class MinuteFeatureConfig:
    open_windows: tuple[int, ...] = (5, 15, 30, 60)
    morning_bar_count: int = 120
    last_window_bars: int = 30
    midday_exclusion_bars: int = 30
    high_low_time_buckets: int = 8
    vwap_large_deviation_threshold: float = 0.01
    vwap_reversion_lookahead_bars: int = 15
    volume_spike_multiplier: float = 3.0
    volume_profile_bins: int = 10
    rolling_windows: tuple[int, ...] = (3, 5, 10, 20)
    large_drawdown_threshold: float = 0.02
    strong_tail_close_threshold: float = 0.01
    strong_afternoon_reversal_threshold: float = 0.01
    relative_weakness_threshold: float = 0.02


@dataclass(frozen=True)
class StrategyLabelConfig:
    vwap_reversion_threshold: float = 0.01
    vwap_reversion_lookahead_bars: int = 30
    vwap_reversion_min_capture_abs: float = 0.005
    vwap_reversion_min_capture_ratio: float = 0.60
    vwap_reversion_residual_threshold: float = 0.003
    vwap_reversion_label_min_success_count: int = 2
    vwap_reversion_label_min_capture_abs: float = 0.011
    vwap_reversion_label_min_cross_count: int = 3
    vwap_reversion_label_max_dominant_side_ratio: float = 0.85
    trend_break_min_open_close_return: float = 0.015
    trend_break_grid_step_multiplier: float = 1.25
    trend_break_directional_efficiency_min: float = 0.55
    trend_break_soft_directional_efficiency_min: float = 0.35
    trend_break_trend_efficiency_ratio_min: float = 0.32
    trend_break_soft_trend_efficiency_ratio_min: float = 0.12
    trend_break_open15_return_min: float = 0.008
    trend_break_soft_open15_return_min: float = 0.004
    trend_break_open15_volume_ratio_min: float = 0.14
    trend_break_soft_open15_volume_ratio_min: float = 0.08
    trend_break_close_location_threshold: float = 0.80
    trend_break_vwap_side_ratio_min: float = 0.70
    trend_break_soft_vwap_side_ratio_min: float = 0.60
    trend_break_max_vwap_cross_count: int = 6
    trend_break_soft_max_vwap_cross_count: int = 12
    trend_break_soft_score_min: int = 5
    trend_break_label_trend_efficiency_ratio_min: float = 0.12
    trend_break_label_vwap_side_ratio_min: float = 0.84
    trend_break_label_max_vwap_cross_count: int = 6
    trend_break_label_soft_score_min: int = 8
    hostile_selloff_min_drawdown: float = 0.015
    hostile_selloff_grid_step_multiplier: float = 1.40
    hostile_selloff_open15_return_max: float = -0.006
    hostile_selloff_open15_volume_ratio_min: float = 0.08
    hostile_selloff_negative_vwap_ratio_min: float = 0.68
    hostile_selloff_close_return_max: float = -0.008
    hostile_selloff_recovery_ratio_max: float = 0.55
    hostile_selloff_soft_score_min: int = 6
    hostile_selloff_early_bar_limit: int = 60


@dataclass(frozen=True)
class ProjectConfig:
    base_dir: Path
    runtime_data_dir: Path | None = None
    archive_data_dir: Path | None = None
    stock_symbol: str = "300661"
    stock_exchange: str = "SZ"
    start_date: str = "2020-01-01"
    prediction_fetch_calendar_days: int = 180
    min_prediction_bars: int = 60
    test_ratio: float = 0.2
    data_source: str = "akshare"
    label_thresholds: LabelThresholds = field(default_factory=LabelThresholds)
    model_params: ModelHyperparameters = field(default_factory=ModelHyperparameters)
    recall_tuning: RecallTuningConfig = field(default_factory=RecallTuningConfig)
    grid_replay: GridReplayConfig = field(default_factory=GridReplayConfig)
    minute_features: MinuteFeatureConfig = field(default_factory=MinuteFeatureConfig)
    strategy_labels: StrategyLabelConfig = field(default_factory=StrategyLabelConfig)

    @property
    def stock_code(self) -> str:
        return f"{self.stock_symbol}.{self.stock_exchange}"

    @property
    def data_dir(self) -> Path:
        return self.runtime_data_dir or (self.base_dir / "data")

    @property
    def backup_archive_data_dir(self) -> Path | None:
        return self.archive_data_dir

    @property
    def models_dir(self) -> Path:
        return self.base_dir / "models"

    @property
    def plots_dir(self) -> Path:
        return self.base_dir / "plots"

    @property
    def raw_data_path(self) -> Path:
        return self.data_dir / f"{self.stock_symbol}_raw_daily.csv"

    @property
    def local_input_csv_path(self) -> Path:
        return self.data_dir / f"{self.stock_symbol}.csv"

    @property
    def foundation_dir(self) -> Path:
        return self.data_dir / "foundation"

    @property
    def stock_ptrade_1m_path(self) -> Path:
        return self.data_dir / f"{self.stock_symbol}_{self.stock_exchange}_1m_ptrade.csv"

    @property
    def canonical_1m_path(self) -> Path:
        return self.foundation_dir / f"{self.stock_symbol}_{self.stock_exchange}_1m_canonical.csv"

    @property
    def canonical_1m_daily_summary_path(self) -> Path:
        return self.foundation_dir / f"{self.stock_symbol}_{self.stock_exchange}_1m_daily_summary.csv"

    @property
    def canonical_1m_audit_path(self) -> Path:
        return self.foundation_dir / f"{self.stock_symbol}_{self.stock_exchange}_1m_audit.json"

    @property
    def label_targets_path(self) -> Path:
        return self.foundation_dir / f"{self.stock_symbol}_{self.stock_exchange}_label_targets.csv"

    @property
    def label_targets_audit_path(self) -> Path:
        return self.foundation_dir / f"{self.stock_symbol}_{self.stock_exchange}_label_audit.json"

    @property
    def feature_table_path(self) -> Path:
        return self.foundation_dir / f"{self.stock_symbol}_{self.stock_exchange}_feature_table.csv"

    @property
    def feature_audit_path(self) -> Path:
        return self.foundation_dir / f"{self.stock_symbol}_{self.stock_exchange}_feature_audit.json"

    @property
    def training_dataset_path(self) -> Path:
        return self.foundation_dir / f"{self.stock_symbol}_{self.stock_exchange}_training_dataset.csv"

    @property
    def analysis_dir(self) -> Path:
        return self.base_dir / "analysis"

    @property
    def baseline_test_predictions_path(self) -> Path:
        return self.analysis_dir / "baseline_test_predictions.csv"

    @property
    def head_bucket_summary_path(self) -> Path:
        return self.analysis_dir / "head_bucket_summary.csv"

    @property
    def safe_mode_replay_summary_path(self) -> Path:
        return self.analysis_dir / "safe_mode_replay_summary.csv"

    @property
    def controller_interaction_summary_path(self) -> Path:
        return self.analysis_dir / "controller_interaction_summary.csv"

    @property
    def downside_error_cases_path(self) -> Path:
        return self.analysis_dir / "downside_error_cases.csv"

    @property
    def head_feature_importance_path(self) -> Path:
        return self.analysis_dir / "head_feature_importance.csv"

    @property
    def downside_target_comparison_path(self) -> Path:
        return self.analysis_dir / "downside_target_comparison.csv"

    @property
    def downside_target_predictions_path(self) -> Path:
        return self.analysis_dir / "downside_target_predictions.csv"

    @property
    def walk_forward_test_predictions_path(self) -> Path:
        return self.analysis_dir / "walk_forward_test_predictions.csv"

    @property
    def walk_forward_head_metrics_path(self) -> Path:
        return self.analysis_dir / "walk_forward_head_metrics.csv"

    @property
    def walk_forward_window_mode_summary_path(self) -> Path:
        return self.analysis_dir / "walk_forward_window_mode_summary.csv"

    @property
    def walk_forward_mode_summary_path(self) -> Path:
        return self.analysis_dir / "walk_forward_mode_summary.csv"

    @property
    def walk_forward_controller_interaction_summary_path(self) -> Path:
        return self.analysis_dir / "walk_forward_controller_interaction_summary.csv"

    @property
    def walk_forward_failure_windows_path(self) -> Path:
        return self.analysis_dir / "walk_forward_failure_windows.csv"

    @property
    def walk_forward_failure_cohort_summary_path(self) -> Path:
        return self.analysis_dir / "walk_forward_failure_cohort_summary.csv"

    @property
    def walk_forward_failure_feature_delta_path(self) -> Path:
        return self.analysis_dir / "walk_forward_failure_feature_delta.csv"

    @property
    def walk_forward_failure_threshold_drift_path(self) -> Path:
        return self.analysis_dir / "walk_forward_failure_threshold_drift.csv"

    @property
    def walk_forward_failure_cases_path(self) -> Path:
        return self.analysis_dir / "walk_forward_failure_cases.csv"

    @property
    def overnight_factors_path(self) -> Path:
        return self.data_dir / "overnight_factors.csv"

    @property
    def overnight_semiconductor_source_path(self) -> Path:
        return self.data_dir / "soxx_daily.csv"

    @property
    def overnight_nasdaq_source_path(self) -> Path:
        return self.data_dir / "nasdaq_daily.csv"

    @property
    def baseline_models_dir(self) -> Path:
        return self.models_dir / "baseline_stock_only"

    @property
    def baseline_metadata_path(self) -> Path:
        return self.baseline_models_dir / "baseline_stock_only_metadata.json"

    @property
    def features_path(self) -> Path:
        return self.data_dir / f"{self.stock_symbol}_features.csv"

    @property
    def labeled_data_path(self) -> Path:
        return self.data_dir / f"{self.stock_symbol}_labeled_dataset.csv"

    @property
    def model_path(self) -> Path:
        return self.models_dir / "xgb_t0_model.json"

    @property
    def model_metadata_path(self) -> Path:
        return self.models_dir / "xgb_t0_model_metadata.json"

    @property
    def feature_importance_plot_path(self) -> Path:
        return self.plots_dir / "feature_importance_top10.png"

    @property
    def daily_signal_csv_path(self) -> Path:
        return self.data_dir / "daily_signal.csv"

    @property
    def daily_signal_json_path(self) -> Path:
        return self.data_dir / "signal.json"

    @property
    def ml_daily_signal_csv_path(self) -> Path:
        return self.data_dir / "ml_daily_signal.csv"

    @property
    def ml_daily_signal_json_path(self) -> Path:
        return self.data_dir / "ml_daily_signal.json"

    @property
    def generated_dir(self) -> Path:
        return self.base_dir / "generated"

    @property
    def ptrade_strategy_template_path(self) -> Path:
        return self.data_dir / f"ptrade_{self.stock_symbol}.py"

    @property
    def ptrade_strategy_output_dir(self) -> Path:
        return self.generated_dir / "ptrade"

    @property
    def ptrade_strategy_latest_path(self) -> Path:
        return self.ptrade_strategy_output_dir / f"ptrade_{self.stock_symbol}_latest.py"

    def ptrade_strategy_dated_path(self, signal_for_date: str) -> Path:
        compact_date = signal_for_date.replace("-", "")
        return self.ptrade_strategy_output_dir / f"ptrade_{self.stock_symbol}_{compact_date}.py"

    @property
    def today_str(self) -> str:
        return date.today().isoformat()


BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_optional_path(env_name: str) -> Path | None:
    raw_value = os.getenv(env_name, "").strip()
    if not raw_value:
        return None
    return Path(raw_value).expanduser()


DEFAULT_CONFIG = ProjectConfig(
    base_dir=BASE_DIR,
    runtime_data_dir=_resolve_optional_path("PTRADE_RUNTIME_DATA_DIR"),
    archive_data_dir=_resolve_optional_path("PTRADE_ARCHIVE_DATA_DIR"),
)

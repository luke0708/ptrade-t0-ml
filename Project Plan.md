# Project Plan

## 项目定位

这是一个面向 `300661` 的专属 T+0 机器学习辅助项目，不是通用 A 股择时框架。

目标不是让 PTrade 在盘中跑复杂模型，而是构建一条稳定、可复盘、可落地的两层链路：

1. 本地离线机器学习
   - 每个交易日收盘后，在本地 Python 环境中使用分钟、日线和环境特征训练/打分
   - 导出第二个交易日要使用的 `ml_daily_signal.json`
2. PTrade 盘中规则执行
   - `before_trading_start` 读取离线信号
   - 盘中只结合 Level2 做轻量硬规则过滤、降级和参数调整
   - 不在 PTrade 沙盒里做 XGBoost/LightGBM 推理

## 当前真实状态

- 已完成 `Phase 1/2/3`
  - `300661` 长历史 `1m` 底座
  - 生产标签引擎
  - 生产特征引擎
- 已完成 baseline 多头训练与实验版日信号导出
- 已新增 baseline 质量复盘工具
- 当前关键问题不是“怎么把盘中模型塞进 PTrade”，而是：
  - baseline 质量还不够强
  - `SAFE/NORMAL` 的策略级分离度仍弱
  - `downside_regression` 当前表现异常，需要先排查目标定义、样本污染和特征传导问题

## 当前主线文件

### 核心训练链路

- `build_minute_foundation.py`
- `build_label_engine.py`
- `build_feature_engine.py`
- `train_baseline_models.py`
- `export_ml_daily_signal.py`
- `analyze_baseline_quality.py`

### 核心包模块

- `ptrade_t0_ml/minute_foundation.py`
- `ptrade_t0_ml/label_engine.py`
- `ptrade_t0_ml/feature_engine.py`
- `ptrade_t0_ml/baseline_models.py`
- `ptrade_t0_ml/signal_export.py`
- `ptrade_t0_ml/baseline_quality.py`

## 最近确认的架构口径

### 1. PTrade 不跑盘中机器学习推理

PTrade 是封闭 Python 沙盒，盘中运行预算很紧，不能假设可以稳定加载复杂模型并高频推理。

所以当前架构固定为：

- 离线机器学习负责“明天大方向”
- PTrade 负责“今天盘中怎么按规则执行”

### 2. Level2 的正确接入方式

Level2 在当前项目中有两种正确入口：

1. 盘中硬规则
   - 用于即时降级或限流
   - 例如关闭抄底、放宽网格、限制开仓
2. 收盘后摘要特征
   - 盘中不做复杂学习
   - 收盘后把 Level2 行为压缩成可训练的摘要特征，供次日离线模型使用

### 3. 当前生产优先级

- `pred_positive_grid_day_t1`
- `pred_tradable_score_t1`
- `pred_vwap_reversion_score_t1`
- `pred_trend_break_risk_t1` 仅作软约束
- `pred_grid_pnl_t1` 保留为研究头
- `pred_downside_t1` 先做质量诊断，再决定是否继续沿用当前目标定义

## 当前阶段目标

### 阶段 A：先把 baseline 看懂

当前优先目标：

1. 解释为什么 `SAFE/NORMAL` 没拉开足够大的策略级差异
2. 解释为什么 `downside_regression` 当前弱甚至失真
3. 识别是否存在目标泄露、复权污染、异常事件样本污染
4. 确认下一轮应该优先修：
   - 目标定义
   - 特征工程
   - overnight 因子
   - 还是 Level2 收盘摘要特征

### 阶段 B：再决定模型修复路线

只有在阶段 A 完成后，才决定下一步做哪一条：

- 修复 Target Leakage
- 修复 Downside 风险建模
- 接入 overnight 因子
- 设计 Level2 收盘摘要特征

## 当前可直接使用的分析产物

运行：

```bash
source .venv/bin/activate
python analyze_baseline_quality.py
```

会生成：

- `analysis/baseline_test_predictions.csv`
- `analysis/head_bucket_summary.csv`
- `analysis/safe_mode_replay_summary.csv`
- `analysis/downside_error_cases.csv`
- `analysis/head_feature_importance.csv`

这些文件是当前 baseline 质量复盘的第一入口。

## 当前明确不做的事情

- 不在 PTrade 盘中跑 XGBoost 实时推理
- 不在 PTrade 盘中动态构造大批量分钟特征再评分
- 不把旧版日线单模型流程继续当作主线维护
- 不在 baseline 质量还没看明白前就继续堆复杂模型

## 下一步计划

1. 完成仓库清理，移除旧版日线单模型链路与散落的临时测试/抓取脚本
2. 基于 `analysis/` 下的复盘结果，优先排查：
   - Target Leakage
   - `downside_regression` 异常
3. 根据排查结论再更新 `docs/ml_implementation_plan.md` 的执行顺序

# Project Plan

## 项目定位

这是一个面向 `300661` 的专属 T+0 机器学习辅助项目，不是通用 A 股择时框架。

目标不是让 PTrade 在盘中跑复杂模型，而是构建一条稳定、可复盘、可落地的两层链路：

1. 本地离线机器学习
   - 每个交易日收盘后，先补齐分钟 / 日线数据，再用当前生产模型做日频推理
   - 周末或版本升级时，才补标签并重训模型
   - 导出下一个交易日要使用的 `ml_daily_signal.json`
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
- `analyze_walk_forward.py`

### 核心包模块

- `ptrade_t0_ml/minute_foundation.py`
- `ptrade_t0_ml/label_engine.py`
- `ptrade_t0_ml/feature_engine.py`
- `ptrade_t0_ml/baseline_models.py`
- `ptrade_t0_ml/signal_export.py`
- `ptrade_t0_ml/baseline_quality.py`
- `ptrade_t0_ml/walk_forward_analysis.py`

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

### 4. 当前固定运行节奏

当前正式口径已经固定为：

1. 日频推理
   - 每个交易日盘后都要补数
   - 每个交易日盘后都要生成第二天信号和 dated PTrade 策略脚本
2. 周频训练
   - 默认只在周末或版本升级时重训
   - 默认不在工作日随手重训并替换 baseline
3. 训练与采用分离
   - 能训练，不等于应该立刻接受新模型
   - 只有 walk-forward / failure analysis 过关，才接受新的 baseline 作为生产模型

### 5. PTrade 模板与日生成文件

- `data/ptrade_300661.py`
  - 作为模板源文件维护
  - 该文件可能持续优化
  - 也可能由外部 PTrade 环境手工拷回仓库
- `generated/ptrade/ptrade_300661_YYYYMMDD.py`
  - 作为每日可直接复制进 PTrade 的产物
  - `YYYYMMDD` 使用 `signal_for_date`
  - 当前会优先按 A 股交易日历顺延，自动跳过周末与节假日

如果模板更新了，但不需要重新推理，只需要基于已有信号重新生成策略脚本，则执行：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python export_ptrade_strategy.py
```

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

## 固定执行清单

### 每日盘后：生产必跑

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python daily_backfill_data_mac.py
python build_minute_foundation.py
python build_feature_engine.py
python export_ml_daily_signal.py
```

目的：

- 每天补齐 `1m` 和环境日线数据
- 每天生成下一交易日信号
- 每天生成 dated PTrade 策略文件

### 每周末：训练 / 换模评估

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python build_label_engine.py
python train_baseline_models.py
python analyze_walk_forward.py
python analyze_walk_forward_failures.py
python export_ml_daily_signal.py
```

目的：

- 训练候选新模型
- 评估滚动稳定性
- 只在确认通过后，接受新的 baseline 作为生产模型

### 什么时候不要重训

下面这些情况默认不要跑 `train_baseline_models.py`：

- 普通工作日盘后
- 你只是想生成第二天信号
- 你没有做完整的 walk-forward 评估
- 你不准备正式接受新模型

## 当前明确不做的事情

- 不在 PTrade 盘中跑 XGBoost 实时推理
- 不在 PTrade 盘中动态构造大批量分钟特征再评分
- 不把旧版日线单模型流程继续当作主线维护
- 不在 baseline 质量还没看明白前就继续堆复杂模型

## 下一步计划

1. `walk-forward` 失败模式已经落地，下一步优先复盘：
   - 为什么 `clean_edge_without_hostile_selloff` 仍会落到极差日
   - 为什么 `NORMAL` 在失败窗口里高估了 `positive_grid / tradable / vwap_reversion`
2. 如果需要接隔夜因子，先补真实源文件：
   - `data/soxx_daily.csv`
   - `data/nasdaq_daily.csv`
3. 在滚动失败模式看清楚之前，不再优先继续调 controller，而是优先修特征/标签上下文，尤其是：
   - 隔夜 gap / 外盘风险
   - 早盘 hostile selloff 前兆
   - VWAP reversion 失效的 regime 上下文

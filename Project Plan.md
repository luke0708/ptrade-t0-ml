# Project Plan

## 项目定位

这是一个面向 `300661` 的专属 T+0 机器学习辅助项目，不是通用 A 股择时框架。

当前目标不是让 PTrade 在盘中跑复杂模型，而是构建一条稳定、可复盘、可落地的两层链路：

1. 本地离线机器学习
   - 每个交易日收盘后，先补齐分钟 / 日线数据，再用当前 production 模型做日频推理
   - 周末或版本升级时，才补标签并训练 candidate
   - 只有评估通过后，才把 candidate promote 成 production
2. PTrade 盘中规则执行
   - `before_trading_start` 读取离线信号
   - 盘中只结合 Level2 做轻量硬规则过滤、降级和参数调整
   - 不在 PTrade 沙盒里做 XGBoost/LightGBM 推理

## 当前真实状态

- 已完成 `Phase 1/2/3`
  - `300661` 长历史 `1m` 底座
  - 生产标签引擎
  - 生产特征引擎
- 已完成 baseline 多头训练、日信号导出、PTrade dated 脚本导出
- 已完成 candidate / production 分离
- 已完成 baseline 质量复盘、walk-forward、failure analysis 工具
- 当前 production 已更新到 `2026-04-23T13:43:11` 稳定节点
- 当前稳定节点使用：
  - `positive_grid_day_classifier = top 64`
  - `tradable_classifier = top 96`
  - `AGGRESSIVE = 0`，强信号统一落到 `NORMAL`
- 当前 walk-forward 结果：
  - `NORMAL` 共 `51` 天，`grid_pnl_mean = 0.004650`
  - `SAFE` 共 `1334` 天，`grid_pnl_mean = -0.004308`
  - 失败 / 胜利窗口为 `3 / 19`

当前关键问题不是“怎么把盘中模型塞进 PTrade”，而是：

- 当前 production 已经偏稳定，但开仓频率低
- 下一阶段要提高 `NORMAL` 覆盖率，同时不能明显破坏 `3 / 19` 的 walk-forward 稳定性
- 继续提升 `positive_grid / tradable` 的头部质量，比继续小幅放松 controller 阈值更重要

## 当前主线文件

### 训练 / 推理入口

- `daily_backfill_data_mac.py`
- `build_minute_foundation.py`
- `build_label_engine.py`
- `build_feature_engine.py`
- `train_baseline_models.py`
- `export_ml_daily_signal.py`
- `export_ptrade_strategy.py`
- `promote_baseline_candidate.py`
- `analyze_baseline_quality.py`
- `analyze_walk_forward.py`
- `analyze_walk_forward_failures.py`

### 核心包模块

- `ptrade_t0_ml/minute_foundation.py`
- `ptrade_t0_ml/label_engine.py`
- `ptrade_t0_ml/feature_engine.py`
- `ptrade_t0_ml/baseline_models.py`
- `ptrade_t0_ml/signal_export.py`
- `ptrade_t0_ml/ptrade_strategy_export.py`
- `ptrade_t0_ml/baseline_promotion.py`
- `ptrade_t0_ml/baseline_quality.py`
- `ptrade_t0_ml/walk_forward_analysis.py`
- `ptrade_t0_ml/walk_forward_failure_analysis.py`

## 当前固定运行口径

### 1. 训练与采用分离

- `train_baseline_models.py`
  - 只训练 candidate
- `promote_baseline_candidate.py`
  - 是唯一把 candidate 提升成 production 的动作
- `export_ml_daily_signal.py`
  - 只读取 production

这意味着：

- 周末可以放心训练和评估 candidate
- 工作日每日推理不会被研究重训污染

### 2. 补数与推理分离，但当日推理依赖当日主数据

概念上：

- 补数
- 推理
- 训练

是三件不同的事。

但在当前项目里：

- 当日推理必须建立在最新 `300661 1m` 和最新特征行之上
- 如果 `300661 1m` 或 `feature_table` 过期，禁止导出下一交易日信号
- `399006` / `512480` 是软依赖，少一天时允许继续，但导出会强制降级到 `SAFE`

### 3. PTrade 模板与每日产物分离

- `data/ptrade_300661.py`
  - 作为模板源文件维护
  - 可能持续优化
  - 也可能由外部 PTrade 环境手工拷回仓库
- `generated/ptrade/ptrade_300661_YYYYMMDD.py`
  - 作为每日可直接复制进 PTrade 的产物
  - `YYYYMMDD` 使用 `signal_for_date`
  - 优先按 A 股交易日历顺延，自动跳过周末与节假日

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

### 每周末：训练与评估

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python build_label_engine.py
python train_baseline_models.py
python analyze_baseline_quality.py
python analyze_walk_forward.py
python analyze_walk_forward_failures.py
```

目的：

- 用最新真实路径补标签
- 训练 candidate
- 评估 candidate 的测试切片质量与滚动稳定性

### 每周末：正式接受新模型

只有 candidate 通过评估后，才执行：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
cp -R models/baseline_stock_only models/baseline_stock_only_backup_$(date +%Y%m%d_%H%M%S)
python promote_baseline_candidate.py
python export_ml_daily_signal.py
```

目的：

- 把 candidate 提升为 production
- 用新 production 模型导出下一交易日信号和 dated PTrade 文件
- promote 前备份旧 production，避免误接受后无法快速回滚

### 什么时候不要重训

下面这些情况默认不要跑 `train_baseline_models.py`：

- 普通工作日盘后
- 你只是想生成第二天信号
- 你没有做完整的 walk-forward 评估
- 你不准备正式接受新模型

## 当前阶段目标

### 阶段 A：保持可挂稳定版

当前优先目标：

1. 保持当前 production 可挂，不在工作日随意替换模型
2. 每日继续补齐 `1m` 数据并导出下一交易日 PTrade 文件
3. 任何训练实验先进入 candidate，不直接污染 production

### 阶段 B：提高开仓质量与频率

下一步优先路线：

1. 继续提升 `positive_grid_day_classifier` 和 `tradable_classifier` 质量
2. 针对 `300661` 高开低走、弱跟随指数的特征，补更明确的隔夜 / 早盘失败 regime 分析
3. 研究更贴近实盘开仓的复合标签或分层 controller，目标是提高 `NORMAL` 数量而不破坏 walk-forward 稳定

当前拆分为三步执行：

1. 阶段 1：只做大振幅机会诊断，不改 production
   - 输出 `analysis/high_swing_recent_review.csv`
   - 拆分“高抛窗口”和“低吸修复窗口”
   - 复盘当前模型把大振幅日判为 `SAFE` 的具体原因
   - 当前已完成首版脚本：`python analyze_high_swing_opportunities.py`
2. 阶段 2：新增 candidate 研究标签
   - `target_high_sell_window_t1`
   - `target_dip_repair_window_t1`
   - 先只进入 candidate 训练和 walk-forward，不直接影响实盘
   - 根据阶段 1 初步结果，优先做 `target_high_sell_window_t1`
3. 阶段 3：再拆 controller 和 PTrade 信号
   - 保留 `recommended_mode`
   - 强化 `high_sell_enabled` / `dip_buy_enabled` / `dip_rebuy_enabled` 等执行开关
   - PTrade 仍只读离线 JSON，不在盘中跑模型

### 阶段 C：补上下文，而不是盲目加模型复杂度

下一步优先路线：

1. 继续补能解释失败窗口的上下文特征
2. 复盘 `overnight` 因子在失败窗口和 `NORMAL` 命中日里的真实贡献
3. 如果现有多头组合仍不稳，再考虑更贴近执行目标的复合标签

## 当前明确不做的事情

- 不在 PTrade 盘中跑 XGBoost 实时推理
- 不在 PTrade 盘中动态构造大批量分钟特征再评分
- 不把旧版日线单模型流程继续当作主线维护
- 不在当前稳定版还没积累实盘反馈前继续堆复杂模型

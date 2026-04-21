# A 股回归数据底座

这是一个面向 `300661` 的专属 T+0 机器学习辅助仓库。

当前固定架构不是“在 PTrade 里盘中跑模型”，而是：

1. 本地离线 ML 在收盘后生成下一交易日的 `ml_daily_signal.json`
2. PTrade 在 `before_trading_start` 读取该信号
3. PTrade 盘中只结合 Level2 做轻量硬规则过滤、降级和参数调整

PTrade 是封闭沙盒，因此当前主线明确不在盘中运行 XGBoost/LightGBM 推理。

## 快速导航

- Mac 日常操作：`docs/mac_daily_weekly_runbook.md`
- 跨机接手说明：`docs/cross_machine_dev_guide.md`
- 当前项目计划：`Project Plan.md`
- 当前进度快照：`docs/ml_progress.md`
- PTrade 信号契约：`docs/ptrade_signal_contract.md`

## 当前固定口径

### 运行目录

- `data/`
  - 本地运行目录
  - 每日补数、foundation、feature、signal 都写到这里
  - 这是开发、训练、推理的唯一真源
- OneDrive
  - 只做备份 / 跨机归档
  - 不再作为每日运行依赖

### 模型槽位

- `models/baseline_stock_only/`
  - 当前 production 模型目录
  - 每日推理只读取这里
- `models/baseline_candidate/`
  - 当前 candidate 模型目录
  - 周末训练和研究分析默认写这里

固定规则：

1. `python train_baseline_models.py`
   - 只训练 candidate
2. `python analyze_baseline_quality.py`
   - 默认分析 candidate
3. `python analyze_walk_forward.py`
   - 默认分析 candidate
4. `python analyze_walk_forward_failures.py`
   - 默认分析 candidate
5. `python export_ml_daily_signal.py`
   - 只读取 production
6. `python promote_baseline_candidate.py`
   - 是唯一把 candidate 提升成 production 的动作

### PTrade 文件关系

- `data/ptrade_300661.py`
  - PTrade 策略模板源文件
  - 可能持续优化
  - 也可能由外部 PTrade 环境手工拷回仓库
- `generated/ptrade/ptrade_300661_latest.py`
  - 当前最新渲染结果
- `generated/ptrade/ptrade_300661_YYYYMMDD.py`
  - 每日实际可复制进 PTrade 的 dated 文件
  - `YYYYMMDD` 使用 `signal_for_date`
  - 该日期表示“下一次真正要在 PTrade 里运行的交易日”
  - 当前优先按 A 股交易日历顺延，自动跳过周末和节假日；如果交易日历接口失败，才退回只跳周末

## 每日 / 每周执行清单

这是当前 `300661` 项目的唯一推荐操作节奏。

核心原则：

1. `1m` 原始数据必须每天盘后补
2. 第二天要用的信号和 PTrade 策略必须每天盘后导出
3. 模型默认不每天重训
4. 周末先评估 candidate，确认通过后再 promote

### 每日盘后：生产必跑

适用场景：

- 普通交易日收盘后
- 目标是生成下一交易日要用的信号和 PTrade 文件

命令：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python daily_backfill_data_mac.py
python build_minute_foundation.py
python build_feature_engine.py
python export_ml_daily_signal.py
```

四步含义：

- `python daily_backfill_data_mac.py`
  - 每天补齐原始数据
  - `300661_SZ_1m_ptrade.csv` 是硬依赖，没补到最新交易日就应该停止后续流程
  - `399006.csv`、`512480.csv` 是软依赖；如果少一天，脚本会警告，但不会因为这两份数据直接失败
- `python build_minute_foundation.py`
  - 基于最新分钟数据重建 canonical / summary
- `python build_feature_engine.py`
  - 基于最新 `t` 日数据生成当天特征
- `python export_ml_daily_signal.py`
  - 使用当前 production 模型做日频推理
  - 生成 `t+1` 交易日信号和 dated PTrade 文件
  - 如果 `300661 1m` 或 `feature_table` 过期，会直接失败
  - 如果 `399006` / `512480` 过期，会允许继续，但会把导出结果强制降级到 `SAFE`

每日跑完后，真正给 PTrade 用的文件是：

- `generated/ptrade/ptrade_300661_YYYYMMDD.py`
- 或 `generated/ptrade/ptrade_300661_latest.py`

推荐做法：

1. 先看 dated 文件名日期是否就是下一交易日
2. 再把 dated 文件内容复制到 PTrade 平台

### 只改了 PTrade 模板时

适用场景：

- 你刚从外部 PTrade 环境拷回新的 `data/ptrade_300661.py`
- 只改了模板
- 不需要重新推理模型

命令：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python export_ptrade_strategy.py
```

说明：

- 这一步不会重算 `ml_daily_signal.json`
- 只是把当前已有信号重新渲染进新的模板

### 每周末：训练与评估

适用场景：

- 周末停盘后
- 本周改了标签 / 特征 / controller
- 你准备评估 candidate 模型

命令：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python build_label_engine.py
python train_baseline_models.py
python analyze_baseline_quality.py
python analyze_walk_forward.py
python analyze_walk_forward_failures.py
```

五步含义：

- `python build_label_engine.py`
  - 用最新真实路径补标签
- `python train_baseline_models.py`
  - 训练 candidate
- `python analyze_baseline_quality.py`
  - 复盘 candidate 在测试切片上的头部质量
- `python analyze_walk_forward.py`
  - 看 candidate 的滚动稳定性
- `python analyze_walk_forward_failures.py`
  - 看 candidate 的失败窗口和 `NORMAL` 失效模式

### 每周末：确认接受新模型时

只有当你确认 candidate 通过评估时，才执行下面两步：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python promote_baseline_candidate.py
python export_ml_daily_signal.py
```

两步含义：

- `python promote_baseline_candidate.py`
  - 把当前 candidate 提升成 production
- `python export_ml_daily_signal.py`
  - 用新的 production 模型重新导出下一交易日信号和 PTrade 文件

### 什么时候不要重训

下面这些情况，默认只跑“每日盘后 4 步”，不要跑 `train_baseline_models.py`：

- 普通工作日盘后
- 你只是想准备明天的策略
- 你没有时间做完整的 walk-forward 评估
- 你不准备正式接受新模型

一句话：

- 工作日默认只推理
- 周末默认才讨论换模

### 什么时候可以接受新模型

当前阶段，建议至少满足下面条件才执行 `python promote_baseline_candidate.py`：

1. `analysis/walk_forward_mode_summary.csv` 里，`NORMAL` 没继续明显差于 `SAFE`
2. `analysis/walk_forward_failure_windows.csv` / `analysis/walk_forward_failure_cohort_summary.csv` 没出现新的大幅恶化窗口
3. 本次改动属于明确版本升级：
   - 标签升级
   - 特征升级
   - controller 升级
4. 你愿意让新的 candidate 覆盖当前 production

## 最低环境验收

如果你是接手机器学习开发，至少先确认：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python -c "import pandas, akshare, numpy, sklearn, matplotlib, xgboost, pandas_ta"
python -m unittest discover -s tests
```

如果上面两步还没通过，说明当前机器还不是完整算法开发环境。

## 详细文档

- `docs/mac_daily_weekly_runbook.md`
  - Mac 每日 / 每周操作手册
- `docs/cross_machine_dev_guide.md`
  - 跨机接手与环境恢复
- `docs/label_definition.md`
  - 标签定义
- `docs/minute_feature_schema.md`
  - 特征结构
- `docs/model_spec.md`
  - 模型规格
- `docs/ptrade_signal_contract.md`
  - PTrade 信号契约
- `docs/ml_progress.md`
  - 最新进度快照

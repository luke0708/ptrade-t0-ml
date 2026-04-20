# A 股回归数据底座

这是一个面向 `300661` 的专属 T+0 机器学习辅助仓库。

当前固定架构不是“在 PTrade 里盘中跑模型”，而是：

1. 本地离线 ML 在收盘后生成第二天的 `ml_daily_signal.json`
2. PTrade 在 `before_trading_start` 读取该信号
3. PTrade 盘中只结合 Level2 做轻量硬规则过滤、降级和参数调整

PTrade 是封闭沙盒，因此当前主线明确**不在盘中运行 XGBoost/LightGBM 推理**。

## 快速导航

如果你是第一次接手这个仓库，不要先通读全文，先按你的目标分流：

- 我在 **Mac** 上接手开发
  - 先看 [docs/cross_machine_dev_guide.md](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/docs/cross_machine_dev_guide.md)
  - 日常执行直接看 [docs/mac_daily_weekly_runbook.md](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/docs/mac_daily_weekly_runbook.md)
  - 优先执行 `bash setup_venv_mac.sh`
  - 默认把仓库下的 `data/` 当作本地运行目录
  - 如果只是补数或轻量运行，可退回 `setup_vendor_env_mac.sh`
- 我在 **Windows** 上接手开发
  - 先看 [docs/cross_machine_dev_guide.md](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/docs/cross_machine_dev_guide.md)
  - 使用本机 `.venv`
  - 默认把仓库下的 `data/` 当作本地运行目录
- 我的目标是 **机器学习算法开发**
  - 不要只装 `requirements.txt`
  - 必须使用完整开发环境，也就是 `requirements-dev.txt`
  - 只有导入检查和 `unittest` 通过，才算真正完成接手
- 我的目标只是 **补数 / 看代码 / 跑轻量脚本**
  - `requirements.txt` 即可
  - 这不等于已经具备完整算法开发能力

接手开发的最低验收标准：

```bash
python -c "import pandas, akshare, numpy, sklearn, matplotlib, xgboost, pandas_ta"
python -m unittest discover -s tests
```

如果上面两步还没通过，说明当前机器还不是完整算法开发环境。

## 运行与归档架构

当前推荐架构如下：

- `data/`
  - 本地运行目录
  - 每日补数、foundation、feature、signal 都写到这里
  - 这是日常生产真源
- `OneDrive`
  - 只做备份 / 跨机同步
  - 不再作为每日运行硬依赖
  - 如需归档同步，使用环境变量 `PTRADE_ARCHIVE_DATA_DIR` 配合 `python sync_runtime_data_to_archive.py`

如果你当前的 `data/` 还是 OneDrive 软链接，先迁回本地：

```bash
bash migrate_data_dir_to_local.sh
```

当前依赖等级：

- `300661_SZ_1m_ptrade.csv`
  - 硬依赖
  - 缺失或过期时，禁止导出下一交易日信号
- `399006.csv`、`512480.csv`
  - 软依赖
  - 缺失或过期时允许继续导出，但会强制降级到 `SAFE`

## 每日 / 每周执行清单

这是当前 `300661` 项目的固定操作节奏。核心原则只有 4 条：

1. `1m` 原始数据必须**每天盘后补**
2. 第二天要用的信号和 PTrade 策略必须**每天盘后导出**
3. 模型默认**不每天重训**
4. 只有周末验证通过，才正式接受新的模型版本

### 每日盘后：生产必跑

适用场景：

- 普通交易日收盘后
- 目标是生成第二天要用的 `ml_daily_signal.json`
- 目标是生成第二天要复制进 PTrade 的 dated 策略文件

命令：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python daily_backfill_data_mac.py
python build_minute_foundation.py
python build_feature_engine.py
python export_ml_daily_signal.py
```

这 4 步的含义：

- `daily_backfill_data_mac.py`
  - 每天补齐原始数据
  - 尤其是 `300661_SZ_1m_ptrade.csv`，不要隔几天再补
- `build_minute_foundation.py`
  - 基于最新分钟数据重建 canonical / summary
- `build_feature_engine.py`
  - 基于最新 `t` 日数据生成特征
- `export_ml_daily_signal.py`
  - 使用**当前生产模型**
  - 导出 `t+1` 交易日信号
  - 同时导出 PTrade 策略脚本

每日跑完后，真正给 PTrade 用的文件是：

- `generated/ptrade/ptrade_300661_latest.py`
- `generated/ptrade/ptrade_300661_YYYYMMDD.py`

其中：

- `YYYYMMDD` 使用 `signal_for_date`
- 这个日期表示“下一次实际要运行该策略的交易日”
- 当前实现会优先按 A 股交易日历顺延，节假日与周末都会顺延；如果交易日历接口失败，才退回“只跳周末”的后备逻辑

### 每周末：训练 / 换模评估

适用场景：

- 周末停盘后
- 你本周改了标签 / 特征 / controller
- 你准备评估是否接受新的模型版本

命令：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python build_label_engine.py
python train_baseline_models.py
python analyze_walk_forward.py
python analyze_walk_forward_failures.py
python export_ml_daily_signal.py
```

这 5 步的含义：

- `build_label_engine.py`
  - 用最新真实路径补齐监督标签
- `train_baseline_models.py`
  - 训练候选新模型
- `analyze_walk_forward.py`
  - 看滚动稳定性
- `analyze_walk_forward_failures.py`
  - 看失败窗口和 `NORMAL` 失效模式
- `export_ml_daily_signal.py`
  - 如果你接受本次模型，就基于新模型导出下一个交易日信号和 PTrade 策略

### 什么时候只跑旧模型推理

下面这些情况，都只跑“每日盘后 4 步”，不要重训：

- 普通工作日盘后
- 这周没有改标签 / 特征 / controller
- 你没有时间做 walk-forward 复盘
- 你不准备正式接受新模型

一句话：

- **工作日默认只推理**
- **周末默认才讨论换模**

### 什么时候可以接受新模型

当前阶段，至少满足下面条件，才建议把新模型当作生产模型：

1. `walk_forward_mode_summary.csv` 里，`NORMAL` 没有继续明显差于 `SAFE`
2. `walk_forward_failure_windows.csv` / `walk_forward_failure_cohort_summary.csv` 没出现新的大幅恶化窗口
3. 本次改动属于明确版本升级：
   - 标签升级
   - 特征升级
   - controller 升级
4. 你愿意接受这次训练结果覆盖当前 baseline 目录

### PTrade 模板与生成文件的关系

- `data/ptrade_300661.py`
  - 视为**模板源文件**
  - 它可能持续优化
  - 它也可能来自外部 PTrade 环境的手工拷贝
- `generated/ptrade/ptrade_300661_YYYYMMDD.py`
  - 视为**每日实际可复制进 PTrade 的产物**

如果你更新了模板 `data/ptrade_300661.py`，但不需要重新推理，只想把当前已有信号重新渲染成新策略文件，执行：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python export_ptrade_strategy.py
```

一个面向 `300661` 次日高低点幅度回归任务的本地数据底座项目。当前方案以 `AkShare` 为主，优先使用东方财富相关接口；当部分接口不稳定时，允许切换到 `AkShare` 的新浪后备接口，并在日志与 README 中明确记录限制。

当前目标已经不再是单纯的高低点幅度回归，而是为 `300661` 的离线多头模型准备训练数据：

- `target_upside_t1 = high[t+1] / close[t] - 1`
- `target_downside_t1 = low[t+1] / close[t] - 1`
- `target_hostile_selloff_risk_t1`

项目当前同时覆盖：

- 主标的 `300661`
- 宽基指数 `399006`（创业板指）
- 行业代理 `512480`（半导体 ETF）

并同时保留：

- 日线数据
- 分钟级数据

当前已经真实完成的生产底座阶段有三步：

- `Phase 1`：`300661` 长历史 `1m` 规范化与审计
- `Phase 2`：基于 canonical `1m` 的首批生产标签引擎
- `Phase 3`：基于 canonical `1m` 的首批生产特征引擎（已并入环境日线）

当前主线优先级是：

- 先做 baseline 质量复盘
- 先解释 `SAFE/NORMAL` 为什么分离度不足
- 先解释 `downside_regression` 为什么失真
- 然后再决定是否修复目标、补 overnight 因子、还是引入 Level2 收盘摘要特征

## 接手入口

如果你是在**新机器**、**新会话**或**新的大模型代理**里接手这个仓库，先看上面的“快速导航”，再继续阅读下面两个部分：

1. 本文档的“开发环境模式”
2. [docs/cross_machine_dev_guide.md](/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml/docs/cross_machine_dev_guide.md)

## 当前结论

当前项目的**主分钟数据源**已经不是短历史的外部 `5m` 文件，而是：

- [300661_SZ_1m_ptrade.csv](</E:/AI炒股/机器学习/data/300661_SZ_1m_ptrade.csv>)

这份文件覆盖：

- `2017-06-06 09:31:00` 到 `2026-04-14 15:00:00`
- 共 `516240` 行
- 字段：`datetime, code, open, high, low, close, volume, amount, price`

对后续机器学习来说，这意味着：

- `300661` 的分钟增强建模已经有正式可用的长历史主数据
- 旧的 `300661_5m.csv` 不再是主分钟数据源，只能视为外部接口补数或派生数据
- 当前机器学习主线已经升级为“`300661` 长历史 `1m` + 主标的派生日级基线 + `399006/512480` 真实环境日线”

## 规范文档

当前机器学习与策略联动的正式规范在 `docs/` 下：

- [minute_feature_schema.md](</E:/AI炒股/机器学习/docs/minute_feature_schema.md>)
- [label_definition.md](</E:/AI炒股/机器学习/docs/label_definition.md>)
- [model_spec.md](</E:/AI炒股/机器学习/docs/model_spec.md>)
- [ptrade_signal_contract.md](</E:/AI炒股/机器学习/docs/ptrade_signal_contract.md>)
- [ml_implementation_plan.md](</E:/AI炒股/机器学习/docs/ml_implementation_plan.md>)
- [ml_progress.md](</E:/AI炒股/机器学习/docs/ml_progress.md>)

如果你当前接手的是“模型质量诊断”而不是“补数”，还应优先关注：

- `analysis/baseline_test_predictions.csv`
- `analysis/head_bucket_summary.csv`
- `analysis/safe_mode_replay_summary.csv`
- `analysis/downside_error_cases.csv`
- `analysis/head_feature_importance.csv`
- `analysis/walk_forward_test_predictions.csv`
- `analysis/walk_forward_head_metrics.csv`
- `analysis/walk_forward_window_mode_summary.csv`
- `analysis/walk_forward_mode_summary.csv`
- `analysis/walk_forward_failure_windows.csv`
- `analysis/walk_forward_failure_feature_delta.csv`
- `analysis/walk_forward_failure_cases.csv`

## 目录结构

```text
E:\AI炒股\机器学习
|-- data/
|   |-- 300661.csv
|   |-- 300661_SZ_1m_ptrade.csv
|   |-- 300661_5m.csv
|   |-- 399006.csv
|   |-- 399006_5m.csv
|   |-- 512480.csv
|   `-- 512480_5m.csv
|-- build_dataset.py
|-- build_feature_engine.py
|-- build_label_engine.py
|-- build_regression_dataset.py
|-- data_updater.py
|-- build_minute_foundation.py
|-- download_required_market_data.py
|-- train_baseline_models.py
|-- requirements.txt
`-- README.md
```

## GitHub 协作

推荐把这个项目作为“代码仓库”同步到 GitHub，而不是把大体量训练数据和模型文件一起推上去。

当前仓库协作策略：

- 上传：
  - Python 源码
  - `docs/`
  - `tests/`
  - `README.md`
  - `requirements.txt`
  - 脚本入口文件
- 不上传：
  - `.venv/`
  - `vendor/`、`env/`、`lib/` 这类本机依赖目录
  - `data/` 下的大体量原始数据、训练产物、信号文件
  - `analysis/` 下的本地质量复盘产物
  - `models/` 下模型权重与临时文件
  - `plots/` 下图片产物

这样做的目的：

- 让另一台电脑能继续开发和重跑流程
- 避免把几十 MB 到上百 MB 的原始分钟数据直接塞进 Git 历史
- 避免把临时训练产物和本地环境噪音带进协作仓库

## 开发环境模式

为了让另一台机器能够“读 README 就接手开发”，这里明确区分两种模式：

- `requirements.txt`
  - 最小运行依赖
  - 适用于数据补数、轻量 CSV 处理、只跑基础脚本
- `requirements-dev.txt`
  - 完整算法开发依赖
  - 适用于特征工程、标签构建、baseline 训练、单元测试

如果你的目标是**接手机器学习开发**，不要只安装 `requirements.txt`，而是要使用完整开发环境。

### Mac 电脑如何继续开发

1. 安装基础环境

- 安装 `git`
- 安装 `Python 3.11+`
- 如果后续要训练 `xgboost` baseline，Mac 上还需要安装 OpenMP 运行库：

```bash
brew install libomp
```

2. 克隆仓库

```bash
git clone <你的 GitHub 仓库地址>
cd 机器学习
```

3. 安装完整开发环境

优先使用虚拟环境：

```bash
bash setup_venv_mac.sh
source .venv/bin/activate
python -V
python -c "import pandas, akshare, numpy, sklearn, matplotlib, xgboost, pandas_ta"
```

这台 Mac 当前已验证的解释器是 `python3.12`。`setup_venv_mac.sh` 会自动选择 `python3.12` 或 `python3.11` 创建 `.venv`。如果仓库里已有完整的 `vendor/` 依赖，它会自动接入虚拟环境；否则请在激活 `.venv` 后执行：

如果这里在 `xgboost` 导入时报 `libomp.dylib` 缺失，不是 Python 包没装全，而是系统缺少 OpenMP 运行库。先执行：

```bash
brew install libomp
```

```bash
pip install -r requirements-dev.txt
```

如果你明确要手动创建，也请使用实际存在的解释器，例如：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

如果当前 Mac 因权限或隐藏目录策略不方便创建 `.venv/`，可以改用本地 `vendor/` 方案：

```bash
bash setup_vendor_env_mac.sh
source activate_vendor_env.sh
python3.12 -c "import pandas, akshare, numpy, sklearn, matplotlib, xgboost, pandas_ta; print('vendor ok')"
```

默认情况下，`setup_vendor_env_mac.sh` 会安装 `requirements-dev.txt`，也就是完整算法开发依赖。`activate_vendor_env.sh` 会把仓库根目录下的 `vendor/` 加到 `PYTHONPATH`。请确保后续运行脚本时使用与安装 `vendor/` 相同的解释器；当前这台 Mac 已验证的是 `python3.12`，而不是系统自带的 `python3`（通常还是 3.9）。

同样地，如果 `xgboost` 报 `libomp.dylib` 缺失，也要先执行：

```bash
brew install libomp
```

4. 可选配置 OneDrive 归档目录

默认不再把 `data/` 软链接到 OneDrive。
如果你需要把本地运行数据归档到 OneDrive，请配置：

```bash
export PTRADE_ARCHIVE_DATA_DIR="$HOME/Library/CloudStorage/OneDrive-你的目录/Development/data_bundle/ptrade-t0-ml"
python sync_runtime_data_to_archive.py
```

5. 补回本地数据

由于 `data/` 和 `models/` 默认不进 Git，Mac 端需要你自己补回这些文件到本地运行目录 `data/`，至少包括：

- `data/300661_SZ_1m_ptrade.csv`
- `data/399006.csv`
- `data/512480.csv`

如果后面要启用隔夜因子，还要补：

- `data/soxx_daily.csv`
- `data/nasdaq_daily.csv`

6. 按顺序重建产物

```bash
python build_minute_foundation.py
python build_label_engine.py
python build_feature_engine.py
python train_baseline_models.py
python export_ml_daily_signal.py
```

7. 日常协作方式

- Windows 改完后：`git add/commit/push`
- Mac 拉最新：`git pull`
- Mac 改完后：`git add/commit/push`
- Windows 再继续：`git pull`

建议始终先同步文档，再同步代码。尤其是：

- `docs/label_definition.md`
- `docs/model_spec.md`
- `docs/ptrade_signal_contract.md`
- `docs/ml_progress.md`

### 接手开发后的验收命令

无论是 Mac 还是 Windows，只要是“接手算法开发”，都建议先跑这组检查：

```bash
python -c "import pandas, akshare, numpy, sklearn, matplotlib, xgboost, pandas_ta"
python -m unittest discover -s tests
```

如果上面两步不能通过，说明当前机器还没有进入“完整开发环境”，不能直接开始算法开发。

## 主要脚本

`daily_backfill_data.py` (日常生产必备)

- 每日收盘后一键全自动**增量更新**脚本，专用于追加拼接最新的日线（`512480`, `399006`）及 1 分钟线（`300661_SZ_1m_ptrade`）数据。
- 自动识别原有大型 CSV 文件的末尾时间点，强制基于 `date` 或 `datetime` 去重追加，安全可靠，不怕重复执行。
- 日线接口使用 Powershell 以绕过 Python SSL 错误被限流，分钟接口使用 Akshare 东方财富源以保证含有 `amount` 列且修复了 `open=0.0` 问题。

收盘后您只需要在终端里执行以下命令就可以一键补齐所有数据
cd E:\AI炒股\机器学习
python daily_backfill_data.py


`daily_backfill_data_mac.py` (Mac 独立补数入口)

- 为 Mac 单独准备的增量补数脚本，不依赖 Windows PowerShell。
- `512480`、`399006` 日线通过 `AkShare` 直接抓取并按 `date` 去重更新。
- `300661_SZ_1m_ptrade.csv` 仍使用 `AkShare` 东方财富分钟接口，并保留 `open=0.0` 修复、`datetime` 去重和 `price` 字段补齐逻辑。

在 Mac 上可直接执行：

```bash
cd ~/Developer/ptrade-t0-ml
python3.12 daily_backfill_data_mac.py
```

当前脚本还会在补数完成后做一次“新鲜度校验”：

- 如果今天已经收盘，但 `300661` 的 `1m`、`399006`、`512480` 仍然没有补到最新交易日
- 脚本会直接以非零退出，不再把旧数据误当作成功补数

如果你使用的是 `vendor/` 模式，运行其他依赖脚本前先执行：

```bash
cd ~/Developer/ptrade-t0-ml
source activate_vendor_env.sh
python3.12 build_minute_foundation.py
```


`data_updater.py`

- 单只或多只 A 股日线全量下载与增量更新
- 默认使用 `stock_zh_a_hist` 前复权日线
- 标准化输出字段：`date, open, close, high, low, volume, amount`

`build_dataset.py`

- 构建 `300661 + 399006 + 半导体行业板块` 的日线宽表
- 输出面向日频特征工程的基础宽表

`build_regression_dataset.py`

- 面向回归任务构建统一训练数据集
- 同时处理日线与分钟线
- 生成分钟聚合特征与目标列
- 包含分钟频率回退、板块/ETF 代理选择、缺失值统计等逻辑

`build_minute_foundation.py`

- 规范化并审计 `300661` 长历史 `1m` 主分钟数据
- 输出正式可复用的分钟底座、日级摘要和审计 JSON
- 是当前机器学习 Phase 1 的正式入口

`build_label_engine.py`

- 基于 canonical `1m` 与日级摘要生成首批生产标签
- 当前已落地：
  - `target_upside_t1`
  - `target_downside_t1`
  - `target_hostile_selloff_risk_t1`
  - `target_positive_grid_day_t1`
  - `target_tradable_score_t1`
  - `target_vwap_reversion_t1`
  - `target_trend_break_risk_t1`
  - 悲观撮合版 `target_grid_pnl_t1`
- 是当前机器学习 Phase 2 的正式入口

`build_feature_engine.py`

- 基于 canonical `1m` 与日级摘要生成首批生产特征表
- 当前已落地：
  - 日内结构特征
  - VWAP / reversion 特征
  - 波动与路径风险特征
  - 成交量与微观摩擦特征
  - 主标的日级派生特征
  - 3/5/10/20 日滚动统计
  - `399006 / 512480` 环境日线特征
  - 可选 `overnight_factors.csv` 隔夜因子合并入口
- 是当前机器学习 Phase 3 的正式入口

`train_baseline_models.py`

- 将首批特征表与标签表按 `date` 合并成训练集
- 训练当前“主标的分钟特征 + 环境日线”的 8 个 baseline 头：
  - `upside_regression`
  - `downside_regression`
  - `grid_pnl_regression`
  - `positive_grid_day_classifier`
  - `tradable_classifier`
  - `trend_break_risk_classifier`
  - `hostile_selloff_risk_classifier`
  - `vwap_reversion_classifier`
- 输出训练集、模型文件和元数据评估
- 模型目录名仍保留为 `baseline_stock_only/`，只是为了兼容旧路径，当前内容已经不再是纯 stock-only slice
- 现已内置时间序列验证切片的阈值校准，并在 metadata 中输出 `recommended_threshold`

`export_ml_daily_signal.py`

- 基于最新 feature row、baseline models 与校准阈值导出每日信号
- 输出：
  - `data/ml_daily_signal.json`
  - `data/ml_daily_signal.csv`
  - `generated/ptrade/ptrade_300661_latest.py`
  - `generated/ptrade/ptrade_300661_YYYYMMDD.py`
- 当前会同步给出：
  - `pred_upside_t1`
  - `pred_downside_t1`
  - `pred_grid_pnl_t1`
  - `pred_positive_grid_day_t1`
  - `pred_tradable_score_t1`
  - `pred_trend_break_risk_t1`
  - `pred_hostile_selloff_risk_t1`
  - `pred_vwap_reversion_score_t1`
  - `recommended_mode`
  - `position_scale`
  - `grid_width_scale`
  - `recommended_grid_width_t1`

`ptrade_export_300661_1m.py` / `ptrade_export_300661_1m_trade.py`

- 从 PTrade 导出 `300661` 长历史 `1m` 数据
- 是当前最重要的主分钟数据获取路径
- 产出文件应优先落为 `data/300661_SZ_1m_ptrade.csv`

`download_required_market_data.py`

- 按当前固定口径一次性准备 6 份基础数据文件
- 固定清单：
  - `data/300661.csv`
  - `data/300661_5m.csv`
  - `data/399006.csv`
  - `data/399006_5m.csv`
  - `data/512480.csv`
  - `data/512480_5m.csv`

## 安装依赖

```powershell
pip install -r requirements.txt
```

## 当前固定数据口径

### 日线

- `300661.csv`：`2020-01-01` 到今天，前复权
- `399006.csv`：`2020-01-01` 到今天
- `512480.csv`：`2020-01-01` 到今天，作为半导体行业代理

标准字段统一为：

```text
date, open, close, high, low, volume, amount
```

### 分钟线

- `300661` 的主分钟口径：优先使用长历史 `1m`（PTrade 导出）
- `399006` / `512480` 的外部分钟口径：当前仍以外部 `5m` 为主
- 如需训练统一分钟增强样本，可将 `300661` 的 `1m` 自行聚合为 `5m`
- 标准字段统一为：

```text
datetime, open, close, high, low, volume, amount
```

## 当前数据文件现状

以下状态基于当前工作区里**已经重新核对过**的真实文件：

| 文件 | 当前状态 | 说明 |
|---|---|---|
| `data/300661_SZ_1m_ptrade.csv` | 已验证可用 | 主分钟源；`516240` 行，`2017-06-06 09:31:00` 到 `2026-04-14 15:00:00`，含 `amount` |
| `data/foundation/300661_SZ_1m_canonical.csv` | 已生成 | Phase 1 规范化分钟底座 |
| `data/foundation/300661_SZ_1m_daily_summary.csv` | 已生成 | Phase 1 日级摘要 |
| `data/foundation/300661_SZ_1m_audit.json` | 已生成 | Phase 1 审计报告 |
| `data/foundation/300661_SZ_label_targets.csv` | 已生成 | Phase 2 首批标签表，覆盖 `2017-06-06` 到 `2026-04-13`，共 `2150` 行 |
| `data/foundation/300661_SZ_label_audit.json` | 已生成 | Phase 2 标签审计报告 |
| `data/foundation/300661_SZ_feature_table.csv` | 已生成 | Phase 3 特征表，覆盖 `2017-06-06` 到 `2026-04-14`，共 `2151` 行、`204` 列，已并入 `399006/512480` 环境日线 |
| `data/foundation/300661_SZ_feature_audit.json` | 已生成 | Phase 3 特征审计报告 |
| `data/foundation/300661_SZ_training_dataset.csv` | 已生成 | Baseline 训练集，特征表与标签表按 `date` 合并后得到，共 `2150` 行 |
| `models/baseline_stock_only/` | 已生成 | 当前 baseline 模型目录；路径名沿用旧名称，但内容已升级为“主标的分钟特征 + 环境日线”版本 |
| `data/ml_daily_signal.json` / `data/ml_daily_signal.csv` | 已生成 | 当前实验版 Phase 5 日信号产物，已接上 baseline 多头与阈值校准 |
| `data/300661.csv` | 当前为空壳文件 | 本工作区里长度仅 `2` 字节，**不能作为当前生产日线输入** |
| `data/399006.csv` | 已恢复可用 | 覆盖 `2020-01-02` 到 `2026-04-14`，字段齐全；`amount` 列为空，属于后备源真实缺失 |
| `data/512480.csv` | 已恢复可用 | 覆盖 `2020-01-02` 到 `2026-04-14`，字段齐全；`amount` 列为空，属于后备源真实缺失 |
| `data/300661_5m.csv` / `data/399006_5m.csv` / `data/512480_5m.csv` | 可选增强 | 仅作为外部分钟补充或兼容数据，不是当前主线生产依赖 |

## 推荐使用方式

### 1. 每日盘后：一键自动补齐核心数据 (日常第一入口)

在盘后直接执行此脚本，即可完成 `300661` 长线 1m 数据和两份核心日线环境数据的无缝增量追加，推荐把此命令加入到系统的定时任务中：

```powershell
python daily_backfill_data.py
```
**功能效果**：
- 自动对 `data/300661_SZ_1m_ptrade.csv` (1分钟大底座)，`data/512480.csv` 以及 `data/399006.csv` 的文件末尾进行时间识别、增量爬取、去重与合并。每天运行仅需几秒钟即可备齐当日所需物料。

### 2. 完整更新 300661 长线数据与拼接 (旧版历史入口)

由于当前的机器与网络环境对东方财富的分钟和部分日线接口产生极强的请求阻隔（SSL 报错），我们过去编写了专属的断点拉取与数据拼接脚本：

```powershell
python update_300661.py
```
**功能效果**：
- 它将利用防封堵请求与新浪降级策略，强制获取并对齐 300661 的日线与分时数据。
- 采用**增量历史拼接**机制：如果历史文件已存在，不覆盖原有数据，自动在末尾去重追加。这是囤积长线高质量 1分钟/5分钟 K 线的唯一关键手段。

### 2.1 当前主分钟数据优先级

如果 `data/300661_SZ_1m_ptrade.csv` 已存在，则后续机器学习开发应默认：

1. 优先使用 `300661_SZ_1m_ptrade.csv` 作为 `300661` 主分钟源
2. 从这份 `1m` 数据中二次聚合出 `5m/15m` 或日级分钟特征
3. 不再把 `300661_5m.csv` 当作主分钟源

换句话说：

- `300661_SZ_1m_ptrade.csv` 是正式建模主源
- `300661_5m.csv` 是辅助/兼容/外部补数文件

### 3. 更新单只股票日线底座（旧命令兼容）

```powershell
python data_updater.py 300661
```

### 4. 一次性准备当前 6 份基础数据（旧口径）

```powershell
python download_required_market_data.py
```

### 5. 构建回归训练宽表

```powershell
python build_regression_dataset.py
```

### 6. 构建 `300661` 主分钟底座

```powershell
python build_minute_foundation.py
```

默认输出：

```text
data/foundation/300661_SZ_1m_canonical.csv
data/foundation/300661_SZ_1m_daily_summary.csv
data/foundation/300661_SZ_1m_audit.json
```

当前这一步已经在本地真实执行过，审计结论是：

- `300661_SZ_1m_ptrade.csv` 已被识别为标准 `1m`
- 覆盖 `2017-06-06 09:31:00` 到 `2026-04-14 15:00:00`
- 共 `2151` 个完整交易日
- 每日稳定 `240` 根 bar
- 未发现重复时间戳、负成交量、负成交额、无效高低收等阻塞性问题

### 7. 构建首批生产标签引擎

```powershell
python build_label_engine.py
```

默认输出：

```text
data/foundation/300661_SZ_label_targets.csv
data/foundation/300661_SZ_label_audit.json
```

当前这一步也已经在本地真实执行过，结论是：

- 标签覆盖：`2017-06-06` 到 `2026-04-13`
- 共 `2150` 条监督样本
- 当前已实现标签：
  - `target_upside_t1`
  - `target_downside_t1`
  - `target_positive_grid_day_t1`
  - `target_tradable_score_t1`
  - `target_vwap_reversion_t1`
  - `target_trend_break_risk_t1`
  - `target_grid_pnl_t1`
- `target_positive_grid_day_t1` 正样本占比约 `41.35%`
- 在悲观撮合假设下，`target_tradable_score_t1` 正样本占比约 `31.21%`
- `target_vwap_reversion_t1` 已收紧为“高质量回归日”口径，正样本占比约 `33.63%`
- `target_trend_break_risk_t1` 当前已改为“两段式趋势风险”口径，正样本占比约 `9.81%`

### 8. 构建首批生产特征引擎

```powershell
python build_feature_engine.py
```

默认输出：

```text
data/foundation/300661_SZ_feature_table.csv
data/foundation/300661_SZ_feature_audit.json
```

当前这一步也已经在本地真实执行过，结论是：

- 特征覆盖：`2017-06-06` 到 `2026-04-14`
- 共 `2151` 行、`204` 列
- 与标签按 `date` 可对齐 `2150` 行
- 当前已经并入：
  - `399006` 环境日线特征
  - `512480` 环境日线特征
- `merged_environment_prefixes = ["idx", "sec"]`
- 当前已新增并生效的趋势增强特征包括：
  - `stk_m_trend_efficiency_ratio`
  - `stk_m_morning_trend_efficiency_ratio`
  - `stk_m_directional_consistency`
  - `stk_m_open15_volume_ratio`
  - `stk_m_open15_volume_shock`
  - `stk_m_open15_breakout_strength`
- 当前已预留隔夜因子入口：
  - `data/overnight_factors.csv`
  - 生成入口：`python build_overnight_factors.py`
  - 原始源文件预期为：
    - `data/soxx_daily.csv`
    - `data/nasdaq_daily.csv`
  - 但本地当前尚未提供上述源文件，因此 `merged_overnight_factor_columns = []`

### 9. 训练第二版 baseline models（含环境日线，已扩为 7 头并带阈值校准）

```powershell
python train_baseline_models.py
```

默认输出：

```text
data/foundation/300661_SZ_training_dataset.csv
models/baseline_stock_only/upside_regression.json
models/baseline_stock_only/downside_regression.json
models/baseline_stock_only/grid_pnl_regression.json
models/baseline_stock_only/positive_grid_day_classifier.json
models/baseline_stock_only/tradable_classifier.json
models/baseline_stock_only/trend_break_risk_classifier.json
models/baseline_stock_only/vwap_reversion_classifier.json
models/baseline_stock_only/baseline_stock_only_metadata.json
```

当前这一步也已经在本地真实执行过，结论是：

- 训练样本：`2150`
- 时间切分：
  - train：`1720`
  - test：`430`
  - test 区间：`2024-07-03` 到 `2026-04-13`
- 训练特征列数：`203`
- 分类头阈值额外使用 train 内部的时间序列 validation slice：
  - classifier_train：`1462`
  - classifier_validation：`258`
- 这是 **去除未来信息泄漏后的可信基线**
- 这是已经吃到环境日线的第二版 baseline
- 当前最新一版的 baseline 读数为：
  - `upside_regression` spearman：`0.0441`
  - `downside_regression` spearman：`0.1169`
  - `grid_pnl_regression` spearman：`-0.0436`
  - `positive_grid_day_classifier` AP / ROC AUC：`0.3734 / 0.4775`
  - `tradable_classifier` AP / ROC AUC：`0.3564 / 0.5616`
  - `trend_break_risk_classifier` AP / ROC AUC：`0.1391 / 0.4951`
  - `vwap_reversion_classifier` AP / ROC AUC：`0.3077 / 0.6395`
- 当前推荐阈值与测试集表现为：
  - `positive_grid_day_classifier`：
    - 推荐 `0.3`：precision `0.3456`，recall `0.5839`
  - `tradable_classifier`：
    - 默认 `0.5`：precision `0.4118`，recall `0.1148`
    - 推荐 `0.35`：precision `0.3478`，recall `0.2623`
  - `trend_break_risk_classifier`：
    - 默认 `0.5`：precision `0.0000`，recall `0.0000`
    - 推荐 `0.30`：precision `0.2000`，recall `0.0526`
  - `vwap_reversion_classifier`：
    - 默认 `0.5`：precision `0.2917`，recall `0.0886`
    - 推荐 `0.3`：precision `0.3028`，recall `0.5443`
- 这意味着：
  - `positive_grid_day_classifier` 已经比直接回归 `grid_pnl` 更适合承担生产 gating 角色
  - `tradable` 和 `vwap_reversion` 仍然能明显受益于阈值校准
  - `trend_break_risk` 已经不再是“极端稀疏标签”，但当前排序能力仍弱，仍只适合作为软约束 / 研究头
- `grid_pnl_regression` 仍然偏弱，当前应保留为研究 / 诊断头，不适合直接拿来驱动实盘参数
- 当前整套 baseline **暂时不能直接接入实盘**

默认目标输出：

```text
data/processed/300661_regression_dataset.csv
```

### 10. 导出实验版 ML 日信号

```powershell
python export_ml_daily_signal.py
```

默认输出：

```text
data/ml_daily_signal.json
data/ml_daily_signal.csv
generated/ptrade/ptrade_300661_latest.py
generated/ptrade/ptrade_300661_YYYYMMDD.py
```

说明：

- `YYYYMMDD` 使用 `signal_for_date`，也就是下一次实际要拷进 PTrade 的交易日
- `signal_for_date` 会优先按 A 股交易日历顺延，自动跳过周末与节假日；如果交易日历接口失败，才退回只跳周末的后备逻辑
- `data/ptrade_300661.py` 作为模板源文件保留
- 每次执行 `python export_ml_daily_signal.py` 时，会自动把最新 `ML_SIGNAL_PAYLOAD` 渲染进一份新的 PTrade 策略脚本，供你直接复制到 PTrade 平台

当前这一步也已经在本地真实执行过，最新信号样例基于 `2026-04-14` 特征日生成：

- `signal_for_date = 2026-04-15`
- `pred_upside_t1 = 0.0224`
- `pred_downside_t1 = -0.0393`
- `pred_positive_grid_day_t1 = 0.1977`
- `pred_tradable_score_t1 = 0.0835`
- `pred_trend_break_risk_t1 = 0.0618`
- `pred_vwap_reversion_score_t1 = 0.3350`
- `pred_grid_pnl_t1 = -0.0126`
- `recommended_mode = SAFE`
- `position_scale = 0.55`
- `grid_width_scale = 1.10`
- `signal_rationale = positive_grid_or_tradable_below_threshold`
- 推荐阈值当前为：
  - `pred_positive_grid_day_t1 = 0.30`
  - `pred_tradable_score_t1 = 0.35`
  - `pred_trend_break_risk_t1 = 0.30`
  - `pred_vwap_reversion_score_t1 = 0.30`

当前输出仍属于 **experimental baseline signal**，主要价值是：

- 固化 ML -> PTrade 的文件契约
- 验证多头模型与阈值校准能稳定落盘
- 让策略侧开始接 reader，而不是继续靠对话记忆协作
- 当前 live gating 应优先参考：
  - `pred_positive_grid_day_t1`
  - `pred_tradable_score_t1`
  - `pred_vwap_reversion_score_t1`
  - `pred_trend_break_risk_t1` 仅作软约束

## 已知限制

这部分很重要，后续做特征和训练时要直接参考。

### 1. 东方财富接口当前不稳定

在本机当前环境下，`399006` 和 `512480` 对应的东方财富接口存在大量：

- `RemoteDisconnected`
- `server closed connection`

因此这两组数据在本轮补数时部分切换到了 `AkShare` 的新浪后备接口。

### 2. 新浪后备接口缺少 `amount`

当前已落盘的以下文件：

- `data/399006.csv`
- `data/399006_5m.csv`
- `data/512480.csv`
- `data/512480_5m.csv`

虽然保留了 `amount` 列，但该列当前为缺失值，因为后备源只稳定提供：

- `open`
- `high`
- `low`
- `close`
- `volume`

不会提供可直接对齐的历史 `amount`。

### 3. 主标的与环境数据当前要分开看

这条旧结论现在只部分成立。

当前真实情况是：

- `300661_SZ_1m_ptrade.csv` 含有完整 `amount`
- `399006.csv` 和 `512480.csv` 已恢复为真实可用日线环境文件
- `399006_5m.csv` 和 `512480_5m.csv` 的 `amount` 仍为空
- `overnight_factors.csv` 的特征入口已经接好，但本地当前还没有实际文件
- 如果要启用隔夜因子，至少需要补：
  - `data/soxx_daily.csv`
  - `data/nasdaq_daily.csv`
- 在隔夜源文件补齐之前，下一步推荐先运行：
  - `python analyze_walk_forward.py`
  - `python analyze_walk_forward_failures.py`
- `300661_5m.csv` 如果来自外部免费接口，`amount` 可能为空
- `300661.csv` 在**当前工作区**里仍是空壳文件，不能继续被误认为可直接使用的日线真值源

因此现在的正确口径是：

- **主标的 `300661` 可以做完整 VWAP / 资金类分钟特征**
- **环境日线 `399006 / 512480` 已经可以并入正式特征表**
- **外部环境分钟特征目前更多依赖价格与成交量，不依赖 `amount`**
- **当前 Phase 1/2 生产管道优先使用 `300661` 的 canonical `1m` 与派生日级摘要**
- **当前 Phase 3/4 已经能消费 `399006 / 512480` 恢复后的环境日线**

### 4. 免费开源接口的“外部分钟历史长度极限”！

这也是我们需要“本地拼接架构”的根本原因。新浪对历史 K 线有总量限制硬顶（固定吐出最近约 1970 根）：
- **5分钟线**：最多只能往前追溯约 **2个月** (41 个交易日)
- **1分钟线**：最多只能往前追溯约 **8到9个交易日**

因此，想仅靠开源免费接口去获取几年级别的分钟历史并不现实；但这一限制**已经不再阻塞 `300661` 主标的建模**，因为我们已经拿到了本地长历史 `1m` 主数据。

现在这条限制主要影响的是：

- `399006` 外部分钟环境数据
- `512480` 外部分钟环境数据

所以当前推荐建模主线应改为：

- **主标的：`300661` 长历史 `1m`**
- **外部环境：先用日线，外部分钟特征为增强项而不是阻塞项**

## 建模建议

如果马上进入建模，建议优先这样处理：

- `300661` 的分钟特征以 `300661_SZ_1m_ptrade.csv` 为核心生成
- `300661` 的目标列优先基于分钟路径生成，更贴近策略
- 第一版监督学习直接消费：
  - `data/foundation/300661_SZ_1m_canonical.csv`
  - `data/foundation/300661_SZ_1m_daily_summary.csv`
  - `data/foundation/300661_SZ_label_targets.csv`
  - `data/foundation/300661_SZ_feature_table.csv`
- 大盘和行业分钟特征允许 `amount` 缺失，不要强行伪造
- 对 `399006/512480` 先更多依赖价格与成交量类分钟特征
- 第一版正式模型可采用：
  - `300661` 长历史 `1m` 分钟特征
  - `300661` 派生日级基线
  - `399006 / 512480` 日线环境特征
  - 外部分钟特征作为增强项
- 当前 baseline 的意义主要是：
  - 验证训练链路已经完整打通
  - 暴露当前特征与标签仍然偏弱
  - 为下一轮标签增强和环境特征回补提供对照组

## 当前执行原则

- 不在 PTrade 盘中运行复杂模型推理
- 盘中 Level2 只用于硬规则过滤和降级
- 收盘后的离线 ML 才负责输出第二天的基础 playbook
- 在 `SAFE/NORMAL` 分离度和 `downside` 目标问题没看清之前，不继续堆更复杂模型

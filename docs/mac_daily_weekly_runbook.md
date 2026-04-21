# Mac 每日 / 每周操作手册

本文档只回答一个问题：这台 Mac 上每天和每周到底该跑什么。

## 一、先记住 6 条固定原则

1. `300661` 的 `1m` 原始数据必须每天盘后补
2. 第二天要用的信号必须每天盘后生成
3. PTrade 使用的是每日生成的 dated 脚本，不是模板文件本身
4. 模型默认不每天重训
5. 周末先评估 candidate，确认通过后再 promote
6. 本地 `data/` 是运行真源，OneDrive 只做备份

## 二、关键文件

### 模板文件

- `data/ptrade_300661.py`

说明：

- 它是 PTrade 策略模板源文件
- 这个文件可能持续优化
- 它也可能由外部 PTrade 环境手工拷回仓库

### 每日生成文件

- `data/ml_daily_signal.json`
- `generated/ptrade/ptrade_300661_latest.py`
- `generated/ptrade/ptrade_300661_YYYYMMDD.py`

说明：

- `YYYYMMDD` 使用 `signal_for_date`
- 该日期表示“下一次真正要在 PTrade 里运行的交易日”
- 当前优先按 A 股交易日历顺延，自动跳过周末和节假日；如果交易日历接口失败，才退回只跳周末

### 模型目录

- `models/baseline_stock_only/`
  - 当前 production 模型目录
  - 每日推理只读取这里
- `models/baseline_candidate/`
  - 当前 candidate 模型目录
  - 周末训练和研究分析默认写这里

## 三、每日盘后必跑

适用场景：

- 普通交易日收盘后
- 目标是准备下一交易日的信号和 PTrade 文件

命令：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python daily_backfill_data_mac.py
python build_minute_foundation.py
python build_feature_engine.py
python export_ml_daily_signal.py
```

### 每一步的真实作用

`python daily_backfill_data_mac.py`

- 每天补原始数据
- `data/300661_SZ_1m_ptrade.csv` 是硬依赖
- 这一步不能攒着不跑，因为 `1m` 数据隔太久会越来越难补
- 当前脚本校验逻辑是：
  - `300661 1m` 没补到当前应有交易日，会直接失败
  - `399006` / `512480` 少一天会告警，但不会因为这两份环境数据直接失败

`python build_minute_foundation.py`

- 基于最新分钟数据重建标准化分钟底座

`python build_feature_engine.py`

- 基于最新收盘数据生成当天特征

`python export_ml_daily_signal.py`

- 使用当前 production 模型做日频推理
- 生成下一交易日的 `ml_daily_signal.json`
- 同时生成下一交易日的 PTrade dated 策略脚本
- 当前导出阶段校验逻辑是：
  - `300661 1m` 和 `feature_table` 是硬依赖，过期就直接失败
  - `399006` / `512480` 是软依赖，过期时允许继续，但导出会强制降级到 `SAFE`

### 每日跑完后怎么用

优先使用：

- `generated/ptrade/ptrade_300661_YYYYMMDD.py`

也可以使用：

- `generated/ptrade/ptrade_300661_latest.py`

推荐做法：

1. 先确认 dated 文件名日期就是下一交易日
2. 再把其内容复制到 PTrade 平台

## 四、如果当天只改了 PTrade 模板

适用场景：

- 你刚从外部 PTrade 环境拷回新的 `data/ptrade_300661.py`
- 你只改了策略模板
- 你不需要重新推理模型

命令：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python export_ptrade_strategy.py
```

说明：

- 这一步不会重新生成 `ml_daily_signal.json`
- 它只是把当前已有信号重新渲染进新的模板

## 五、每周末先训练与评估

适用场景：

- 周末停盘后
- 本周改了标签 / 特征 / controller
- 你准备判断 candidate 是否值得采用

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

### 每一步的作用

`python build_label_engine.py`

- 用最新真实路径补标签

`python train_baseline_models.py`

- 训练 candidate
- 输出到 `models/baseline_candidate/`

`python analyze_baseline_quality.py`

- 看 candidate 在测试切片上的质量

`python analyze_walk_forward.py`

- 看 candidate 在滚动窗口下的整体稳定性

`python analyze_walk_forward_failures.py`

- 看失败窗口和 `NORMAL` 失效模式

## 六、每周末确认通过后再 promote

只有 candidate 通过评估时，才执行下面两步：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python promote_baseline_candidate.py
python export_ml_daily_signal.py
```

说明：

- `python promote_baseline_candidate.py`
  - 把 candidate 提升为 production
- `python export_ml_daily_signal.py`
  - 用新 production 模型导出下一交易日信号和 PTrade 文件

## 七、什么时候不要重训

下面这些情况，默认只跑“每日盘后必跑”，不要跑 `train_baseline_models.py`：

- 普通工作日盘后
- 你只是想准备明天的策略
- 你没有做完整的 walk-forward 评估
- 你不准备正式接受新模型

一句话：

- 工作日默认只推理
- 周末默认才讨论换模

## 八、candidate / production 规则

固定规则：

1. `python train_baseline_models.py`
   - 只更新 candidate
2. `python analyze_baseline_quality.py`
   - 默认分析 candidate
3. `python analyze_walk_forward.py`
   - 默认分析 candidate
4. `python analyze_walk_forward_failures.py`
   - 默认分析 candidate
5. `python export_ml_daily_signal.py`
   - 只读取 production
6. `python promote_baseline_candidate.py`
   - 才会把 candidate 变成新的 production

## 九、什么时候可以接受新模型

当前阶段，建议至少满足下面条件才接受新模型：

1. `analysis/walk_forward_mode_summary.csv` 里，`NORMAL` 没继续明显差于 `SAFE`
2. `analysis/walk_forward_failure_windows.csv` / `analysis/walk_forward_failure_cohort_summary.csv` 没出现新的大幅恶化窗口
3. 本次改动属于明确版本升级：
   - 标签升级
   - 特征升级
   - controller 升级
4. 你愿意执行 `python promote_baseline_candidate.py`

## 十、最简操作版

### 每天收盘后

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python daily_backfill_data_mac.py
python build_minute_foundation.py
python build_feature_engine.py
python export_ml_daily_signal.py
```

### 每周末先评估

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python build_label_engine.py
python train_baseline_models.py
python analyze_baseline_quality.py
python analyze_walk_forward.py
python analyze_walk_forward_failures.py
```

### 每周末确认通过后再采用

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python promote_baseline_candidate.py
python export_ml_daily_signal.py
```

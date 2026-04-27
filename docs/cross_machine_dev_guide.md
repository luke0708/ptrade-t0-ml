# 双机协作开发指南：Windows + Mac

本文档说明如何在多台机器之间接手 `ptrade-t0-ml`。当前固定原则是：代码用 Git 同步，运行数据放本机本地 `data/`，OneDrive 只做备份 / 归档，不作为每日训练或推理的运行依赖。

## 一、当前协作架构

| 内容 | 当前做法 |
| --- | --- |
| Python 源码 | Git / GitHub |
| `docs/`、`tests/` | Git / GitHub |
| `README.md`、`Project Plan.md` | Git / GitHub |
| `data/` | 每台机器本地运行目录 |
| `models/` | 本地为准，必要时手工归档 |
| OneDrive | 只做备份 / 跨机复制 |

关键约束：

- `data/` 不应该依赖 OneDrive 软链接
- 每台机器都可以独立补数
- `300661_SZ_1m_ptrade.csv` 是每日推理硬依赖
- `399006.csv` / `512480.csv` 是软依赖，过期时允许导出但强制降级 `SAFE`
- 生产推理只读 `models/baseline_stock_only/`
- 研究训练只写 `models/baseline_candidate/`

## 二、推荐目录

Mac 当前推荐路径：

```bash
/Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
```

Windows 可使用自己的本地路径，例如：

```powershell
E:\AI炒股\机器学习\ptrade-t0-ml
```

不要把仓库的 `data/` 目录直接软链接到 OneDrive。如果要归档，使用单独的归档目录或手工复制。

## 三、Mac 首次接手

```bash
cd /Users/wangluke/Localprojects/机器学习
git clone https://github.com/luke0708/ptrade-t0-ml.git
cd ptrade-t0-ml
bash setup_venv_mac.sh
source .venv/bin/activate
python -c "import pandas, akshare, numpy, sklearn, matplotlib, xgboost, pandas_ta"
python -m unittest discover -s tests
```

如果 `xgboost` 报 `libomp.dylib` 缺失：

```bash
brew install libomp
```

如果旧环境里的 `data/` 仍是 OneDrive 软链接，先迁回本地目录：

```bash
bash migrate_data_dir_to_local.sh
```

确认：

```bash
ls -la data/
```

应看到 `data/` 是本地目录，而不是指向 OneDrive 的软链接。

## 四、每日生产流程

普通交易日收盘后运行：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python daily_backfill_data_mac.py
python build_minute_foundation.py
python build_feature_engine.py
python export_ml_daily_signal.py
```

产物：

- `data/ml_daily_signal.json`
- `data/ml_daily_signal.csv`
- `generated/ptrade/ptrade_300661_latest.py`
- `generated/ptrade/ptrade_300661_YYYYMMDD.py`

使用时优先复制 dated 文件到 PTrade。`YYYYMMDD` 是 `signal_for_date`，表示下一次真正运行策略的交易日。

## 五、周末研究流程

只有在周末或明确做模型升级时运行：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python build_label_engine.py
python train_baseline_models.py
python analyze_baseline_quality.py
python analyze_walk_forward.py
python analyze_walk_forward_failures.py
```

这组命令只训练和评估 candidate，不会直接影响每日 production 推理。

## 六、接受新模型

只有 candidate 通过 walk-forward 复盘后，才执行：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
cp -R models/baseline_stock_only models/baseline_stock_only_backup_$(date +%Y%m%d_%H%M%S)
python promote_baseline_candidate.py
python export_ml_daily_signal.py
```

说明：

- promote 前先备份旧 production
- `promote_baseline_candidate.py` 是唯一把 candidate 变成 production 的动作
- promote 后必须重跑 `export_ml_daily_signal.py`

## 七、当前稳定节点

截至 `2026-04-24`：

- production 训练时间：`2026-04-23T13:43:11`
- `model_version`：`baseline_multihead_20260423_134311`
- `positive_grid_day_classifier`：top `64`
- `tradable_classifier`：top `96`
- walk-forward：失败 / 胜利窗口 `3 / 19`
- `NORMAL`：`51` 天，`grid_pnl_mean = 0.004650`
- 当前 production 可挂，但开仓频率偏低

下一步研究目标不是替换 PTrade 架构，而是在 candidate 中提高 `positive_grid / tradable` 头部质量，并安全提高 `NORMAL` 覆盖率。

## 八、代码同步

开始工作前：

```bash
git pull origin main
```

收工提交：

```bash
git status --short
git add README.md "Project Plan.md" docs ptrade_t0_ml tests
git commit -m "docs: sync current ml production workflow"
git push origin main
```

不要把 `data/`、`analysis/`、`models/` 的大文件默认加入 Git；如需归档，单独复制到 OneDrive 或其它备份目录。

## 九、常见检查命令

确认 production / candidate 是否一致：

```bash
cd /Users/wangluke/Localprojects/机器学习/ptrade-t0-ml
source .venv/bin/activate
python - <<'PY'
import json
from pathlib import Path

base = Path(".")
for name, rel in [
    ("candidate", "models/baseline_candidate/baseline_candidate_metadata.json"),
    ("production", "models/baseline_stock_only/baseline_stock_only_metadata.json"),
]:
    data = json.loads((base / rel).read_text())
    print(name, data.get("trained_at"), data.get("model_slot"))
    for head in ["positive_grid_day_classifier", "tradable_classifier"]:
        head_meta = data.get("heads", {}).get(head, {})
        print(" ", head, len(head_meta.get("feature_columns", [])))
PY
```

确认每日信号：

```bash
python - <<'PY'
import json
from pathlib import Path

signal = json.loads(Path("data/ml_daily_signal.json").read_text())
for key in [
    "date",
    "signal_for_date",
    "recommended_mode",
    "signal_rationale",
    "model_version",
    "feature_version",
]:
    print(key, signal.get(key))
PY
```

文档最后更新：`2026-04-24`

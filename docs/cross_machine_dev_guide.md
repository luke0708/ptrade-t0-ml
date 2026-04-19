# 双机协作开发指南：Windows + Mac Mini M4

> 本文档说明如何在 **Windows（主力开发机）** 和 **Mac Mini M4** 之间，通过 **GitHub（代码同步）+ OneDrive（大数据同步）** 实现无缝协作开发，并保持每日数据自动补齐。

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        协作架构                              │
├──────────────────────┬──────────────────────────────────────┤
│  同步内容             │  同步方式                            │
├──────────────────────┼──────────────────────────────────────┤
│  Python 源码          │  Git + GitHub                        │
│  docs/、tests/        │  Git + GitHub                        │
│  requirements.txt     │  Git + GitHub                        │
├──────────────────────┼──────────────────────────────────────┤
│  data/ 大数据文件     │  OneDrive（网盘自动同步）            │
│  models/ 模型权重     │  OneDrive（网盘自动同步）            │
│  plots/ 图表产物      │  OneDrive（网盘自动同步）            │
└──────────────────────┴──────────────────────────────────────┘
```

**核心原则**：
- 代码（轻量）→ GitHub 同步，支持版本控制和回溯
- 数据（重量，几十 MB 到几 GB）→ OneDrive 同步，避免污染 Git 历史
- `data/` 目录在两台机器上都是指向 OneDrive 的**软链接（Junction/Symlink）**，代码路径写法完全一致，无需任何修改

---

## 二、目录与路径约定

| 项目   | Windows 路径                                  | Mac 路径                                           |
|--------|-----------------------------------------------|----------------------------------------------------|
| 代码仓库 | `e:\AI炒股\机器学习\`                          | `~/Developer/ptrade-t0-ml/`（可自定义）            |
| data 软链接 | `e:\AI炒股\机器学习\data\` → OneDrive     | `~/Developer/ptrade-t0-ml/data/` → OneDrive        |
| OneDrive 数据实体 | `D:\onedrive\Development\data_bundle\ptrade-t0-ml\` | `~/Library/CloudStorage/OneDrive-Personal/Development/data_bundle/ptrade-t0-ml/` |

---

## 三、首次配置（二选其一，按电脑操作）

### 3.1 Windows 端配置

> 前提：已安装 Python 3.11、Git，OneDrive 已登录并同步

**Step 1**：以管理员身份打开 PowerShell

```powershell
# 进入项目目录
cd "e:\AI炒股\机器学习"

# 运行 data 软链接配置脚本（会自动迁移 data/ 到 OneDrive 并创建软链接）
.\setup_data_link.ps1
```

运行后 `data/` 会变成指向 OneDrive 的 Junction 软链接，所有代码中的 `data/xxx.csv` 路径写法保持不变。

**Step 2**：创建虚拟环境（如果还未创建）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

### 3.2 Mac Mini M4 端配置

> 前提：已安装 Python 3.11、Git，OneDrive 已登录并完成初次同步

**Step 1**：克隆代码仓库

```bash
git clone https://github.com/luke0708/ptrade-t0-ml.git
cd ptrade-t0-ml
```

**Step 2**：创建虚拟环境

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Step 3**：等待 OneDrive 把 Windows 上传的数据同步完成，然后运行软链接脚本

```bash
bash setup_data_link_mac.sh
```

> ⚠️ 如果你的 OneDrive 路径不是默认的 `~/Library/CloudStorage/OneDrive-Personal/...`，
> 请先运行 `ls ~/Library/CloudStorage/` 查看实际路径，然后修改脚本开头的 `ONEDRIVE_DATA_PATH`。

**Step 4**：验证软链接是否生效

```bash
ls -la data/
# 应看到 data -> /Users/xxx/Library/CloudStorage/.../ptrade-t0-ml
```

---

## 四、日常开发工作流

### 4.1 每日开盘前：补齐数据（两端各自独立运行）

这是**最高频**的操作，建议收盘后（A 股 15:00 之后）各自独立执行：

**Windows 端**（PowerShell / 终端）：

```powershell
cd "e:\AI炒股\机器学习"
.\.venv\Scripts\Activate.ps1
python daily_backfill_data.py
```

**Mac 端**（Terminal / zsh）：

```bash
cd ~/Developer/ptrade-t0-ml
source .venv/bin/activate
python daily_backfill_data.py
```

> ✅ 两端数据完全独立更新，无须协调。OneDrive 会在两端运行后自动合并（文件覆盖，以最新时间戳为准）。

#### `daily_backfill_data.py` 做了什么？

| 数据文件 | 更新方式 | 数据源 |
|----------|----------|--------|
| `data/512480.csv` | 增量追加日线 | 东方财富（PowerShell 绕 SSL） |
| `data/399006.csv` | 增量追加日线 | 东方财富（PowerShell 绕 SSL） |
| `data/300661_SZ_1m_ptrade.csv` | 增量追加 1 分钟线 | AkShare 东方财富 |

**特点**：
- 自动识别文件末尾时间，只拉取缺失部分，不重复不覆盖
- 基于 `date` / `datetime` 去重，可以放心重复执行
- 修复了 EM 接口返回 `open=0.0` 的已知 bug
- 正常情况下每次运行几秒钟内完成

> ⚠️ **Mac 端注意**：`daily_backfill_data.py` 内的日线更新方法使用了 `powershell` 子进程命令，
> 在 Mac 上**无法运行**。Mac 端建议只用于代码开发，数据由 Windows 端更新后通过 OneDrive 同步。
> 
> 如果 Mac 端也需要独立拉数据，请告知，我会为 Mac 单独编写一个 `daily_backfill_data_mac.py`（使用 `curl` 替代 PowerShell）。

---

### 4.2 代码同步工作流

#### Windows 端推送代码

```powershell
cd "e:\AI炒股\机器学习"
git add .
git commit -m "feat: 描述你的改动"
git push origin main
```

#### Mac 端拉取代码

```bash
cd ~/Developer/ptrade-t0-ml
git pull origin main
```

#### Mac 端推送代码

```bash
git add .
git commit -m "feat: 描述你的改动"
git push origin main
```

#### Windows 端拉取 Mac 的代码

```powershell
git pull origin main
```

---

### 4.3 推荐的日常开发顺序

```
每天开始工作时：
  1. git pull                   ← 先拉最新代码
  2. python daily_backfill_data.py  ← 补齐最新数据（Windows）
  3. 开发写代码 / 训练模型 ...

收工时：
  4. git add . && git commit && git push  ← 推送代码到 GitHub
  5. OneDrive 后台自动同步 data/          ← 无需手动操作
```

---

## 五、重建生产流水线（新机器首次运行）

当 OneDrive 数据同步完成后，如需重新生成所有中间产物（`foundation/` 目录），按以下顺序运行：

```bash
# Phase 1：规范化并审计主分钟数据底座
python build_minute_foundation.py

# Phase 2：生成首批生产标签
python build_label_engine.py

# Phase 3：生成首批生产特征表
python build_feature_engine.py

# Phase 4：训练 baseline 7 头模型（含阈值校准）
python train_baseline_models.py

# Phase 5：导出当日 ML 信号
python export_ml_daily_signal.py
```

> ❗ 以上每步有依赖关系，必须按顺序执行。仅当 `data/300661_SZ_1m_ptrade.csv` 已就位（通过 OneDrive 同步）时才能正常运行。

---

## 六、OneDrive 数据目录说明

通过软链接方案，`data/` 在 Git 层面始终只保留一个 `.gitkeep` 占位文件，实际数据存储在 OneDrive：

```
D:\onedrive\Development\data_bundle\ptrade-t0-ml\   （Windows 上的 OneDrive 实体目录）
├── 300661_SZ_1m_ptrade.csv     ← 主分钟数据：~40MB，516240 行
├── 300661_features.csv
├── 300661_labeled_dataset.csv
├── 300661_regression_dataset.csv
├── 399006.csv                  ← 创业板指日线
├── 512480.csv                  ← 半导体 ETF 日线
├── ml_daily_signal.json        ← 每日 ML 信号
├── ml_daily_signal.csv
├── foundation/                 ← Phase 1-3 产物目录
│   ├── 300661_SZ_1m_canonical.csv
│   ├── 300661_SZ_1m_daily_summary.csv
│   ├── 300661_SZ_label_targets.csv
│   ├── 300661_SZ_feature_table.csv
│   └── 300661_SZ_training_dataset.csv
└── ...
```

OneDrive 会在两台机器之间**自动后台同步**，无需任何手动操作。

---

## 七、不同场景的处理方式

### 场景 A：只在 Windows 开发，Mac 只查看结果

- Windows 负责跑 `daily_backfill_data.py` 更新数据、训练模型、推送代码
- Mac 只用 `git pull` 拉代码，数据通过 OneDrive 自动同步

### 场景 B：两台电脑都在开发代码

- 遵守"**先 pull 再 push**"原则，避免代码冲突
- 数据文件通过 OneDrive 同步，无冲突风险（`.gitignore` 已排除）

### 场景 C：Mac 端也需要独立补数据

目前 `daily_backfill_data.py` 的日线拉取方法依赖 Windows PowerShell。如需 Mac 端独立跑，可以：

```bash
# Mac 端可用 akshare 直接拉日线（无 SSL 问题）
python3 -c "
import akshare as ak
df = ak.stock_zh_a_hist(symbol='399006', period='daily', start_date='20200101', adjust='qfq')
print(df.tail())
"
```

如需完整 Mac 端补数脚本，请告知即可生成 `daily_backfill_data_mac.py`。

---

## 八、常见问题

### Q1：git push 失败，提示 `Failed to connect to 127.0.0.1 port 10809`

旧的代理配置导致，运行以下命令清除：

```powershell
# Windows
git config --global --unset http.proxy
git config --global --unset https.proxy
```

```bash
# Mac
git config --global --unset http.proxy
git config --global --unset https.proxy
```

---

### Q2：OneDrive 数据还没同步完，如何查看同步状态？

- **Windows**：右键任务栏 OneDrive 图标，查看同步进度
- **Mac**：点击菜单栏 OneDrive 图标，查看同步状态

大文件（如 `300661_SZ_1m_ptrade.csv` ~40MB）首次同步可能需要几分钟，请等待完成后再运行流水线脚本。

---

### Q3：如何确认软链接配置成功？

**Windows**：

```powershell
(Get-Item "e:\AI炒股\机器学习\data").Attributes
# 应包含 ReparsePoint
```

**Mac**：

```bash
ls -la ~/Developer/ptrade-t0-ml/data
# 应显示：data -> /Users/xxx/Library/CloudStorage/.../ptrade-t0-ml
```

---

### Q4：如何添加新的大文件到数据同步？

只需将文件放入 `data/` 目录（实际写入 OneDrive），OneDrive 会自动同步到另一台机器。无需修改 `.gitignore`，因为 `data/*` 已整体排除。

---

## 九、快速参考卡

```
┌─────────────────────────────────────────────────────────────┐
│                    日常操作速查                              │
├────────────────────────┬────────────────────────────────────┤
│  操作                  │  命令                               │
├────────────────────────┼────────────────────────────────────┤
│  每日补数据（Windows） │  python daily_backfill_data.py      │
│  拉取最新代码          │  git pull origin main               │
│  推送代码              │  git add . && git commit && git push│
│  重建特征标签          │  按第五节顺序运行 5 个脚本         │
│  导出当日信号          │  python export_ml_daily_signal.py   │
└────────────────────────┴────────────────────────────────────┘
```

---

*文档最后更新：2026-04-19 | 维护人：luke0708*

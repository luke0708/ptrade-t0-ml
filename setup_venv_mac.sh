#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
VENDOR_DIR="$PROJECT_DIR/vendor"
REQUIREMENTS_FILE="${REQUIREMENTS_FILE:-$PROJECT_DIR/requirements-dev.txt}"

if [ -n "${PYTHON_BIN:-}" ]; then
    SELECTED_PYTHON="$PYTHON_BIN"
elif command -v python3.12 >/dev/null 2>&1; then
    SELECTED_PYTHON="python3.12"
elif command -v python3.11 >/dev/null 2>&1; then
    SELECTED_PYTHON="python3.11"
else
    echo "❌ 未找到 python3.12 或 python3.11。请先安装 Python 3.11+。"
    echo "macOS 建议命令: brew install python@3.12"
    exit 1
fi

echo "=== ptrade-t0-ml 虚拟环境初始化 (Mac) ==="
echo "使用解释器: $SELECTED_PYTHON"
echo "开发依赖清单: $REQUIREMENTS_FILE"

"$SELECTED_PYTHON" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip --version >/dev/null

if [ -d "$VENDOR_DIR" ]; then
    SITE_PACKAGES="$("$VENV_DIR/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
    PTH_FILE="$SITE_PACKAGES/ptrade_vendor.pth"
    printf '%s\n' "$VENDOR_DIR" > "$PTH_FILE"
    echo "✅ 已将 vendor/ 注入虚拟环境: $PTH_FILE"
else
    echo "⚠️ 未找到 vendor/。如果需要完整算法开发环境，请执行:"
    echo ".venv/bin/pip install -r requirements-dev.txt"
fi

if "$VENV_DIR/bin/python" -c "import pandas, akshare, numpy" >/dev/null 2>&1; then
    echo "✅ 基础依赖检查通过"
else
    echo "⚠️ 基础依赖仍不完整，请执行:"
    echo ".venv/bin/pip install -r requirements.txt"
fi

if "$VENV_DIR/bin/python" -c "import sklearn, matplotlib, xgboost, pandas_ta" >/dev/null 2>&1; then
    echo "✅ 完整算法开发依赖检查通过"
else
    echo "⚠️ 当前还不是完整算法开发环境，请执行:"
    echo ".venv/bin/pip install -r requirements-dev.txt"
fi

echo ""
echo "后续使用方式:"
echo "source .venv/bin/activate"
echo "python -V"
echo "python -c \"import pandas, akshare, numpy, sklearn, matplotlib, xgboost, pandas_ta\""
echo "python -m unittest discover -s tests"

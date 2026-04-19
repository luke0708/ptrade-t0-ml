#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
REQUIREMENTS_FILE="${REQUIREMENTS_FILE:-$PROJECT_DIR/requirements-dev.txt}"

check_libomp_runtime() {
    if [ -f "/opt/homebrew/opt/libomp/lib/libomp.dylib" ] || [ -f "/usr/local/opt/libomp/lib/libomp.dylib" ]; then
        echo "✅ 已检测到 libomp，xgboost 可使用 OpenMP 运行库"
    elif command -v brew >/dev/null 2>&1; then
        echo "⚠️ 未检测到 libomp。macOS 上运行 xgboost 训练前请先执行:"
        echo "brew install libomp"
    else
        echo "⚠️ 未检测到 libomp，且当前没有找到 brew。"
        echo "请先安装 Homebrew，然后执行: brew install libomp"
    fi
}

if [ -n "${PYTHON_BIN:-}" ]; then
    SELECTED_PYTHON="$PYTHON_BIN"
elif command -v python3.12 >/dev/null 2>&1; then
    SELECTED_PYTHON="python3.12"
else
    SELECTED_PYTHON="python3"
fi

cd "$PROJECT_DIR"

echo "=== ptrade-t0-ml Vendor 依赖安装 (Mac) ==="
echo "使用解释器: $SELECTED_PYTHON"
echo "依赖清单: $REQUIREMENTS_FILE"
check_libomp_runtime

"$SELECTED_PYTHON" -m pip install --upgrade pip
"$SELECTED_PYTHON" -m pip install --upgrade --target "$PROJECT_DIR/vendor" -r "$REQUIREMENTS_FILE"

if "$SELECTED_PYTHON" -c "import sys; sys.path.insert(0, '$PROJECT_DIR/vendor'); import pandas, akshare, numpy, sklearn, matplotlib, xgboost, pandas_ta" >/dev/null 2>&1; then
    echo "✅ 完整算法开发依赖检查通过"
else
    echo "⚠️ vendor/ 依赖检查未完全通过，请检查安装日志"
    if [ ! -f "/opt/homebrew/opt/libomp/lib/libomp.dylib" ] && [ ! -f "/usr/local/opt/libomp/lib/libomp.dylib" ]; then
        echo "⚠️ 如果失败点出现在 xgboost / libomp，请先执行: brew install libomp"
    fi
fi

echo ""
echo "✅ vendor/ 依赖安装完成"
echo "后续如需运行其它脚本，请先执行: source activate_vendor_env.sh"
echo "并继续使用同一个解释器，例如: $SELECTED_PYTHON daily_backfill_data_mac.py"

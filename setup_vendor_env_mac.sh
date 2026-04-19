#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

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

"$SELECTED_PYTHON" -m pip install --upgrade pip
"$SELECTED_PYTHON" -m pip install --upgrade --target "$PROJECT_DIR/vendor" -r "$PROJECT_DIR/requirements.txt"

echo ""
echo "✅ vendor/ 依赖安装完成"
echo "后续如需运行其它脚本，请先执行: source activate_vendor_env.sh"
echo "并继续使用同一个解释器，例如: $SELECTED_PYTHON daily_backfill_data_mac.py"

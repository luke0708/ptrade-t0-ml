#!/bin/bash

if [ -n "${ZSH_VERSION:-}" ]; then
    SCRIPT_PATH="${(%):-%N}"
else
    SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
fi

PROJECT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
VENDOR_DIR="$PROJECT_DIR/vendor"

if [ ! -d "$VENDOR_DIR" ]; then
    echo "❌ 未找到 vendor/ 目录，请先运行 bash setup_vendor_env_mac.sh"
    return 1 2>/dev/null || exit 1
fi

export PYTHONPATH="$VENDOR_DIR${PYTHONPATH:+:$PYTHONPATH}"
echo "✅ 已启用 vendor Python 路径: $VENDOR_DIR"
echo "当前请使用与 vendor 安装时相同的解释器，例如: python3.12"

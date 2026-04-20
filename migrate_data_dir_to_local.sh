#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_PATH="$PROJECT_DIR/data"

if [ ! -L "$DATA_PATH" ]; then
    echo "✅ data/ 已经是本地目录，无需迁移"
    exit 0
fi

SOURCE_PATH="$(readlink "$DATA_PATH")"
TEMP_DIR="$PROJECT_DIR/.data_local_tmp"

echo "=== ptrade-t0-ml 本地运行数据目录迁移 ==="
echo "当前软链接: $DATA_PATH -> $SOURCE_PATH"

rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"

cp -R "$SOURCE_PATH"/. "$TEMP_DIR"/
rm "$DATA_PATH"
mv "$TEMP_DIR" "$DATA_PATH"

echo "✅ 已将 data/ 迁移回本地目录: $DATA_PATH"
echo "如需继续归档到 OneDrive，请设置："
echo "export PTRADE_ARCHIVE_DATA_DIR=\"$SOURCE_PATH\""

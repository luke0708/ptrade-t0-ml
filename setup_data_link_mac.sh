#!/bin/bash
# ============================================================
# setup_data_link_mac.sh
# 用途：Mac 电脑将项目 data/ 目录软链接到 OneDrive 共享数据目录
# 使用前提：OneDrive 已安装并同步
# ============================================================

# ⚠️ 根据你的 Mac OneDrive 路径修改下面这行
ONEDRIVE_DATA_PATH="$HOME/Library/CloudStorage/OneDrive-Personal/Development/data_bundle/ptrade-t0-ml"
# 如果你的 OneDrive 路径不同，可以运行以下命令查找：
# ls ~/Library/CloudStorage/

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DATA_PATH="$PROJECT_DIR/data"

echo "=== ptrade-t0-ml 数据目录配置 (Mac) ==="

# 1. 确保 OneDrive 数据目录存在（等待 OneDrive 同步）
if [ ! -d "$ONEDRIVE_DATA_PATH" ]; then
    echo "📁 创建 OneDrive 数据目录: $ONEDRIVE_DATA_PATH"
    mkdir -p "$ONEDRIVE_DATA_PATH"
    echo "✅ 已创建（数据将在 OneDrive 同步后自动填充）"
else
    echo "✅ OneDrive 数据目录已存在: $ONEDRIVE_DATA_PATH"
fi

# 2. 检查 data/ 目录情况
if [ -L "$PROJECT_DATA_PATH" ]; then
    echo "⚠️  data/ 已是软链接，目标: $(readlink "$PROJECT_DATA_PATH")"
    echo "无需重新配置。"
    exit 0
elif [ -d "$PROJECT_DATA_PATH" ]; then
    echo "发现现有 data/ 目录，保留（Mac 端通常从 OneDrive 获取数据）"
    # 如果本地 data/ 只有 .gitkeep，则删除并重建软链接
    FILE_COUNT=$(find "$PROJECT_DATA_PATH" -not -name ".gitkeep" -type f | wc -l)
    if [ "$FILE_COUNT" -eq 0 ]; then
        rm -rf "$PROJECT_DATA_PATH"
        echo "✅ 已移除空的 data/ 目录"
    else
        echo "⚠️  data/ 目录有 $FILE_COUNT 个文件，手动确认后删除再运行此脚本"
        exit 1
    fi
fi

# 3. 创建软链接
echo "创建软链接: $PROJECT_DATA_PATH -> $ONEDRIVE_DATA_PATH"
ln -s "$ONEDRIVE_DATA_PATH" "$PROJECT_DATA_PATH"
echo "✅ 软链接创建成功！"
echo ""
echo "现在 data/ 目录实际存储在: $ONEDRIVE_DATA_PATH"
echo "OneDrive 会自动同步数据，Windows 电脑更新数据后 Mac 这边会自动同步。"

# ============================================================
# setup_data_link.ps1
# 用途：将项目 data/ 目录软链接到 OneDrive 共享数据目录
# 适用：Windows (PowerShell，需以管理员身份运行)
# ============================================================

$OneDriveDataPath = "D:\onedrive\Development\data_bundle\ptrade-t0-ml"
$ProjectDataPath  = "$PSScriptRoot\data"

Write-Host "=== ptrade-t0-ml 数据目录配置 ===" -ForegroundColor Cyan

# 1. 确保 OneDrive 数据目录存在
if (-not (Test-Path $OneDriveDataPath)) {
    Write-Host "创建 OneDrive 数据目录: $OneDriveDataPath" -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $OneDriveDataPath -Force | Out-Null
    Write-Host "✅ 已创建" -ForegroundColor Green
} else {
    Write-Host "✅ OneDrive 数据目录已存在: $OneDriveDataPath" -ForegroundColor Green
}

# 2. 检查 data/ 目录情况
if (Test-Path $ProjectDataPath) {
    $item = Get-Item $ProjectDataPath -Force
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        Write-Host "⚠️  data/ 已是软链接，目标: $($item.Target)" -ForegroundColor Yellow
        Write-Host "无需重新配置。" -ForegroundColor Green
        exit 0
    } else {
        Write-Host "发现现有 data/ 目录，将迁移数据到 OneDrive..." -ForegroundColor Yellow
        # 把已有数据迁移过去（跳过 .gitkeep）
        Get-ChildItem -Path $ProjectDataPath -File | Where-Object { $_.Name -ne ".gitkeep" } | ForEach-Object {
            $dest = Join-Path $OneDriveDataPath $_.Name
            if (-not (Test-Path $dest)) {
                Copy-Item $_.FullName -Destination $dest
                Write-Host "  迁移: $($_.Name)" -ForegroundColor Gray
            }
        }
        # 迁移子目录
        Get-ChildItem -Path $ProjectDataPath -Directory | ForEach-Object {
            $dest = Join-Path $OneDriveDataPath $_.Name
            if (-not (Test-Path $dest)) {
                Copy-Item $_.FullName -Destination $dest -Recurse
                Write-Host "  迁移目录: $($_.Name)" -ForegroundColor Gray
            }
        }
        Write-Host "✅ 数据迁移完成" -ForegroundColor Green

        # 删除原始 data/ 目录
        Remove-Item -Path $ProjectDataPath -Recurse -Force
        Write-Host "✅ 已删除原始 data/ 目录" -ForegroundColor Green
    }
}

# 3. 创建软链接
Write-Host "创建软链接: $ProjectDataPath -> $OneDriveDataPath" -ForegroundColor Yellow
try {
    New-Item -ItemType Junction -Path $ProjectDataPath -Target $OneDriveDataPath | Out-Null
    Write-Host "✅ 软链接创建成功！" -ForegroundColor Green
    Write-Host ""
    Write-Host "现在 data/ 目录实际存储在: $OneDriveDataPath" -ForegroundColor Cyan
    Write-Host "OneDrive 会自动同步数据到云端，Mac 电脑可通过 OneDrive 访问。" -ForegroundColor Cyan
} catch {
    Write-Host "❌ 创建软链接失败: $_" -ForegroundColor Red
    Write-Host "请确保以管理员身份运行此脚本！" -ForegroundColor Yellow
}

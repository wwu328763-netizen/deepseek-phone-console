# 手机远程控制台启动脚本（Windows）
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# 让中文正常显示
try {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

# 优先使用 Codex 自带的 Python；找不到则用系统 python
$py = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

# 读取或生成 PIN（保证一定存在且可查看）
$dataDir = Join-Path $root "console_data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$pinFile = Join-Path $dataDir "pin.txt"
$pin = $null
if (Test-Path $pinFile) { $pin = (Get-Content -LiteralPath $pinFile -Raw).Trim() }
if ($pin -and $pin -notmatch '^[0-9]+$') {
  Write-Host "旧 PIN 含字母，已自动换成 8 位数字 PIN（手机输入更方便）" -ForegroundColor Yellow
  $pin = $null
}
if (-not $pin) {
  $pin = -join (1..8 | ForEach-Object { (Get-Random -Maximum 10).ToString() })
  Set-Content -LiteralPath $pinFile -Value $pin -Encoding UTF8
}

Write-Host ""
Write-Host "==== PIN: $pin ====" -ForegroundColor Green
Write-Host "PIN file: $pinFile" -ForegroundColor Cyan
Write-Host "提示：建议以管理员身份运行（DSH 命令沙箱需要管理员权限）" -ForegroundColor Yellow

# 对接目标：默认自动发现（桌面端 DeepSeek Harness 优先，找不到再用网页端 3080）
Write-Host "对接目标：正在查找 DeepSeek Harness…" -ForegroundColor Cyan
Write-Host "  桌面端：启动「DeepSeek Harness」桌面程序即可（端口自动发现）"
Write-Host "  网页端：dsh web --port 3080；也可用 --dsh-url 手动指定"
Write-Host ""

try {
  & $py (Join-Path $root "server.py") --pin $pin @args
} catch {
  Write-Host "启动失败: $($_.Exception.Message)" -ForegroundColor Red
  Read-Host "按回车关闭"
}

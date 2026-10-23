$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$dataDir = Join-Path $root "console_data"
$pidFile = Join-Path $dataDir "server.pid"

$stopped = $false
if (Test-Path $pidFile) {
  $saved = (Get-Content -LiteralPath $pidFile -Raw).Trim()
  if ($saved) {
    Stop-Process -Id $saved -Force -ErrorAction SilentlyContinue
    $stopped = $true
  }
  Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

$conn = Get-NetTCPConnection -State Listen -LocalPort 8787 -ErrorAction SilentlyContinue
if ($conn) {
  foreach ($p in ($conn.OwningProcess | Select-Object -Unique)) {
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    $stopped = $true
  }
}

if ($stopped) {
  Write-Host "控制台服务已停止。"
} else {
  Write-Host "控制台服务未在运行。"
}
Read-Host "按回车关闭"

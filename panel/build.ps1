# 打包 WebView2 管理面板（PyInstaller + pywebview）
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File panel\build.ps1
$ErrorActionPreference = 'Continue'
$panel = $PSScriptRoot
$pkg = Split-Path -Parent $panel
$out = Join-Path $pkg 'ConsolePanel.exe'

Write-Host '[1/3] 检查依赖 ...'
python -c "import webview; print('pywebview OK')"
if ($LASTEXITCODE -ne 0) { Write-Host '缺少依赖：python -m pip install pywebview'; exit 1 }

Write-Host '[2/3] 打包中（约 1-3 分钟）...'
Get-Process -Name 'ConsolePanel' -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item (Join-Path $env:TEMP 'consolepanel_build') -Recurse -Force -ErrorAction SilentlyContinue

python -m PyInstaller --noconfirm --onefile --windowed `
  --name ConsolePanel `
  --icon "$pkg\console.ico" `
  --add-data "$panel\webui;webui" `
  --add-data "$pkg\vendor\qrcode;qrcode" `
  --paths "$pkg" `
  --paths "$pkg\vendor" `
  --hidden-import webview.platforms.edgechromium `
  --hidden-import webview.platforms.winforms `
  --hidden-import clr `
  --collect-all webview `
  --collect-all pythonnet `
  --collect-all clr_loader `
  --distpath "$pkg" `
  --workpath (Join-Path $env:TEMP 'consolepanel_build') `
  --specpath (Join-Path $env:TEMP 'consolepanel_build') `
  "$panel\host.py" 2>&1 |
  Select-String -Pattern 'ERROR|Build complete|completed successfully|Traceback|missing module' |
  Select-Object -Last 10

if (-not (Test-Path $out)) { Write-Host '打包失败：没有生成 exe'; exit 1 }
$mb = [math]::Round((Get-Item $out).Length / 1MB, 1)
Write-Host "[3/3] 完成：$out ($mb MB)"

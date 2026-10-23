$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$exe = Join-Path $root "cloudflared.exe"

if (Test-Path $exe) {
  if ((Get-Item $exe).Length -gt 5000000) {
    Write-Host "cloudflared 已存在，跳过下载。"
  } else {
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
  }
}

if (-not (Test-Path $exe)) {
  Write-Host "正在下载 cloudflared（约 50MB，走国内镜像加速）..." -ForegroundColor Cyan
  $urls = @(
    "https://gh.ddlc.top/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    "https://gh-proxy.com/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    "https://ghfast.top/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    "https://ghproxy.net/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
  )
  $ok = $false
  foreach ($u in $urls) {
    Write-Host "尝试: $u"
    & curl.exe -L -C - --retry 5 --retry-delay 3 --connect-timeout 15 -o $exe $u
    if ($LASTEXITCODE -eq 0 -and (Test-Path $exe) -and (Get-Item $exe).Length -gt 5000000) {
      $ok = $true
      break
    }
  }
  if (-not $ok) {
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "自动下载失败。请手动下载（浏览器或迅雷/IDM 会更快）:" -ForegroundColor Yellow
    Write-Host "  https://ghfast.top/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Write-Host ""
    Write-Host "下载完成后，把文件改名为 cloudflared.exe 放到这个文件夹:" -ForegroundColor Yellow
    Write-Host "  $root"
    Read-Host "按回车关闭"
    exit 1
  }
  Write-Host "下载完成。"
}

Write-Host ""
Write-Host "请先确认手机远程控制台（start-console.bat）已在运行。" -ForegroundColor Yellow
Write-Host "启动隧道后，把下面出现的 https://xxx.trycloudflare.com 地址发到手机即可。"
Write-Host "手机用流量或任何 Wi-Fi 都能打开（无需同一网络）。"
Write-Host "注意：隧道地址每次启动都会变化；关闭本窗口隧道即失效。"
Write-Host ""
& $exe tunnel --url http://127.0.0.1:8787 --no-prechecks --no-autoupdate --protocol http2

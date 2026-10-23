$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$port = 8787
$py = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

# ---------- PIN ----------
$dataDir = Join-Path $root "console_data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$pinFile = Join-Path $dataDir "pin.txt"
$pin = $null
if (Test-Path $pinFile) { $pin = (Get-Content -LiteralPath $pinFile -Raw).Trim() }
if ($pin -and $pin -notmatch '^[0-9]+$') { $pin = $null }
if (-not $pin) {
  $pin = -join (1..8 | ForEach-Object { (Get-Random -Maximum 10).ToString() })
  Set-Content -LiteralPath $pinFile -Value $pin -Encoding UTF8
}

# ---------- 0/2 对接目标 ----------
# 不再要求先跑 dsh web（3080）：服务启动时会自动发现桌面端 DeepSeek Harness 的端口，
# 找不到才回退到网页端 http://127.0.0.1:3080。
Write-Host "[0/2] 对接目标：自动查找 DeepSeek Harness（桌面端优先，其次网页端 3080）"

# ---------- 1/2 console server ----------
$serverPid = $null
$inUse = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($inUse) {
  Write-Host "[1/2] 控制台已在运行（端口 $port），跳过启动。"
  $serverPid = ($inUse | Select-Object -First 1).OwningProcess
} else {
  Write-Host "[1/2] 正在启动手机远程控制台..."
  $serverOut = Join-Path $dataDir "server.out.log"
  $serverErr = Join-Path $dataDir "server.err.log"
  $proc = Start-Process -FilePath $py `
    -ArgumentList @((Join-Path $root "server.py"), "--port", "$port", "--pin", $pin) `
    -WindowStyle Hidden -RedirectStandardOutput $serverOut -RedirectStandardError $serverErr -PassThru
  $serverPid = $proc.Id
  Set-Content -LiteralPath (Join-Path $dataDir "server.pid") -Value $serverPid -Encoding UTF8
  $ready = $false
  for ($i = 0; $i -lt 110; $i++) {
    $code = & curl.exe -s -o NUL -w "%{http_code}" "http://127.0.0.1:$port/" 2>$null
    if ($code -eq "200") { $ready = $true; break }
    Start-Sleep -Milliseconds 500
  }
  if (-not $ready) {
    Write-Host "控制台启动失败，请检查端口是否被占用、Python 路径是否正确。" -ForegroundColor Red
    Write-Host "（最常见原因：桌面端 DeepSeek Harness 没有运行，且网页端 dsh web 也没启动）" -ForegroundColor Yellow
    if (Test-Path $serverOut) { Get-Content $serverOut -Tail 15 -ErrorAction SilentlyContinue }
    if (Test-Path $serverErr) { Get-Content $serverErr -Tail 15 -ErrorAction SilentlyContinue }
    Write-Host "日志文件: $serverOut / $serverErr" -ForegroundColor Yellow
    if ($serverPid) { Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue }
    Read-Host "按回车关闭"
    exit 1
  }
  Write-Host "控制台已启动。"
}

Write-Host ""
Write-Host "==== PIN: $pin ====" -ForegroundColor Green
$lan = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        Select-Object -First 1).IPAddress
if ($lan) { Write-Host "局域网访问(同WiFi): http://$lan`:$port" }

# ---------- 2/2 tunnel ----------
$exe = Join-Path $root "cloudflared.exe"
if (-not (Test-Path $exe)) {
  Write-Host ""
  Write-Host "未找到 cloudflared.exe。" -ForegroundColor Red
  Write-Host "请先双击「start-tunnel.bat」完成下载，再运行 start-all.bat。" -ForegroundColor Yellow
  if ($serverPid) { Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue }
  Read-Host "按回车关闭"
  exit 1
}

Write-Host ""
Write-Host "[2/2] 正在建立公网隧道，请稍候..."
Write-Host "下面出现 https://xxx.trycloudflare.com 即为外网地址："
Write-Host "手机在任何网络打开该地址，输入 PIN 即可。关闭本窗口 = 全部停止。"
Write-Host "注意：控制台服务会一直在后台运行（本窗口关闭也不影响），"
Write-Host "      需要关闭服务时请双击「stop-all.bat」。"
Write-Host ""
& $exe tunnel --url "http://127.0.0.1:$port" --no-prechecks --no-autoupdate --protocol http2
Write-Host ""
Write-Host "隧道已断开。控制台服务仍在后台运行，手机仍可局域网连接；" -ForegroundColor Yellow
Write-Host "如需关闭服务，请双击「stop-all.bat」。"
Read-Host "按回车关闭本窗口"

# 下载 cloudflared.exe（隧道用）
$ErrorActionPreference = 'Stop'
$dir = Split-Path -Parent $PSScriptRoot
$dst = Join-Path $dir 'cloudflared.exe'
if (Test-Path $dst) { "已存在: $dst"; exit 0 }
$url = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'
"下载 $url ..."
Invoke-WebRequest -Uri $url -OutFile $dst -UseBasicParsing
"完成: $dst ($([math]::Round((Get-Item $dst).Length/1MB,1)) MB)"

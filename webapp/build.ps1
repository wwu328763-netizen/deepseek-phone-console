# Build the mobile frontend (TypeScript + Preact + esbuild)
#
# 两种用法：
#   1) 有 npm 环境（推荐）：先 `npm install`，再跑本脚本 —— 会用 node_modules 里的 tsc/esbuild/preact
#   2) 离线：把 tsc / esbuild / preact 放进 webapp\_tools\（见 docs/BUILD.md）
#
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File webapp\build.ps1
$ErrorActionPreference = 'Stop'
$app = $PSScriptRoot
$pkg = Split-Path -Parent $app
$out = Join-Path $pkg 'web\app'
$tools = Join-Path $app '_tools'
$nm = Join-Path $app 'node_modules'

# ---------- node ----------
$node = $env:NODE_EXE
if (-not $node) { $node = (Get-Command node -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source) }
if (-not $node) {
    foreach ($c in @("$env:ProgramFiles\nodejs\node.exe", (Join-Path $env:LOCALAPPDATA 'Programs\nodejs\node.exe'))) {
        if ($c -and (Test-Path $c)) { $node = $c; break }
    }
}
if (-not $node) { throw '找不到 node：请安装 Node.js 20+ 并加入 PATH' }

# ---------- tsc / esbuild：node_modules 优先，其次离线 _tools ----------
$tsc = Join-Path $nm '.bin\tsc.cmd'
if (-not (Test-Path $tsc)) { $tsc = Join-Path $tools 'pkg_typescript\package\bin\tsc' }

$esbuild = $null
foreach ($c in @((Join-Path $nm '.bin\esbuild.cmd'), (Join-Path $nm 'esbuild\esbuild.exe'),
                 (Join-Path $tools 'pkg_esbuild\package\esbuild.exe'))) {
    if ($c -and (Test-Path $c)) { $esbuild = $c; break }
}
if (-not (Test-Path $tsc)) {
    throw '缺少 tsc：先在 webapp 目录执行 npm install（或提供 webapp\_tools\pkg_typescript）'
}
if (-not $esbuild) {
    throw '缺少 esbuild：先在 webapp 目录执行 npm install（或提供 webapp\_tools\pkg_esbuild）'
}

# ---------- preact：缺 node_modules 时用离线副本 ----------
if (-not (Test-Path (Join-Path $nm 'preact\package.json'))) {
    $pkgPreact = Join-Path $tools 'pkg_preact\package'
    if (Test-Path $pkgPreact) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent (Join-Path $nm 'preact')) | Out-Null
        Copy-Item $pkgPreact (Join-Path $nm 'preact') -Recurse -Force
    } else {
        throw '缺少 preact：先在 webapp 目录执行 npm install（或提供 webapp\_tools\pkg_preact）'
    }
}

New-Item -ItemType Directory -Force -Path $out | Out-Null

Write-Host '[1/3] type check (tsc --noEmit) ...'
Push-Location $app
try {
    if ($tsc -match '\.(cmd|exe)$') { & $tsc -p tsconfig.json }
    else { & $node $tsc -p tsconfig.json }
    if ($LASTEXITCODE -ne 0) { throw 'TypeScript type check failed' }

    Write-Host '[2/3] bundle (esbuild) ...'
    if ($esbuild -match '\.exe$') {
        & $esbuild src/main.tsx --bundle --minify --format=iife --target=es2020 --jsx=automatic --jsx-import-source=preact --outfile="$out\app.js" --log-level=warning
    } elseif ($esbuild -match '\.cmd$') {
        & $esbuild src/main.tsx --bundle --minify --format=iife --target=es2020 --jsx=automatic --jsx-import-source=preact --outfile="$out\app.js" --log-level=warning
    } else {
        & $node $esbuild src/main.tsx --bundle --minify --format=iife --target=es2020 --jsx=automatic --jsx-import-source=preact --outfile="$out\app.js" --log-level=warning
    }
    if ($LASTEXITCODE -ne 0) { throw 'esbuild bundle failed' }
} finally {
    Pop-Location
}

Write-Host '[3/3] copy html ...'
Copy-Item (Join-Path $app 'index.html') (Join-Path $out 'index.html') -Force

$js = Get-Item (Join-Path $out 'app.js')
$css = Get-Item (Join-Path $out 'app.css') -ErrorAction SilentlyContinue
$extra = ''
if ($css) { $extra = ' + app.css ' + [math]::Round($css.Length / 1KB, 1) + ' KB' }
Write-Host ('done: ' + $js.FullName + ' (' + [math]::Round($js.Length / 1KB, 1) + ' KB)' + $extra)

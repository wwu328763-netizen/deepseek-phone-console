# Build the new mobile frontend (TypeScript + Preact + esbuild, no npm).
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File webapp\build.ps1
$ErrorActionPreference = 'Stop'
$app = $PSScriptRoot
$pkg = Split-Path -Parent $app
$tools = Join-Path $app '_tools'
$out = Join-Path $pkg 'web\app'

$node = (Get-Command node -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
if (-not $node) { $node = 'C:\Agent\DSH\resources\runtime\primary-runtime\dependencies\node\bin\node.exe' }
if (-not (Test-Path $node)) { throw 'node.exe not found' }

$esbuild = Join-Path $tools 'pkg_esbuild\package\esbuild.exe'
$tsc = Join-Path $tools 'pkg_typescript\package\bin\tsc'
if (-not (Test-Path $esbuild)) { throw "missing esbuild: $esbuild" }
if (-not (Test-Path $tsc)) { throw "missing tsc: $tsc" }

$nm = Join-Path $app 'node_modules\preact'
if (-not (Test-Path (Join-Path $nm 'package.json'))) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $nm) | Out-Null
  Copy-Item (Join-Path $tools 'pkg_preact\package') $nm -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $out | Out-Null

Write-Host '[1/3] type check (tsc --noEmit) ...'
Push-Location $app
try {
  & $node $tsc -p tsconfig.json
  if ($LASTEXITCODE -ne 0) { throw 'TypeScript type check failed' }

  Write-Host '[2/3] bundle (esbuild) ...'
  & $esbuild src/main.tsx --bundle --minify --format=iife --target=es2020 --jsx=automatic --jsx-import-source=preact --outfile="$out\app.js" --log-level=warning
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
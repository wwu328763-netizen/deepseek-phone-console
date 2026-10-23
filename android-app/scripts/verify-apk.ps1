# Verify the release APK: package/version, signer cert, zipalign, size.
# Usage:  pwsh -File .\scripts\verify-apk.ps1 [-Apk <path>]
param(
    [string]$Apk,
    [string]$ExpectedSha256 = "fdc19571dfaf7a14af9364d350e638954e056465bddc71f27455a4230e6ebc17"
)

$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $PSScriptRoot            # ...\phone-console\android-app
if (-not $Apk) { $Apk = Join-Path $proj "..\android\build\PhoneConsole-v2.3.apk" }
$Apk = [System.IO.Path]::GetFullPath($Apk)
if (-not (Test-Path $Apk)) { Write-Host "APK NOT FOUND: $Apk" -ForegroundColor Red; exit 2 }

# --- locate SDK: ANDROID_HOME / ANDROID_SDK_ROOT / local.properties ---
$sdk = $env:ANDROID_HOME
if (-not $sdk) { $sdk = $env:ANDROID_SDK_ROOT }
if (-not $sdk) {
    $lp = Join-Path $proj "local.properties"
    if (Test-Path $lp) {
        $line = (Get-Content $lp | Where-Object { $_ -match '^\s*sdk\.dir\s*=' } | Select-Object -First 1)
        if ($line) { $sdk = ($line -replace '^\s*sdk\.dir\s*=\s*', '') -replace '\\:', ':' -replace '\\\\', '\' }
    }
}
if (-not $sdk) { Write-Host "SDK not found (set ANDROID_HOME or local.properties)" -ForegroundColor Red; exit 2 }

$bt = Join-Path $sdk "build-tools\33.0.2"
foreach ($tool in @("aapt2.exe", "zipalign.exe", "apksigner.bat")) {
    if (-not (Test-Path (Join-Path $bt $tool))) { Write-Host "MISSING TOOL: $bt\$tool" -ForegroundColor Red; exit 2 }
}

$fail = 0
$size = (Get-Item $Apk).Length
Write-Host ("== APK: {0}" -f $Apk)
Write-Host ("== size: {0:N0} bytes ({1:N2} MiB)" -f $size, ($size / 1MB))
Write-Host ("== sha256: {0}" -f (Get-FileHash $Apk -Algorithm SHA256).Hash.ToLower())

Write-Host "`n== [1/3] aapt2 dump badging =="
& (Join-Path $bt "aapt2.exe") dump badging $Apk 2>&1 | Select-Object -First 4
$badging = & (Join-Path $bt "aapt2.exe") dump badging $Apk 2>&1
$pkg = ($badging | Select-String "package: name=" | Select-Object -First 1).Line
if ($pkg -notmatch "name='com\.home\.phoneconsole'") { Write-Host "PACKAGE MISMATCH" -ForegroundColor Red; $fail++ }
if ($pkg -match "versionCode='(\d+)'") {
    $vc = [int]$Matches[1]
    Write-Host ("== versionCode = {0} (must be >= 13): {1}" -f $vc, $(if ($vc -ge 13) { "OK" } else { "FAIL" }))
    if ($vc -lt 13) { $fail++ }
} else { Write-Host "versionCode NOT FOUND" -ForegroundColor Red; $fail++ }

Write-Host "`n== [2/3] apksigner verify --print-certs =="
$certs = & (Join-Path $bt "apksigner.bat") verify --print-certs $Apk 2>&1
$certs | Select-String "certificate (DN|SHA-256|SHA-1)" | ForEach-Object { $_.Line }
$sha = ($certs | Select-String "SHA-256 digest" | Select-Object -First 1).Line
if ($sha -match "([0-9a-f]{64})") {
    $actual = $Matches[1]
    if ($actual -eq $ExpectedSha256) { Write-Host "== certificate SHA-256: MATCH (same as old APK)" -ForegroundColor Green }
    else { Write-Host "== certificate SHA-256: MISMATCH -> $actual" -ForegroundColor Red; $fail++ }
} else { Write-Host "certificate SHA-256 NOT FOUND" -ForegroundColor Red; $fail++ }

$verbose = & (Join-Path $bt "apksigner.bat") verify --verbose $Apk 2>&1
$verbose | Select-String "Verified using v(1|2) scheme|Number of signers" | ForEach-Object { $_.Line.Trim() }
if (-not ($verbose -match "v1 scheme \(JAR signing\): true")) { Write-Host "v1 signature MISSING" -ForegroundColor Red; $fail++ }

Write-Host "`n== [3/3] zipalign -c -v 4 =="
& (Join-Path $bt "zipalign.exe") -c -v 4 $Apk *> $null
if ($LASTEXITCODE -eq 0) { Write-Host "zipalign: OK (4-byte aligned)" -ForegroundColor Green }
else { Write-Host "zipalign: FAILED (exit $LASTEXITCODE)" -ForegroundColor Red; $fail++ }

Write-Host ""
if ($fail -eq 0) { Write-Host "RESULT: ALL CHECKS PASSED" -ForegroundColor Green; exit 0 }
Write-Host "RESULT: $fail CHECK(S) FAILED" -ForegroundColor Red
exit 1

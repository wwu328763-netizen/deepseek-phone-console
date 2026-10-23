# One-shot: build -> verify -> publish (web distribution + archive + app-version.json)
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File android-app\scripts\build-and-publish.ps1
$ErrorActionPreference = 'Stop'
$app = Split-Path -Parent $PSScriptRoot          # android-app
$pkg = Split-Path -Parent $app                   # phone-console
$jdk = 'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\.jdk17\jdk-17.0.20+8'
$sdk = 'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\.android-sdk'
$bt = Join-Path $sdk 'build-tools\33.0.2'
$localGradle = Join-Path $sdk '_gradle_unzip\gradle-8.2.1\bin\gradle.bat'

$env:JAVA_HOME = $jdk
$env:ANDROID_HOME = $sdk
$env:ANDROID_SDK_ROOT = $sdk
# keep the Gradle cache out of the user profile (same place the original build used)
if (-not $env:GRADLE_USER_HOME) { $env:GRADLE_USER_HOME = Join-Path $env:TEMP 'pc-gradle-home' }
$env:Path = (Join-Path $jdk 'bin') + ';' + $bt + ';' + $env:Path

$gradle = if (Test-Path $localGradle) { $localGradle } else { Join-Path $app 'gradlew.bat' }

Write-Host '[1/4] assembleRelease ...'
$sw = [Diagnostics.Stopwatch]::StartNew()
Push-Location $app
try {
  & $gradle :app:assembleRelease --no-daemon --console=plain
  if ($LASTEXITCODE -ne 0) { throw 'gradle build failed' }
} finally { Pop-Location }
Write-Host ('      done in ' + [math]::Round($sw.Elapsed.TotalSeconds, 0) + ' s')

$apk = Get-ChildItem (Join-Path $app 'app\build\outputs\apk\release') -Filter '*.apk' | Select-Object -First 1
if (-not $apk) { throw 'no apk produced' }
Write-Host ('[2/4] apk: ' + $apk.FullName + ' (' + [math]::Round($apk.Length / 1KB, 1) + ' KB)')

Write-Host '[3/4] verify ...'
$badge = (& (Join-Path $bt 'aapt2.exe') dump badging $apk.FullName 2>&1 | Select-String 'package:').ToString()
$certLine = ((& (Join-Path $bt 'apksigner.bat') verify --print-certs $apk.FullName 2>&1) | Select-String 'SHA-256').ToString()
$align = ((& (Join-Path $bt 'zipalign.exe') -c -v 4 $apk.FullName 2>&1) | Select-Object -Last 1)
Write-Host ('      ' + $badge.Trim())
Write-Host ('      ' + $certLine.Trim())
Write-Host ('      zipalign: ' + $align)

$expected = 'fdc19571dfaf7a14af9364d350e638954e056465bddc71f27455a4230e6ebc17'
if ($certLine -notmatch $expected) { throw 'signer cert mismatch - would break overwrite install' }
if ($align -notmatch 'succe') { throw 'zipalign check failed' }

$code = [regex]::Match($badge, "versionCode='(\d+)'").Groups[1].Value
$name = [regex]::Match($badge, "versionName='([^']+)'").Groups[1].Value

Write-Host '[4/4] publish ...'
$targets = @(
  (Join-Path $pkg 'web\phone-console.apk'),
  (Join-Path $pkg ('android\build\PhoneConsole-v' + $name + '.apk'))
)
foreach ($t in $targets) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $t) | Out-Null
  Copy-Item $apk.FullName $t -Force
  Write-Host ('      -> ' + $t)
}
$verFile = Join-Path $pkg 'web\app-version.json'
$json = @{
  versionCode = [int]$code
  versionName = $name
  url = '/phone-console.apk'
  notes = '新图标（深色砖 + 薄荷绿 >_，自适应图标）+ 适配 Android 13 主题图标；体积 ~870KB'
} | ConvertTo-Json -Depth 3
[System.IO.File]::WriteAllText($verFile, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host ('      app-version.json -> ' + $name + ' / ' + $code + ' (no BOM)')
Write-Host 'ALL OK'

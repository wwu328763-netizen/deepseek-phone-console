# One-shot: build -> verify -> publish (web distribution + archive + app-version.json)
#
# 用法:
#   powershell -NoProfile -ExecutionPolicy Bypass -File android-app\scripts\build-and-publish.ps1
#
# 环境要求（任选一种方式提供）:
#   JDK 17      : 设置 $env:JAVA_HOME，或把 jdk 放在 phone-console\.jdk17\ 下
#   Android SDK : 设置 $env:ANDROID_HOME / $env:ANDROID_SDK_ROOT，
#                 或放在 phone-console\.android-sdk\，或默认 %LOCALAPPDATA%\Android\Sdk
#   签名(可选)  : 环境变量 CONSOLE_KEYSTORE / CONSOLE_STORE_PASSWORD / CONSOLE_KEY_ALIAS / CONSOLE_KEY_PASSWORD
#                 未提供时构建**不签名**（仅供本地调试，不能覆盖安装已发布 APK）
#
param(
    [string]$Notes = '',
    [string]$ExpectedCert = $env:CONSOLE_EXPECTED_CERT
)
$ErrorActionPreference = 'Stop'
$app = Split-Path -Parent $PSScriptRoot          # android-app
$pkg = Split-Path -Parent $app                   # phone-console

function First-Existing([string[]]$paths) {
    foreach ($p in $paths) {
        if ($p -and (Test-Path $p)) { return (Resolve-Path $p).Path }
    }
    return $null
}

# ---------------------------------------------------------------- JDK 17
$jdk = $env:JAVA_HOME
if (-not $jdk -or -not (Test-Path (Join-Path $jdk 'bin\javac.exe'))) {
    $jdk = First-Existing @(
        (Join-Path $pkg '.jdk17\jdk-17.0.20+8'),
        (Join-Path (Split-Path $pkg -Parent) '.jdk17\jdk-17.0.20+8'),
        (Join-Path $env:ProgramFiles 'Java\jdk-17'),
        (Join-Path $env:ProgramFiles 'Eclipse Adoptium\jdk-17*')
    )
}
if (-not $jdk) {
    throw '找不到 JDK 17：请安装 JDK 17 并设置 JAVA_HOME（或把 JDK 放到 phone-console\.jdk17\ 下）'
}
$env:JAVA_HOME = $jdk

# ---------------------------------------------------------------- Android SDK
$sdk = $env:ANDROID_HOME
if (-not $sdk) { $sdk = $env:ANDROID_SDK_ROOT }
if (-not $sdk -or -not (Test-Path $sdk)) {
    $sdk = First-Existing @(
        (Join-Path $pkg '.android-sdk'),
        (Join-Path (Split-Path $pkg -Parent) '.android-sdk'),
        (Join-Path $env:LOCALAPPDATA 'Android\Sdk')
    )
}
if (-not $sdk) {
    throw '找不到 Android SDK：请安装 SDK 并设置 ANDROID_HOME（或放到 phone-console\.android-sdk\）'
}
$env:ANDROID_HOME = $sdk
$env:ANDROID_SDK_ROOT = $sdk

# Gradle 需要 local.properties 里的 sdk.dir（反斜杠要转义）
$localProps = Join-Path $app 'local.properties'
$sdkEscaped = $sdk -replace '\\', '\\'
[System.IO.File]::WriteAllText($localProps, "sdk.dir=$sdkEscaped`n", (New-Object System.Text.UTF8Encoding($false)))

# build-tools: 优先 33.0.2，没有就用最新的
$btRoot = Join-Path $sdk 'build-tools'
if (-not (Test-Path $btRoot)) { throw "Android SDK 缺少 build-tools 目录：$btRoot" }
$bt = Join-Path $btRoot '33.0.2'
if (-not (Test-Path $bt)) {
    $bt = Get-ChildItem $btRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1 -ExpandProperty FullName
    Write-Host ("      build-tools 33.0.2 不存在，改用 " + (Split-Path $bt -Leaf))
}

# keep the Gradle cache out of the user profile
if (-not $env:GRADLE_USER_HOME) { $env:GRADLE_USER_HOME = Join-Path $env:TEMP 'pc-gradle-home' }
$env:Path = (Join-Path $jdk 'bin') + ';' + $bt + ';' + $env:Path

# gradle：优先仓库自带 wrapper，其次本机解压版
# gradle：优先本机已解压的发行版（避免 wrapper 联网下载），否则用 gradlew
$cachedGradle = First-Existing @(
    (Join-Path $sdk '_gradle_unzip\gradle-8.2.1\bin\gradle.bat')
)
$gradle = $cachedGradle
if (-not $gradle) { $gradle = Join-Path $app 'gradlew.bat' }
if (-not (Test-Path $gradle)) { throw '找不到 gradlew.bat 或本地 gradle' }

Write-Host '[1/4] assembleRelease ...'
$sw = [Diagnostics.Stopwatch]::StartNew()
Push-Location $app
try {
    & $gradle :app:assembleRelease --no-daemon --console=plain
    if ($LASTEXITCODE -ne 0) { throw 'gradle build failed' }
} finally { Pop-Location }
Write-Host ('      done in ' + [math]::Round($sw.Elapsed.TotalSeconds, 0) + ' s')

$apk = Get-ChildItem (Join-Path $app 'app\build\outputs\apk\release') -Filter '*.apk' -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $apk) { throw 'no apk produced' }
Write-Host ('[2/4] apk: ' + $apk.FullName + ' (' + [math]::Round($apk.Length / 1KB, 1) + ' KB)')

Write-Host '[3/4] verify ...'
$badge = (& (Join-Path $bt 'aapt2.exe') dump badging $apk.FullName 2>&1 | Select-String 'package:').ToString()
Write-Host ('      ' + $badge.Trim())
$signed = $false
try {
    $certLine = ((& (Join-Path $bt 'apksigner.bat') verify --print-certs $apk.FullName 2>&1) | Select-String 'SHA-256') | Select-Object -First 1
    if ($certLine) {
        $signed = $true
        Write-Host ('      ' + $certLine.ToString().Trim())
        if ($ExpectedCert -and ($certLine.ToString() -notmatch [regex]::Escape($ExpectedCert))) {
            throw '签名证书与 CONSOLE_EXPECTED_CERT 不一致（会导致无法覆盖安装）'
        }
    }
} catch {
    if ($ExpectedCert) { throw }
}
if (-not $signed) {
    Write-Host '      [warn] APK 未签名（未提供 keystore）—— 仅供本地调试，不能覆盖已发布版本' -ForegroundColor Yellow
}
$align = ((& (Join-Path $bt 'zipalign.exe') -c -v 4 $apk.FullName 2>&1) | Select-Object -Last 1)
Write-Host ('      zipalign: ' + $align)

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
if (-not $Notes) { $Notes = '修复与优化（详见仓库 CHANGELOG / Release 说明）' }
$verFile = Join-Path $pkg 'web\app-version.json'
$json = @{
    versionCode = [int]$code
    versionName = $name
    url = '/phone-console.apk'
    notes = $Notes
} | ConvertTo-Json -Depth 3
[System.IO.File]::WriteAllText($verFile, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host ('      app-version.json -> ' + $name + ' / ' + $code + ' (no BOM)')
Write-Host 'ALL OK'

# 构建与发布

## 环境

- Windows 10/11
- Python 3.11+（本仓库用 `colorama`、`qrcode`、`Pillow`；面板额外需要 `pywebview`）
- Node.js 20+（只构建前端时需要）
- 构建 APK：JDK 17 + Android SDK（compileSdk 33、build-tools 33.0.2）+ Gradle 8.2

```powershell
pip install -r requirements.txt
```

## 1. 前端（手机端 UI）

```powershell
powershell -ExecutionPolicy Bypass -File webapp/build.ps1
# 产物：web/app/app.js、app.css、index.html
```

## 2. 桌面面板

```powershell
powershell -ExecutionPolicy Bypass -File panel/build.ps1
# 产物：ConsolePanel.exe（需要 pyinstaller + pywebview）
```

## 3. Android APK

1. 准备自己的签名密钥（**不要用仓库里的，也不要提交 keystore**）：

```powershell
keytool -genkeypair -keystore android\console.keystore -alias mykey `
  -keyalg RSA -keysize 2048 -validity 36500 -storepass 你的密码 -keypass 你的密码 `
  -dname "CN=PhoneConsole, OU=Dev, O=Home, L=CN, S=CN, C=CN"
```

2. `android-app/app/build.gradle.kts` 的 `signingConfigs` 默认读 `../android/console.keystore`，
   可用环境变量覆盖：`CONSOLE_KS_PASS`、`CONSOLE_KEY_PASS`、`CONSOLE_KEY_ALIAS`；
   没有密钥文件时会跳过签名（产出 unsigned APK，仅供调试）。

3. 构建 + 校验 + 发布：

```powershell
powershell -ExecutionPolicy Bypass -File android-app/scripts/build-and-publish.ps1
# assembleRelease → aapt2 badging → apksigner 校验 → zipalign
# 复制到 web/phone-console.apk 与 android/build/PhoneConsole-v<ver>.apk
# 写入 web/app-version.json（App 内更新检查用）
```

4. Android SDK / JDK 路径在 `android-app/local.properties`（**不提交**）和脚本变量里配置。

## 4. 隧道

`console_core.start_tunnel()` 使用 Cloudflare Quick Tunnel；
需要 `cloudflared.exe` 在程序目录（或 PATH）：

```powershell
powershell -File tools/fetch-cloudflared.ps1
```

临时域名每次重启都会变，手机端可用「扫码 / 粘贴地址」重新连接。

## 版本策略

- `appVersionCode` 每次发布 +1，`appVersionName` 语义版本
- 前端资源版本：`web/sw.js` 里 `CACHE = "phone-console-v<N>"`，每次前端发布 +1
- 发布后更新 `web/app-version.json`（App 更新提示读取它）

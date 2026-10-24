# 构建与发布

本仓库包含三块产物：手机前端（网页）、桌面面板（exe）、Android APK。

## 环境

- **Windows 10/11**（面板依赖 WebView2；脚本为 PowerShell）
- Python 3.11+（`colorama`、`qrcode`、`Pillow`；面板额外需要 `pywebview`）
- Node.js 20+（只构建前端时需要）
- 构建 APK：JDK 17 + Android SDK（compileSdk 33）+ Gradle 8.2

```powershell
pip install -r requirements.txt
```

## 1. 前端（手机端 UI）

```powershell
cd webapp
npm install          # 安装 typescript / esbuild / preact
npm run build        # 等价于 powershell -File build.ps1

# 产物：web/app/app.js、web/app/app.css、web/app/index.html
```

**离线构建**（没有 npm/网络）：把工具链放到 `webapp\_tools\`：

```
webapp\_tools\pkg_typescript\package\      # npm 的 typescript 包
webapp\_tools\pkg_esbuild\package\         # npm 的 esbuild 包（含 esbuild.exe）
webapp\_tools\pkg_preact\package\          # npm 的 preact 包
```

`build.ps1` 会优先用 `node_modules`，找不到再回退到 `_tools`。
Node 不在 PATH 时可用环境变量 `NODE_EXE` 指定 `node.exe` 路径。

> 改了 `webapp/src/styles.css` 或 `app.tsx` 后要重新构建；`web/sw.js` 里的
> `CACHE = "phone-console-vNN"` 记得 +1，否则手机端会继续用旧缓存。

## 2. 桌面面板

```powershell
pip install pywebview pyinstaller
powershell -ExecutionPolicy Bypass -File panel/build.ps1
# 产物：ConsolePanel.exe（图标取自 console.ico，前端在 panel/webui/）
```

## 3. Android APK

一键脚本（自动构建 → 校验签名/对齐 → 发布到 `web/phone-console.apk` 与 `android/build/`）：

```powershell
powershell -File android-app/scripts/build-and-publish.ps1 -Notes "本次更新说明"
```

脚本会用以下顺序找工具链：

| 工具 | 查找顺序 |
| --- | --- |
| JDK 17 | `$env:JAVA_HOME` → `<repo>\.jdk17` → `<repo 上级>\.jdk17` → `Program Files\Java\jdk-17` |
| Android SDK | `$env:ANDROID_HOME` → `<repo>\.android-sdk` → `%LOCALAPPDATA%\Android\Sdk` |
| Gradle | 本地已解压发行版 → `android-app\gradlew.bat` |
| 签名 | `CONSOLE_KEYSTORE` / `CONSOLE_STORE_PASSWORD` / `CONSOLE_KEY_ALIAS` / `CONSOLE_KEY_PASSWORD` |

- **没有 keystore 也能构建**：产出未签名 APK，并打印黄色警告（仅供本地调试）
- 想强制校验签名一致性，设置 `CONSOLE_EXPECTED_CERT=<SHA-256>`（或 `-ExpectedCert`）
- 脚本会写 `android-app/local.properties`（`sdk.dir`），该文件已在 `.gitignore`

自己生成签名：

```powershell
keytool -genkeypair -keystore android\console.keystore -alias phoneconsole `
  -keyalg RSA -keysize 2048 -validity 36500 -storepass 你的密码 -keypass 你的密码 `
  -dname "CN=PhoneConsole, OU=Dev, O=Home, L=CN, S=CN, C=CN"
```

> ⚠️ 自己构建的 APK 与 Release 里的官方包**签名不同**，无法覆盖安装，只能卸载重装。

## 4. 版本号与发布

- APK：`android-app/app/build.gradle.kts` 里 `appVersionCode` 每次 +1，`appVersionName` 语义化
- 前端缓存：`web/sw.js` 的 `phone-console-vNN` 每次前端发布 +1
- 发布后更新 `web/app-version.json`（App「检查更新」读取它）
- 手机端界面是网页：**只改前端时不需要重打 APK**

## 5. 冒烟检查

```powershell
python -m py_compile server.py console_core.py dsh_client.py sessions.py panel/host.py
npx --prefix webapp tsc -p webapp/tsconfig.json --noEmit
```

仓库的 GitHub Actions（`.github/workflows/smoke.yml`）会跑：Python 语法、前端构建、
`app-version.json` 合法性、README 图片引用完整性、敏感文件检查。

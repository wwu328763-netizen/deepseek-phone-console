# 手机远程控制台 —— DSH 版（远程控制 DeepSeek Harness 智能体）

在电脑上跑一个本地 Web 服务，手机用浏览器打开网页，就能**远程控制电脑上的
DeepSeek Harness 智能体（DSH agent）**——发指令、实时看它的思考/工具调用/输出、
随时叫停、回答它向你提的问题，也可以续聊电脑端正在进行的任何会话。

> 本版由「手机远程控制 Codex」改造而来：后端从 Codex CLI 换成 DeepSeek Harness
> （就是你电脑端浏览器 GUI 用的那个 agent）。
> 注：老的 Codex 版回滚说明（`outputs\回滚说明.md`）在本机已经不存在，而且本仓库最早的
> 提交就已经是 DSH 版，所以 git 历史里没有 Codex 版可回滚——真要回退只能靠当时的备份。

## 图标 / 品牌

应用图标是"浅色机身的手机 + 深色屏幕里的绿色终端提示符 `>_`"：

- 文件：`web/icons/*`（PWA/浏览器）、`console.ico`（面板 exe / 桌面快捷方式）、
  `android-app/.../mipmap-xxxhdpi/ic_launcher.png`（APK）、`panel/webui/icon.png`（面板 rail）
- 说明与重新生成方式见 `docs/图标设计.md`
- 手机主屏的 PWA 图标被 Android 缓存，换图标后需**删掉旧图标重新添加**

## 手机端界面 v2（默认入口，TypeScript + Preact）

- **默认打开就是新版**：`/` 与 `/app` 都指向 `web/app/` 的构建产物；旧版微信风格界面在 **`/legacy`**
- 源码在 `webapp/`：TypeScript + Preact + esbuild，**不需要 npm**（tsc/preact/esbuild 已在 `_tools/`）
  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File webapp\build.ps1
  ```
- 已对齐：会话列表、流式聊天（SSE + 3 秒轮询兜底）、思考/工具折叠块、Markdown（含代码块与表格）、
  问答卡（`/api/answer`）、发送/停止/附件上传、设置（外观/模型与思考强度/余额与用量）、新会话（含工作目录浏览）
- v2.2 新增（2026-10-22）：聊天里的**图片缩略图**（点开看大图/下载）、输入栏选图即时预览与进度、
  **长按消息复制**、发送失败自动保留输入内容、翻旧消息时的**「回到底部 / 新消息 N」浮标**、
  **壁纸 + 聊天底色深浅**（走 `/api/bg`，与旧版共用同一张壁纸）
- 未迁移：全屏诊断浮层（仅旧版有，调试用）
- 详见 `webapp/README.md`

## WebView2 管理面板（新，2026-10）

电脑端管理界面除了原来的 Tk 窗口（`gui.pyw`），另有一个 WebView2 面板：

- 免 Python 运行：双击 **`ConsolePanel.exe`**（需系统 WebView2 运行时，Win10/11 自带）
- 源码运行：`python panel\host.py`
- 两者共用核心层 `console_core.py`（从 gui.pyw 抽出，不依赖 tkinter）
- 功能：运行状态 / 手机扫码 / 启停服务与隧道 / 用量统计（官网用量、命中率、环形图、趋势图、明细表）/
  Token 设置 / 导入官网用量 / 深浅主题
- 说明与打包：`panel/README.md`；迁移与自测记录：`docs/交付-WebView2面板.md`
- 旧 Tk 窗口保留可用，回滚只需继续双击 `gui.pyw`
## 它怎么工作

```
手机浏览器 ──> server.py (8787) ──HTTP/WS──> DeepSeek Harness
                    │                          （桌面端 DeepSeek Harness.exe，
                    │                            或网页端 dsh web --port 3080）
                    └── 每个手机任务 = 一个独立的 DSH 会话（cwd=任务目录）
```

- **手机任务**：每个任务在选定目录里建一个独立 DSH 会话，与其它任务/会话隔离；
  实时进度通过 harness 的 WebSocket 事件流（mux）推送到手机，翻译成聊天/工具/命令卡片。
- **电脑端对话**：列出电脑端 DSH 控制台的全部会话，可以点开续聊（向该会话发消息），
  包括你现在在浏览器 GUI 里开的那个会话——这就是「远程控制你」。
- **提问回答**：智能体用 ask_user_question 向你提问时，手机端会弹出问题卡片，选/填后回传，
  智能体继续干活。
- **停止**：随时叫停当前回合（= 向 harness 发 session.cancel）。
- 网页仍是单文件 `index.html`，无第三方前端依赖；Python 侧也全部标准库。

## 前置条件（重要）

1. 电脑上**正在运行 DeepSeek Harness**：推荐直接开**桌面端**程序（就是你平时用的那个
   `DeepSeek Harness.exe`）。它启动时自己挑一个空闲端口，本程序会**自动发现**这个端口，
   不用手工配置，也不用另外再跑一个 web 服务。
   - 也可以用**网页端**：`dsh web --port 3080`（找不到桌面端时会自动回退到这个地址）；
   - 想**优先**连某个地址（连不上时仍会自动去找别的 harness）：在 `console_data\settings.json`
     里加 `"dsh_url": "http://127.0.0.1:3080"`；
   - 想**硬指定**、连不上直接报错（不自动发现）：启动时加 `--dsh-url http://...`。
2. Windows + Python 3.11+（脚本会自动找 `~/.cache/codex-runtimes/.../python`）。
3. 建议以管理员身份运行（DSH 命令沙箱需要权限，与电脑端一致）。

> 桌面端和网页端用的是**同一套 API**：手机任务一样会落在 harness 的「手机任务」工作区，
> 能看的「电脑端对话」也一样。区别只是你从哪个程序去用它；桌面端关掉后控制台会连不上
> （启动横幅和日志里会写明"对接：桌面端 / 网页端"）。

## 快速开始

### 图形管理界面（推荐）

双击 `phone-console\manager.vbs`（或桌面快捷方式「手机远程控制台」）：
- **启动（服务+隧道）**：一键启动后台服务并建公网隧道，窗口显示 PIN、局域网/隧道地址和二维码；
- 手机扫码或输地址 + PIN 即可用。

### 一键启动（命令行）

1. 确认 DSH 控制台已在运行（上面「前置条件」第 1 条）。
2. 双击 `start-all.bat`（自动请求管理员权限）：
   启动控制台 → 显示 `==== PIN: xxxx ====` → 建立公网隧道 → 显示 `https://xxx.trycloudflare.com`。
3. 手机在任何网络打开隧道地址，输入 PIN 即可。**关掉这个窗口 = 全部停止。**

启动窗口会显示：
```
本机访问:   http://127.0.0.1:8787
局域网访问: http://192.168.x.x:8787
PIN: xxxx（8 位数字）
```

PIN 同时保存在 `phone-console\console_data\pin.txt`。

## 安卓 APK（可选，手机上更省事）

把手机端页面包成一个壳 APK，从桌面图标直接打开，不用每次开浏览器。**改界面/功能不用重装 APK**——
网页内容由控制台实时提供，APK 里只有壳。

- **安装**：手机浏览器打开 `http://<电脑IP>:8787/phone-console.apk` 下载安装
  （首次要允许「安装未知来源应用」）。也可以在电脑上直接用这个文件：
  `android\build\PhoneConsole-v1.2.apk`。手机若连不上电脑的局域网地址（例如电脑在
  CGNAT/热点网络下），就改用管理界面显示的**隧道地址**下载：
  `https://<隧道域名>/phone-console.apk`。
- **首次打开**：点「**扫码识别二维码**」拍一下桌面端显示的二维码，地址和 PIN 会自动填好
  （没装相机 App 时会退回从相册选图）；或点「**扫描局域网**」自动找电脑（手机和电脑要在同一个
  Wi-Fi）；也可以手动填地址（只填 IP 也行，会自动补 `http://` 和 `:8787`）再填 PIN。
  地址以后可随时在 App 里改。
- **关于扫码**：解码用 **ZXing core 3.5.3**（`android\libs\zxing-core-3.5.3.jar`，离线内置、
  不发网络请求），通过「系统相机拍照 → App 内解码」实现，所以**不需要 CAMERA 权限**：
  拍照交给系统相机 App（`ACTION_IMAGE_CAPTURE`），照片经 `QrImageProvider`（`cache/qr/`）
  写回 App，再用 `RGBLuminanceSource` + `HybridBinarizer` 解码。
  没装相机 App 时自动退回「从相册选图」。若扫码不灵，仍可用「扫描局域网」或「从剪贴板粘贴」。
- **自更新**：App 里「检查更新」→ 读 `<控制台地址>/app-version.json`，若 `versionCode` 更大就下载
  `/phone-console.apk` 并调起系统安装（需允许安装未知来源）。
  发新版本：改 `android\` 里的代码 → 跑 `android\build.ps1` → 把新 APK 覆盖到 `web\phone-console.apk`，
  同时把 `web\app-version.json` 的 `versionCode` 加一。
- **签名**：`android\console.keystore`（别名 `qqmeow`，口令 `qqmeow123`）。**升级必须用同一把钥匙**，
  否则手机会拒绝覆盖安装——这个文件别删、别重新生成。

## 手机端能做什么

- **界面（微信风格）**：对话区做成微信那样 —— 浅灰底、自己的消息是绿色气泡、智能体是白色气泡，
  都带尖角和左右头像；时间/系统提示是居中的小灰字；工具、命令、思考、提问都是白底卡片。
  顶栏、输入栏、状态条同步改成浅色；侧栏、设置弹窗、登录页仍保持原来的深色。
- **新建任务**：选择工作目录（可浏览文件夹、新建子文件夹）、填名称和第一条指令；
  新建的手机任务会**归入 harness 的「手机任务」工作区**（不再是"未分组"）——
  harness 只承认在 workspaceId 下创建的会话（`workspaceId` 与 `cwd` 只能二选一），
  所以会话 cwd 就是该工作区目录（默认 `--workdir-root/手机任务`，没有会自动创建），
  若在对话框里另选了别的目录，会写进首条指令告诉智能体；
- **多轮对话**：随时追加指令（同一 DSH 会话，上下文连续）；
- **实时进度**：流式显示智能体的思考（可折叠）、回复、工具调用（参数/结果）、命令执行（输出）；
- **回答提问**：智能体用 ask_user_question 提问时，出现问题卡片，可选/可自定义填写；
- **停止**：运行中可随时叫停（输入框右边的按键在运行中会变成红色方块 ■，点它就是停止，
  空闲时是绿色发送 ➤，这样一个按键顶两个，输入栏不挤）；
- **任务历史**：关掉网页、重启服务后任务和会话还在（DSH 会话保存在 harness 里）；
- **删除对话**：删除本地任务记录（DSH 会话本身保留在电脑端 harness 里）；
- **上传文件**：📎 上传图片/PPT/PDF/Word/Excel/文本（单文件最大 50MB），图片会随消息一起发送，
  其它文件提示智能体读取（存在任务目录 `.uploads`）；
- **电脑端对话**：侧栏切到「电脑端对话」，列出 DSH 控制台全部会话（含当前 GUI 会话），
  点开即可实时查看/继续该会话；
- **输入栏下方的状态条**：一行小字实时显示这段对话的 **轮数/步数 · 输出速度 tok/s · 累计 token ·
  缓存命中率**，以及 **余额 · 官网消费 · 本对话估算消费 · 官网均价（元/亿 token）**；
  点一下直接打开设置看详细用量（数据来自 harness 的 sessionStats / tokenUsage 投影 + 官网导出的
  cost.json 与用量 CSV；本对话消费按官网均价估算）；
- **Token 余额与充值**：设置里看 DeepSeek 余额（官方接口）与官网用量；余额旁边有「充值」按钮，
  余额不足 10 元时按钮变金色并提示，点它会在手机浏览器里打开 DeepSeek 官方充值页；
- **切换模型与思考强度**：设置里是两个**下拉式菜单** —— 点开选模型（DeepSeek-V41-Flash / V4-Flash /
  V4-Pro / V4-Flash-Vision-Exp）或思考强度（关闭/低/高/最高），**选完立即生效**，不用再点应用按钮；
  换模型时会自动把强度切到该模型的默认档；手机任务和电脑端对话都能切（走 harness 的 `session/selectModel`）；
- **全屏（隐藏浏览器界面）**：顶栏 `⛶` 一键进真全屏（再点退出），设置里还能开「打开时自动全屏」；
  iPhone 的 Safari 不支持网页全屏，点 `⛶` 会提示「添加到主屏幕」，从桌面图标打开即无浏览器界面；
- **PWA**：可添加到主屏幕当 App 用。

## 想在外网用？

- **方式一（默认）**：管理界面点「启动（服务+隧道）」，自带 Cloudflare 临时隧道，**不需要注册任何账号**。
  二维码与地址每 10 秒自动刷新，隧道掉线会**自动重连**；代价是临时地址**每次重连都会变** ——
  手机端不用记地址，扫一下桌面二维码即可（地址也写在 `console_data\phone-address.txt`）。
- **方式二**：局域网直接 `http://<电脑IP>:8787`（手机和电脑连同一个 Wi-Fi 时最快、最稳）。
- **想要永不变化的外网地址**：需要额外服务，例如 Cloudflare 命名隧道（要自己的域名）或
  Tailscale Funnel（要账号并在管理台授权一次）。程序已内置对 **Tailscale 网卡地址**的识别：
  装上并登录后，管理界面会自动把它的 `100.x` 固定地址排到最前（手机端要装 Tailscale 才能用）。

## 安全须知

- 监听 `0.0.0.0:8787`，任何能连到你电脑的人都会看到登录页，但必须输 PIN（8 位数字，
  防爆破限速：同一 IP 连续错 10 次锁 15 分钟）。不要把 PIN 发给别人。
- 局域网明文 HTTP 仅供可信网络；外网务必走带 HTTPS 的隧道。
- 手机端相当于你在操作这台电脑上的智能体（危险权限），只在自己信任的设备上用，
  离开时建议停掉服务。

## 常用参数（`run.ps1` 后面可加）

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--port 8787` | Web 端口 | 8787 |
| `--pin xxxx` | 指定 PIN | 自动生成保存 |
| `--workdir-root 路径` | 允许浏览/执行的工作目录根 | `Documents\Codex` |
| `--dsh-url http://...` | DSH 地址（默认自动发现，桌面端优先） | 自动发现 |
| `--dsh-wait 40` | 启动时等待 harness 出现的秒数（0=不等） | `40` |
| `--agent-preset standard` | 手机任务会话的 agent 预设 | standard |

例：`powershell -File run.ps1 --dsh-url http://127.0.0.1:3080`

## 目录结构

```
phone-console\
├─ server.py          # 主服务（HTTP + DSH bridge + 事件翻译）
├─ dsh_client.py      # DSH API 客户端（HTTP RPC + 桌面端目标发现，标准库）
├─ sessions.py        # DSH 事件 → 显示条目翻译 + 官网用量解析
├─ gui.pyw            # 电脑端图形管理界面
├─ web/
│  ├─ index.html      # 手机端控制台页面（单文件）
│  └─ phone-console.apk / app-version.json   # 安卓壳 APK 与更新信息（见「安卓 APK」）
├─ tests/
│  └─ phone-ui-test.mjs    # 端到端测试（真实 Chrome：全屏布局 + 输入栏 + 发送/停止）
├─ android-app/       # 安卓壳 APK 工程（Gradle 8.2.1 + AGP 8.2.2 + Kotlin，现代标准布局）
├─ console_data/      # PIN、任务记录、背景设置、日志、phone-address.txt（当前手机地址）
├─ cloudflared.exe    # 公网隧道工具
├─ README.md
└─ start-all.bat / start-console.bat / start-tunnel.bat / stop-all.bat
   manager.bat + manager.vbs   # 图形管理界面（双击即开）
```

### 文件命名对照（打包时统一改成 ASCII 名）

带中文名的文件以前被 ANSI 工具写坏过（`管理界面.vbs` 里的路径变成了 `???????`，
双击完全没反应）。所以这一版把文件名都改成了 ASCII：

| 原名字 | 现在的名字 |
|---|---|
| `手机远程控制台\`（根目录） | `phone-console\` |
| `一键启动.bat` | `start-all.bat` |
| `启动控制台.bat` | `start-console.bat` |
| `启动隧道.bat` | `start-tunnel.bat` |
| `停止服务.bat` | `stop-all.bat` |
| `管理界面.bat` / `管理界面.vbs` | `manager.bat` / `manager.vbs` |
| `测试\手机端界面测试.mjs` | `tests\phone-ui-test.mjs` |
| `console_data\手机地址.txt` | `console_data\phone-address.txt` |

`manager.vbs` 现在**按自身所在目录**定位 `gui.pyw`（不再写死绝对路径），
所以整个文件夹随便挪位置都不会失效；文件内容也刻意只用 ASCII，避免再被编码问题弄坏。

## 常见问题

- **启动提示"未找到可用的 DeepSeek Harness"**：先把**桌面端** DeepSeek Harness 打开（推荐），
  或运行 `dsh web --port 3080`，然后重开本服务。启动顺序无所谓：服务会等最多 40 秒。
- **看不到 PIN？** 启动窗口单独显示 `PIN: xxxx`，也在 `phone-console\console_data\pin.txt`。
- **手机打不开页面？** 同 Wi-Fi；防火墙放行 8787（第一次启动会弹窗，勾选专用网络）。
- **手机页面变成乱码 / 空白？** 说明 `web/index.html` 的编码被改坏了（见下方「开发注意」）。
  先确认文件是干净 UTF-8，再在手机上刷新；必要时清一次浏览器缓存或重新添加到主屏幕。
- **想回滚到 Codex 版？** 本机已经没有那个回滚说明/脚本，git 历史里也没有 Codex 版
  （最早的提交 `ddaac02` 就是 DSH 版）——需要回退只能用当时另外的备份。

## 开发注意（编码，踩过坑）

- **不要用 Windows PowerShell 的 `Get-Content` / `Set-Content` 直接改 `web/index.html`**：
  这个环境的 PowerShell 默认按本机 ANSI（GBK）读文件，会把 UTF-8 中文整篇写成乱码，
  手机打开就是乱码/白屏。**本项目被这样弄坏过一次，已从 git 恢复。**
- 改文件请用 UTF-8 编辑工具；必须脚本化时显式指定编码，例如：
  ```powershell
  $p = "web\index.html"
  $t = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8)
  $t = $t.Replace("v15", "v16")
  [System.IO.File]::WriteAllText($p, $t, (New-Object System.Text.UTF8Encoding($false)))
  ```
- 改完自检（正常应输出 `OK 手机远程控制台`，否则说明编码坏了）：
  ```powershell
  $t = [System.IO.File]::ReadAllText("web\index.html", [System.Text.Encoding]::UTF8)
  $title = [regex]::Match($t, '<title>(.*?)</title>').Groups[1].Value
  if ($title -eq "手机远程控制台") { "OK $title" } else { "编码可能坏了：$title" }
  ```


- **改这几个 `.ps1` 时别把 UTF-8 BOM 去掉**：`.bat` 里是用 Windows PowerShell 5.1 跑的
  （`powershell -File xxx.ps1`），它读**无 BOM** 的文件会按本机 ANSI 解码，`Write-Host` 里的
  中文会全部变成乱码（实测：无 BOM 乱码，有 BOM 正常输出「控制台服务未在运行。」）。
  反过来 `.bat` / `.vbs` **必须没有** BOM，否则 cmd / WSH 会读坏第一行。

## 改造说明（v2 = DSH 版）

- 新增 `dsh_client.py`：纯标准库的 harness HTTP RPC + RFC 6455 WebSocket 客户端；
- `server.py` 重写驱动层：手机任务 = DSH 会话，实时事件走 mux WebSocket，
  统一翻译成显示条目（user/agent/reasoning/tool/command/question/status…）；
- 移除 codex/relay/phone_home 依赖；保留 PIN、背景图、官网用量、文件浏览等功能；
- 手机端 index.html 改为统一的条目流渲染（SSE），支持流式思考/回复、工具卡片、提问卡片。

## APK 构建（Gradle 版，推荐）

手机端壳 APK 现在有两条构建路径：

- **Gradle + Kotlin（标准工程）**：`android-app\`，一条命令完成构建 + 校验 + 发布
  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File android-app\scripts\build-and-publish.ps1
  ```
  产物：`web\phone-console.apk`、`android\build\PhoneConsole-v{版本}.apk`，
  并自动更新 `web\app-version.json`（无 BOM）。详见 `android-app\README-构建.md`。
- **旧手写管线（保留回滚）**：`android\build.ps1`（aapt2 → javac → d8 → 对齐 → 签名，纯离线）。

两者共用同一 keystore（`android\console.keystore`，别名 qqmeow），签名证书一致，可互相覆盖安装。

## 手机端 v2.6（2026-10-23）

- **修复启动闪退**：`MainActivity.loadConsole()` 仍在调用已删除顶栏的 `titleView.setText()` → NPE。已加空判断，并新增崩溃落盘（`files/last-crash.txt`）与连接页崩溃摘要。
- **扫码预览不再拉伸**：预览比例改为按"实际给相机的 displayOrientation"判定（手机竖持时屏幕旋转=0、但预览要转 90°，旧逻辑按屏幕旋转判断导致 SurfaceView 按横向摆放），并把适配方式从留黑边（min）改成居中裁切铺满（max）。
- **连接页重做**（深色高级 UI）：
  - 深色渐变背景 + 卡片化布局 + 薄荷绿主按钮（渐变/水波纹）+ 聚焦时输入框描边高亮
  - 分组小标题、最近使用深色 chip、折叠式"怎么连接？"说明
  - 逻辑优化：首启自动扫描局域网；检测剪贴板里的地址并提示；保留扫码/局域网/粘贴三种入口
- **图标统一**：APK 自适应图标、PWA 图标、电脑面板 exe 与桌面快捷方式全部使用同一枚「深色砖 + 薄荷绿 >_」图标；面板 exe 已用新 `console.ico` 重新打包，快捷方式已重建并清图标缓存。
- 版本：`versionCode 18` / `versionName 2.6`（签名证书不变，可覆盖安装）

## v3.0.0（2026-10-23）新版本基线

从这一版开始版本号重新起算：ersionName 3.0.0 / ersionCode 100，
之后每次发版 versionCode +1、versionName 语义化递增（3.0.1、3.1.0…）。

- **图标**：回到电脑端旧版图标（深色圆角砖 + 白色机身 + 薄荷绿 >_），APK / PWA / 面板 exe / 快捷方式全部统一
- **连接页**：改为黑白 + DeepSeek 蓝（#4D6BFE），与对话页同一套配色；新增「启动时先显示登录页」开关
- **修 404**：手机在 session 里发消息走 /api/sessions/{id}/send，服务端只有 continue → 404。已加 send → continue 别名
- **文件发送卡死**：上传 XHR 增加 60s 超时（超时给出明确提示，不再无限等待）
- **充值入口**：v2「设置 → 用量与余额」增加「去充值」（platform.deepseek.com/top_up）与「更换地址 / 重新登录」
- **过渡动画**：进入控制台 WebView 淡入、页面加载完成内容再淡入；连接页白底浅色状态栏
- **登录跳过**：默认仍是连过就直进（体验优先）；需要每次登录时在连接页勾选「启动时先显示登录页」

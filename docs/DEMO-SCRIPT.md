# 实操录制脚本（给 Codex / 录屏工具）

本文件是「产品发布会视频」的录制说明书：项目在哪、怎么起、录什么、**技术怎么实现**。
配套文档：`dist/手机远程控制台-产品发布会.docx`（口播稿在附录 A，录制分镜在附录 B）。

---

## 1. 项目位置

| 项 | 值 |
| --- | --- |
| 本地路径 | `C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console` |
| 仓库 | https://github.com/wwu328763-netizen/deepseek-phone-console |
| APK | `dist/` 或 Release `v3.2.1`（`phone-console-v3.2.1.apk`） |
| 发布会文档 | `dist/手机远程控制台-产品发布会.docx` / `.pdf` |
| 截图素材 | `screenshots/`（与仓库 README 同一套） |
| 前端源码 | `webapp/`（Preact + TS）→ 产物 `web/app/` |
| 电脑面板 | `ConsolePanel.exe`（源码 `panel/`） |

## 2. 录制前准备（Windows）

```powershell
cd C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console

# 1) 依赖（首次）
pip install -r requirements.txt

# 2) 确认 DSH 已启动并登录（桌面端或 dsh web）

# 3) 启动控制台：服务 + 隧道
powershell -ExecutionPolicy Bypass -File run.ps1

# 4) 启动桌面面板（录制电脑端画面用）
.\ConsolePanel.exe
```

- 面板会显示「手机访问地址 + 二维码」，录制前把 PIN / 隧道地址打码（或用局域网地址）
- 手机端：同 Wi-Fi 打开 `http://<内网IP>:8787`，或装 APK 扫码
- 手机投屏建议：`scrcpy --max-size 1080 --max-fps 60`（或系统自带投屏）

## 3. 录制参数

| 项 | 建议 |
| --- | --- |
| 分辨率 | 1920×1080（电脑端）；手机画面竖屏画中画 |
| 帧率 | 60 fps |
| 编码 | H.264 / yuv420p / AAC 192k |
| 时长 | 2:30 ± 15s |
| 字幕 | 可选，按口播稿断句 |

---

## 4. 技术实现（录制前先看懂这一节）

### 4.1 一句话架构

```
手机（网页 / APK WebView）
   │  HTTP + SSE，X-Console-Pin 鉴权
   ▼
本机服务 server.py :8787 ── 会话/发送/上传/模型/用量/计划
   │  DSH JSON-RPC（session/*）
   ▼
DSH 主体（桌面端或网页端，:7101）── agent / 工具 / 上下文
```

四层接口：

| 层 | 接口 | 干什么 |
| --- | --- | --- |
| ① 对外 HTTP | `/api/*`（:8787，`X-Console-Pin`） | 会话、发送、上传、停止、模型、用量、归档、文件；SSE 推送 |
| ② 面板桥 | `window.pywebview.api.*` | 启停服务/隧道、二维码、日志、官网用量 |
| ③ 手机壳桥 | `window.PhoneConsole.*` | 注入 PIN、扫码/换地址、返回登录、版本检查 |
| ④ DSH RPC | `session/*`（JSON-RPC） | `list` / `page` / `prompt` / `cancel` / `rename` / `modelCatalog` / `selectModel` |

### 4.2 关键文件地图

| 文件 | 作用 |
| --- | --- |
| `server.py`（~2100 行） | 唯一后端：`Console`（会话池）、`ThreadState`（每会话状态）、`Handler`（HTTP 路由 + SSE + CORS） |
| `console_core.py` | 纯逻辑：配置、PIN、隧道（cloudflared）、DSH 连接探测、面板用的状态快照 |
| `panel/host.py` + `panel/webui/` | pywebview + WebView2 面板；`Api` 类只做转发和线程包装 |
| `webapp/src/{app.tsx,store.ts,api.ts,styles.css}` | 手机前端（Preact + TS） |
| `web/app/` | 前端构建产物（`app.js` / `app.css`），由 `webapp/build.ps1` 生成 |
| `web/sw.js` | Service Worker 缓存（当前 `phone-console-v71`） |
| `android-app/app/src/main/java/com/home/phoneconsole/` | `MainActivity`（WebView + 桥）、`SetupActivity`（扫码/输入/局域网扫描）、`Prefs`、`ScannerActivity` |
| `android-app/scripts/build-and-publish.ps1` | 找 JDK/SDK → 构建 → 验签 → 落盘 + 发布 |
| `.github/workflows/smoke.yml` | CI：py_compile、前端真构建、资源与敏感文件检查 |

### 4.3 会话镜像（手机任务 = DSH 真会话）

- `create_thread` 时把工作目录 `cwd` 设为任务目录；`Console` 把每个手机会话和 DSH 的 `dsh_session_id` 绑定
- 发消息走 DSH RPC `session/prompt`（带 `sessionId`），不是转发到别的服务
- 列表/历史走 `session/list`、`session/page`，`ThreadState` 缓存最近一页并做增量合并
- 所以电脑端和手机端看到的是**同一个会话、同一份上下文**，不是镜像副本

### 4.4 消息与事件流

```
手机 POST /api/threads/{id}/send
  → 服务端拆附件、归一化文本
  → DSH session/prompt
  → DSH 事件（assistant/tool/plan/status…）
  → 服务端 SSE 推给手机 & 面板
  → 前端按 kind 渲染（user / assistant / tool / plan / status）
```

- `normalize_user_items()`：剥掉 `[图片]`、`[附带文件]` 这类标记，把附件还原成 `attachments/images/files`
- `stream` 断线重连：手机侧用 `EventSource`，服务端保持 `last_event_id`

### 4.5 忙时发送：一个按钮的三种语义

| 手势/状态 | 行为 |
| --- | --- |
| 空闲 + 点击 | 正常发送 |
| 繁忙 + 输入框为空 + 点击 | **停止**当前回合（`session/cancel`） |
| 繁忙 + 有文字 + 点击 | **排队**（进 `pending_ops`） |
| 繁忙 + 有文字 + 长按 | **立即插入**（插队到队首，下一轮就发） |
| 排队条上 | 取消 / 插队（↑） / 铅笔重新编辑（内容取回输入框） |

实现：`server.py` 的 `pending_ops` 队列 + `_trim_pending_ops()`；前端 `store.ts` 维护 `queue`，`app.tsx` 的 `QueueChips` 渲染；"插队"= 把该项移到数组首位（服务端对应 `insert` 操作）。回合结束（`turn_done`）后服务端自动 drain 下一条。

### 4.6 图片 / 文件链路

```
选图 → POST /api/threads/{id}/upload（multipart）
  → 落盘到该会话工作区 .uploads/
  → 发送时：server 把图片变成 markdown 内联链接
  → DSH 侧 agent 用 READ_IMAGE 读图
  → 回传 user 消息时归一化：剥标记、还原真附件
  → 手机显示缩略图，电脑端聊天里直接显示
```

- `/api/raw?path=…&pin=…` 提供带鉴权的原图/缩略图读取（`_authorized()` 同时接受 header 和 query，方便 `<img>`）
- 图片用 `<img>` 直出，不做 base64（避免长消息和内存膨胀）

### 4.7 计划 / 目标镜像

- 数据来源：DSH 会话的 todo/plan 状态 + 长期 goal
- 服务端在会话详情里附带 `plan { todos, goal, active }`
- 手机端 `PlanBar` 常驻输入框上方：`进度 x/N`、当前步骤、可折叠；有 goal 时标题直接显示目标
- 面板命令 `plan:toggle` 不发网络请求，前端本地折叠状态存 `PLAN_OPEN_KEY`
- 计划模式（`/plan`）**不在手机上开放**：DSH 未暴露对应 RPC，实测把 `/plan` 当文本发过去无效

### 4.8 模型与强度

- 模型列表：DSH `session/modelCatalog`；切换：`session/selectModel`
- 强度（effort）：`high / medium / low`，随会话保存，前端输入栏第二行显示 `模型 · 强度`
- 弹窗入口：输入栏第二行 + 斜杠命令「模型」

### 4.9 用量与计费

```
/api/usage（本机 SSR/JSON）  ← 汇总 DSH 累计 token
/api/balance（官网余额）     ← api.deepseek.com/user/balance
官网平台用量 CSV              ← platform.deepseek.com usage/export（zip→csv，按 UTC 天）
        ↓
面板「用量」页：命中率 / 命中 / 未命中 / 输出 / 金额 + 环形图 + 每日折线 + 明细表
手机「用量与计费」：余额、官方 token、按天消耗
```

- 金额按 `cost-*.csv` 的 `utc_date + cost` 聚合，缓存到 `console_data/usage/`
- 面板图表支持 Ctrl+滚轮缩放、Alt+滚轮平移；每块卡片显示该区间花费

### 4.10 鉴权与隧道

- 所有 `/api/*` 校验 `X-Console-Pin`（200ms 内失败即 401）；`/api/raw` 额外接受 `?pin=`
- PIN 存在 `console_data/pin.txt`，可重新生成；二维码内容 = `https://<隧道>/?pin=<PIN>`
- 隧道：`cloudflared tunnel --url http://127.0.0.1:8787`（Quick Tunnel，**地址每次重启都变**，Error 1033 就是地址失效）
- 面板/服务会列 `lan_ips`，优先局域网；C-GNAT（100.64/10，如 Tailscale）会被标记

### 4.11 前端构建与缓存

- `webapp/build.ps1`：`tsc --noEmit` 类型检查 → esbuild 打包到 `web/app/`
- 每次发版把 `web/sw.js` 的 `CACHE` 版本号 +1（当前 `v71`），避免旧缓存
- `web/app-version.json`：APK 版本/下载地址/更新说明，App 启动时读它检查更新

### 4.12 Android 壳

- `MainActivity`：全屏 WebView 加载 `consoleUrl()`；原生 JS 桥 `window.PhoneConsole`（`toSettings()` / `logout()` / `savePin()` 等）
- `SetupActivity`：**扫码连接** / 手动地址+PIN / 扫描局域网 / 剪贴板 / 历史地址；「保存并连接」
- 3.2.1 的登录 UX：登录页有「扫码登录 / 更换地址」；退出或连接失败直接回原生扫码页
- 错误页（云隧 1033）由 `MainActivity` 用 `loadDataWithBaseURL` 渲染，按钮走 JS 桥

### 4.13 面板

- pywebview + WebView2，`panel/host.py` 的 `Api` 是唯一桥接面：`snap / start / stop / tunnel / qr / usage / logs / official_*`
- 四个页：状态、用量、日志、关于；`panel/webui/` 是纯静态 HTML/CSS/JS
- `panel/build.ps1` 用 PyInstaller 打成 `ConsolePanel.exe`（WebView2 由系统运行时提供）

### 4.14 构建、发布、CI

- APK：`android-app/scripts/build-and-publish.ps1`（JDK/SDK 自动探测 → `assembleRelease` → apksigner 校验 → 复制到 `web/` + `android/build/`）
- 发布：GitHub Release 上传 `phone-console-vX.Y.Z.apk`；`web/app-version.json` 同步版本
- CI（`.github/workflows/smoke.yml`）：`py_compile`（含 `panel/host.py`）、`npm install + webapp/build.ps1`、README 图片引用检查、敏感文件检查

---

## 5. 分镜脚本（10 个镜头）

| # | 时长 | 画面 | 操作 | 对应旁白 | 可讲的技术点 |
|---|---|---|---|---|---|
| 1 | 10s | 封面 + 图标 | 静态推进 | 开场 | — |
| 2 | 12s | DSH 正在跑 | 展示会话在动 | 问题 | 会话就在本机跑 |
| 3 | 10s | 手机 → 控制台 | 扫码 / 输 PIN | 转折 | PIN + 隧道/局域网 |
| 4 | 15s | 面板状态页 | 点「启动」，服务/隧道变绿 | 电脑端 | pywebview 桥 → console_core |
| 5 | 18s | 手机聊天 | 发一条，展示回复 | 手机端 | prompt → SSE → 渲染 |
| 6 | 15s | 计划条 | 让 DSH 生成计划，看 0/N 变化 | 计划 | plan 字段镜像 |
| 7 | 20s | 排队 → 插队 → 重编辑 | 长回答中发第二条，点铅笔改 | 忙时 | pending_ops 状态机 |
| 8 | 15s | 接口演示 | `curl /api/info`（可选） | 技术 | 四层接口 |
| 9 | 20s | 面板用量页 | 金额、命中率、Ctrl/Alt+滚轮 | 数字 | usage 聚合 |
| 10 | 15s | 收尾 | 仓库地址 + 标语 | 边界 / 收尾 | 开源 MIT |

## 6. 打码与安全（必须）

- 录制前隐藏：PIN、隧道地址、内网 IP、`console_data` 目录内容
- 桌面面板：用仓库同款打码方式，或用局域网地址并后期模糊
- 不要在画面里出现 `pin.txt`、`*.keystore`、`console_data/usage/*.csv`
- 发布前检查：录屏字幕里不能出现 `pin=`

## 7. 交付物

1. `phone-console-demo-1080p60.mp4`（H.264，约 2:30）
2. `phone-console-demo-cover.png`（封面帧）
3. `phone-console-demo.srt`（可选字幕，按口播稿）
4. 核对表：8 个界面（登录、聊天、侧栏、计划、命令菜单、排队、用量、面板）全部出现

## 8. 验收清单

- [ ] 时长 2:15–2:45
- [ ] 开头 3 秒内出现产品名
- [ ] 手机端 8 个界面至少出现 6 个
- [ ] 面板「启动 → 运行中 → 隧道已连接」有可见变化
- [ ] 画面无 PIN / 隧道地址 / 内网 IP
- [ ] 结尾出现仓库地址与「让智能体跟着你走」

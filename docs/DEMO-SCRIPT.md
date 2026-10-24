# 实操录制脚本（给 Codex / 录屏工具）

本文件是「产品发布会视频」的录制说明书：项目在哪、怎么起、录什么、怎么验收。
配套文档：`dist/手机远程控制台-产品发布会.docx`（含口播稿，第 17 页）。

---

## 1. 项目位置

| 项 | 值 |
| --- | --- |
| 本地路径 | `C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console` |
| 仓库 | https://github.com/wwu328763-netizen/deepseek-phone-console |
| APK | `dist/手机远程控制台-v3.2.0.apk`（或 Release 下载） |
| 发布会文档 | `dist/手机远程控制台-产品发布会.docx` / `.pdf` |
| 截图素材 | `screenshots/`（与仓库 README 同一套） |
| 前端源码 | `webapp/`（Preact + TS），产物 `web/app/` |
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

- 面板会显示「手机访问地址 + 二维码」，录制前**先把 PIN / 隧道地址打码**（或用干净环境：局域网地址）
- 手机端：同 Wi-Fi 打开 `http://<内网IP>:8787`，或装 APK 扫码
- 手机投屏建议：`scrcpy --max-size 1080 --max-fps 60`（或系统自带投屏）

## 3. 录制参数

| 项 | 建议 |
| --- | --- |
| 分辨率 | 1920×1080（电脑端）；手机画面 1080×2340 竖屏画中画 |
| 帧率 | 60 fps |
| 编码 | H.264 / yuv420p / AAC 192k |
| 时长 | 2:30 ± 15s（对应口播稿 12 段） |
| 字幕 | 可选，按口播稿断句 |

## 4. 分镜脚本（10 个镜头）

| # | 时长 | 画面 | 操作 | 对应旁白（文档第 17 页） |
|---|---|---|---|---|
| 1 | 10s | 封面图 + 图标 | 静态，缓慢推进 | 开场 |
| 2 | 12s | 电脑桌面 / DSH 正在跑 | 展示 DSH 会话在动 | 问题 |
| 3 | 10s | 手机锁屏 → 打开控制台 | 输入 PIN / 扫码 | 转折 |
| 4 | 15s | 电脑端面板「状态」页 | 点「启动」，展示服务/隧道变绿 | 电脑端 |
| 5 | 18s | 手机聊天页 | 发一条消息，展示回复 | 手机端 |
| 6 | 15s | 输入框上方计划条 | 让 DSH 生成计划，展示 0/N 进度变化 | 计划 |
| 7 | 20s | 繁忙时排队 → 插队 → 重新编辑 | 长回答中发第二条 → 排队 → 点铅笔改 | 忙时 |
| 8 | 15s | 命令行/接口演示 | 用 curl 调 `/api/info`（可选，展示底座） | 技术 |
| 9 | 20s | 面板「用量」页 | 展示金额、命中率、Ctrl/Alt+滚轮缩放 | 数字 |
| 10 | 15s | 封面收尾 + 仓库地址 | 静态 + 标语 | 边界 / 收尾 |

## 5. 打码与安全（必须）

- 录制前隐藏：PIN、隧道地址、内网 IP、`console_data` 目录内容
- 桌面面板：用仓库 `screenshots/00-电脑端面板.png` 同款打码方式，或用局域网地址并后期模糊
- 不要在画面里出现 `pin.txt`、`*.keystore`、`console_data/usage/*.csv`
- 发布前检查：`grep -i "pin=" 你的录屏字幕` 不应命中

## 6. 交付物

1. `phone-console-demo-1080p60.mp4`（H.264，约 2:30）
2. `phone-console-demo-cover.png`（封面帧，可用文档第 1 页）
3. `phone-console-demo.srt`（可选字幕，按口播稿）
4. 核对表：8 个界面（登录、聊天、侧栏、计划、命令菜单、排队、用量、面板）全部出现

## 7. 验收清单

- [ ] 时长 2:15–2:45
- [ ] 开头 3 秒内出现产品名
- [ ] 手机端 8 个界面至少出现 6 个
- [ ] 面板「启动 → 运行中 → 隧道已连接」有可见变化
- [ ] 画面无 PIN / 隧道地址 / 内网 IP
- [ ] 结尾出现仓库地址与「让智能体跟着你走」

# 参与贡献

感谢你愿意改进 **DeepSeek Phone Console**！这个项目是「DSH 的遥控器」，
代码量不大，但踩过的坑不少，欢迎提 issue / PR。

## 先看这些

- 使用/安装问题 → 先读 [README 常见问题](README.md#常见问题)
- 安全相关问题 → 读 [docs/SECURITY.md](docs/SECURITY.md)，**不要公开贴 PIN / 内网地址 / 隧道地址**
- 想改 DSH 对接逻辑 → 先读 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## 报告问题

请用 [Bug 报告模板](.github/ISSUE_TEMPLATE/bug_report.md)，并尽量附上：

- 手机端截图 / 电脑端面板截图（**遮掉 PIN**）
- 版本：APK `3.2.0 (120)`、前端 SW `vXX`（设置 → 关于 / 诊断信息）
- 日志：`console_data/server.err.log` 尾部、`console_data/panel.log` 尾部
- 复现步骤：点哪里 → 期望什么 → 实际什么

## 提交代码

1. Fork + 新建分支：`fix/queue-edit`、`feat/xxx`
2. 改动范围尽量小，一个 PR 只做一件事
3. 提交前自测：
   - `python -m py_compile server.py console_core.py dsh_client.py sessions.py`
   - 前端：`powershell -File webapp/build.ps1`（需 Node 20+，脚本会用 `webapp/_tools` 里的 tsc/esbuild）
   - 动 APK/原生：`powershell -File android-app/scripts/build-and-publish.ps1`
4. PR 描述里写：**改了什么、为什么、怎么验证的**

## 代码约定

- Python：标准库优先，不引第三方依赖（除 requirements.txt 里那几个）
- 前端：Preact + TypeScript，样式写在 `webapp/src/styles.css`，不要引 UI 框架
- 所有面向用户的中文文案保持一致（简体、口语化、不堆术语）
- 服务端新增接口 → 同步更新 `docs/API.md`
- 涉及 DSH 行为变化 → 在 PR 里说明验证方式（哪条会话、什么现象）

## 不要提交

`console_data/`、`*.keystore`、`local.properties`、`.env`、任何带 PIN/Token 的截图或日志。
仓库的 `.gitignore` 已覆盖，但请注意 `git add -A` 前检查一遍 `git status`。

# 安全须知

## 凭据

| 文件 | 内容 | 是否提交 |
| --- | --- | --- |
| `console_data/pin.txt` | 访问 PIN | ❌ 不提交 |
| `console.keystore` | APK 签名私钥 | ❌ **绝对不要提交** |
| `console_data/natapp-disabled.txt` 等 | 运行状态 | ❌ 不提交 |
| `console_data/usage/*.csv` | 用量数据 | ❌ 不提交 |

仓库里的 `.gitignore` 已排除这些路径；发布前建议再跑一次：

```powershell
git grep -nE "4792ec|pin=|keystore|token" -- "*.py" "*.ps1" "*.kts"
```

## 暴露面

- 服务默认 `0.0.0.0:8787`，局域网可直接访问；公网仅通过隧道临时域名
- 所有 `/api/*` 需要 PIN（错误按 IP 限速）
- `/api/raw` 支持 `?pin=`：这是给聊天里的 markdown 图片用的，**PIN 会出现在对话文本里**。
  介意的话可以只在内网使用，或发完图后重置 PIN
- 文件读写限制在允许根（`--workdir-root` + DSH 工作区 + 手机任务工作区）

## 建议

- 只在需要时开隧道，用完 `stop-all.bat`
- 定期更换 PIN（面板「重新生成 PIN」）
- 不要把带 PIN 的截图/聊天直接发公开渠道

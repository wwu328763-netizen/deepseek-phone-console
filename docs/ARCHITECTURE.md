# 架构说明

## 组件

| 组件 | 技术 | 职责 |
| --- | --- | --- |
| `server.py` | Python `ThreadingHTTPServer` | HTTP API、静态页面、SSE、附件落盘、附件归一化 |
| `console_core.py` | Python | 进程编排：启停服务、Cloudflare 隧道、PIN、地址发现 |
| `dsh_client.py` | Python + urllib | DSH JSON-RPC（`session/*`）客户端、凭据发现 |
| `sessions.py` | Python | 会话数据模型、官网用量 CSV 解析 |
| `panel/` | pywebview + WebView2 | 桌面窗口：二维码、状态、日志、启停 |
| `webapp/` | Preact + TypeScript | 手机端 UI（构建到 `web/app/`） |
| `web/` | 静态产物 | 页面、Service Worker、PWA 清单、APK |
| `android-app/` | Kotlin + WebView | APK 壳：加载远端页面、文件选择、设置页、更新 |

## 数据流

```
手机 UI ──(X-Console-Pin)──► server.py ──► dsh_client ──► DSH :8314
   ▲                            │
   │                            ├─ 附件写入 <会话工作区>/.uploads/
   └──── SSE / 轮询快照 ◄───────┤
                                └─ console_data/
                                     ├─ pin.txt
                                     ├─ threads/<id>/meta.json
                                     ├─ archived.json
                                     └─ usage/*.csv
```

## 关键设计

1. **同一会话镜像**：手机任务会在电脑端 DSH 里创建真实会话（`cwd` = 任务目录），
   因此三端看到的是同一段对话，附件也落在同一工作区。
2. **附件归一化**：DSH 回传的 user 文本会带 `[图片]/[附带文件]` 标记（给 agent 读路径用），
   服务端在返回快照前把标记还原成 `attachments`，同时给出干净的 `displayText`。
3. **电脑端图片渲染**：给 DSH 的文本里附 markdown 内联图片（`/api/raw?pin=`），
   电脑端聊天直接显示图片；手机端解析时剥掉 markdown、用自己的缩略图组件。
4. **忙时排队**：`/send` 返回 `409` 即视为入队；队列在 turn 结束时由前端补发，
   单按钮语义：空 = 停止、有字 = 排队、长按 = 立即插入。
5. **权限边界**：所有 `/api/*` 走 `check_pin`（带 IP 限速）；文件访问限制在允许根内。

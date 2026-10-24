# HTTP 接口文档

服务默认监听 `0.0.0.0:8787`。除 `/api/login`、`/api/raw`（可带 `?pin=`）外，
所有 `/api/*` 都需要请求头：

```http
X-Console-Pin: <PIN>
```

错误统一返回 JSON：`{"error": "..."}`，HTTP 状态码见各接口。

---

## 认证

### POST /api/login

```json
{"pin": "12345678"}
```

- `200 {"ok": true}`：PIN 正确
- `401 {"error": "wrong pin"}`：PIN 错误（按 IP 限速，连续错误会短暂锁定）

---

## 服务信息

### GET /api/info

返回本机访问地址、隧道地址、DSH 连接状态、会话摘要等。

```json
{
  "version": 2,
  "port": 8787,
  "lan_ips": ["192.168.1.20"],
  "dsh_url": "http://127.0.0.1:8314",
  "dsh_connected": true,
  "pin": "12345678",
  "tunnel_url": "https://xxx.trycloudflare.com",
  "threads": [{ "id": "a1b2c3d4", "name": "任务名", "workdir": "C:\\...", "running": false }]
}
```

---

## 手机任务（threads）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/threads` | 列表 `{"threads": [...]}` |
| POST | `/api/threads` | 新建 `{"name": "...", "workdir": "...", "prompt": "..."}` |
| GET | `/api/threads/{id}` | 详情（含 items） |
| POST | `/api/threads/{id}/send` | 发消息 |
| POST | `/api/threads/{id}/upload` | 上传附件 |
| POST | `/api/threads/{id}/stop` | 停止当前回答 |
| POST | `/api/threads/{id}/delete` | 删除 |

### POST /api/threads/{id}/send

```json
{
  "prompt": "帮我看下这个报错",
  "images": ["C:\\...\\.uploads\\a.png"],
  "files": ["C:\\...\\.uploads\\b.docx"]
}
```

- `200 {"ok": true}`
- `409 {"error": "thread is busy"}`：正在跑（客户端据此入队）

### POST /api/threads/{id}/upload

请求体 = 原始字节；请求头：

```http
X-Filename: <URL 编码的文件名>
Content-Type: application/octet-stream
```

返回：

```json
{"name": "b.docx", "path": "...\\<会话工作区>\\.uploads\\b.docx", "size": 215368, "mediaType": null}
```

> 附件会落到**该会话自己的工作目录**下的 `.uploads/`。

---

## 电脑端会话（sessions）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/sessions` | 列表（已按电脑端归档过滤） |
| GET | `/api/sessions/{id}` | 详情（items 已做附件归一化） |
| GET | `/api/sessions/{id}/stream` | SSE 实时流 |
| POST | `/api/sessions/{id}/send`（或 `/continue`） | 继续对话 |
| POST | `/api/sessions/{id}/upload` | 上传附件 |
| POST | `/api/sessions/{id}/stop` | 停止 |

Send 请求体与 threads 相同，忙时同样返回 `409`。

---

## 模型与强度

### GET /api/models?kind=session&id=xxx

```json
{
  "current": {"provider": "deepseek", "model": "...", "reasoningEffort": "high"},
  "models": [{"id": "...", "name": "...", "provider": "deepseek", "reasoningEfforts": [{"id": "low", "name": "低"}]}]
}
```

### POST /api/model

```json
{"kind": "session", "id": "...", "provider": "deepseek", "model": "...", "reasoningEffort": "high"}
```

---

## 用量与计费

### GET /api/usage

```json
{
  "total": {"turns": 12},
  "per_thread": [{"id": "a1b2c3d4", "name": "任务", "turns": 5}],
  "official": {
    "hit": 4647030912, "miss": 37821046, "output": 17172425,
    "requests": 17699, "hit_rate": 99.19,
    "days": ["2026-08-05", "..."],
    "per_day": {"2026-08-05": {"hit": 1, "miss": 2, "output": 3, "requests": 4}}
  }
}
```

### GET /api/balance

```json
{"is_available": true, "balance_infos": [{"currency": "CNY", "total_balance": "10.79", "topped_up_balance": "10.79"}]}
```

---

## 文件

### GET /api/raw?path=<绝对路径>

返回文件字节，`Content-Type` 按扩展名推断。

- 支持 `&pin=<PIN>` 查询参数（给 markdown 内联图片用，`<img>` 无法带请求头）
- 403：PIN 错误 / 路径不在允许根内
- 404：文件不存在

### GET /api/files?path=<目录>

列出目录内容（允许根：`--workdir-root`、DSH 已注册工作区、手机任务工作区）。

### POST /api/fs/mkdir

```json
{"path": "C:\\...\\新目录"}
```

---

## 归档

### GET /api/archived

```json
{"thread": ["id1"], "session": ["id2"]}
```

### POST /api/archive

```json
{"kind": "thread", "id": "a1b2c3d4", "archived": true}
```

> 电脑端（DSH）的归档名单来自 `workspace.json` 的 `archivedSessionIds`，服务端已过滤，不会出现在手机侧栏。

---

## 其他

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/settings` | 面板配置（背景/主题等） |
| POST | `/api/settings` | 保存配置 |
| GET | `/api/bg` / POST `/api/bg` | 聊天壁纸 |
| POST | `/api/answer` | 回答 DSH 的提问卡片 |
| GET | `/app-version.json` | App 更新检查（versionCode/versionName/url） |
| GET | `/phone-console.apk` | 下载当前 APK |

---

## 客户端约定

- 忙时 `409` → 入队；队列在 `running` 由 true→false 时自动补发
- 附件上传用 XHR（浏览器无法取上传进度之外的流式进度），超时 120s
- SSE 断线重连：`/api/sessions/{id}/stream`，事件类型 `session.snapshot` / `session.item` / `session.item_update`


---

## 桌面面板桥（pywebview）

面板网页通过 `window.pywebview.api.*` 调用 Python（`panel/host.py` 的 `Api` 类）：

| 方法 | 说明 |
| --- | --- |
| `log` / `ui_log` | 追加面板日志 |
| `start_all` / `stop_all` | 启动/停止 服务 + 隧道 |
| `start_tunnel_only` / `restart_tunnel` | 只操作隧道 |
| `snap` / `poll` | 当前状态快照 / 轮询 |
| `qr_svg` | 手机访问地址的二维码 SVG |
| `open_phone_page` / `copy_access_url` / `save_phone_address` | 地址相关操作 |
| `open_data_dir` | 打开 console_data |
| `usage(rng, from, to)` | 用量数据（区间） |
| `usage_pull` / `usage_import` | 拉取官网 / 导入 CSV |
| `usage_token_state` / `usage_set_token` / `usage_clear_token` | 平台 Token 管理 |
| `usage_clipboard` / `open_topup` | 剪贴板导入 / 充值页 |

## Android 壳桥（WebView JS）

网页调用 `window.PhoneConsole.*`：

| 方法 | 说明 |
| --- | --- |
| `pin()` | 读取保存的 PIN |
| `toSettings()` | 打开原生扫码/改地址页 |
| `logout()` | 清 PIN 并强制显示登录页 |
| `reload()` | 重新加载控制台 |
| `appVersion()` | 壳版本，如 `3.2.0 (120)` |
| `checkUpdate()` | 检查 `/app-version.json` |
| `setTheme('dark'\|'light')` | 状态栏/导航栏跟随网页主题 |
| `showMenuBridge()` | 原生菜单（已基本弃用） |

## 会话详情新增字段

`GET /api/sessions/{id}`、`GET /api/threads/{id}` 额外返回：

```json
{
  "plan": {
    "todos": [{"content": "…", "status": "pending|in_progress|completed"}],
    "goal": {"objective": "长期目标", "id": "goal-…", "revision": 1},
    "active": false
  }
}
```

手机端在输入框上方渲染为可折叠的「计划 / 目标」条；`plan` 每 3 秒随快照刷新。

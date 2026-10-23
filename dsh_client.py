"""Minimal client for the DeepSeek Harness (DSH) HTTP API (stdlib only).

新版 DSH（2026-09 起）的 Web API：
  * 鉴权：会话签名 cookie。签名密钥存在 $DSH_HOME/.credentials.yaml 的
    `client-connection/browser-session` 记录里；cookie 名为
    `dsh-auth-<base64url(sha256(authority))>`，值为
    `v1.<base64url(payload)>.<base64url(HMAC-SHA256(secret, body))>`。
  * 调用：POST /api/<namespace>/<verb>
      body: {"type":"client-request","rpcId":uuid,"method":"<namespace>/<verb>",
             "payload":{"args":{<参数名>:<值>}}}
      回复: {"type":"server-response","rpcId":...,"result":{"ok":true,"value":...}}
  * 事件：新版没有 WebSocket mux，改用分页/轮询 `session/page`
      args.request = {address:{kind:"session",sessionId}, throughSeq:<游标>, maxMessages?}
      → value.records = [{"type":"event","event":{type,seq,time,data}}, ...]
      游标（当前最大 seq）从 `session/list` 的 projections.asOfSeq 取。

Requires: Python 3.11+. No third-party packages.
"""

import base64
import csv
import hashlib
import hmac
import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

import urllib.request as _urllib_request
import urllib.error as _urllib_error


class DshError(Exception):
    """harness 返回错误结果或传输失败。"""


# --------------------------------------------------------------------------
# 凭证 / 会话 cookie
# --------------------------------------------------------------------------

def default_credentials_path():
    home = os.environ.get("DSH_HOME")
    if home:
        return Path(home) / ".credentials.yaml"
    return Path.home() / ".dsh" / ".credentials.yaml"


_STALE_HINTS = ("backup", ".old", "-old", "old-", "-bak", "_bak", "bak-", "副本", "备份")


def _looks_like_stale(p):
    """备份/副本目录里的凭证一定是过期密钥，用它签 cookie 只会 401。"""
    text = str(p).lower()
    return any(h in text for h in _STALE_HINTS)


def candidate_credentials():
    """按优先级列出候选凭证文件。

    从桌面快捷方式启动时子进程可能没有 DSH_HOME，所以多找几处。
    **顺序很关键**：标准位置（$DSH_HOME、~/.dsh）必须排在最前面，
    程序目录附近的 `*/.dsh-home/` 只能当兜底 —— 它曾经先匹配到
    `.upgrade-backup-*/` 里的过期密钥，签出的 cookie 被 harness 判 401，
    而正确的文件根本没被试过（表现为"harness 明明在跑却说连不上"）。
      1. 环境变量 DSH_CREDENTIALS（显式指定）
      2. $DSH_HOME/.credentials.yaml
      3. ~/.dsh/.credentials.yaml（标准位置）
      4. 程序目录附近 */.dsh-home/.credentials.yaml（启发式兜底，跳过备份目录）
    """
    seen = []

    def add(p):
        try:
            p = Path(p)
        except TypeError:
            return
        if p not in seen:
            seen.append(p)

    env_explicit = os.environ.get("DSH_CREDENTIALS")
    if env_explicit:
        add(env_explicit)
    home = os.environ.get("DSH_HOME")
    if home:
        add(Path(home) / ".credentials.yaml")
    add(Path.home() / ".dsh" / ".credentials.yaml")
    try:
        here = Path(__file__).resolve().parent
        patterns = (
            ".dsh-home/.credentials.yaml",
            "*/.dsh-home/.credentials.yaml",
            "*/*/.dsh-home/.credentials.yaml",
            "work/*/.dsh-home/.credentials.yaml",
            "work/*/*/.dsh-home/.credentials.yaml",
        )
        for root in (here, here.parent, here.parent.parent):
            if not root.is_dir():
                continue
            for pat in patterns:
                try:
                    hits = sorted(root.glob(pat))
                except OSError:
                    continue
                for hit in hits:
                    if _looks_like_stale(hit):
                        continue
                    add(hit)
    except OSError:
        pass
    add(Path.home() / ".dsh" / ".credentials.yaml")
    return seen


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def read_browser_secret(path=None):
    """读取 browser-session 的签名密钥（base64url 文本）。

    path 为 None 时按 candidate_credentials() 顺序逐个尝试，第一个命中即用。
    """
    for p in ([Path(path)] if path else candidate_credentials()):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(
            r"browser-session:\s*\n\s*kind:\s*grant\s*\n\s*payload:\s*\n\s*version:\s*(\d+)\s*\n\s*secret:\s*(\S+)",
            text)
        if m:
            return m.group(2)
    return None


def authority_of(base_url: str) -> str:
    """从 base_url 取 authority（host:port），cookie 名依赖它。"""
    s = base_url.split("://", 1)[1] if "://" in base_url else base_url
    return s.split("/", 1)[0]


def session_cookie(authority: str, secret_b64: str, ttl_seconds=86400):
    """生成 (cookie_name, cookie_value)。"""
    secret = _b64u_decode(secret_b64)
    now_ms = int(time.time() * 1000)
    payload = {"version": 1, "authority": authority,
               "issuedAt": now_ms, "expiresAt": now_ms + ttl_seconds * 1000}
    body = _b64u(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest()
    name = "dsh-auth-" + _b64u(hashlib.sha256(authority.encode("utf-8")).digest())
    return name, "v1." + body + "." + _b64u(sig)


# --------------------------------------------------------------------------
# RPC 客户端
# --------------------------------------------------------------------------

class DshRpc:
    """新版 harness HTTP RPC 客户端（自动附带会话 cookie）。"""

    def __init__(self, base_url="http://127.0.0.1:3080", timeout=25,
                 credentials_path=None, cookie_ttl=86400):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.credentials_path = credentials_path
        self.cookie_ttl = cookie_ttl
        self.authority = authority_of(self.base_url)
        self._cookie = None          # (expires_at_epoch, header_value)
        self._lock = threading.Lock()
        self._sessions_cache = None  # (timestamp, items)

    # -- auth ---------------------------------------------------------------

    def _cookie_header(self):
        with self._lock:
            now = time.time()
            if self._cookie and self._cookie[0] - 3600 > now:
                return self._cookie[1]
            secret = read_browser_secret(self.credentials_path)
            if not secret:
                self._cookie = None
                return None
            try:
                name, value = session_cookie(self.authority, secret, self.cookie_ttl)
            except Exception:
                return None
            header = name + "=" + value
            self._cookie = (now + self.cookie_ttl, header)
            return header

    def auth_status(self):
        """返回 (是否有密钥, cookie 是否可用)。"""
        secret = read_browser_secret(self.credentials_path)
        return bool(secret), bool(self._cookie_header())

    # -- transport ----------------------------------------------------------

    def call(self, endpoint, args=None, timeout=None):
        """endpoint 形如 "session/list"；args 为该端点的参数对象。"""
        rpc_id = str(uuid.uuid4())
        body = json.dumps({
            "type": "client-request",
            "rpcId": rpc_id,
            "method": endpoint,
            "payload": {"args": args or {}},
        }, ensure_ascii=False).encode("utf-8")
        req = _urllib_request.Request(self.base_url + "/api/" + endpoint,
                                      data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        cookie = self._cookie_header()
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with _urllib_request.urlopen(req, timeout=timeout or self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except _urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            raise DshError(f"HTTP {exc.code} for {endpoint}: {detail}") from exc
        except OSError as exc:
            raise DshError(f"cannot reach harness at {self.base_url}: {exc}") from exc
        result = data.get("result") or {}
        if not result.get("ok"):
            err = result.get("error") or {}
            raise DshError(f"{endpoint}: {err.get('message') or err.get('code') or 'unknown error'}")
        return result.get("value")

    # -- sessions -----------------------------------------------------------

    def list_sessions(self, cache_seconds=0.0):
        now = time.time()
        if (cache_seconds and self._sessions_cache
                and now - self._sessions_cache[0] < cache_seconds):
            return self._sessions_cache[1]
        value = self.call("session/list", {"_request": {}})
        items = (value or {}).get("items", []) if isinstance(value, dict) else []
        self._sessions_cache = (now, items)
        return items

    def create_session(self, cwd=None, workspace_id=None, agent_preset="standard"):
        request = {"agentPreset": agent_preset}
        if workspace_id:
            request["workspaceId"] = workspace_id
        elif cwd:
            request["cwd"] = cwd
        value = self.call("session/create", {"request": request})
        self._sessions_cache = None
        return (value or {}).get("sessionId")

    def prompt(self, session_id, text, mode="queue", image_parts=None):
        content = []
        if text:
            content.append({"type": "text", "text": text})
        for part in (image_parts or []):
            content.append(part)
        if not content:
            content.append({"type": "text", "text": "(empty)"})
        return self.call("session/prompt", {"request": {
            "requestId": str(uuid.uuid4()),
            "sessionId": session_id,
            "mode": mode,
            "content": content,
        }})

    def cancel(self, session_id):
        return self.call("session/cancel", {"request": {"sessionId": session_id}})

    def rename(self, session_id, title):
        return self.call("session/rename", {"request": {"sessionId": session_id, "title": title}})

    # -- 模型 / 思考强度 ---------------------------------------------------

    def model_catalog(self):
        """所有可用模型及其支持的思考强度（浏览器模型选择器用的那份数据）。"""
        return self.call("session/modelCatalog", {}, timeout=max(self.timeout, 60)) or {}

    def select_model(self, session_id, provider, model, reasoning_effort=None):
        """切换某个会话使用的模型 / 思考强度（对该会话后续的指令生效）。"""
        request = {"sessionId": session_id, "provider": provider, "model": model}
        if reasoning_effort:
            request["reasoningEffort"] = reasoning_effort
        return self.call("session/selectModel", {"request": request}, timeout=max(self.timeout, 60))

    def session_selection(self, session_id):
        """读某个会话当前的模型选择（None 表示该会话还没选过）。"""
        for item in self.list_sessions(cache_seconds=1.0):
            if item.get("sessionId") != session_id:
                continue
            values = (item.get("projections") or {}).get("values") or {}
            sel = values.get("modelSelection") or {}
            return sel.get("next") or sel.get("lastUsed")
        return None

    def session_ids_in_workspace(self, workspace_id):
        """某个工作区里的会话 id 列表（读 harness 落盘的 workspace.json）。"""
        for cred in candidate_credentials():
            p = Path(cred).parent / "storages" / "workspace.json"
            if not p.is_file():
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except (OSError, json.JSONDecodeError):
                continue
            tables = (data.get("tables") or {}).get("workspaces") or {}
            item = tables.get(workspace_id) or {}
            return [str(x) for x in (item.get("sessionIds") or [])]
        return []

    # -- 工作区（harness 侧的分组） ------------------------------------------

    def call_flex(self, method, payload):
        """有些 RPC 要包一层 request、有些不包，两种都试一次。"""
        try:
            return self.call(method, {"request": payload})
        except DshError as exc:
            text = str(exc)
            if "request" not in text and "unexpected" not in text:
                raise
            return self.call(method, payload)

    def workspace_create(self, path):
        """按目录建工作区，返回 workspaceId。"""
        value = self.call_flex("workspace/create", {"path": str(path)})
        return ((value or {}).get("workspace") or {}).get("workspaceId")

    def workspace_insert_session(self, workspace_id, session_id, before_session_id=None):
        """把某个会话放进工作区。"""
        payload = {"workspaceId": workspace_id, "sessionId": session_id}
        if before_session_id:
            payload["beforeSessionId"] = before_session_id
        return self.call_flex("workspace/insertSessionBefore", payload)

    def page(self, session_id, through_seq, max_messages=None, before_seq=None):
        """取会话事件（尾部）。返回 [{type,seq,time,data}, ...]。"""
        request = {"address": {"kind": "session", "sessionId": session_id},
                   "throughSeq": int(through_seq)}
        if before_seq is not None:
            request["beforeSeq"] = int(before_seq)
        if max_messages is not None:
            request["maxMessages"] = int(max_messages)
        value = self.call("session/page", {"request": request}, timeout=max(self.timeout, 90))
        records = (value or {}).get("records") or []
        out = []
        for rec in records:
            if isinstance(rec, dict) and rec.get("type") == "event":
                ev = rec.get("event")
                if isinstance(ev, dict):
                    out.append(ev)
        return out

    def refresh(self, session_id, after_seq=-1, max_messages=80):
        """增量刷新：返回 (seq > after_seq 的事件列表, 会话是否运行中)。"""
        sess = None
        for item in self.list_sessions(cache_seconds=1.0):
            if item.get("sessionId") == session_id:
                sess = item
                break
        if sess is None:
            return [], False
        proj = sess.get("projections") or {}
        cursor = proj.get("asOfSeq")
        running = bool(sess.get("running"))
        if not isinstance(cursor, int) or cursor < 0:
            return [], running
        if isinstance(after_seq, int) and cursor <= after_seq:
            # 游标没有前进：没有新事件，连 session/page 都不用发。
            # 观看者每 1.5 秒刷新一次，空闲会话因此少打一半 RPC。
            return [], running
        events = self.page(session_id, cursor, max_messages=max_messages)
        fresh = [e for e in events if isinstance(e.get("seq"), int) and e["seq"] > after_seq]
        fresh.sort(key=lambda e: e["seq"])
        return fresh, running

    def answer_question(self, session_id, call_id, answers):
        """回答 ask_user_question 的提问（harness 的 userQuestions/answer）。

        args 形状由 harness 的 typert 描述符决定：
        {agentId, callId, answer: {answers: [{id, selected: [...], custom?}]}}
        返回 harness 的布尔结果（false = 该提问已结束/已被回答）。
        """
        if not session_id or not call_id:
            raise DshError("userQuestions/answer: 缺少 sessionId 或 callId")
        return self.call("userQuestions/answer", {
            "agentId": session_id,
            "callId": call_id,
            "answer": {"answers": list(answers or [])},
        }, timeout=max(self.timeout, 60))


# --------------------------------------------------------------------------
# 兼容占位：新版没有 WebSocket mux
# --------------------------------------------------------------------------

class DshMux:  # pragma: no cover - 保留类名避免旧引用报错
    """新版 harness 不再提供 WebSocket mux；实时性由轮询 session/page 提供。"""

    def __init__(self, *args, **kwargs):
        self.on_frame = kwargs.get("on_frame") or (lambda frame, rpc_id=None: None)

    def start(self):
        raise DshError("WebSocket mux 在新版 harness 中已移除，请使用轮询（session/page）")

    def close(self):
        pass


# --------------------------------------------------------------------------
# 图片内容片段
# --------------------------------------------------------------------------

def image_part(path, media_type=None):
    """构造 session/prompt 的图片内容片段（base64 data）。"""
    if media_type is None:
        ext = os.path.splitext(path)[1].lower()
        media_type = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif",
        }.get(ext, "image/png")
    with open(path, "rb") as fh:
        data = base64.b64encode(fh.read()).decode("ascii")
    return {"type": "image", "mediaType": media_type, "data": data,
            "name": os.path.basename(path)}


# --------------------------------------------------------------------------
# 对接目标发现：桌面端 DeepSeek Harness 优先，网页端 dsh web 兜底
# --------------------------------------------------------------------------
#
# 桌面端（DeepSeek Harness.exe）和网页端（dsh web）用的是同一套 HTTP API，
# 但桌面端启动时自己挑一个空闲端口（不是固定的 3080，配置文件里也没有端口项，
# 每次启动都可能变），所以只能运行时发现：
#   1. --dsh-url 显式指定：只连这个地址，连不上就报错（不做自动发现）
#   2. console_data/settings.json 的 "dsh_url"：优先候选；连不上仍会自动找其他 harness
#   3. 环境变量 DSH_WEB_URL（从 DSH 里拉起本程序时自带）
#   4. 扫描正在运行的 DeepSeek Harness 进程的监听端口（= 桌面端）
#   5. http://127.0.0.1:3080（传统网页端）
# 候选地址必须能真正应答一次 RPC（session/list）才算命中，避免误认。

WEB_PROFILE_URL = "http://127.0.0.1:3080"   # 传统用法：dsh web --port 3080
TARGET_LABELS = {"explicit": "指定地址", "settings": "设置文件",
                 "env": "环境变量", "desktop": "桌面端", "scan": "扫描", "web": "网页端"}

_HARNESS_IMAGE_HINTS = ("deepseek harness", "dsh")
_SCAN_CACHE = {"at": 0.0, "strong": [], "weak": []}
_SCAN_TTL = 5.0


def _no_window():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _listening_loopback_ports():
    """返回 (harness 进程占用的监听端口, 其它回环监听端口)，均升序。

    桌面端与 `dsh web` 都是同一个可执行文件（DeepSeek Harness.exe），
    按进程名即可认出它的监听端口。非 Windows 平台直接返回空。
    """
    now = time.time()
    if now - _SCAN_CACHE["at"] < _SCAN_TTL:
        return list(_SCAN_CACHE["strong"]), list(_SCAN_CACHE["weak"])
    strong, weak = [], []
    if os.name == "nt":
        out = ""
        try:
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                                 text=True, errors="replace", timeout=8,
                                 creationflags=_no_window()).stdout or ""
        except (OSError, subprocess.SubprocessError):
            out = ""
        by_pid, all_ports = {}, set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
                continue
            host, _, port = parts[1].rpartition(":")
            if not port.isdigit() or host.strip("[]") not in ("127.0.0.1", "0.0.0.0", "::1", "::"):
                continue
            by_pid.setdefault(parts[4], set()).add(int(port))
            all_ports.add(int(port))
        names = {}
        try:
            listing = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                                     text=True, errors="replace", timeout=8,
                                     creationflags=_no_window()).stdout or ""
            for row in csv.reader(listing.splitlines()):
                if len(row) >= 2 and row[1].strip().isdigit():
                    names[row[1].strip()] = (row[0] or "").lower()
        except (OSError, subprocess.SubprocessError, csv.Error):
            names = {}
        harness_ports = set()
        for pid, ports in by_pid.items():
            if any(h in names.get(pid, "") for h in _HARNESS_IMAGE_HINTS):
                harness_ports |= ports
        strong = sorted(harness_ports)
        weak = sorted(all_ports - harness_ports)
    _SCAN_CACHE.update({"at": now, "strong": strong, "weak": weak})
    return strong, weak


def _auth_error(text):
    t = str(text).lower()
    return ("401" in t) or ("403" in t) or ("unauthorized" in t)


def probe_dsh_url(base_url, timeout=6.0):
    """该地址能否用本机凭证真正完成一次 RPC（session/list）。

    返回 (是否可用, 失败原因, 生效的凭证文件)。
    会依次尝试各个候选凭证文件，**只要有一个能通过鉴权就用它** ——
    避免"选中过期备份里的密钥 → 401"这种静默失败（真实踩过：程序目录附近的
    *.dsh-home 通配先匹配到 .upgrade-backup-*/，正确文件根本没被试过）。
    """
    if not base_url:
        return False, "空地址", ""
    candidates = [None]
    try:
        candidates += [str(p) for p in candidate_credentials() if p.is_file()]
    except OSError:
        pass
    why = ""
    for cred in candidates:
        try:
            DshRpc(base_url, timeout=timeout, credentials_path=cred).list_sessions(cache_seconds=0.0)
            return True, "", (cred or "")
        except DshError as exc:
            why = str(exc)[:200]
        except Exception as exc:                       # noqa: BLE001
            why = f"{type(exc).__name__}: {exc}"[:200]
        if not _auth_error(why) or cred is None and len(candidates) == 1:
            break        # 不是鉴权问题（网络/端口不对），换凭证也没用
    return False, why, ""


def candidate_dsh_urls(explicit=None, settings_path=None, weak_scan=True):
    """按优先级生成候选地址，返回 (url 列表, {url: 来源标签})。

    weak_scan=False 时不做"所有回环端口"的兜底扫描（重试轮次里用它省时间）。
    """
    urls, sources = [], {}

    def add(url, source):
        url = (url or "").strip().rstrip("/")
        if url and url not in urls:
            urls.append(url)
            sources[url] = source

    if explicit:
        add(explicit, "explicit")
        return urls, sources
    if settings_path:
        try:
            cfg = json.loads(Path(settings_path).read_text(encoding="utf-8"))
            if isinstance(cfg, dict):
                add(cfg.get("dsh_url"), "settings")
        except (OSError, json.JSONDecodeError):
            pass
    add(os.environ.get("DSH_WEB_URL"), "env")
    strong, weak = _listening_loopback_ports()
    for port in strong:
        add(f"http://127.0.0.1:{port}", "desktop")
    if weak_scan:
        # 兜底：不认识进程名时（例如用 node 直接跑），扫非特权端口，
        # 跳过 <1024 的系统服务，避免无谓探测。
        for port in [p for p in weak if p >= 1024][:16]:
            add(f"http://127.0.0.1:{port}", "scan")
    add(WEB_PROFILE_URL, "web")
    return urls, sources


def discover_dsh_url(explicit=None, settings_path=None, wait_seconds=0.0, logger=None):
    """找到可用的 DSH 地址，返回 (url, 来源中文标签, 诊断信息, 生效的凭证文件)。

    找不到时 url 为 None，诊断信息说明"扫到了哪些候选、各自为什么失败"，
    可直接展示给用户，而不是笼统说一句"未找到"。
    找到时第 4 项是**能通过鉴权的**凭证文件（可能不是默认那个），
    调用方应把它固定下来给后续所有请求用。

    wait_seconds > 0 时轮询等待（先开控制台、后开桌面端也能连上）：
    首轮做完整端口扫描并记录每个候选的失败原因，之后每 3 秒重扫一次
    （harness 换端口也能跟上），但只重试已知候选，避免等待期间开销过大。
    """
    started = time.time()
    last_report = 0.0
    first_round = True
    notes = []          # 首轮记录：(候选地址, 失败原因)
    slow = {}           # 上次超时的候选 -> 下一轮给它更长的超时
    while True:
        urls, sources = candidate_dsh_urls(explicit, settings_path, weak_scan=first_round)
        for url in urls:
            base = 3.0 if sources.get(url) == "scan" else 8.0
            timeout = max(base, slow.get(url, 0.0))
            ok, why, cred = probe_dsh_url(url, timeout=timeout)
            if ok:
                return url, TARGET_LABELS.get(sources.get(url, ""), "指定地址"), "", cred
            low = why.lower()
            if ("timed out" in low) or ("timeout" in low) or ("10060" in low):
                # harness 被长回合/高负载拖住时，8 秒可能不够；后续轮次放宽到 20 秒
                slow[url] = 20.0
            if first_round:
                notes.append((url, why))
        if first_round and logger and notes:
            for u, w in notes[:4]:
                logger(f"候选 {u} 无应答：{w}")
            if len(notes) > 4:
                logger(f"（另有 {len(notes) - 4} 个候选无应答）")
        first_round = False
        if time.time() - started >= wait_seconds:
            detail = ""
            if notes:
                head = "\n".join(f"  · {u} → {w}" for u, w in notes[:6])
                more = f"\n  · …另有 {len(notes) - 6} 个候选无应答" if len(notes) > 6 else ""
                detail = ("已经扫到这些候选地址，但没有一个能正常应答"
                          "（常见原因：harness 正在启动/重启、鉴权失败、该端口被别的程序占用）：\n"
                          + head + more)
                if any(("401" in w) or ("unauthorized" in w.lower()) or ("凭证" in w)
                       for _, w in notes):
                    found = [str(p) for p in candidate_credentials() if p.is_file()]
                    detail += ("\n  · 看起来是鉴权失败：harness 要求凭证，本机找到的凭证文件：\n    "
                               + ("\n    ".join(found) if found else "（一个都没找到）"))
            return None, "", detail, ""
        if logger and time.time() - last_report > 6:
            last_report = time.time()
            logger(f"等待 DeepSeek Harness 出现…（正在重试 {len(urls)} 个候选地址）")
        time.sleep(3.0)

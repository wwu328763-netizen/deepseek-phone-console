"""Phone remote console for the DeepSeek Harness (DSH) agent (stdlib only).

Runs a small HTTP server on the host. The phone opens a web page, authenticates
with a PIN, creates agent tasks in chosen folders, sends prompts, watches
progress, and stops runs.

The backend is the *running DeepSeek Harness web profile* (the same agent as in
the desktop browser GUI, normally at http://127.0.0.1:3080):

  * each phone task  = a DSH session created with cwd = the task folder
                       (session.create / session.prompt / session.cancel);
  * live progress   = WebSocket /api/events.mux stream, translated into the
                       same display items the phone UI renders;
  * desktop sessions= the harness session list (session.list); continuing a
                       session prompts that session (the GUI session included).

Requires: Python 3.11+. No third-party packages (dsh_client.py is stdlib-only).
"""

import argparse
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import urllib.request
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

import dsh_client
import sessions as sess

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_AGENT_PRESET = "standard"
# 保留：旧版网页端地址。改成自动发现（--dsh-url 默认 None）后，程序内部已无引用；
# 但常量仍可能被外部脚本 import，故保留并在此标注，不再当作默认值使用。
DEFAULT_DSH_URL = "http://127.0.0.1:3080"
# 没有观看者时最多缓存的增量 ops：下次订阅会先收全量快照，
# 因此积压的旧 ops 可以安全丢弃（否则只被 /api/sessions/<id> 轮询的会话会一直涨）。
MAX_PENDING_OPS = 2000


def _trim_pending_ops(state):
    """调用方必须持有 state.lock：没有订阅者时把 ops 积压裁到上限。"""
    if state.subscribers or len(state.pending_ops) <= MAX_PENDING_OPS:
        return
    del state.pending_ops[:len(state.pending_ops) - MAX_PENDING_OPS]

STATIC_FILES = {
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json; charset=utf-8"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/icons/icon-192.png": ("icons/icon-192.png", "image/png"),
    "/icons/icon-512.png": ("icons/icon-512.png", "image/png"),
    "/icons/icon-maskable-512.png": ("icons/icon-maskable-512.png", "image/png"),
    "/icons/apple-touch-icon.png": ("icons/apple-touch-icon.png", "image/png"),
    "/icons/favicon.png": ("icons/favicon.png", "image/png"),
    "/favicon.ico": ("icons/favicon.png", "image/png"),
    # Android 壳 APK 的自更新分发：android/build.ps1 构建后会把这俩拷进 web/
    # （静态文件在鉴权之前，所以更新检查和下载 APK 都不需要 PIN）
    "/app-version.json": ("app-version.json", "application/json; charset=utf-8"),
    "/phone-console.apk": ("phone-console.apk", "application/vnd.android.package-archive"),
}


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------

def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


_VIRTUAL_ADAPTER_HINTS = (
    "vmware", "vmnet", "virtualbox", "vbox", "hyper-v", "vethernet", "default switch",
    "tap-windows", "tap adapter", "wsl", "docker", "loopback", "bluetooth",
    "wi-fi direct", "microsoft wi-fi", "teredo", "isatap", "npcap", "vpn",
)


def _adapter_ipv4_pairs():
    """[(网卡段落文本, IPv4)]，来自 ipconfig；拿不到就返回 []。"""
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(["ipconfig"], capture_output=True, text=True, errors="replace",
                             timeout=8,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return []
    pairs, section = [], []
    for raw in out.splitlines():
        line = raw.strip()
        if not line:
            continue
        # 适配器头行是**顶格**的（「以太网适配器 VMware Network Adapter VMnet1:」），
        # 属性行都带缩进 —— 而有些属性行同样以冒号结尾（「   连接特定的 DNS 后缀 . . . : 」），
        # 只看冒号会把网卡名冲掉，所以必须按缩进判断。
        if raw[:1] not in (" ", "\t") and line.endswith(":"):
            section = [line]
            continue
        section.append(line)
        m = re.match(r"IPv4[^:：]*[:：]\s*([0-9]{1,3}(?:\.[0-9]{1,3}){3})", line)
        if m:
            pairs.append((" ".join(section), m.group(1)))
    return pairs


def is_cgnat(ip):
    """100.64.0.0/10：运营商级 NAT / 热点常用，手机往往根本到不了。

    注意：Tailscale 的地址也在这个段里，但它是**可达**的（见 tailscale_ips()），
    所以别用这个函数单独判断"能不能连"，要排除 Tailscale 网卡。
    """
    try:
        first, second = (int(x) for x in str(ip).split(".")[:2])
    except (ValueError, TypeError):
        return False
    return first == 100 and 64 <= second <= 127


def tailscale_ips():
    """Tailscale 虚拟网卡的 IPv4（100.x，固定不变、手机在任何网络都能连）。"""
    return [ip for section, ip in _adapter_ipv4_pairs() if "tailscale" in section.lower()]


def get_lan_ips():
    """可供手机访问的本机 IPv4 列表。

    先按网卡过滤：VMware / Hyper-V / VirtualBox / TAP / WSL / Docker 这些虚拟网卡的地址
    手机根本到不了，169.254（APIPA）与 127.x 也不是可用地址。以前不过滤，界面/二维码
    会列出一堆 VMnet 地址 —— 真机踩过：有线网卡断线时只剩 192.168.135.1 / 192.168.145.1，
    用户照着填当然连不上（真正的 Wi-Fi 地址反而不在前面）。
    """
    ips = []
    for section, ip in _adapter_ipv4_pairs():
        if ip.startswith("127.") or ip.startswith("169.254."):
            continue
        if any(h in section.lower() for h in _VIRTUAL_ADAPTER_HINTS):
            continue
        if ip not in ips:
            ips.append(ip)
    if not ips:
        # 兜底：拿不到网卡信息时用 hostname 解析 + 默认路由源地址
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None):
                ip = info[4][0]
                if ":" not in ip and not ip.startswith("127.") and ip not in ips:
                    ips.append(ip)
        except OSError:
            pass
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip not in ips:
                ips.append(ip)
        except OSError:
            pass
    # Tailscale 地址排最前：它固定不变、手机在任何网络都能连，最适合做成二维码；
    # 而且它虽然也在 100.64/10 段，却**不该**被当成"手机连不上的 CGNAT 地址"。
    ts = set(tailscale_ips())
    ips.sort(key=lambda ip: (0 if ip in ts else 1, ip))
    return ips


def find_api_key():
    """Locate a DeepSeek API key for the balance endpoint.

    Tries the DSH home credentials first (the harness the phone console talks
    to), then the classic ~/.codex/config.toml.
    """
    dsh_home = os.environ.get("DSH_HOME")
    candidates = []
    if dsh_home:
        candidates.append(Path(dsh_home) / ".credentials.yaml")
    candidates.append(Path.home() / ".dsh" / ".credentials.yaml")
    candidates.append(Path.home() / ".codex" / "config.toml")
    for p in candidates:
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # 注意用 re.I：harness 的凭证文件里是 `DEEPSEEK_API_KEY:`（大写），
        # 区分大小写会漏掉它 → 余额接口一直报"未找到 DeepSeek API Key"。
        m = re.search(r"(?:api_key|experimental_bearer_token|token)\s*[:=]\s*[\"']?(sk-[A-Za-z0-9_\-]+)",
                      text, re.I)
        if m:
            return m.group(1)
    return None


# --------------------------------------------------------------------------
# Thread state (one phone task = one DSH session)
# --------------------------------------------------------------------------

class ThreadState:
    def __init__(self, tid, name, workdir, data_dir, dsh_session_id=None):
        self.id = tid
        self.name = name or Path(workdir).name or tid
        self.workdir = str(Path(workdir).resolve())
        self.created_at = now_iso()
        self.dsh_session_id = dsh_session_id
        self.tr = sess.DshItems()          # live display items (mutated in place)
        self.pending_ops = []              # (op, item) for SSE subscribers
        self.subscribers = set()           # set of threading.Condition
        self.lock = threading.RLock()
        self.running = False
        self.last_usage = None
        self.stderr_tail = []
        self.pending_user_atts = []        # 等 DSH 回传 user 消息时补附件信息
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._seeded = False
        self.last_seq = -1          # 已翻译到的事件序号（增量轮询用）
        self._load()
        # 提问卡片要带上会话 id（手机端回答时回传），_load 之后才知道最终 id
        self.tr.session_id = self.dsh_session_id

    # -- persistence ------------------------------------------------------
    def _meta_path(self):
        return self.data_dir / "meta.json"

    def _save_meta(self):
        try:
            with open(self._meta_path(), "w", encoding="utf-8") as fh:
                json.dump({"name": self.name, "workdir": self.workdir,
                           "dsh_session_id": self.dsh_session_id,
                           "created_at": self.created_at}, fh, ensure_ascii=False)
        except OSError:
            pass

    def _load(self):
        try:
            meta = json.loads(self._meta_path().read_text(encoding="utf-8"))
            self.dsh_session_id = meta.get("dsh_session_id") or meta.get("codex_thread_id")
            self.name = meta.get("name", self.name)
            self.workdir = meta.get("workdir", self.workdir)
            # 还原创建时间：__init__ 里刚设成"现在"，不还原的话每次启动都会把它覆盖掉，
            # 手机端任务列表（按 created_at 倒序）就会乱序。
            self.created_at = meta.get("created_at") or self.created_at
        except (OSError, json.JSONDecodeError):
            pass
        self._save_meta()

    @property
    def items(self):
        """条目快照（浅拷贝）：遍历时不会和翻译器的原地更新撞车。"""
        with self.lock:
            return [dict(it) for it in self.tr.items]

    # -- event feeding -----------------------------------------------------

    def apply_ops(self, ops):
        """Apply translator ops (items are already mutated in place) + notify."""
        with self.lock:
            self.pending_ops.extend(ops)
            _trim_pending_ops(self)
            conds = list(self.subscribers)
        for cond in conds:
            with cond:
                cond.notify_all()

    def drain_ops(self):
        with self.lock:
            out, self.pending_ops = self.pending_ops, []
        return out

    def snapshot_and_drain(self):
        """同一把锁里取条目快照 + 清空 ops：SSE 首帧用，保证不漏条目也不重复。"""
        with self.lock:
            items = [dict(it) for it in self.tr.items]
            ops, self.pending_ops = self.pending_ops, []
        return items, ops

    def _annotate_new_user(self, before_count):
        """新到的 user 消息：贴上排队中的附件信息 + 原始文本（去掉给 agent 的附加说明）。"""
        if not self.pending_user_atts:
            return
        try:
            new_items = self.tr.items[before_count:]
        except Exception:
            return
        for it in new_items:
            if (it.get("kind") or "").lower() != "user":
                continue
            meta = self.pending_user_atts.pop(0)
            it["attachments"] = meta.get("attachments") or []
            it["images"] = meta.get("images") or []
            it["files"] = meta.get("files") or []
            if meta.get("text"):
                it["displayText"] = meta["text"]   # 手机端优先显示这条（干净原文）
            return

    def feed_event(self, ev):
        before = len(self.tr.items)
        ops = self.tr.feed(ev)
        self._annotate_new_user(before)
        self.apply_ops(ops)
        if ev.get("type") == "turn/end":
            self.running = False
        if ev.get("type") == "turn/start":
            self.running = True

    def push_error(self, text):
        self.apply_ops(self.tr.append_item("error", text=text, at=now_iso()))
        self.running = False

    def _feed_events(self, events, running=None):
        """锁内按 seq 去重后翻译事件，再唤醒订阅者。

        去重必须在锁内、和 last_seq 的读写同一把锁：SSE 每 1.5 秒刷新一次、
        手机端每 3 秒又轮询 /api/sessions/<id>，两个线程会同时拉到同一批
        事件（after_seq 相同），旧实现在锁外读 last_seq，同一批 347 个事件
        会被喂两遍（user 2→4、agent 29→58、reasoning 39→78、tool 重复）。
        """
        with self.lock:
            before_count = len(self.tr.items)
            ops = []
            for ev in events:
                seq = ev.get("seq")
                if isinstance(seq, int) and seq <= self.last_seq:
                    continue
                ops.extend(self.tr.feed(ev))
                if isinstance(seq, int) and seq > self.last_seq:
                    self.last_seq = seq
            _ann = getattr(self, "_annotate_new_user", None)   # 桌面会话视图没有附件队列
            if _ann:
                _ann(before_count)
            self.pending_ops.extend(ops)
            _trim_pending_ops(self)
            if running is not None:
                self.running = bool(running)
            conds = list(self.subscribers)
        for cond in conds:
            with cond:
                cond.notify_all()

    def refresh(self, dsh, max_messages=80, legacy_hint=True):
        """从 harness 拉取新事件（含首次播种）并翻译成显示条目。

        新版 harness 没有 mux 推送，统一用 session/page 轮询：
        last_seq = -1 时取尾部历史作为播种，之后只取增量。
        """
        if not self.dsh_session_id:
            if legacy_hint and not self._seeded:
                self._seeded = True
                self.tr.append_item(
                    "error",
                    text="这个任务没有关联 DSH 会话（旧版遗留），无法继续运行。请删除后新建任务。",
                    at=now_iso())
                self.apply_ops([])
            self.running = False
            return
        with self.lock:                 # after_seq 与 last_seq 的更新必须同锁
            after_seq = self.last_seq
        try:
            events, running = dsh.refresh(self.dsh_session_id, after_seq=after_seq,
                                          max_messages=max_messages)
        except dsh_client.DshError as exc:
            if not self._seeded:
                self._seeded = True
                self.push_error(str(exc))
            return
        self._seeded = True
        self._feed_events(events, running)

    def seed_from_history(self, dsh, running=False):
        """兼容旧调用：等价于一次全量刷新（last_seq=-1 时取尾部历史）。"""
        self.refresh(dsh, max_messages=120)

    # -- subscribers -------------------------------------------------------

    def add_subscriber(self, cond):
        with self.lock:
            self.subscribers.add(cond)

    def remove_subscriber(self, cond):
        with self.lock:
            self.subscribers.discard(cond)

    def snapshot(self):
        """条目快照（浅拷贝）：交给调用方做 json 序列化时不会撞上原地更新。"""
        with self.lock:
            return [dict(it) for it in self.tr.items]

    def to_public(self, with_items=True):
        # 必须带 items：手机端 3 秒兜底轮询就是拿这个接口，
        # 之前不带 items 会把聊天记录清空（表现为"看不到自己发送的消息"）。
        data = {
            "id": self.id,
            "name": self.name,
            "workdir": self.workdir,
            "created_at": self.created_at,
            "running": self.running,
            "dsh_session_id": self.dsh_session_id,
            "legacy": self.dsh_session_id is None,
        }
        if with_items:
            data["items"] = self.items
        return data


# --------------------------------------------------------------------------
# Live view of an arbitrary DSH session (the "desktop sessions" list)
# --------------------------------------------------------------------------

class DshSessionView:
    """Tracks one harness session for the phone: seeds from history, then
    follows live mux events. Created on demand, expires when unused."""

    def __init__(self, sid, dsh, console):
        self.sid = sid
        self.dsh = dsh
        self.console = console
        self.tr = sess.DshItems(sid)
        self.pending_ops = []              # (op, item) for SSE subscribers
        self._seeded = False
        self.last_seq = -1
        self.running = False
        self.name = None
        self.cwd = None
        self.updated = None
        self.subscribers = set()
        self.lock = threading.RLock()
        self.last_used = time.time()

    def _feed_events(self, events, running=None):
        """锁内按 seq 去重后翻译（并发刷新不会把同一批事件喂两遍）。"""
        with self.lock:
            before_count = len(self.tr.items)
            ops = []
            for ev in events:
                seq = ev.get("seq")
                if isinstance(seq, int) and seq <= self.last_seq:
                    continue
                ops.extend(self.tr.feed(ev))
                if isinstance(seq, int) and seq > self.last_seq:
                    self.last_seq = seq
            _ann = getattr(self, "_annotate_new_user", None)   # 桌面会话视图没有附件队列
            if _ann:
                _ann(before_count)
            self.pending_ops.extend(ops)
            _trim_pending_ops(self)
            if running is not None:
                self.running = bool(running)
            conds = list(self.subscribers)
        for cond in conds:
            with cond:
                cond.notify_all()
        return ops

    def refresh(self, dsh=None, max_messages=80):
        """轮询刷新：拉取 seq > last_seq 的事件并翻译（首次即播种）。"""
        self.last_used = time.time()
        client = dsh or self.dsh
        with self.lock:                 # after_seq 与 last_seq 的更新必须同锁
            after_seq = self.last_seq
        try:
            events, running = client.refresh(self.sid, after_seq=after_seq,
                                             max_messages=max_messages)
        except dsh_client.DshError:
            self._seeded = True
            return
        with self.lock:
            self._seeded = True
        return self._feed_events(events, running)

    def seed(self, running=False):
        """兼容旧调用：一次刷新即完成播种。"""
        return self.refresh()

    def feed(self, ev):
        """兼容旧调用：单个事件入翻译器（带 seq 去重）。"""
        return self._feed_events([ev])

    def drain_ops(self):
        with self.lock:
            out, self.pending_ops = self.pending_ops, []
        return out

    def snapshot_and_drain(self):
        """同一把锁里取条目快照 + 清空 ops（SSE 首帧用）。"""
        with self.lock:
            items = [dict(it) for it in self.tr.items]
            ops, self.pending_ops = self.pending_ops, []
        return items, ops

    def add_subscriber(self, cond):
        with self.lock:
            self.subscribers.add(cond)

    def remove_subscriber(self, cond):
        with self.lock:
            self.subscribers.discard(cond)

    def snapshot(self):
        """条目快照（浅拷贝）：json 序列化在外层也不会撞上原地更新。"""
        with self.lock:
            return [dict(it) for it in self.tr.items]


# --------------------------------------------------------------------------
# Console application
# --------------------------------------------------------------------------

class Console:
    def __init__(self, args):
        self.args = args
        self.pin = args.pin
        self.port = int(getattr(args, "port", 8787) or 8787)
        self.workdir_root = Path(args.workdir_root).expanduser().resolve()
        self.workdir_root.mkdir(parents=True, exist_ok=True)
        self.dsh_url = args.dsh_url
        self.agent_preset = args.agent_preset or DEFAULT_AGENT_PRESET

        self.dsh = dsh_client.DshRpc(self.dsh_url,
                                     credentials_path=getattr(args, "dsh_credentials", None))
        try:
            self.dsh.list_sessions()
        except dsh_client.DshError as exc:
            hint = "请先在电脑上启动 DSH 控制台（dsh web --port 3080）再启动本服务。"
            if "401" in str(exc) or "unauthorized" in str(exc).lower():
                found = [str(p) for p in dsh_client.candidate_credentials() if p.is_file()]
                hint = ("harness 要求鉴权但未找到有效凭证。已尝试：\n  " +
                        ("\n  ".join(found) if found else "（未找到任何 .credentials.yaml）") +
                        "\n请确认 DSH 控制台正在运行，或用 --dsh-credentials 指定凭证文件。")
            sys.exit(f"无法连接 DeepSeek Harness（{self.dsh_url}）：{exc}\n{hint}")
        self.dsh_connected = True

        self.api_key = find_api_key()
        self.balance_cache = None  # (timestamp, data)
        self.sessions_cache = None  # (timestamp, list)
        self.model_catalog_cache = None  # (timestamp, catalog)
        self.money_cache = None     # (timestamp, 余额/官网消费/均价)
        self.login_fails = {}      # client ip -> [fail_count, first_fail_ts]
        self.login_lock = threading.Lock()
        self.threads = {}
        self.threads_lock = threading.Lock()
        self.data_dir = SCRIPT_DIR / "console_data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.views = {}            # sid -> DshSessionView
        self.pending_questions = {}  # sid -> {rpc_id, sessionId}
        self._shutdown = False

        # 恢复历史手机任务（每个任务 = 一个 DSH 会话）
        for meta in (self.data_dir / "threads").glob("*/meta.json") if (self.data_dir / "threads").is_dir() else []:
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                tid = meta.parent.name
                self.threads[tid] = ThreadState(tid, data.get("name"), data.get("workdir"),
                                                meta.parent, data.get("dsh_session_id"))
            except (OSError, json.JSONDecodeError, ValueError):
                continue

        # 新版 harness 没有 mux 推送：实时性由各会话打开时的轮询刷新提供
        # （见 ThreadState.refresh / DshSessionView.refresh 与 _stream_session）

    # -- 刷新（轮询 session/page）------------------------------------------

    def refresh_target(self, sid, max_messages=80):
        """刷新某个会话（手机任务线程或正在查看的会话），返回是否有目标。"""
        state = self.thread_by_session(sid)
        if state is not None:
            state.refresh(self.dsh, max_messages=max_messages)
            return True
        view = self.views.get(sid)
        if view is not None:
            view.refresh(self.dsh, max_messages=max_messages)
            return True
        return False

    def answer_question(self, session_id, rpc_id, answers):
        """回答智能体的提问（ask_user_question → harness 的 userQuestions/answer）。

        提问卡片由 sessions.DshItems 在 tool/call(ask_user_question) 时生成，
        rpc_id 就是该工具调用的 callId；harness 返回 false 表示这条提问
        已经结束或已被回答（例如在电脑端答过）。
        """
        if not session_id or not rpc_id:
            return False, "缺少会话或提问标识，无法回答"
        try:
            ok = self.dsh.answer_question(session_id, rpc_id, answers)
        except dsh_client.DshError as exc:
            return False, "回答失败：" + str(exc)
        if not ok:
            return False, "这条提问已结束或已被回答（harness 未接受本次回答）"
        with self.threads_lock:
            self.pending_questions.pop(session_id, None)
        return True, {"ok": True}

    # -- PIN 鉴权限速 ------------------------------------------------------
    #
    # 以前只有 POST /api/login 计数，而真正鉴权的 _authorized() 不做任何
    # 计数：攻击者直接对任意 GET 猜 X-Console-Pin 就能无限尝试。
    # 现在两条路都走 check_pin()，按来源 IP 计数、窗口语义照旧（10 次锁 15 分钟）。
    #
    # 注意：先比对 PIN 再看锁定，即"正确 PIN 永远能进"——否则手机端
    # localStorage 里存了旧 PIN 时会把自己锁在门外 15 分钟；
    # 猜错的请求照样计数、锁定期内照样被拒（401/429 与原来一致）。

    PIN_MAX_FAILS = 10
    PIN_LOCK_SECONDS = 900

    def _login_remaining(self, ip):
        """该 IP 的锁定剩余秒数（0 = 未锁定）；调用方不必持锁。"""
        with self.login_lock:
            rec = self.login_fails.get(ip)
            if rec and rec[0] >= self.PIN_MAX_FAILS:
                used = time.time() - rec[1]
                if used < self.PIN_LOCK_SECONDS:
                    return self.PIN_LOCK_SECONDS - used
        return 0.0

    def _login_fail(self, ip):
        """记一次失败，窗口过期就从 0 重新计（窗口起点是第一次失败的时间）。"""
        with self.login_lock:
            rec = self.login_fails.get(ip, [0, time.time()])
            if time.time() - rec[1] > self.PIN_LOCK_SECONDS:
                rec = [0, time.time()]
            rec[0] += 1
            self.login_fails[ip] = rec
            count = rec[0]
        if count == self.PIN_MAX_FAILS:
            sys.stderr.write("[console] PIN 连续输错 %d 次，%s 锁定 %d 分钟\n"
                             % (count, ip, self.PIN_LOCK_SECONDS // 60))
        return count

    def check_pin(self, ip, supplied):
        """统一鉴权入口：返回 (是否通过, 锁定剩余秒数)。"""
        if hmac.compare_digest(str(supplied or ""), self.pin):
            with self.login_lock:
                self.login_fails.pop(ip, None)
            return True, 0.0
        self._login_fail(ip)
        return False, self._login_remaining(ip)

    def _get_view(self, sid, running=False):
        with self.threads_lock:
            view = self.views.get(sid)
            if view is None:
                view = DshSessionView(sid, self.dsh, self)
                self.views[sid] = view
            view.last_used = time.time()
            return view

    def _sweep_views(self):
        now = time.time()
        with self.threads_lock:
            stale = [sid for sid, v in self.views.items()
                     if now - v.last_used > 600 and not v.subscribers]
            for sid in stale:
                self.views.pop(sid, None)

    # -- thread management ------------------------------------------------

    def reconcile_threads_running(self):
        """用 harness 的 session/list 校正手机任务的 running 标志。

        以前只靠事件更新：事件丢一条，running 就永远停在 true，
        侧边栏的小绿点会挂在已经结束的对话上（真机反馈）。
        """
        try:
            rows = self.dsh.list_sessions()
        except Exception:
            return
        live = {}
        for row in rows:
            sid = row.get("sessionId")
            if sid:
                live[sid] = bool(row.get("running"))
        with self.threads_lock:
            for state in self.threads.values():
                sid = state.dsh_session_id
                if not sid or sid not in live:
                    continue
                real = live[sid]
                if state.running != real:
                    state.running = real
                    if not real and state.status in ("运行中", "running"):
                        state.status = ""

    def normalize_user_items(self, items, base_dir=None):
        """把 user 消息里的 [图片]/[附带文件] 标记还原成附件字段。

        DSH 回传的 user 文本是追加过标记的（"

[图片] .uploads/x.png（可用 READ_IMAGE 查看）"），
        手机端如果拿它直接渲染，就会把图片显示成一串路径文字。这里统一清洗：
        - displayText = 去掉标记后的原文（前端优先显示它）
        - attachments/images/files = 还原出的文件（相对路径按 base_dir 解析）
        """
        if not items:
            return items
        base = Path(base_dir) if base_dir else self.workdir_root
        img_re = re.compile(r"\n\n\[图片\]\s*(.+?)(?:（可用 READ_IMAGE 查看）|$)", re.S)
        md_img_re = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
        md_tail_re = re.compile(r"\n*（图片：[^）]*）\s*$")
        file_re = re.compile(r"\n\n\[附带文件\]\s*(.+?)(?:（请按需读取这些文件）|$)", re.S)

        def resolve(p):
            p = p.strip().strip(",")
            if not p:
                return None
            path = Path(p)
            if not path.is_absolute():
                path = base / path
            try:
                return path.resolve()
            except OSError:
                return path

        for it in items:
            if (it.get("kind") or "").lower() != "user":
                continue
            text = it.get("text") or ""
            imgs, files = [], []
            # 新版：markdown 内联图片 ![](/api/raw?path=...&pin=...)
            for mm in md_img_re.finditer(text):
                try:
                    from urllib.parse import urlparse as _up, parse_qs as _pq
                    qs = _pq(_up(mm.group(1)).query)
                    rawp = (qs.get("path") or [""])[0]
                    if rawp:
                        rp = Path(rawp)
                        imgs.append(rp.resolve() if rp.is_absolute() else (base / rp).resolve())
                except Exception:
                    pass
            m = img_re.search(text)
            if m:
                for piece in re.split(r"[,，]", m.group(1)):
                    rp = resolve(piece)
                    if rp:
                        imgs.append(rp)
            m2 = file_re.search(text)
            if m2:
                for piece in re.split(r"[,，]", m2.group(1)):
                    rp = resolve(piece)
                    if rp:
                        files.append(rp)
            if not imgs and not files:
                continue
            clean = md_img_re.sub("", text)
            clean = md_tail_re.sub("", clean)
            clean = img_re.sub("", clean)
            clean = file_re.sub("", clean).strip()
            atts = [{"name": p.name, "path": str(p), "image": True} for p in imgs]
            atts += [{"name": p.name, "path": str(p), "image": False} for p in files]
            it["displayText"] = clean
            it["attachments"] = atts
            it["images"] = [str(p) for p in imgs]
            it["files"] = [str(p) for p in files]
        return items

    def create_thread(self, name, workdir, prompt=None):
        tid = uuid.uuid4().hex[:8]
        try:
            Path(workdir).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        # 每个手机任务一个独立会话。关键：会话 cwd 必须等于手机任务目录，
        # 否则「手机任务目录 / DSH 会话工作区 / 上传落盘」三处对不上（真机反馈）。
        # - 指定了工作目录：直接 cwd=该目录（三方一致；电脑端按该路径归组）
        # - 没指定：用「手机任务」工作区目录 + workspaceId（电脑端仍归在“手机任务”）
        chosen = str(Path(workdir).resolve())
        ws_path = self.phone_workspace_path()
        ws_path = str(Path(ws_path).resolve()) if ws_path else None
        wid = self.phone_workspace_id()
        session_cwd = None
        if wid and ws_path and chosen == ws_path:
            sid = self.dsh.create_session(workspace_id=wid, agent_preset=self.agent_preset)
            session_cwd = ws_path
        else:
            sid = self.dsh.create_session(cwd=chosen, agent_preset=self.agent_preset)
            session_cwd = chosen
        if sid and name:
            try:
                self.dsh.rename(sid, name)
            except dsh_client.DshError:
                pass
        state = ThreadState(tid, name, workdir, self.data_dir / "threads" / tid, sid)
        state.running = False
        with self.threads_lock:
            self.threads[tid] = state
        if prompt:
            # 正常情况下 session_cwd == chosen；只有 harness 降级时才把目录写进指令兜底
            if session_cwd and str(Path(session_cwd).resolve()) != chosen:
                prompt = prompt + "\n\n（本任务的工作目录是：%s，请在其中工作）" % chosen
            self.start_turn(tid, prompt)
        return state

    def get_thread(self, tid):
        with self.threads_lock:
            return self.threads.get(tid)

    def _thread_states(self):
        """线程表快照：创建/删除任务只会换掉 self.threads 里的键，
        遍历时用副本就不会撞上 RuntimeError: dictionary changed size during iteration。"""
        with self.threads_lock:
            return list(self.threads.values())

    def thread_by_session(self, sid):
        with self.threads_lock:
            states = list(self.threads.values())
        for state in states:
            if state.dsh_session_id == sid:
                return state
        return None

    def delete_thread(self, tid):
        with self.threads_lock:
            state = self.threads.pop(tid, None)
        if state is None:
            return False
        if state.running:
            self.stop_thread(tid)
        shutil.rmtree(state.data_dir, ignore_errors=True)
        return True

    # -- prompts / runs ----------------------------------------------------

    def _split_content(self, prompt, images=None, files=None, base_dir=None):
        """Build (text, image_parts) for session.prompt.

        消息文本保持用户原话 + 附件清单：
          * 图片/文件都存进 <workdir>/.uploads/，agent 用 READ_IMAGE / 读文件自己看；
          * 图片额外给一行 markdown 链接（电脑端聊天里直接显示图，手机端归一化时剥掉）。
        """
        text = prompt or ""

        base = Path(base_dir) if base_dir else self.workdir_root

        def _rel(p):
            if not os.path.isabs(p):
                return p
            try:
                r = os.path.relpath(p, base)
            except ValueError:
                r = p
            # 不在 base 下面时（例如线程目录在 workdir_root 之外），退化成 ".uploads/文件名"
            if r.startswith(".."):
                r = str(Path(Path(p).parent.name) / Path(p).name)
            return r

        if files:
            text = text + "\n\n[附带文件] " + ", ".join(_rel(f) for f in files) + "（请按需读取这些文件）"
        if images:
            # 电脑端（DSH 聊天界面）会渲染 markdown 图片，这里直接给可访问的图片地址；
            # 手机端在归一化时会把这些标记剥掉、改用自己的缩略图组件。
            try:
                pin_val = (self.data_dir / "pin.txt").read_text(encoding="utf-8").strip()
            except OSError:
                pin_val = ""
            links = []
            for i in images:
                try:
                    q = urllib.parse.quote(str(i))
                except Exception:
                    q = str(i)
                links.append("![图片](http://127.0.0.1:%d/api/raw?path=%s&pin=%s)" % (self.port, q, pin_val))
            text = text + "\n\n" + "\n".join(links) + "\n\n（图片：" + ", ".join(_rel(i) for i in images) + "，可用 READ_IMAGE 查看）"

        return text, []

    def _dsh_prompt(self, state, prompt, images=None, files=None):
        """Send one prompt into the task's DSH session and stream events."""
        state.running = True
        with state.lock:
            conds = list(state.subscribers)
        for cond in conds:
            with cond:
                cond.notify_all()
        if state.dsh_session_id is None:
            state.push_error("任务尚未关联 DSH 会话")
            return
        # 附件元数据排队：DSH 会把用户消息作为事件回传（重复的那条来源），
        # 等它到达时把附件信息贴到那一条上，避免重复消息、也避免手机上只看到占位文字。
        atts = [{"name": Path(p).name, "path": str(p), "image": True} for p in (images or [])]
        atts += [{"name": Path(p).name, "path": str(p), "image": False} for p in (files or [])]
        with state.lock:
            state.pending_user_atts.append({
                "text": prompt, "attachments": atts,
                "images": [str(p) for p in (images or [])],
                "files": [str(p) for p in (files or [])],
            })
        try:
            text, image_parts = self._split_content(prompt, images, files, base_dir=getattr(state, "workdir", None))
            self.dsh.prompt(state.dsh_session_id, text, mode="queue",
                            image_parts=image_parts or None)
        except dsh_client.DshError as exc:
            state.push_error(str(exc))

    def start_turn(self, tid, prompt, images=None, files=None):
        state = self.get_thread(tid)
        if state is None:
            return False
        threading.Thread(target=self._dsh_prompt,
                         args=(state, prompt, images, files), daemon=True).start()
        return True

    def stop_thread(self, tid):
        state = self.get_thread(tid)
        if state is None or not state.dsh_session_id:
            return
        try:
            self.dsh.cancel(state.dsh_session_id)
        except dsh_client.DshError:
            pass
        state.running = False
        with state.lock:
            conds = list(state.subscribers)
        for cond in conds:
            with cond:
                cond.notify_all()

    def session_workdir(self, sid):
        """电脑端会话的工作目录（DSH cwd）；取不到就回退根目录。"""
        try:
            for item in self.dsh.list_sessions():
                if item.get("sessionId") == sid and item.get("cwd"):
                    return str(item["cwd"])
        except Exception:
            pass
        return str(self.workdir_root)

    @staticmethod
    def save_upload(state, filename, data):
        return Console.save_upload_to(state.workdir, filename, data)

    @staticmethod
    def save_upload_to(workdir, filename, data):
        filename = os.path.basename(filename.replace("\\", "/")).strip()
        filename = re.sub(r"[^\w.\-()（）]", "_", filename, flags=re.UNICODE) or "upload.bin"
        upload_dir = Path(workdir) / ".uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        target = upload_dir / filename
        target.write_bytes(data)
        ext = os.path.splitext(filename)[1].lower()
        media_type = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif",
        }.get(ext)
        return {
            "name": filename,
            "path": str(target),
            "relative": str(Path(".uploads") / filename),
            "size": len(data),
            "mediaType": media_type,
        }

    # -- 手机端归档（本地文件 archived.json） --------------------------------
    def _archive_file(self):
        return self.data_dir / "archived.json"

    def local_archived(self):
        try:
            data = json.loads(self._archive_file().read_text(encoding="utf-8") or "{}")
        except Exception:
            data = {}
        return {k: [str(x) for x in (data.get(k) or [])] for k in ("thread", "session")}

    def set_archived(self, kind, ident, archived):
        data = self.local_archived()
        cur = set(data.get(kind) or [])
        if archived:
            cur.add(str(ident))
        else:
            cur.discard(str(ident))
        data[kind] = sorted(cur)
        try:
            self._archive_file().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        self.sessions_cache = None
        return data

    # -- sessions -----------------------------------------------------------

    def _workspace_data(self, max_age=10):
        """读 harness 落盘的 workspace.json（工作区分组 + 归档名单都在里面），10 秒缓存。"""
        now = time.time()
        cache = getattr(self, "_wsdata_cache", None)
        if cache and now - cache[0] < max_age:
            return cache[1]
        data = None
        for cred in dsh_client.candidate_credentials():
            p = Path(cred).parent / "storages" / "workspace.json"
            if not p.is_file():
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
                break
            except (OSError, json.JSONDecodeError):
                continue
        self._wsdata_cache = (now, data)
        return data

    def archived_session_ids(self):
        """已归档会话名单（直接从 workspace.json 里取）。"""
        data = self._workspace_data()
        ids = set()
        if not data:
            return ids

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "archivedSessionIds" and isinstance(v, list):
                        ids.update(str(x) for x in v)
                    else:
                        walk(v)
            elif isinstance(node, list):
                for x in node:
                    walk(x)

        walk(data)
        return ids

    # -- 手机任务的工作区 ---------------------------------------------------

    PHONE_WS_TITLE = "手机任务"

    def workspaces(self):
        """当前所有工作区：{id: {title, path, sessionIds}}。"""
        data = self._workspace_data()
        return ((data or {}).get("tables") or {}).get("workspaces") or {}

    def grouped_session_ids(self):
        ids = set()
        for item in self.workspaces().values():
            ids.update(str(x) for x in ((item or {}).get("sessionIds") or []))
        return ids

    def phone_workspace_id(self, max_age=30):
        """「手机任务」工作区的 id；没有就在 workdir_root 下建一个。"""
        now = time.time()
        cache = getattr(self, "_phone_ws_cache", None)
        if cache and now - cache[0] < max_age:
            return cache[1]
        wid = None
        for key, item in self.workspaces().items():
            if (item or {}).get("title") == self.PHONE_WS_TITLE:
                wid = key
                break
        if not wid:
            path = self.workdir_root / self.PHONE_WS_TITLE
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            try:
                wid = self.dsh.workspace_create(path)
            except (dsh_client.DshError, Exception):
                wid = None
            self._wsdata_cache = None      # 让下次重新读文件
        self._phone_ws_cache = (now, wid)
        return wid

    def phone_workspace_path(self):
        """「手机任务」工作区的磁盘路径（用于新建任务时对齐工作目录）。"""
        wid = self.phone_workspace_id()
        if not wid:
            return None
        item = self.workspaces().get(wid) or {}
        path = item.get("path")
        return str(path) if path else None

    def ensure_in_phone_workspace(self, sid):
        """把会话放进「手机任务」工作区。

        注意：harness 只允许把「在这个目录里创建」的会话算作该工作区成员
        （insertSessionBefore 对别的会话会报 the session is not accounted），
        所以真正要归组必须在 session/create 时给 workspaceId；这里只在
        「本来就属于该目录」时兜底用一下。
        """
        if not sid:
            return False
        wid = self.phone_workspace_id()
        if not wid:
            return False
        try:
            if sid in self.dsh.session_ids_in_workspace(wid):
                return True
            self.dsh.workspace_insert_session(wid, sid)
            self._wsdata_cache = None
            self._phone_ws_cache = None
            return True
        except dsh_client.DshError:
            return False

    def list_sessions(self):
        now = time.time()
        if self.sessions_cache and now - self.sessions_cache[0] < 5:
            return self.sessions_cache[1]
        out = []
        self.reconcile_threads_running()
        states = self._thread_states()
        # 手机任务线程
        for t in states:
            updated = None
            for it in reversed(t.items):
                if it.get("at"):
                    updated = it["at"]
                    break
            out.append({"id": t.id, "source": "console", "name": t.name, "workdir": t.workdir,
                        "updated": updated, "running": t.running,
                        "dsh_session_id": t.dsh_session_id,
                        "legacy": t.dsh_session_id is None})
        # Harness 会话（电脑端 GUI 同款）
        phone_sids = {t.dsh_session_id for t in states if t.dsh_session_id}
        archived = self.archived_session_ids()
        try:
            items = self.dsh.list_sessions()
        except dsh_client.DshError:
            items = []
        for s in items:
            sid = s.get("sessionId")
            if not sid or sid in phone_sids:
                continue
            if s.get("blank"):
                continue
            # 子代理 / 子智能体会话不进手机端会话目录（它们没有独立入口，只会淹没主会话）
            if s.get("origin") == "subagent" or s.get("parentSessionId") or s.get("parentId"):
                continue
            if sid in archived:      # 电脑端已归档的会话不在手机端显示
                continue
            proj = s.get("projections") or {}
            values = proj.get("values") or {}
            title = values.get("title")
            if not title:
                continue
            updated = s.get("updatedAt")
            out.append({"id": sid, "source": "desktop", "name": title,
                        "cwd": s.get("cwd"),
                        "updated": time.strftime("%Y-%m-%dT%H:%M:%S",
                                                 time.localtime(updated / 1000.0)) if updated else None,
                        "running": bool(s.get("running")),
                        "origin": s.get("origin")})
        # 列表行也带子代理数量（会话目录里能一眼看到哪个会话有子代理在跑）
        sub_total = {}
        sub_running = {}
        for s in items:
            if str(s.get("origin")) != "subagent":
                continue
            par = s.get("parentSessionId") or s.get("parentId")
            if not par:
                continue
            sub_total[par] = sub_total.get(par, 0) + 1
            if s.get("running"):
                sub_running[par] = sub_running.get(par, 0) + 1
        for row in out:
            key = row.get("dsh_session_id") or (row["id"] if row.get("source") == "desktop" else None)
            row["subagent_total"] = sub_total.get(key, 0)
            row["subagent_running"] = sub_running.get(key, 0)
        out.sort(key=lambda s: s.get("updated") or "", reverse=True)
        out = out[:60]
        # 顺带把每段对话当前的模型/思考强度带上（harness 的投影里就有，手机端直接显示）
        sel_map = {}
        for s in items:
            values = (s.get("projections") or {}).get("values") or {}
            sel = values.get("modelSelection") or {}
            sel = sel.get("next") or sel.get("lastUsed")
            if s.get("sessionId") and sel:
                sel_map[s["sessionId"]] = sel
        for row in out:
            key = row.get("dsh_session_id") or (row["id"] if row.get("source") == "desktop" else None)
            sel = sel_map.get(key)
            if sel:
                row["model"] = sel.get("model")
                row["provider"] = sel.get("provider")
                row["reasoningEffort"] = sel.get("reasoningEffort")
        self.sessions_cache = (now, out)
        return out

    # -- 模型 / 思考强度 ----------------------------------------------------

    def model_catalog(self, max_age=30):
        """可用模型清单（含每个模型支持的思考强度），30 秒缓存。"""
        now = time.time()
        if self.model_catalog_cache and now - self.model_catalog_cache[0] < max_age:
            return self.model_catalog_cache[1]
        try:
            catalog = self.dsh.model_catalog()
        except dsh_client.DshError:
            catalog = {}
        self.model_catalog_cache = (now, catalog)
        return catalog

    def session_target(self, kind, sid):
        """手机端的「手机任务」或「电脑端对话」对应的 DSH 会话 id。"""
        state = self.get_thread(sid)
        if state is not None and state.dsh_session_id:
            return state.dsh_session_id
        if kind == "session" and sid:
            return sid
        return None

    def switch_model(self, kind, sid, provider, model, reasoning_effort=None):
        """切换某段对话的模型/思考强度，返回 (selection, error)。"""
        target = self.session_target(kind, sid)
        if not target:
            return None, "这段对话还没关联到 DSH 会话，暂时不能切换模型"
        if not provider or not model:
            return None, "没有选择模型"
        # harness 自己不校验，这里先对着清单核一遍，避免写进一个不存在的模型把会话弄坏
        catalog = self.model_catalog()
        entry = None
        for group in catalog.get("groups") or []:
            if group.get("id") != provider:
                continue
            for item in group.get("models") or []:
                if item.get("id") == model:
                    entry = item
                    break
        if entry is None:
            return None, "这个模型不在可用清单里：%s / %s" % (provider, model)
        efforts = [e.get("id") for e in ((entry.get("reasoning") or {}).get("efforts") or [])]
        if reasoning_effort and efforts and reasoning_effort not in efforts:
            return None, "该模型不支持「%s」这个思考强度（可选：%s）" % (
                reasoning_effort, "、".join(efforts))
        try:
            res = self.dsh.select_model(target, provider, model, reasoning_effort)
        except dsh_client.DshError as exc:
            return None, "切换失败：" + str(exc)
        selected = (res or {}).get("selected") or {"provider": provider, "model": model}
        if reasoning_effort:
            selected.setdefault("reasoningEffort", reasoning_effort)
        self.sessions_cache = None      # 让列表/设置页立刻反映新选择
        return selected, None

    # -- 会话统计 / 消费（手机端输入栏下方那行状态） -------------------------

    def session_stats(self, sid):
        """某段对话的统计：轮数、步数、输出速度、token、缓存命中率。

        数据来自 harness 的两份会话投影：sessionStats（轮/步/解码耗时）与
        tokenUsage（未缓存输入 / 缓存读取 / 缓存写入 / 输出）。
        """
        target = self.session_target(None, sid) or sid
        try:
            items = self.dsh.list_sessions(cache_seconds=2.0)
        except dsh_client.DshError:
            return None
        for item in items:
            if item.get("sessionId") != target:
                continue
            values = (item.get("projections") or {}).get("values") or {}
            st = values.get("sessionStats") or {}
            usage = values.get("tokenUsage") or {}
            # 线上是扁平的；磁盘缓存里会多包一层 totals，两种都兼容
            totals = usage.get("totals") or usage
            uncached = int(totals.get("uncachedInputTokens") or 0)
            cache_read = int(totals.get("cacheReadTokens") or 0)
            cache_write = int(totals.get("cacheWriteTokens") or 0)
            output = int(totals.get("outputTokens") or 0)
            prompt = uncached + cache_read + cache_write
            decode_ms = float(st.get("decodeMs") or 0)
            decode_tokens = float(st.get("decodeTokens") or 0)
            return {
                "turns": int(st.get("turns") or 0),
                "steps": int(st.get("steps") or 0),
                "tps": round(decode_tokens / (decode_ms / 1000.0), 1) if decode_ms > 0 and decode_tokens > 0 else None,
                "tokens": prompt + output,
                "prompt": prompt,
                "output": output,
                "cached": cache_read,
                "uncached": uncached,
                "cacheWrite": cache_write,
                "cacheHit": round(cache_read * 100.0 / prompt, 1) if prompt > 0 else None,
            }
        return None

    def money(self, chat_tokens=None, max_age=60):
        """余额 / 官网消费 / 官网均价（元每亿 token），可选带上这段对话的估算消费。"""
        now = time.time()
        if not (self.money_cache and now - self.money_cache[0] < max_age):
            data = {"balance": None, "currency": "CNY", "officialCost": None,
                    "officialTokens": None, "avgPer1e8": None, "perToken": None}
            try:
                bal = self.get_balance()
            except Exception:
                bal = None
            infos = (bal or {}).get("balance_infos") or []
            if infos:
                data["balance"] = infos[0].get("total_balance")
                data["currency"] = infos[0].get("currency") or "CNY"
            cost = sess.load_official_cost(self.data_dir / "usage")
            if cost:
                data["officialCost"] = cost.get("cost")
                data["currency"] = cost.get("currency") or data["currency"]
            official = sess.load_official_usage(self.data_dir / "usage")
            if official:
                tokens = int(official.get("hit", 0)) + int(official.get("miss", 0)) + int(official.get("output", 0))
                data["officialTokens"] = tokens
                if tokens > 0 and data["officialCost"]:
                    per_token = float(data["officialCost"]) / tokens
                    data["perToken"] = per_token
                    data["avgPer1e8"] = round(per_token * 1e8, 2)
            self.money_cache = (now, data)
        out = dict(self.money_cache[1])
        if chat_tokens and out.get("perToken"):
            out["chatCost"] = round(float(chat_tokens) * out["perToken"], 2)
        return out

    def status(self, sid):
        """给手机端「输入栏下方」那行状态用的全部数据。"""
        stats = self.session_stats(sid) if sid else None
        tokens = (stats or {}).get("tokens")
        return {"session": stats, "money": self.money(tokens), "at": now_iso()}

    def team_of(self, sid, rows=None):
        """当前会话的子代理 / 子智能体状态（给手机端镜像）。

        数据来源：DSH 会话投影的 subagentCatalog（名字） + agentTeam（成员/任务）
        + 子会话自身的 running/updatedAt。
        """
        if not sid:
            return None
        try:
            rows = rows if rows is not None else self.dsh.list_sessions(cache_seconds=2.0)
        except Exception:
            return None
        parent = None
        for row in rows:
            if row.get("sessionId") == sid:
                parent = row
                break
        if parent is None:
            return None
        vals = (parent.get("projections") or {}).get("values") or {}
        catalog = {}
        for c in (vals.get("subagentCatalog") or []):
            if isinstance(c, dict) and c.get("id"):
                catalog[str(c["id"])] = str(c.get("label") or "")
        team = vals.get("agentTeam") or {}
        team_members = {}
        for m in (team.get("members") or []):
            if isinstance(m, dict) and m.get("id"):
                team_members[str(m["id"])] = m
        children = [r for r in rows
                    if str(r.get("origin")) == "subagent"
                    and (r.get("parentSessionId") == sid or r.get("parentId") == sid)]
        members = []
        for ch in children:
            cid = str(ch.get("sessionId") or "")
            m = team_members.get(cid) or {}
            cv = (ch.get("projections") or {}).get("values") or {}
            title = str(cv.get("title") or "").strip()
            if len(title) > 60:
                title = title[:60] + "…"
            updated = ch.get("updatedAt")
            members.append({
                "id": cid,
                "name": str(m.get("name") or ""),
                "label": catalog.get(cid) or title or "子代理",
                "role": str(m.get("role") or "teammate"),
                "phase": str(m.get("phase") or ""),
                "running": bool(ch.get("running")),
                "updated": int(updated) if updated else None,
            })
        members.sort(key=lambda x: (not x["running"], -(x.get("updated") or 0)))
        tasks = []
        for t in (team.get("tasks") or []):
            if not isinstance(t, dict):
                continue
            tasks.append({"subject": str(t.get("subject") or "")[:40],
                          "status": str(t.get("status") or ""),
                          "owner": str(t.get("ownerName") or "")})
        if not members and not tasks:
            return None
        return {"total": len(members),
                "running": sum(1 for m in members if m["running"]),
                "members": members[:12],
                "tasks": tasks[:12]}

    def session_plan(self, sid):
        """DSH 的计划 / 待办 / 目标（电脑端输入框上方那块内容），供手机端镜像显示。"""
        if not sid:
            return None
        try:
            rows = self.dsh.list_sessions(cache_seconds=2.0)
        except Exception:
            return None
        for row in rows:
            if row.get("sessionId") != sid:
                continue
            vals = (row.get("projections") or {}).get("values") or {}
            todos = []
            for t in (vals.get("todos") or []):
                if not isinstance(t, dict):
                    continue
                todos.append({"content": str(t.get("content") or ""),
                              "status": str(t.get("status") or "pending")})
            goal = vals.get("goal") or None
            goal_obj = None
            if isinstance(goal, dict):
                goal_obj = goal.get("goal") if isinstance(goal.get("goal"), dict) else goal
            objective = (goal_obj or {}).get("objective") if goal_obj else None
            plan = vals.get("plan") or {}
            out = {
                "todos": todos,
                "goal": {"objective": objective,
                         "id": (goal_obj or {}).get("id") if goal_obj else None,
                         "revision": (goal_obj or {}).get("revision") if goal_obj else None},
                "active": bool((plan or {}).get("active")),
                "pending": bool((plan or {}).get("pending")),
            }
            if not todos and not objective:
                return None
            return out
        return None

    def session_detail(self, sid):
        state = self.get_thread(sid)
        detail = None
        if state is not None:
            self._sweep_views()
            state.refresh(self.dsh, max_messages=120)
            detail = {"id": sid, "source": "console", "name": state.name,
                      "workdir": state.workdir, "running": state.running,
                      "dsh_session_id": state.dsh_session_id,
                      "items": state.snapshot()}
        else:
            view = self._get_view(sid)
            view.refresh(self.dsh, max_messages=120)
            detail = {"id": sid, "source": "desktop", "name": view.name,
                      "cwd": view.cwd, "running": view.running,
                      "items": view.snapshot()}
        try:                       # 统计/消费只是锦上添花，取不到不影响消息
            detail["status"] = self.status(sid)
        except Exception:
            detail["status"] = None
        try:
            detail["plan"] = self.session_plan(
                state.dsh_session_id if state is not None else sid)
        except Exception:
            detail["plan"] = None
        try:
            detail["team"] = self.team_of(
                state.dsh_session_id if state is not None else sid)
        except Exception:
            detail["team"] = None
        return detail

    def continue_session(self, sid, prompt, images=None, files=None):
        state = self.get_thread(sid)
        if state is not None:
            if state.running:
                return False, "busy"
            self.start_turn(sid, prompt, images, files)
            return True, "ok"
        try:
            slist = self.dsh.list_sessions(cache_seconds=1.0)
        except dsh_client.DshError:
            return False, "harness 不可达"
        running = any(s.get("sessionId") == sid and s.get("running") for s in slist)
        if running:
            return False, "busy"
        try:
            _v = self._get_view(sid)
            text, image_parts = self._split_content(prompt, images, files,
                                                    base_dir=getattr(_v, "cwd", None) or self.workdir_root)
            self.dsh.prompt(sid, text, mode="queue", image_parts=image_parts or None)
        except dsh_client.DshError as exc:
            return False, str(exc)
        view = self._get_view(sid)
        view.refresh(self.dsh, max_messages=120)
        return True, "ok"

    def stop_session(self, sid):
        state = self.get_thread(sid)
        target = state.dsh_session_id if state is not None else sid
        if not target:
            return
        try:
            self.dsh.cancel(target)
        except dsh_client.DshError:
            pass
        if state is not None:
            state.running = False

    # -- balance / usage ----------------------------------------------------

    def get_balance(self):
        now = time.time()
        if self.balance_cache and now - self.balance_cache[0] < 60:
            return self.balance_cache[1]
        if not self.api_key:
            return {"error": "未找到 DeepSeek API Key（DSH 凭据或 ~/.codex/config.toml）"}
        try:
            req = urllib.request.Request(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": "Bearer " + self.api_key})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self.balance_cache = (now, data)
            return data
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    def get_usage(self):
        totals = {"turns": 0}
        per_thread = []
        for state in self._thread_states():
            t = {"turns": 0, "id": state.id, "name": state.name}
            for it in state.items:
                if it.get("kind") == "turn_done":
                    t["turns"] += 1
                    totals["turns"] += 1
            if t["turns"]:
                per_thread.append(t)
        per_thread.sort(key=lambda x: -x["turns"])
        official = None
        try:
            official = sess.load_official_usage(self.data_dir / "usage")
        except Exception:
            official = None
        return {"total": totals, "per_thread": per_thread,
                "official": official, "at": now_iso()}

    def get_bg(self):
        try:
            p = self.data_dir / "phone_bg.json"
            if not p.exists():
                return None
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_bg(self, url, alpha):
        cur = self.get_bg() or {"url": "", "alpha": 90}
        if url is not None:
            cur["url"] = url
        if alpha is not None:
            cur["alpha"] = alpha
        (self.data_dir / "phone_bg.json").write_text(
            json.dumps(cur), encoding="utf-8")

# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "PhoneConsole/2.0"
    protocol_version = "HTTP/1.1"

    def handle(self):
        """客户端突然断开时不要打整段 traceback。

        手机切走页面 / 杀进程 / 隧道抖动都会让 keep-alive 连接被 RST，
        底层 recv 抛 ConnectionResetError（WinError 10054）。这类断开是正常现象，
        但 traceback 会写进 server.err.log，而 GUI 的「错误行」提取会把含
        Traceback/Error 的行当成启动失败原因展示给用户，所以这里静默关掉连接。
        """
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    # 早返回时最多替客户端读掉多少请求体（超过就关连接）
    DRAIN_LIMIT = 8 * 1024 * 1024
    # /api/* 的 JSON 请求体上限（背景图 data URL 最大 8MB，base64 后约 11MB）
    MAX_JSON_BODY = 32 * 1024 * 1024

    @property
    def app(self) -> Console:
        return self.server.console

    # -- helpers -----------------------------------------------------------

    def _maybe_close_header(self):
        """要关连接时必须明确告诉客户端（HTTP/1.1 keep-alive 下客户端否则会
        继续复用这条连接，白等一个已经被服务端关掉的 socket）。"""
        if self.close_connection:
            self.send_header("Connection", "close")

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._maybe_close_header()
        self.end_headers()
        self.wfile.write(body)

    def _text(self, text, status=200, content_type="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._maybe_close_header()
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._maybe_close_header()
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, relpath, content_type):
        file_path = SCRIPT_DIR / "web" / relpath
        if not file_path.is_file():
            self._json({"error": "not found"}, 404)
            return
        self._bytes(file_path.read_bytes(), content_type)

    def _discard_request_body(self, max_bytes=None):
        """早返回前把没读的请求体读掉，避免 HTTP/1.1 keep-alive 连接错位。

        不读的话，残留字节会被当成下一个请求的请求行（手机端表现为
        「上传了一个超大文件被拒之后，接下来就再也连不上」）。
        超过 max_bytes 的部分不再读、直接关连接：被拒绝的大文件不值得
        再搬一遍几十兆。
        """
        limit = self.DRAIN_LIMIT if max_bytes is None else max_bytes
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return
        todo = min(length, limit)
        while todo > 0:
            try:
                chunk = self.rfile.read(min(65536, todo))
            except OSError:
                self.close_connection = True
                return
            if not chunk:
                break
            todo -= len(chunk)
        if length > limit:
            self.close_connection = True

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return {}
        if length > self.MAX_JSON_BODY:
            # 超大 JSON 体一味读进来会直接吃掉内存；丢掉并关连接。
            self._discard_request_body()
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return {}

    def _authorized(self):
        """所有 /api/* 的统一鉴权口（含限速）：PIN 错误会按 IP 计数。"""
        supplied = self.headers.get("X-Console-Pin", "")
        # /api/raw 允许 ?pin= （桌面聊天里的 markdown 图片没法带请求头）
        if not supplied:
            try:
                q = parse_qs(urlparse(self.path).query)
                if urlparse(self.path).path == "/api/raw":
                    supplied = (q.get("pin") or [""])[0]
            except Exception:
                pass
        ok, _locked = self.app.check_pin(self.client_address[0], supplied)
        return ok

    def _allowed_roots(self):
        """允许的工作目录根：DSH 工作区 + 「手机任务」工作区。

        手机任务工作区的真实路径来自 DSH workspace 注册表，可能不在 workdir_root 下面
        （历史上就出现过 C:/.../work/手机任务），只认 workdir_root 会把用户选的目录
        静默替换成 Documents/Codex —— 新建对话的"工作目录不对"就是这个原因。
        """
        roots = [self.app.workdir_root]
        try:
            pw = self.app.phone_workspace_path()
            if pw:
                roots.append(Path(pw).expanduser().resolve())
        except Exception:
            pass
        # DSH 里注册过的所有工作区目录也允许（手机端选项目目录时不会再被静默替换成手机任务目录）
        try:
            for item in (self.app.workspaces() or {}).values():
                wp = (item or {}).get("path")
                if wp:
                    roots.append(Path(wp).expanduser().resolve())
        except Exception:
            pass
        return roots

    def _resolve_workdir(self, raw):
        if not raw:
            return None
        try:
            target = Path(raw).expanduser().resolve()
        except OSError:
            return None
        for root in self._allowed_roots():
            if target == root or root in target.parents:
                return str(target)
        return None

    def _sse_send(self, event):
        payload = json.dumps(event, ensure_ascii=False)
        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
        self.wfile.flush()

    # -- routes ------------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 默认入口 = 新版界面（webapp 构建产物）；构建缺失时回退旧版，保证永远有页面可用
        if path in ("/", "/index.html"):
            v2 = SCRIPT_DIR / "web" / "app" / "index.html"
            legacy = SCRIPT_DIR / "web" / "index.html"
            index = v2 if v2.is_file() else legacy
            if index.is_file():
                self._text(index.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")
            else:
                self._text("no UI found: build web/app via webapp/build.ps1", status=404)
            return

        # 旧版界面（微信风格）留在这里，方便对比与回退
        if path in ("/legacy", "/legacy/"):
            legacy = SCRIPT_DIR / "web" / "index.html"
            if legacy.is_file():
                self._text(legacy.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")
            else:
                self._text("web/index.html not found", status=404)
            return

        # 新版手机界面（webapp 构建产物：TypeScript + Preact，构建见 webapp/build.ps1）
        if path in ("/app", "/app/"):
            page = SCRIPT_DIR / "web" / "app" / "index.html"
            if page.is_file():
                self._text(page.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")
            else:
                self._text("web/app/index.html not built: run webapp/build.ps1", status=404)
            return
        if path.startswith("/app/"):
            # 只暴露构建产物里的平铺文件，禁止用 .. 之类的路径穿越
            name = os.path.basename(path[len("/app/"):])
            ctypes = {"app.js": "text/javascript; charset=utf-8",
                      "app.css": "text/css; charset=utf-8",
                      "index.html": "text/html; charset=utf-8"}
            if name in ctypes:
                self._serve_static("app/" + name, ctypes[name])
            else:
                self._json({"error": "not found"}, 404)
            return

        if path in STATIC_FILES:
            self._serve_static(*STATIC_FILES[path])
            return

        if not path.startswith("/api/"):
            self._json({"error": "not found"}, 404)
            return

        if path == "/api/login":
            self._json({"ok": True})
            return
        if not self._authorized():
            self._json({"error": "unauthorized"}, 401)
            return

        if path == "/api/info":
            self._json({
                "version": 2,
                "host": socket.gethostname(),
                "lan_ips": get_lan_ips(),
                "port": self.server.server_address[1],
                "model": "DSH agent",
                "provider": "DeepSeek Harness",
                "dsh_url": self.app.dsh_url,
                "dsh_connected": self.app.dsh_connected,
                "agent_preset": self.app.agent_preset,
                "workdir_root": str(self.app.workdir_root),
                "phone_workspace": self.app.phone_workspace_path(),
                "threads": [t.to_public(with_items=False) for t in self.app._thread_states()],
            })
            return

        if path == "/api/settings":
            self._json({
                "model": "DSH agent",
                "provider": "DeepSeek Harness",
                "agent_preset": self.app.agent_preset,
                "dsh_url": self.app.dsh_url,
            })
            return

        if path == "/api/models":
            # 模型清单 + 某段对话当前的选择：?kind=thread|session&id=<会话/任务 id>
            kind = (query.get("kind") or [""])[0]
            tid = (query.get("id") or [""])[0]
            catalog = self.app.model_catalog()
            current = None
            if tid:
                target = self.app.session_target(kind, tid)
                if target:
                    try:
                        current = self.app.dsh.session_selection(target)
                    except dsh_client.DshError:
                        current = None
            self._json({
                "catalog": catalog,
                "current": current or catalog.get("default") or None,
                "kind": kind or None,
                "id": tid or None,
                "canSwitch": bool(tid and self.app.session_target(kind, tid)),
            })
            return

        if path == "/api/balance":
            self._json(self.app.get_balance())
            return

        if path == "/api/usage":
            # CSV 超过 30 分钟没更新：后台拉一次官网用量（不阻塞本次响应）
            try:
                import console_core as _cc
                _cc.refresh_official_usage(max_age_sec=1800)
            except Exception:
                pass
            self._json(self.app.get_usage())
            return

        if path == "/api/bg":
            self._json(self.app.get_bg())
            return

        if path == "/api/archived":
            self._json(self.app.local_archived())
            return

        if path == "/api/sessions":
            self._json({"sessions": self.app.list_sessions()})
            return

        if path.startswith("/api/sessions/"):
            parts = path.split("/")
            if len(parts) < 4:
                self._json({"error": "bad path"}, 400)
                return
            sid = parts[3]
            if len(parts) == 4:
                detail = self.app.session_detail(sid)
                if detail is None:
                    self._json({"error": "session not found"}, 404)
                    return
                try:
                    detail["items"] = self.app.normalize_user_items(
                        detail.get("items") or [], detail.get("cwd") or self.app.session_workdir(sid))
                except Exception:
                    pass
                self._json(detail)
                return
            if parts[4] == "stream":
                self._stream_session(sid)
                return
            self._json({"error": "not found"}, 404)
            return

        if path == "/api/threads":
            self._json({"threads": [t.to_public(with_items=False) for t in self.app._thread_states()]})
            return

        if path.startswith("/api/threads/"):
            parts = path.split("/")
            if len(parts) < 4:
                self._json({"error": "bad path"}, 400)
                return
            tid = parts[3]
            state = self.app.get_thread(tid)
            if state is None:
                self._json({"error": "thread not found"}, 404)
                return
            if len(parts) == 4:
                pub = state.to_public()
                try:
                    pub["items"] = self.app.normalize_user_items(pub.get("items") or [], state.workdir)
                except Exception:
                    pass
                try:
                    pub["plan"] = self.app.session_plan(state.dsh_session_id or state.id)
                except Exception:
                    pub["plan"] = None
                try:
                    pub["team"] = self.app.team_of(state.dsh_session_id or state.id)
                except Exception:
                    pub["team"] = None
                self._json(pub)
                return
            action = parts[4]
            if action == "history":
                self._json({"events": state.snapshot(), "stderr_tail": list(state.stderr_tail)})
                return
            if action == "stream":
                self._stream_session(tid)
                return

        if path == "/api/files":
            raw = (query.get("path") or [""])[0]
            default_dir = str(self.app.phone_workspace_path() or self.app.workdir_root)
            target = self._resolve_workdir(raw or default_dir)
            if target is None:
                self._json({"error": "path outside allowed root"}, 403)
                return
            roots = self._allowed_roots()
            p_target = Path(target)
            root = next((r for r in roots if p_target == r or r in p_target.parents), self.app.workdir_root)
            entries = []
            try:
                p = Path(target)
                for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
                    try:
                        st = child.stat()
                    except OSError:
                        continue
                    entries.append({
                        "name": child.name,
                        "dir": child.is_dir(),
                        "size": st.st_size if not child.is_dir() else None,
                        "mtime": st.st_mtime,
                    })
            except OSError as exc:
                self._json({"error": str(exc)}, 500)
                return
            self._json({
                "path": str(p),
                "root": str(root),
                "can_up": p != root,
                "entries": entries,
            })
            return

        # 文件内容预览（图片缩略图/下载）：/api/raw?path=<相对workdir_root或绝对路径>
        if path == "/api/raw":
            raw = (query.get("path") or [""])[0]
            # markdown 图片（电脑端聊天里内联渲染）没法带 X-Console-Pin 头，这里允许 ?pin=
            qpin = (query.get("pin") or [""])[0]
            if qpin:
                try:
                    okp, _ = self.app.check_pin(self.client_address[0], qpin)
                    if not okp:
                        self._json({"error": "bad pin"}, 403)
                        return
                except Exception:
                    self._json({"error": "bad pin"}, 403)
                    return
            target = self._resolve_workdir(raw)
            if target is None or not Path(target).is_file():
                self._json({"error": "file not found"}, 404)
                return
            tp = Path(target)
            ext = tp.suffix.lower()
            mime = {
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
                ".txt": "text/plain; charset=utf-8", ".md": "text/markdown; charset=utf-8",
                ".json": "application/json", ".csv": "text/csv; charset=utf-8",
                ".html": "text/html; charset=utf-8",
            }.get(ext, "application/octet-stream")
            try:
                data = tp.read_bytes()
            except OSError as exc:
                self._json({"error": str(exc)}, 500)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self._maybe_close_header()
            self.end_headers()
            self.wfile.write(data)
            return

        self._json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/login":
            data = self._read_json()
            ip = self.client_address[0]
            ok, locked = self.app.check_pin(ip, data.get("pin", ""))
            if ok:
                self._json({"ok": True})
            elif locked:
                self._json({"error": "too many attempts, try again later"}, 429)
            else:
                self._json({"error": "wrong pin"}, 401)
            return
        if not self._authorized():
            self._discard_request_body()
            self._json({"error": "unauthorized"}, 401)
            return

        if path == "/api/usage/refresh":
            import console_core as _cc
            self._json(_cc.refresh_official_usage(force=True))
            return

        if path == "/api/archive":
            data = self._read_json()
            kind = "session" if str(data.get("kind")) == "session" else "thread"
            ident = str(data.get("id") or "").strip()
            if not ident:
                self._json({"error": "empty id"}, 400)
                return
            out = self.app.set_archived(kind, ident, bool(data.get("archived")))
            self._json({"ok": True, "archived": out.get(kind, [])})
            return

        if path == "/api/bg":
            data = self._read_json()
            url = data.get("url")
            alpha = data.get("alpha")
            if url is None and alpha is None:
                self._json({"error": "nothing to save"}, 400)
                return
            if url is not None and len(url) > 8 * 1024 * 1024:
                self._json({"error": "image too large (max 8MB)"}, 413)
                return
            if alpha is not None:
                try:
                    alpha = int(alpha)
                except (TypeError, ValueError):
                    alpha = 90
            self.app.save_bg(url, alpha)
            self._json({"ok": True})
            return

        if path == "/api/model":
            data = self._read_json()
            kind = str(data.get("kind") or "thread")
            rid = str(data.get("id") or "")
            selected, err = self.app.switch_model(
                kind, rid,
                str(data.get("provider") or ""), str(data.get("model") or ""),
                str(data.get("reasoningEffort") or "") or None,
            )
            if err:
                self._json({"error": err}, 502)
            else:
                self._json({"ok": True, "selected": selected})
            return

        if path == "/api/answer":
            data = self._read_json()
            session_id = str(data.get("sessionId") or "")
            rpc_id = str(data.get("rpcId") or "")
            answers = data.get("answers")
            if not session_id or not isinstance(answers, list):
                self._json({"error": "bad request"}, 400)
                return
            ok, result = self.app.answer_question(session_id, rpc_id, answers)
            if not ok:
                self._json({"error": result}, 500)
                return
            with self.app.threads_lock:
                self.app.pending_questions.pop(session_id, None)
            self._json({"ok": True, "result": result})
            return

        if path == "/api/threads":
            data = self._read_json()
            workdir = self._resolve_workdir(data.get("workdir"))
            if workdir is None:
                # 手机端没选目录：默认落到「手机任务」工作区，电脑端能看到同一目录
                workdir = self.app.phone_workspace_path() or str(self.app.workdir_root)
            try:
                state = self.app.create_thread(data.get("name"), workdir, data.get("prompt"))
            except dsh_client.DshError as exc:
                # 把具体原因回给手机端（会话创建失败通常是 harness 未运行/鉴权失效）
                self._json({"error": "创建 DSH 会话失败：" + str(exc)}, 502)
                return
            self._json({"thread": state.to_public()}, 201)
            return

        if path.startswith("/api/sessions/"):
            parts = path.split("/")
            if len(parts) < 5:
                self._json({"error": "bad path"}, 400)
                return
            sid = parts[3]
            action = parts[4]
            if action == "send":
                # v2 手机界面统一调 /api/{kind}/{id}/send；sessions 旧契约叫 continue。
                # 少了这个别名，手机在 session 里发消息就是 HTTP 404。
                action = "continue"
            if action == "continue":
                data = self._read_json()
                prompt = str(data.get("prompt", "")).strip()
                if not prompt:
                    self._json({"error": "empty prompt"}, 400)
                    return
                images = [p for p in (data.get("images") or []) if Path(p).is_file()]
                files = [p for p in (data.get("files") or []) if Path(p).is_file()]
                ok, msg = self.app.continue_session(sid, prompt, images, files)
                if not ok:
                    self._json({"error": msg}, 409 if msg == "busy" else 404)
                    return
                self._json({"ok": True})
                return
            if action == "stop":
                self._discard_request_body()
                self.app.stop_session(sid)
                self._json({"ok": True})
                return
            if action == "upload":
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    self._json({"error": "empty upload"}, 400)
                    return
                if length > 50 * 1024 * 1024:
                    self._discard_request_body()
                    self._json({"error": "file too large (max 50MB)"}, 413)
                    return
                filename = unquote(self.headers.get("X-Filename", ""))
                data = self.rfile.read(length)
                result = self.app.save_upload_to(self.app.session_workdir(sid), filename, data)
                self._json(result, 201)
                return
            self._json({"error": "not found"}, 404)
            return

        if path.startswith("/api/threads/"):
            parts = path.split("/")
            if len(parts) < 4:
                self._json({"error": "bad path"}, 400)
                return
            tid = parts[3]
            state = self.app.get_thread(tid)
            if state is None:
                self._json({"error": "thread not found"}, 404)
                return
            action = parts[4] if len(parts) > 4 else ""
            if action == "send":
                data = self._read_json()
                prompt = str(data.get("prompt", "")).strip()
                if not prompt:
                    self._json({"error": "empty prompt"}, 400)
                    return
                if state.running:
                    self._json({"error": "thread is busy"}, 409)
                    return
                images = [p for p in (data.get("images") or []) if Path(p).is_file()]
                files = [p for p in (data.get("files") or []) if Path(p).is_file()]
                self.app.start_turn(tid, prompt, images or None, files or None)
                self._json({"ok": True})
                return
            if action == "upload":
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    self._json({"error": "empty upload"}, 400)
                    return
                if length > 50 * 1024 * 1024:
                    self._discard_request_body()
                    self._json({"error": "file too large (max 50MB)"}, 413)
                    return
                filename = unquote(self.headers.get("X-Filename", ""))
                data = self.rfile.read(length)
                result = self.app.save_upload(state, filename, data)
                self._json(result, 201)
                return
            if action == "stop":
                self._discard_request_body()
                self.app.stop_thread(tid)
                self._json({"ok": True})
                return
            if action == "delete":
                self._discard_request_body()
                self.app.delete_thread(tid)
                self._json({"ok": True})
                return

        if path == "/api/fs/mkdir":
            data = self._read_json()
            workdir = self._resolve_workdir(data.get("path"))
            if workdir is None:
                self._json({"error": "path outside allowed root"}, 403)
                return
            try:
                Path(workdir).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self._json({"error": str(exc)}, 500)
                return
            self._json({"ok": True})
            return

        self._discard_request_body()
        self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if not self._authorized():
            self._discard_request_body()
            self._json({"error": "unauthorized"}, 401)
            return
        if path.startswith("/api/threads/"):
            parts = path.split("/")
            if len(parts) > 4 and parts[4] == "delete":
                self.app.delete_thread(parts[3])
                self._json({"ok": True})
                return
        self._json({"error": "not found"}, 404)

    # -- item streams (threads + harness sessions) --------------------------

    def _stream_items(self, snapshot, drain, subscribe, unsubscribe,
                      session_view, refresh=None, extra=None, snapshot_and_drain=None):
        """SSE：首帧全量快照，之后只推增量（session.item / session.item_update）。

        新版 harness 没有事件推送，实时性来自这里的 refresh 轮询。
        旧实现每 1.5 秒就把整份条目列表重发一遍（会话越长、观看者越多，
        重复流量和 harness 负载越大）；现在只有第一帧是全量，
        首帧用 snapshot_and_drain 在同一把锁里取快照 + 清空积压 ops，
        因此"快照之后、清空之前"到达的条目不会被丢掉。
        """
        cond = threading.Condition()
        subscribe(cond)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            meta = dict(session_view)
            if extra:
                meta.update(extra)
            if snapshot_and_drain is not None:
                items, _ops = snapshot_and_drain()   # 已被快照覆盖，无需再推
            else:
                items = snapshot()
                drain()
            self._sse_send({"type": "session.snapshot", "session": meta,
                            "items": items})
            last_refresh = 0.0
            while True:
                if refresh is not None and time.time() - last_refresh >= 1.5:
                    last_refresh = time.time()
                    try:
                        refresh()
                    except Exception:
                        pass
                    if snapshot_and_drain is None:
                        # 兼容旧调用方：没有原子快照接口时仍重发全量快照
                        self._sse_send({"type": "session.snapshot", "session": meta,
                                        "items": snapshot()})
                for op, item in drain():
                    if item is None:
                        continue
                    if op == "update":
                        self._sse_send({"type": "session.item_update", "item": item})
                    else:
                        self._sse_send({"type": "session.item", "item": item})
                with cond:
                    cond.wait(timeout=1.5)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            unsubscribe(cond)

    def _stream_session(self, sid):
        """Stream display items for a phone thread or any harness session."""
        state = self.app.get_thread(sid)
        if state is not None:
            state.refresh(self.app.dsh, max_messages=120)
            self._stream_items(
                state.snapshot, state.drain_ops,
                state.add_subscriber, state.remove_subscriber,
                {"id": sid, "source": "console", "name": state.name,
                 "running": state.running},
                refresh=lambda: state.refresh(self.app.dsh, max_messages=80),
                snapshot_and_drain=state.snapshot_and_drain)
            return
        view = self.app._get_view(sid)
        view.refresh(self.app.dsh, max_messages=120)
        self._stream_items(
            view.snapshot, view.drain_ops,
            view.add_subscriber, view.remove_subscriber,
            {"id": sid, "source": "desktop", "name": view.name,
             "cwd": view.cwd, "running": view.running},
            refresh=lambda: view.refresh(self.app.dsh, max_messages=80),
            snapshot_and_drain=view.snapshot_and_drain)

    def log_message(self, fmt, *args):
        sys.stderr.write("[console] %s %s\n" % (self.address_string(), fmt % args))


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Phone remote console for DSH agent")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--pin", default=None, help="Access PIN (auto-generated if omitted)")
    parser.add_argument("--workdir-root", default=str(Path.home() / "Documents" / "Codex"))
    parser.add_argument("--dsh-url", default=None,
                        help="DeepSeek Harness 地址；指定后只连它、不再自动发现。"
                             "不填则自动发现（桌面端优先，找不到再退到网页端 3080）")
    parser.add_argument("--dsh-wait", type=float, default=40.0,
                        help="启动时等待 harness 出现的秒数，0 表示不等待（默认 40）")
    parser.add_argument("--agent-preset", default=DEFAULT_AGENT_PRESET,
                        help="DSH agent preset for phone-created sessions")
    parser.add_argument("--dsh-credentials", default=None,
                        help="harness 凭证文件路径（默认自动查找 .credentials.yaml）")
    args = parser.parse_args()

    # 先把 stdout/stderr 切成 UTF-8：提示和报错都会被重定向进 server.out/err.log，
    # 而 GUI 是按 UTF-8 读日志的，用默认 ANSI 编码写会整篇乱码。
    for _stream in (sys.stdout, sys.stderr):
        if _stream is not None and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    if not args.pin:
        pin_file = SCRIPT_DIR / "console_data" / "pin.txt"
        if pin_file.is_file():
            args.pin = pin_file.read_text(encoding="utf-8-sig").strip()
        else:
            args.pin = "".join(secrets.choice("0123456789") for _ in range(8))
            pin_file.parent.mkdir(parents=True, exist_ok=True)
            pin_file.write_text(args.pin, encoding="utf-8")

    # ---- 对接目标：默认自动发现（桌面端 DeepSeek Harness 优先） ----------------
    settings_path = SCRIPT_DIR / "console_data" / "settings.json"
    explicit = (args.dsh_url or "").strip()
    if explicit.lower() in ("", "auto"):
        explicit = None
    if explicit is None:
        print("正在查找 DeepSeek Harness（桌面端优先，找不到再用网页端 3080）…", flush=True)
    resolved, source, diag, credentials = dsh_client.discover_dsh_url(
        explicit=explicit, settings_path=settings_path,
        wait_seconds=args.dsh_wait,
        logger=lambda m: print("  " + m, flush=True))
    if not resolved:
        lines = ["未找到可用的 DeepSeek Harness。"]
        if diag:
            # 扫到了候选但都连不上时，把真实原因（超时/401/被占用）一起报出来
            lines.append(diag)
        lines += [
            "  · 桌面端：启动「DeepSeek Harness」桌面程序，本程序会自动发现它的端口（推荐）",
            "  · 网页端：运行 dsh web --port 3080",
            "  · 也可手动指定：加参数 --dsh-url http://127.0.0.1:3080，",
            "    或在该文件里加一个 dsh_url 字段：",
            f"    {settings_path}",
        ]
        sys.exit("\n".join(lines))
    args.dsh_url = resolved
    args.dsh_source = source
    if credentials and not getattr(args, "dsh_credentials", None):
        # 能通过鉴权的那份凭证可能不是默认解析出来的那个（真实踩过：默认命中了
        # 程序目录附近 .upgrade-backup-*/ 里的过期密钥 → cookie 被判 401）。
        # 把它固定下来，后续所有 harness 请求都用它。
        args.dsh_credentials = credentials
        print(f"  凭证文件: {credentials}", flush=True)

    if os.name == "nt":
        try:
            import ctypes
            if not ctypes.windll.shell32.IsUserAnAdmin():
                print("提示: 当前未以管理员身份运行。DSH 会话的命令沙箱可能需要管理员权限")
                print("      （与电脑端一致）。建议以管理员身份运行，或接受 UAC 弹窗。")
        except Exception:
            pass

    console = Console(args)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.console = console

    print("=" * 56)
    print("  手机远程控制台（DSH 版）已启动")
    print(f"  本机访问:   http://127.0.0.1:{args.port}")
    lan = get_lan_ips()
    ts_ips = [ip for ip in lan if ip in set(tailscale_ips())]
    for ip in lan:
        tag = "   ← Tailscale 固定地址（推荐）" if ip in ts_ips else ""
        print(f"  局域网访问: http://{ip}:{args.port}{tag}")
    if ts_ips:
        print(f"  另有 Tailscale 固定地址: http://{ts_ips[0]}:{args.port}（手机需装 Tailscale 并登录同一账号）")
    if lan and all(is_cgnat(ip) for ip in lan) and not ts_ips:
        print("  提示: 只检测到运营商 NAT / 热点地址（100.64~100.127），手机多半连不上；")
        print("        请用管理界面上的公网隧道地址（或直接扫二维码）。")
    print(f"  PIN: {args.pin}")
    print(f"  PIN 文件: {SCRIPT_DIR / 'console_data' / 'pin.txt'}")
    print(f"  DSH: {console.dsh_url}  agentPreset={console.agent_preset}"
          f"  （对接：{getattr(args, 'dsh_source', '指定地址')}）")
    if ts_ips:
        print("  手机端零安装用法：用管理界面上的隧道地址（或直接扫二维码）；装了 Tailscale 才用上面那个固定地址")
    elif lan and not all(is_cgnat(ip) for ip in lan):
        print("  手机和电脑连同一个 Wi-Fi，浏览器打开上面的局域网地址，输入 PIN 即可")
    else:
        print("  手机请用隧道地址（手机端地址见管理界面二维码下方，或 console_data/phone-address.txt）")
    print("=" * 56, flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        console._shutdown = True


if __name__ == "__main__":
    main()

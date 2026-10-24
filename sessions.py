"""Codex 会话文件解析（遗留）+ DSH 事件 → 显示条目翻译（stdlib only）。

本文件只有两部分在线上使用：
  * ``scan_usage`` / ``parse_official_usage_csv`` / ``load_official_usage`` /
    ``load_official_cost``：用量与对账读取（gui.pyw 依赖 ``scan_usage``）；
  * 文件末尾的 ``DshItems``：DSH 会话事件 → 手机端显示条目。
中间那段 Codex rollout 解析器（``rollout_line_items`` / ``parse_rollout`` /
``DesktopWatcher`` / ``console_items_from_events`` / ``session_file_by_id`` 等）
是新版 harness 之前的遗留实现，全仓库已无引用（见各函数上的标注），
保留仅为回放旧会话时参考，改动时不必跟随新协议。
"""

import csv
import json
import os
import threading
import time
from pathlib import Path


# --------------------------------------------------------------------------
# 遗留：Codex rollout 事件解析（无引用，勿在新代码里调用）
# --------------------------------------------------------------------------

def rollout_line_items(d):
    """Extract display items from one rollout JSONL line."""
    out = []
    ts = d.get("timestamp", "")
    t = d.get("type")
    pay = d.get("payload") or {}
    pt = pay.get("type")
    if t == "event_msg" and pt == "user_message":
        msg = (pay.get("message") or "").strip()
        if msg:
            out.append({"kind": "user", "text": msg, "at": ts})
    elif t == "event_msg" and pt == "agent_message":
        msg = (pay.get("message") or "").strip()
        if msg:
            out.append({"kind": "agent", "text": msg, "at": ts, "phase": pay.get("phase")})
    elif t == "response_item" and pt == "message":
        role = pay.get("role")
        if role in ("user", "assistant"):
            texts = [c.get("text", "") for c in (pay.get("content") or [])
                     if c.get("type") in ("input_text", "output_text") and c.get("text")]
            text = "\n".join(texts).strip()
            if text:
                out.append({"kind": "user" if role == "user" else "agent", "text": text, "at": ts})
    elif t == "response_item" and pt == "function_call":
        name = pay.get("name", "")
        args = pay.get("arguments", "")
        try:
            argd = json.loads(args) if args else {}
        except json.JSONDecodeError:
            argd = {}
        cmd = argd.get("command") or argd.get("cmd") or args
        out.append({"kind": "command", "name": name, "command": cmd, "output": None, "status": "run", "at": ts})
    elif t == "response_item" and pt == "function_call_output":
        out.append({"kind": "command_update", "output": (pay.get("output") or "")[:3000], "status": "done", "at": ts})
    return out


def merge_item(items, it):
    """Append an item, attaching command_update to the last open command."""
    if it.get("kind") == "command_update":
        for prev in reversed(items):
            if prev.get("kind") == "command" and prev.get("output") is None:
                prev["output"] = it.get("output")
                prev["status"] = it.get("status", "done")
                return
        return
    items.append(it)


def parse_rollout(path):
    """[遗留·全仓库无引用] Parse a Codex rollout JSONL. Returns (meta, items)."""
    meta = {}
    items = []
    prev_text = {"user": None, "agent": None}
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return meta, items
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "session_meta":
                pay = d.get("payload") or {}
                for k in ("session_id", "cwd", "originator", "cli_version", "model_provider", "model", "title"):
                    if k in pay:
                        meta[k] = pay[k]
                continue
            for it in rollout_line_items(d):
                kind = it.get("kind")
                text = it.get("text")
                if kind in ("user", "agent") and text:
                    if text == prev_text[kind]:
                        continue
                    prev_text[kind] = text
                    if kind == "user" and ("# AGENTS.md" in text or "<INSTRUCTIONS>" in text):
                        continue
                merge_item(items, it)
    return meta, items


def summarize_rollout(path):
    """Fast summary for the session list (no full parse)."""
    title = None
    counts = {"user": 0, "agent": 0, "command": 0}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"type":"event_msg"' in line:
                    if '"user_message"' in line:
                        counts["user"] += 1
                        if title is None:
                            try:
                                d = json.loads(line)
                                title = (d.get("payload", {}).get("message") or "").strip()[:80]
                            except (json.JSONDecodeError, AttributeError):
                                pass
                    elif '"agent_message"' in line:
                        counts["agent"] += 1
                elif '"type":"response_item"' in line and '"function_call"' in line:
                    counts["command"] += 1
    except OSError:
        pass
    if not title:
        title = "(no text messages)"
    return title, counts


def session_originator(path):
    """读取会话的创建来源：Codex Desktop=电脑端 / codex_exec=手机任务 / 其他。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") == "session_meta":
                    return (d.get("payload") or {}).get("originator", "") or ""
    except OSError:
        pass
    return ""


_SCAN_CACHE = {}
_SCAN_LOCK = threading.Lock()

# --- 以上到「遗留」段落为止的旧 Codex rollout 解析器已无引用（见文件头说明）；---
# --- 以下是线上代码：用量/对账读取（gui.pyw 依赖 scan_usage）。              ---


def _parse_usage_file(f):
    """解析单个会话文件的用量，返回 (turns, last_usage, title) 或 None。"""
    last = None
    turns = 0
    title = None
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"token_count"' in line:
                    try:
                        d = json.loads(line)
                        pay = d.get("payload", {})
                        info = pay.get("info") or {}
                        if pay.get("type") == "token_count" and info.get("total_token_usage"):
                            last = info["total_token_usage"]
                            turns += 1
                    except json.JSONDecodeError:
                        pass
                elif title is None and '"user_message"' in line:
                    try:
                        d = json.loads(line)
                        pay = d.get("payload", {})
                        if pay.get("type") == "user_message" and pay.get("message"):
                            title = pay["message"].strip()[:40]
                    except json.JSONDecodeError:
                        pass
    except OSError:
        return None
    if not last:
        return None
    return turns, last, title


def scan_usage(codex_home, force=False):
    """Aggregate token usage by scanning all session rollout files.

    Each session file ends with cumulative ``token_count`` events; the last one
    holds the session's total usage. Works without a running server.
    Uses per-file (mtime, size) cache so repeated calls only re-read files
    that actually changed (Codex appends to the active session file).
    """
    keys = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
            "output_tokens", "reasoning_output_tokens")
    totals = {k: 0 for k in keys}
    totals["turns"] = 0
    # Codex ???????? archived_sessions?????????????
    bases = [Path(codex_home) / "sessions", Path(codex_home) / "archived_sessions"]
    files = []
    for b in bases:
        if not b.is_dir():
            continue
        try:
            files.extend(b.rglob("*.jsonl"))
        except OSError:
            continue
    cache = _SCAN_CACHE
    with _SCAN_LOCK:
        live = {str(p) for p in files}
        for k in list(cache):
            if k not in live:
                del cache[k]
    per_session = []
    for f in files:
        key = str(f)
        try:
            st = f.stat()
            sig = (round(st.st_mtime, 3), st.st_size)
        except OSError:
            continue
        entry = cache.get(key)
        if not force and entry is not None and entry[0] == sig:
            parsed = entry[1]
        else:
            parsed = _parse_usage_file(f)
            with _SCAN_LOCK:
                cache[key] = (sig, parsed)
        if parsed:
            turns, last, title = parsed
            miss = max(last.get("cache_write_input_tokens", 0),
                       last.get("input_tokens", 0) - last.get("cached_input_tokens", 0))
            total = (last.get("input_tokens", 0) + last.get("output_tokens", 0)
                     + last.get("reasoning_output_tokens", 0))
            per_session.append({
                "name": title or f.stem.split("-")[-1][:10],
                "turns": turns,
                "input": last.get("input_tokens", 0),
                "output": last.get("output_tokens", 0),
                "reasoning": last.get("reasoning_output_tokens", 0),
                "cached": last.get("cached_input_tokens", 0),
                "cache_write": miss,
                "total": total,
            })
            for k in keys:
                if k == "cache_write_input_tokens":
                    totals[k] += miss
                else:
                    totals[k] += last.get(k, 0)
            totals["turns"] += turns
    per_session.sort(key=lambda x: -x["total"])
    return totals, per_session


def parse_official_usage_csv(path):
    """解析 DeepSeek 官网导出的用量 CSV（兼容 start_time_iso / utc_date 字段）。
    返回含按天明细的汇总或 None。"""
    per_day = {}
    keys = {"input_cache_hit_tokens": "hit", "input_cache_miss_tokens": "miss",
            "output_tokens": "output", "request_count": "requests"}
    try:
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                t = (r.get("type") or "").strip()
                st = (r.get("start_time_iso") or r.get("utc_date") or "")[:10]
                if t not in keys or len(st) != 10:
                    continue
                try:
                    amt = int(float(r.get("amount") or 0))
                except (TypeError, ValueError):
                    amt = 0
                per_day.setdefault(st, {"hit": 0, "miss": 0, "output": 0, "requests": 0})[keys[t]] += amt
    except OSError:
        return None
    if not per_day:
        return None
    return {"hit": sum(d["hit"] for d in per_day.values()),
            "miss": sum(d["miss"] for d in per_day.values()),
            "output": sum(d["output"] for d in per_day.values()),
            "requests": sum(d["requests"] for d in per_day.values()),
            "days": sorted(per_day), "per_day": per_day}


def load_official_cost(usage_dir):
    """读取官网导出的对账金额（usage/cost.json），返回 {"cost": float, "currency": str} 或 None。"""
    import json as _json
    p = Path(usage_dir) / "cost.json"
    if not p.is_file():
        return None
    try:
        data = _json.loads(p.read_text(encoding="utf-8"))
        return {"cost": float(data.get("cost") or 0), "currency": str(data.get("currency") or "CNY")}
    except (OSError, ValueError, TypeError):
        return None


def load_official_usage(usage_dir):
    """合并 usage 目录下所有官网用量 CSV（按天取最大），供电脑端/手机端共用。
    返回 {"hit","miss","output","requests","days","hit_rate"} 或 None。"""
    d = Path(usage_dir)
    if not d.is_dir():
        return None
    files = sorted(d.glob("*.csv"))
    if not files:
        return None
    merged = {}
    for p in files:
        parsed = parse_official_usage_csv(p)
        if not parsed:
            continue
        for day, dd in parsed["per_day"].items():
            cur = merged.get(day)
            if cur is None:
                merged[day] = dict(dd)
            else:
                for k in ("hit", "miss", "output", "requests"):
                    cur[k] = max(cur[k], dd[k])
    if not merged:
        return None
    # 官网接口会把「整个月」都返回，未来日期全是 0；不滤掉的话手机端「近 7 天」全是 0
    today = time.strftime("%Y-%m-%d", time.localtime())
    merged = {k: v for k, v in merged.items() if k <= today}
    if not merged:
        return None
    hit = sum(d["hit"] for d in merged.values())
    miss = sum(d["miss"] for d in merged.values())
    total_in = hit + miss
    return {"hit": hit, "miss": miss,
            "output": sum(d["output"] for d in merged.values()),
            "requests": sum(d["requests"] for d in merged.values()),
            "days": sorted(merged),
            "per_day": merged,
            "hit_rate": round(hit / total_in * 100, 2) if total_in else 0.0}


def session_file_by_id(codex_home, sid):
    """[遗留·全仓库无引用] 按会话 id 找 rollout 文件。"""
    for base in (Path(codex_home) / "sessions", Path(codex_home) / "archived_sessions"):
        if not base.is_dir():
            continue
        for p in base.rglob("*.jsonl"):
            if p.stem == sid or p.stem.split("-")[-1] == sid:
                return p
    return None


def console_event_items(ev):
    """Map console thread events to unified session items."""
    t = ev.get("type")
    if t == "user.message":
        return [{"kind": "user", "text": ev.get("text", ""), "at": ev.get("at")}]
    if t == "item.started":
        it = ev.get("item", {})
        if it.get("type") == "command_execution":
            return [{"kind": "command", "name": "shell_command", "command": it.get("command"),
                     "output": None, "status": "run", "at": ev.get("at")}]
        return []
    if t == "item.completed":
        it = ev.get("item", {})
        if it.get("type") == "agent_message":
            return [{"kind": "agent", "text": it.get("text", ""), "at": ev.get("at")}]
        if it.get("type") == "command_execution":
            return [{"kind": "command_update", "output": (it.get("aggregated_output") or "")[:3000],
                     "status": "done", "at": ev.get("at")}]
        return []
    if t == "turn.completed":
        return [{"kind": "turn_done", "usage": ev.get("usage"), "at": ev.get("at")}]
    if t == "process.exited":
        return [{"kind": "status", "running": False, "exit_code": ev.get("exit_code"), "at": ev.get("at")}]
    if t in ("process.error", "turn.failed"):
        return [{"kind": "error", "text": ev.get("message") or (ev.get("error") or {}).get("message", ""),
                 "at": ev.get("at")}]
    return []


def console_items_from_events(events):
    """[遗留·全仓库无引用] 旧控制台事件 → 显示条目。"""
    items = []
    for ev in events:
        for it in console_event_items(ev):
            merge_item(items, it)
    return items


class DesktopWatcher:
    """[遗留·全仓库无引用] Polls a rollout file and emits newly appended display items."""

    def __init__(self, sid, path, codex_home=None):
        self.sid = sid
        self.path = path
        self.codex_home = codex_home
        self.offset = 0
        self.running = False
        self.proc = None
        self.fork_base = None
        self.fork_sid = None
        self.subscribers = set()
        self.pending = []
        self.stderr_tail = []
        self.lock = threading.RLock()
        self.thread = None

    def add_subscriber(self, cond):
        with self.lock:
            self.subscribers.add(cond)

    def remove_subscriber(self, cond):
        with self.lock:
            self.subscribers.discard(cond)

    def notify_all(self):
        with self.lock:
            conds = list(self.subscribers)
        for c in conds:
            with c:
                c.notify_all()

    def add_pending(self, items):
        if isinstance(items, dict):
            items = [items]
        with self.lock:
            self.pending.extend(items)

    def drain_pending(self):
        with self.lock:
            out, self.pending = self.pending, []
        return out

    def reset_offset(self):
        """Tail strictly after the current file end (call after a snapshot)."""
        try:
            with open(self.path, "rb") as fh:
                fh.seek(0, 2)
                self.offset = fh.tell()
        except OSError:
            pass

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def _loop(self):
        while True:
            with self.lock:
                alive = bool(self.subscribers) or self.running
            if not alive:
                return
            self._poll()
            self.notify_all()
            time.sleep(1.5)

    def _poll(self):
        new_items = []
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                data = fh.read()
                if data:
                    self.offset += len(data)
                    for line in data.decode("utf-8", "replace").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        for it in rollout_line_items(d):
                            new_items.append(it)
        except OSError:
            pass
        if new_items:
            self.add_pending(new_items)
        if self.running and self.fork_base and not self.fork_sid:
            self._detect_fork()

    def _detect_fork(self):
        base = Path(self.codex_home) / "sessions" if self.codex_home else None
        if not base or not base.is_dir():
            return
        newest = None
        try:
            for p in base.rglob("*.jsonl"):
                if str(p) == str(self.path):
                    continue
                try:
                    mt = p.stat().st_mtime
                except OSError:
                    continue
                if mt >= self.fork_base - 5:
                    if newest is None or mt > newest[0]:
                        newest = (mt, p)
        except OSError:
            return
        if newest:
            p = newest[1]
            sid = p.stem.split("-")[-1]
            if sid and sid != self.sid:
                self.fork_sid = sid
                self.add_pending({"kind": "fork", "sid": sid})


# --------------------------------------------------------------------------
# DSH (DeepSeek Harness) session-event -> display-item translation
# --------------------------------------------------------------------------
# The phone console no longer parses Codex rollout files; phone tasks and
# "desktop" sessions are DSH sessions driven through the harness API. The
# harness emits a rich session-event stream (user/message, assistant/chunk
# deltas, tool/call, tool/result, turn/start ...). This translator folds that
# stream into the same stable display-item model the phone UI already knows
# (user / agent / command / status / error) plus a few new kinds
# (reasoning / tool / agent-delta streaming bubbles).

COMMAND_TOOLS = ("bash", "pwsh", "shell", "cmd", "powershell")
# 会向人提问的工具：命中时生成 question 卡片（手机端已有该 kind 的渲染与回答入口）
ASK_TOOLS = ("ask_user_question", "ask-user-question", "askUserQuestion")
MAX_TOOL_OUTPUT = 4000
# 单个会话最多保留的显示条目（超出只留最近这些 + 一条提示条目），
# 否则长会话的 items 会无限增长，每次快照都要重发整份列表。
MAX_ITEMS = 400


def _content_text(content):
    """Join text blocks from a DSH content array (user message / tool result)."""
    out = []
    for blk in content or []:
        bt = blk.get("type")
        if bt == "text" and blk.get("text"):
            out.append(blk["text"])
        elif bt == "tool-result":
            out.append(_content_text(blk.get("content")))
    return "\n".join(out).strip()


def _parse_args(args):
    """工具调用参数：harness 给的是 JSON 字符串，解不出来就返回 {}。"""
    if isinstance(args, dict):
        return args
    try:
        argd = json.loads(args) if args else {}
    except (json.JSONDecodeError, TypeError):
        argd = {}
    return argd if isinstance(argd, dict) else {}


def _command_of(name, args):
    """命令类工具（bash/pwsh/...）返回要显示的命令行，否则 None。

    `tool/call` 与 `assistant/message` 的 tool-call block 都要用它，
    两边都走同一个判定，命令卡片才不会因为消息先到而被当成普通工具。
    """
    if name not in COMMAND_TOOLS:
        return None
    cmd = _parse_args(args).get("command")
    return cmd if isinstance(cmd, str) and cmd else None


def _questions_of(args):
    """提问工具的参数 → 手机端 question 卡片要的 questions 列表，取不到返回 None。"""
    qs = _parse_args(args).get("questions")
    if not isinstance(qs, list):
        return None
    out = []
    for q in qs:
        if isinstance(q, dict) and (q.get("question") or q.get("id")):
            out.append({
                "id": q.get("id"),
                "header": q.get("header"),
                "question": q.get("question"),
                "options": [o for o in (q.get("options") or []) if isinstance(o, dict)],
            })
    return out or None


def _fmt_time(ms):
    try:
        if not isinstance(ms, (int, float)) or ms <= 0:
            return ""
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ms / 1000.0))
    except (OSError, ValueError, OverflowError, TypeError):
        return ""


class DshItems:
    """Incremental DSH event -> display-item translator.

    Holds ONE mutable item list (the live conversation state). `feed(event)`
    returns ops: ("append", item) for new items, ("update", item) when an
    existing item mutated (streaming bubbles / tool results).

    注意：翻译器本身不按 seq 去重（同一批事件喂两遍就是两遍），
    去重由 server 的 ThreadState/DshSessionView 在锁内完成（见 _feed_events）。
    """

    def __init__(self, session_id=None):
        self.items = []
        self._ids = {}
        self._seq = 0
        self._open_text = None
        self._open_reasoning = None
        self._tools = {}          # tool callId -> item id
        self._open_turn = None
        self.session_id = session_id   # 提问卡片回填用（手机端回答时要带会话 id）
        self._notice = None            # 截断提示条目（只保留一条，文本原地更新）
        self._dropped = 0              # 已被裁掉的条目数

    # -- helpers ------------------------------------------------------------

    def _new(self, kind, **kw):
        self._seq += 1
        item = {"id": "d%d" % self._seq, "kind": kind, **kw}
        self.items.append(item)
        self._ids[item["id"]] = item
        self._trim()
        return item

    def _trim(self):
        """条目上限：只保留最近 MAX_ITEMS 条，并在最前面留一条提示条目。

        截断只影响服务端的 items（内存与快照体积）；手机端重开对话时
        先收到的是全量快照，因此会自然回到"最近 N 条"。
        """
        if len(self.items) <= MAX_ITEMS:
            return
        if self._notice is None:
            drop = len(self.items) - (MAX_ITEMS - 1)
            for it in self.items[:drop]:
                self._ids.pop(it.get("id"), None)
            del self.items[:drop]
            self._dropped += drop
            self._seq += 1
            notice = {"id": "d%d" % self._seq, "kind": "notice",
                      "text": "更早的 %d 条记录已省略" % self._dropped}
            self._notice = notice
            self._ids[notice["id"]] = notice
            self.items.insert(0, notice)
            return
        drop = len(self.items) - MAX_ITEMS
        if drop <= 0:
            return
        # items[0] 是提示条目，不能丢：从下标 1 开始丢最老的
        for it in self.items[1:1 + drop]:
            self._ids.pop(it.get("id"), None)
        del self.items[1:1 + drop]
        self._dropped += drop
        self._notice["text"] = "更早的 %d 条记录已省略" % self._dropped

    def _tool_item(self, name, args, at, cid=None):
        """按工具类型建条目：提问 → question，命令 → command，其余 → tool。

        `tool/call` 与 `assistant/message` 的 tool-call block 都会经过这里，
        两个分支的判定因此完全一致（谁先到都得到同一种卡片）。
        """
        if name in ASK_TOOLS:
            questions = _questions_of(args)
            if questions:
                return self._new("question", questions=questions, rpc_id=cid,
                                 sessionId=self.session_id, status="run", at=at)
        cmd = _command_of(name, args)
        if cmd is not None:
            return self._new("command", name=name, command=cmd, output=None,
                             status="run", error=False, at=at)
        # output/error 先建好：tool/result 落地时是原地 update，
        # 预建键就不会出现"序列化时 dict 变大"的竞争（P1-7）。
        return self._new("tool", name=name, args=args, output=None, error=False,
                         status="run", at=at)

    def _update(self, item_id, **kw):
        item = self._ids.get(item_id)
        if item is None:
            return None
        item.update(kw)
        return item

    def _close_streams(self):
        if self._open_text:
            self._update(self._open_text, stream=False)
            self._open_text = None
        if self._open_reasoning:
            self._update(self._open_reasoning, stream=False)
            self._open_reasoning = None

    # -- main entry ----------------------------------------------------------

    def feed(self, ev):
        """Translate one DSH session event; returns a list of (op, item)."""
        ops = []
        if not isinstance(ev, dict):
            return ops
        t = ev.get("type")
        d = ev.get("data") or {}
        at = _fmt_time(ev.get("time"))

        if t == "user/message":
            # 只渲染真实用户消息；系统注入的种子消息（运行时上下文/技能目录）
            # source.kind 为 plugin / skill-catalog，跳过。
            if (d.get("source") or {}).get("kind") != "user":
                return ops
            text = _content_text(d.get("content"))
            if text:
                ops.append(("append", self._new("user", text=text, at=at)))
        elif t == "turn/start":
            self._open_turn = d.get("turn")
            self._close_streams()
            ops.append(("append", self._new("status", running=True, at=at)))
        elif t == "assistant/chunk":
            chunk = d.get("chunk") or {}
            ct = chunk.get("type")
            if ct == "block-start":
                bt = chunk.get("blockType")
                if bt == "reasoning":
                    item = self._new("reasoning", text="", at=at, stream=True)
                    self._open_reasoning = item["id"]
                    ops.append(("append", item))
                elif bt == "text":
                    item = self._new("agent", text="", at=at, stream=True)
                    self._open_text = item["id"]
                    ops.append(("append", item))
            elif ct == "reasoning-delta" and self._open_reasoning:
                cur = self._ids[self._open_reasoning]
                it = self._update(self._open_reasoning,
                                  text=cur.get("text", "") + (chunk.get("text") or ""))
                ops.append(("update", it))
            elif ct == "text-delta" and self._open_text:
                cur = self._ids[self._open_text]
                it = self._update(self._open_text,
                                  text=cur.get("text", "") + (chunk.get("text") or ""))
                ops.append(("update", it))
            elif ct == "tool-call-delta":
                cid = chunk.get("id")
                if cid:
                    if cid not in self._tools:
                        # 增量阶段拿不到完整参数，只能先建普通 tool 条目
                        # （本机 harness 不发 assistant/chunk，这里通常不会走到）
                        item = self._new("tool", name=chunk.get("name") or "",
                                         args=chunk.get("argumentsDelta") or "",
                                         output=None, error=False, status="run", at=at)
                        self._tools[cid] = item["id"]
                        ops.append(("append", item))
                    else:
                        cur = self._ids[self._tools[cid]]
                        it = self._update(self._tools[cid],
                                          args=cur.get("args", "") + (chunk.get("argumentsDelta") or ""))
                        ops.append(("update", it))
        elif t == "assistant/message":
            # 新版 harness 常常直接给出完整消息（没有 assistant/chunk 增量），
            # 因此没有开放流时要新建条目，而不是丢弃正文。
            for blk in (d.get("message") or {}).get("content") or []:
                bt = blk.get("type")
                if bt == "text":
                    text = blk.get("text") or ""
                    if not text:
                        continue
                    if self._open_text:
                        it = self._update(self._open_text, text=text)
                    else:
                        item = self._new("agent", text=text, at=at)
                        self._open_text = item["id"]
                        it = item
                    ops.append(("update", it))
                elif bt == "reasoning":
                    text = blk.get("text") or ""
                    if not text:
                        continue
                    if self._open_reasoning:
                        it = self._update(self._open_reasoning, text=text)
                    else:
                        item = self._new("reasoning", text=text, at=at)
                        self._open_reasoning = item["id"]
                        it = item
                    ops.append(("update", it))
                elif bt == "tool-call":
                    cid = blk.get("id")
                    if cid and cid not in self._tools:
                        item = self._tool_item(blk.get("name") or "",
                                               blk.get("arguments") or "", at, cid)
                        self._tools[cid] = item["id"]
                        ops.append(("append", item))
            self._close_streams()
        elif t == "tool/call":
            cid = d.get("callId")
            if cid and cid not in self._tools:
                item = self._tool_item(d.get("name") or "", d.get("arguments") or "", at, cid)
                self._tools[cid] = item["id"]
                ops.append(("append", item))
        elif t == "tool/result":
            msg = d.get("message") or {}
            cid = (msg.get("source") or {}).get("callId") or msg.get("toolCallId")
            if cid and cid in self._tools:
                text = _content_text(msg.get("content"))[:MAX_TOOL_OUTPUT]
                # 真实的失败标志在 message.isError 上；data 里没有 isError
                # （本机 345 个真实 tool/result：data.isError 命中 0 次、
                #  message.isError 命中 5 次），只看 d 会让失败的命令永远显示「成功」。
                err = bool(msg.get("isError")) or bool(d.get("isError"))
                it = self._update(self._tools[cid], output=text,
                                  status="fail" if err else "done", error=err)
                if it is not None and it.get("kind") == "command":
                    it["kind"] = "command_update"
                ops.append(("update", it))
        elif t == "turn/end":
            self._close_streams()
            self._open_turn = None
            usage = (d.get("usage") or {}) if isinstance(d.get("usage"), dict) else {}
            ops.append(("append", self._new("turn_done", usage=usage, at=at)))
            ops.append(("append", self._new("status", running=False, at=at)))
        elif t in ("approval/asked", "approval/decided"):
            pass
        elif t == "session/title":
            pass
        return ops

    def feed_many(self, events):
        """Feed a list of {type,seq,time,data} events; returns all ops."""
        ops = []
        for ev in events:
            ops.extend(self.feed(ev))
        return ops

    def append_item(self, kind, **kw):
        """Directly append a display item (e.g. local errors); returns ops."""
        return [("append", self._new(kind, **kw))]

    def snapshot(self):
        return list(self.items)


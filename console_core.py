# -*- coding: utf-8 -*-
"""手机远程控制台 —— 核心逻辑（不依赖任何 GUI 库）。

从 gui.pyw 抽出：路径/端口探测、PIN、局域网地址、服务与隧道启停、日志、
官网用量解析、Token 管理、浏览器 token 搜索等。
Tkinter 旧界面（gui.pyw）与新 WebView2 面板（panel/host.py）共用这一层。
"""
import re
import json
import secrets
import socket
import queue
import csv
import calendar
import datetime
import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import zipfile
import urllib.request
from pathlib import Path

from sessions import scan_usage as sess_scan_usage
from server import find_api_key as find_dsh_api_key
from server import get_lan_ips as session_lan_ips
from server import tailscale_ips as session_tailscale_ips


# 打包成 exe 后 __file__ 在 _MEIPASS 临时目录里，数据/资源应相对 exe 所在目录（否则配置会写进临时目录，退出即丢）
ROOT = (Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False) else Path(__file__).resolve().parent)
_VENDOR = ROOT / "vendor"
if _VENDOR.is_dir():
    sys.path.insert(0, str(_VENDOR))

import qrcode  # noqa: E402

PORT = 8787


# ---------------------------------------------------------------------------
# 核心逻辑（可独立测试，不依赖 GUI）
# ---------------------------------------------------------------------------

def data_dir():
    d = ROOT / "console_data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_or_create_pin():
    pf = data_dir() / "pin.txt"
    pin = None
    if pf.exists():
        pin = pf.read_text(encoding="utf-8-sig").strip()
    if not pin or not (pin.isdigit() and len(pin) == 8):
        pin = "".join(secrets.choice("0123456789") for _ in range(8))
        pf.write_text(pin, encoding="utf-8")
    return pin


def is_running(port=PORT):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def find_listener_pid(port=PORT):
    try:
        proc = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                              encoding="mbcs", errors="replace", timeout=3,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        # UTF-8/GBK 混用时 netstat 输出可能解码失败，stdout 会是 None，
        # 直接 splitlines() 会抛 AttributeError 并被 _refresh 静默吞掉
        # （表现为 PID 与按钮状态不再刷新），所以这里兜底成空串。
        out = proc.stdout or ""
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):
        return None
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            parts = line.split()
            if parts:
                return parts[-1]
    return None


_LAN_IPS_CACHE = (None, 0.0)


def lan_ips():
    """可供手机访问的本机 IPv4（10 秒缓存）。

    直接复用服务端那份实现（会过滤 VMware/Hyper-V/TAP 等虚拟网卡与 169.254），
    否则界面上会把手机根本到不了的地址当成"局域网地址"显示、还会写进二维码。
    """
    global _LAN_IPS_CACHE
    cached, ts = _LAN_IPS_CACHE
    if cached is not None and time.time() - ts < 10:
        return cached
    try:
        ips = list(session_lan_ips())
    except Exception:
        ips = []
    if not ips:      # 兜底：老逻辑
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None):
                ip = info[4][0]
                if ":" not in ip and not ip.startswith("127."):
                    ips.append(ip)
        except OSError:
            pass
    _LAN_IPS_CACHE = (sorted(set(ips)), time.time())
    return list(_LAN_IPS_CACHE[0])


def _log_tail(path, lines=14):
    """读取日志末尾若干行（用于把失败原因直接展示给用户）。"""
    try:
        p = Path(path)
        if not p.is_file():
            return ""
        text = p.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            return ""
        rows = [r for r in text.splitlines() if r.strip()]
        return "\n".join(rows[-lines:])
    except OSError:
        return ""


def _log_errors(path, lines=8):
    """从日志里挑出"错误行"（原因通常在开头，不一定是最后几行）。"""
    try:
        p = Path(path)
        if not p.is_file():
            return ""
        rows = [r.strip() for r in p.read_text(encoding="utf-8", errors="replace").splitlines() if r.strip()]
    except OSError:
        return ""
    pat = re.compile(r"Traceback|Error|Exception|错误|失败|无法|拒绝|未找到|未检测到|unauthorized|forbidden|"
                     r"refused|timed out|超时|ECONN|ENOENT|WinError|端口|port", re.I)
    hits = [r for r in rows if pat.search(r)]
    # 去掉纯访问日志（[console] "GET ... 200 -"）
    hits = [r for r in hits if not re.match(r"^\[console\]\s+\S+\s+\"(GET|POST|DELETE)\s.*\s(200|201)\s", r)]
    return "\n".join(hits[-lines:])


def _server_failure_reason(d):
    """汇总服务启动失败原因：优先错误行，其次日志末尾。"""
    for name in ("server.err.log", "server.out.log"):
        p = d / name
        err = _log_errors(p)
        if err:
            return f"\n\n原因：\n{err}\n\n完整日志：{d / 'server.err.log'}"
    tail = _log_tail(d / "server.err.log") or _log_tail(d / "server.out.log")
    if tail:
        return f"\n\n日志末尾：\n{tail}\n\n完整日志：{d / 'server.err.log'}"
    return (f"\n\n未捕获到错误输出。请手动查看日志：\n{d / 'server.err.log'}\n{d / 'server.out.log'}\n"
            f"（常见原因：桌面端 DeepSeek Harness 未启动、8787 端口被占用、凭证文件缺失）")


def read_dsh_target(d=None):
    """从 server.out.log 的启动横幅里读出实际对接的 harness，返回如「已对接桌面端：http://…」。"""
    d = d or data_dir()
    try:
        text = (d / "server.out.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in reversed(text.splitlines()):
        if "DSH:" not in line:
            continue
        m = re.search(r"DSH:\s*(\S+).*?（对接：([^）]+)）", line)
        if m:
            return f"已对接{m.group(2)}：{m.group(1)}"
        return line.strip()
    return ""


def _strip_scheme(url):
    """状态行里省掉 http(s):// 前缀：给地址留出宽度（完整地址见二维码下方文案）。"""
    return re.sub(r"^https?://", "", (url or "").strip())


def dsh_target_text(target, limit=34):
    """把 read_dsh_target() 的结果整理成状态行文案，如「桌面端 · 127.0.0.1:3080」。

    只做界面展示层整理：不改动 read_dsh_target() 的解析逻辑，也不改日志格式。
    状态行宽度有限，所以去掉 http:// 前缀并按 limit 截断，保证一行放得下。
    """
    target = (target or "").strip()
    if not target:
        return ""
    m = re.match(r"^已对接(.+?)：(.*)$", target)
    if m:
        src, url = m.group(1).strip(), m.group(2).strip()
        text = f"{src} · {_strip_scheme(url)}" if url else src
    else:
        # 兼容旧日志（没有「（对接：…）」字段）：只取 DSH 地址，避免整行过长换行
        mu = re.search(r"https?://\S+", target)
        text = _strip_scheme(mu.group(0)) if mu else target
    if limit and len(text) > limit:
        text = text[:limit - 1] + "…"
    return text


def _python_for_server():
    """返回能运行 server.py 的 Python 命令前缀。

    打包成 ConsolePanel.exe 后 sys.executable 指向面板自己（不是 Python），
    直接拿它起 server.py 会变成"再开一个面板" —— 第二个实例弹"面板已经在运行了"，
    看起来就像"点启动说已经启动了"（真机踩过）。
    查找顺序：console_data/python_path.txt → PATH 里的 python/pythonw → py -3。
    """
    if not getattr(sys, "frozen", False):
        return [sys.executable]

    try:
        cfg = data_dir() / "python_path.txt"
        if cfg.is_file():
            p = cfg.read_text(encoding="utf-8").strip().strip('"')
            if p and Path(p).is_file():
                return [p]
    except OSError:
        pass

    for name in ("python.exe", "pythonw.exe"):
        p = shutil.which(name)
        if p:
            return [p]
    py = shutil.which("py")
    if py:
        return [py, "-3"]
    return []

def start_server(pin):
    if is_running():
        return True, "already running"
    py = _python_for_server()
    if not py:
        return False, ("找不到可用的 Python 3（面板是独立 exe，需要系统里装有 python，"
                       "或把解释器路径写进 console_data\\python_path.txt）")
    server_py = ROOT / "server.py"
    if not server_py.is_file():
        return False, f"同目录下找不到 server.py：{server_py}"
    d = data_dir()
    out = open(d / "server.out.log", "w", encoding="utf-8")
    err = open(d / "server.err.log", "w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            py + [str(server_py), "--port", str(PORT), "--pin", pin],
            stdout=out, stderr=err,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        (d / "server.pid").write_text(str(proc.pid), encoding="utf-8")
    except Exception as exc:
        out.close(); err.close()
        return False, f"无法启动进程（{py[0]}）：{exc}"
    for _ in range(110):   # 服务启动时会自动发现/等待 harness，最多 40 秒，留足余量
        if is_running():
            out.close(); err.close()
            return True, "started"
        if proc.poll() is not None:
            out.close(); err.close()
            return False, (f"服务进程退出（代码 {proc.returncode}）" +
                           _server_failure_reason(d))
        time.sleep(0.5)
    out.close(); err.close()
    return False, "启动超时（60 秒内端口未就绪）" + _server_failure_reason(d)


def stop_server():
    pid = find_listener_pid(PORT)
    if pid:
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        time.sleep(1)
    pf = data_dir() / "server.pid"
    if pf.exists():
        saved = pf.read_text(encoding="utf-8").strip()
        if saved and saved.isdigit():
            subprocess.run(["taskkill", "/PID", saved, "/T", "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            pf.unlink()
        except OSError:
            pass
    return not is_running()


def _pid_alive(pid):
    try:
        # 中文 Windows 的 tasklist 输出是 GBK：用 mbcs 解码，避免 reader 线程抛 UnicodeDecodeError
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True,
            encoding="mbcs", errors="replace", timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout or ""
        if "Access is denied" in out or not out.strip():
            # 无法确认时按“存活”处理，避免误重启
            return True
        return str(pid) in out
    except (OSError, subprocess.TimeoutExpired):
        return True


# natapp 隧道 authtoken（natapp.cn 免费隧道，流量不足时自动回退 cloudflared）
NATAUTHToken = os.environ.get("NATAPP_TOKEN", "")
_active_tunnel = None   # "natapp" | "cloudflared"


def tunnel_pid():
    mf = data_dir() / "tunnel.pid"
    if mf.exists():
        t = mf.read_text(encoding="utf-8").strip()
        if t.isdigit():
            return t
    return None


def _tunnel_alive():
    """隧道进程真的还活着吗？（pid 文件里的进程是否存活）

    只看日志会误判：进程被杀掉后 tunnel.log 里的地址还在，
    get_tunnel_url() 会返回一个已经死掉的 URL —— 面板/二维码显示它，手机扫码直接打不开。
    """
    pid = tunnel_pid()
    if not pid:
        return False
    try:
        p = int(pid)
    except (TypeError, ValueError):
        return False
    if not _pid_alive(p):
        return False
    # PID 会被系统复用：光看"这个 PID 存在"不够，必须确认它仍然是隧道进程
    name = _tunnel_process_name(p)
    return ("cloudflared" in name) or ("natapp" in name)

def _spawn_tunnel(cmd):
    d = data_dir()
    log = open(d / "tunnel.log", "wb")   # 每次新起隧道清空旧日志
    try:
        proc = subprocess.Popen(
            cmd, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        (d / "tunnel.pid").write_text(str(proc.pid), encoding="utf-8")
    except Exception as exc:
        log.close()
        return False, str(exc)
    return True, "starting"


def _natapp_failed():
    """natapp 日志出现认证失败/流量不足/隧道禁用等错误即判定失败。"""
    log = data_dir() / "tunnel.log"
    if not log.exists():
        return False
    try:
        txt = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return ("errorCode" in txt or "认证错误" in txt or "流量不足" in txt
            or "隧道被禁用" in txt or "auth fail" in txt.lower())


def _tunnel_process_name(pid):
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True,
                             encoding="mbcs", errors="replace", timeout=2,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout or ""
        return out.lower()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def cloudflared_cmd(protocol=None):
    """cloudflared 启动参数。协议可选 quic（默认）或 http2（走 TCP/443）。

    国内网络/手机热点（CGNAT）下 QUIC(UDP) 经常被限速丢包，日志里会刷
    "timeout: no recent network activity" 并反复重连，隧道时断时续；
    这时换 http2 明显更稳，所以启动优先用 http2，失败再回退 quic。
    """
    args = [str(ROOT / "cloudflared.exe"), "tunnel", "--url", f"http://127.0.0.1:{PORT}",
            "--no-prechecks", "--no-autoupdate"]
    if protocol:
        args += ["--protocol", protocol]
    return args


def natapp_token():
    """natapp authtoken：优先读 console_data/natapp-token.txt。

    这样换 token 只要往文件里粘一行，不用改代码（真机踩过：写死在代码里的
    token 会失效，报 errorCode 1101 authtoken无效）。
    """
    f = data_dir() / "natapp-token.txt"
    if f.exists():
        try:
            t = f.read_text(encoding="utf-8", errors="replace").strip()
            if t:
                return t
        except OSError:
            pass
    return NATAUTHToken


def _natapp_disabled_path():
    return data_dir() / "natapp-disabled.txt"


def natapp_disabled():
    """这个 token 已被证明用不了（禁用/流量不足）？是则别再每次先试 natapp、
    白等 25 秒才回退。文件里记录的是哪个 token，换成新 token 后会自动重新尝试。"""
    p = _natapp_disabled_path()
    if not p.exists():
        return False
    try:
        return p.read_text(encoding="utf-8", errors="replace").strip() == natapp_token()
    except OSError:
        return False


def disable_natapp():
    """记下"当前这个 natapp token 不可用"。"""
    try:
        _natapp_disabled_path().write_text(natapp_token(), encoding="utf-8")
    except OSError:
        pass


def start_tunnel(allow_before_server=False):
    global _active_tunnel
    pid = tunnel_pid()
    if pid and _pid_alive(pid):
        # 正在运行的隧道如果是 natapp 且已认证失败 → 视为未启动，先清掉再重来
        pname = _tunnel_process_name(pid)
        if "natapp" in pname and _natapp_failed():
            disable_natapp()          # token 用不了就记下来，别再反复白试
            stop_tunnel()
        elif not tunnel_connected():
            # 进程活着但已经掉线（超时/被网络掐断后一直重试）：
            # 以前这里直接返回 already running，卡死的隧道就再也重启不了
            stop_tunnel()
        else:
            return True, "tunnel already running"
    if not is_running() and not allow_before_server:
        return False, "请先启动控制台服务"
    # 优先 natapp（固定域名 + 国内节点快）；token 用不了/无文件则直接用 cloudflared
    exe = ROOT / "natapp.exe"
    if exe.exists() and not natapp_disabled():
        ok, msg = _spawn_tunnel([str(exe), "-authtoken=" + natapp_token(), "-log=stdout"])
        if ok:
            _active_tunnel = "natapp"
            return True, "starting (natapp)"
    exe2 = ROOT / "cloudflared.exe"
    if exe2.exists():
        ok, msg = _spawn_tunnel(cloudflared_cmd("http2"))
        if ok:
            _active_tunnel = "cloudflared"
            return True, "starting (cloudflared)"
    return False, "未找到可用的隧道工具（natapp.exe / cloudflared.exe）"


def stop_tunnel():
    global _active_tunnel
    pid = tunnel_pid()
    if pid:
        # 只杀确认是隧道进程的 PID（PID 会被系统复用，避免误杀别的程序）
        try:
            pname = _tunnel_process_name(int(pid))
        except (TypeError, ValueError):
            pname = ""
        if "cloudflared" in pname or "natapp" in pname:
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    # 兜底：按进程名结束 natapp / cloudflared（兼容旧终端方式启动的隧道）
    subprocess.run(["taskkill", "/IM", "natapp.exe", "/F"], capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    subprocess.run(["taskkill", "/IM", "cloudflared.exe", "/F"], capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        (data_dir() / "tunnel.pid").unlink()
    except OSError:
        pass
    _active_tunnel = None
    time.sleep(1)
    return True


def _save_phone_address(url, pin):
    """把当前手机访问地址写到 console_data/phone-address.txt：隧道重启换地址时方便找回。"""
    try:
        p = data_dir() / "phone-address.txt"
        p.write_text(
            "手机远程控制台 · 当前访问地址\n"
            "=============================\n"
            f"{url}/?pin={pin}\n\n"
            "家庭/同一 Wi-Fi 也可用局域网地址（见管理界面「局域网地址」一行）。\n"
            "注意：这个 https 地址是临时隧道地址，隧道重启后会变化，\n"
            "以管理界面上的二维码/地址为准（每 10 秒自动刷新）。\n"
            f"更新时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n",
            encoding="utf-8")
    except OSError:
        pass


def get_tunnel_url():
    # 进程不在 -> 日志里的地址是历史残留，绝不能再拿来展示/生成二维码
    if not _tunnel_alive():
        return None
    log = data_dir() / "tunnel.log"
    if not log.exists():
        return None
    try:
        if log.stat().st_size > 2 * 1024 * 1024:
            return None
        txt = log.read_text(encoding="utf-8", errors="replace")
        # natapp 地址优先（国内节点，速度快）
        m = re.search(r"https?://[a-z0-9-]+\.natappfree\.cc", txt)
        if m:
            return m.group(0)
        # 兼容 cloudflared / trycloudflare 隧道
        # 注意 (?!api\.)：cloudflared 申请隧道失败时日志里会打印
        # "Post \"https://api.trycloudflare.com/tunnel\" ..."，不排除的话
        # 界面/二维码会把 API 域名当成手机访问地址（真机踩过）。
        m = re.search(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com", txt)
        if m:
            return m.group(0)
    except OSError:
        pass
    return None


# cloudflared 日志里代表"这一侧连接状态"的关键行
_TUNNEL_OK_RE = re.compile(r"Registered tunnel connection")
_TUNNEL_BAD_RE = re.compile(
    r"Unable to establish connection|Connection terminated|Serve tunnel error|"
    r"no recent network activity|Retrying connection")


def restart_cloudflared_tunnel():
    """隧道掉线自愈：直接重起 cloudflared(http2)。

    不走 natapp —— 它的鉴权/流量状态不确定，而自动重连需要"必定可用"的路径。
    _spawn_tunnel 会清空 tunnel.log，所以 tunnel_connected() 不会被上一次的
    成功记录骗到。
    """
    global _active_tunnel
    stop_tunnel()
    exe = ROOT / "cloudflared.exe"
    if not exe.exists():
        return False, "未找到 cloudflared.exe"
    ok, msg = _spawn_tunnel(cloudflared_cmd("http2"))
    if ok:
        _active_tunnel = "cloudflared"
    return ok, msg


def tunnel_connected():
    """隧道进程虽然活着，但真的和 Cloudflare 边缘连着吗？

    为什么不能只看"日志里有没有地址"：地址是**第一次启动时**写进日志的，
    之后连接断了地址还留在日志里，于是界面显示"隧道已运行"、点「只启动隧道」
    也直接返回 already running —— 卡死的隧道永远救不回来（真机踩过：
    dial tcp <边缘>:7844 i/o timeout 之后一直重试，手机端直接 530）。
    这里改成看**日志末尾最后一次连接状态**：最后一次是 Registered 才算连着。
    """
    if not _tunnel_alive():
        return False
    log = data_dir() / "tunnel.log"
    if not log.exists():
        return False
    try:
        txt = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if not txt:
        return False
    lines = txt.splitlines()[-500:]          # 只看末尾，避免旧的成功记录干扰
    last_ok = last_bad = -1
    for i, line in enumerate(lines):
        if _TUNNEL_OK_RE.search(line):
            last_ok = i
        elif _TUNNEL_BAD_RE.search(line):
            last_bad = i
    if last_ok < 0 and last_bad < 0:
        return False                          # 还没连过（刚启动）
    return last_ok > last_bad


# ---------------------------------------------------------------------------
# 图形界面
# ---------------------------------------------------------------------------

# 深色科技感配色（与手机端一致：深蓝底 + 绿主色）
BG_COLOR = "#12141C"
PANEL_COLOR = "#1B1F2B"
PANEL2_COLOR = "#232838"
PANEL3_COLOR = "#2A3043"
BORDER_COLOR = "#2E3446"
TEXT_COLOR = "#EDF1F7"
MUTED_COLOR = "#8C96AB"
ACCENT_COLOR = "#3FBF7F"   # 绿：主强调（按钮/状态/命中缓存）
ACCENT_DARK = "#2E9B66"    # 绿：渐变/按压
CYAN_COLOR = "#4FD8FF"     # 青：输入/隧道
BLUE_COLOR = "#5B8CFF"     # 蓝：输出
AMBER_COLOR = "#E6B84C"    # 琥珀：推理
RED_COLOR = "#E5534B"      # 红：告警
GRAY_COLOR = "#7D8AA0"     # 灰：未命中缓存/占位
RADIUS = 12                # 统一圆角半径：卡片 / 占位框 / 提示条共用同一套


def _round_rect(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# ?????????DeepSeek ????????? amount-*.csv / zip?
# ---------------------------------------------------------------------------

def parse_official_usage_csv(path):
    """????????? CSV???????????? None?"""
    per_day = {}
    keys = {"input_cache_hit_tokens": "hit", "input_cache_miss_tokens": "miss",
            "output_tokens": "output", "request_count": "requests"}
    try:
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                t = (r.get("type") or "").strip()
                st = (r.get("start_time_iso") or "")[:10]
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


def official_usage_dir():
    return data_dir() / "usage"


def save_official_usage(src_path):
    d = official_usage_dir()
    d.mkdir(parents=True, exist_ok=True)

    def _uniq(name):
        p = d / name
        if p.exists():
            name = "amount-" + time.strftime("%Y%m%d%H%M%S") + ".csv"
        return d / name
    if str(src_path).lower().endswith(".zip"):
        with zipfile.ZipFile(src_path) as z:
            cands = [n for n in z.namelist()
                     if n.lower().endswith(".csv") and "amount" in n.lower()]
            if not cands:
                cands = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not cands:
                raise OSError("zip ???? CSV")
            dst = _uniq(Path(cands[0]).name)
            with z.open(cands[0]) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
            return dst
    dst = _uniq(Path(src_path).name)
    shutil.copyfile(src_path, dst)
    return dst


def load_official_usage():
    d = official_usage_dir()
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
    return {"hit": sum(d["hit"] for d in merged.values()),
            "miss": sum(d["miss"] for d in merged.values()),
            "output": sum(d["output"] for d in merged.values()),
            "requests": sum(d["requests"] for d in merged.values()),
            "days": sorted(merged), "per_day": merged}


def parse_official_usage_any(path):
    """?? csv ? zip?zip ???? amount-*.csv??"""
    if str(path).lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as z:
                cands = [n for n in z.namelist()
                         if n.lower().endswith(".csv") and "amount" in n.lower()]
                if not cands:
                    cands = [n for n in z.namelist() if n.lower().endswith(".csv")]
                if not cands:
                    return None
                tmp = Path(tempfile.mkdtemp()) / "amount.csv"
                with z.open(cands[0]) as src, open(tmp, "wb") as fh:
                    shutil.copyfileobj(src, fh)
                return parse_official_usage_csv(tmp)
        except Exception:
            return None
    return parse_official_usage_csv(path)


def find_official_downloads():
    """????????? (path, mtime) ?????????"""
    cands = []
    bases = [Path.home() / "Downloads", Path.home() / "??", data_dir() / "import"]
    for base in bases:
        if not base.is_dir():
            continue
        try:
            for p in base.iterdir():
                if not p.is_file():
                    continue
                name = p.name.lower()
                if (name.startswith("usage_data_") and name.endswith(".zip")) or \
                   (name.startswith("amount-") and name.endswith(".csv")):
                    try:
                        cands.append((p, p.stat().st_mtime))
                    except OSError:
                        pass
        except OSError:
            pass
    cands.sort(key=lambda x: -x[1])
    return cands


def imported_state_path():
    return data_dir() / "usage" / "imported.json"


def load_imported_state():
    try:
        return json.loads(imported_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {"files": {}}


def save_imported_state(st):
    imported_state_path().write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def mark_imported(path):
    st = load_imported_state()
    try:
        st["files"][Path(path).name] = round(Path(path).stat().st_mtime)
    except OSError:
        pass
    save_imported_state(st)


class UsageAuthError(Exception):
    """官网登录 token 无效/过期（接口 code 40002/40003）。"""


def usage_token_path():
    return data_dir() / "usage" / "api_token.txt"


def load_usage_token():
    try:
        t = usage_token_path().read_text(encoding="utf-8-sig").strip()
        return t or None
    except OSError:
        return None


def save_usage_token(token):
    p = usage_token_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(token.strip(), encoding="utf-8")


def _usage_api_error(raw):
    """解析官网接口 JSON 错误响应，返回 (code, msg) 或 None。"""
    try:
        obj = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None
    if isinstance(obj, dict) and obj.get("code") in (40002, 40003):
        return obj.get("code"), obj.get("msg") or "invalid token"
    return None


def verify_usage_token(token):
    """用官网 amount 接口验证 token 是否有效。返回 (ok, msg)。"""
    token = (token or "").strip()
    if not token:
        return False, "Token 为空"
    now = time.localtime()
    url = ("https://platform.deepseek.com/api/v0/usage/amount?month=%d&year=%d"
           % (now.tm_mon, now.tm_year))
    try:
        req = urllib.request.Request(
            url, headers={"Authorization": "Bearer " + token, "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read(4096)
    except Exception as exc:
        return False, "网络请求失败：%s" % exc
    err = _usage_api_error(raw)
    if err:
        return False, "Token 无效或已过期（%s）" % err[1]
    return True, "Token 有效"


def fetch_official_usage_api(token):
    """???? amount ??????+????????? JSON????? per_day ???
    token ??/??? UsageAuthError??????? None?"""
    now = time.localtime()
    months = [(now.tm_year, now.tm_mon)]
    months.append((now.tm_year - 1, 12) if now.tm_mon == 1 else (now.tm_year, now.tm_mon - 1))
    per_day = {}
    cost_total = 0.0
    cost_currency = "CNY"
    for year, month in months:
        url = f"https://platform.deepseek.com/api/v0/usage/amount?month={month}&year={year}"
        try:
            req = urllib.request.Request(
                url, headers={"Authorization": "Bearer " + token, "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                obj = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        code = obj.get("code")
        if code in (40002, 40003):
            raise UsageAuthError("%s?%s?" % (obj.get("msg") or "invalid token", code))
        if code != 0 or not isinstance(obj.get("data"), dict):
            continue
        biz = (obj["data"].get("biz_data") or {})
        for d in biz.get("days") or []:
            date = (d.get("date") or "")[:10]
            if len(date) != 10:
                continue
            dd = per_day.setdefault(date, {"hit": 0, "miss": 0, "output": 0, "requests": 0})
            for m in d.get("data") or []:
                for u in m.get("usage") or []:
                    try:
                        amt = int(float(u.get("amount") or 0))
                    except (TypeError, ValueError):
                        amt = 0
                    t = u.get("type")
                    if t == "PROMPT_CACHE_HIT_TOKEN":
                        dd["hit"] += amt
                    elif t == "PROMPT_CACHE_MISS_TOKEN":
                        dd["miss"] += amt
                    elif t == "RESPONSE_TOKEN":
                        dd["output"] += amt
                    elif t == "REQUEST":
                        dd["requests"] += amt
        # 官网对账消费金额（export 接口的 cost-*.csv）
        url = f"https://platform.deepseek.com/api/v0/usage/export?month={month}&year={year}"
        try:
            req = urllib.request.Request(
                url, headers={"Authorization": "Bearer " + token,
                              "Accept": "application/zip", "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read()
        except Exception:
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                for n in z.namelist():
                    if n.lower().startswith("cost") and n.lower().endswith(".csv"):
                        tmp = Path(tempfile.mkdtemp()) / "cost.csv"
                        with z.open(n) as src, open(tmp, "wb") as fh:
                            shutil.copyfileobj(src, fh)
                        with open(tmp, encoding="utf-8-sig", errors="replace", newline="") as fh:
                            for r in csv.DictReader(fh):
                                try:
                                    cost_total += float(r.get("cost") or 0)
                                except (TypeError, ValueError):
                                    pass
                                if r.get("currency"):
                                    cost_currency = r["currency"]
        except Exception:
            continue
    if not per_day:
        return None
    return {"hit": sum(d["hit"] for d in per_day.values()),
            "miss": sum(d["miss"] for d in per_day.values()),
            "output": sum(d["output"] for d in per_day.values()),
            "requests": sum(d["requests"] for d in per_day.values()),
            "days": sorted(per_day), "per_day": per_day, "source": "api",
            "cost": round(cost_total, 2), "cost_currency": cost_currency}





def save_api_usage(per_day):
    """把官网 API 拉取的 per_day 明细写成官方格式 CSV（api-latest.csv，覆盖写），
    与手动导入文件一起按天 max 合并，不重复累计。"""
    d = official_usage_dir()
    d.mkdir(parents=True, exist_ok=True)
    dst = d / "api-latest.csv"
    header = ["user_id", "start_time_iso", "end_time_iso", "model",
              "api_key_name", "api_key", "type", "price", "amount"]
    type_map = {"hit": "input_cache_hit_tokens", "miss": "input_cache_miss_tokens",
                "output": "output_tokens", "requests": "request_count"}
    tmp = dst.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for day in sorted(per_day):
            dd = per_day[day]
            for k in ("hit", "miss", "output", "requests"):
                w.writerow(["api", day + "T00:00:00+08:00", "", "",
                            "", "", type_map[k], "", dd[k]])
    tmp.replace(dst)
    return dst


def _ldb_varint(buf, pos):
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def _snappy_decompress(data):
    n = len(data)
    if n < 1:
        return b""
    try:
        _, pos = _ldb_varint(data, 0)
    except IndexError:
        return b""
    out = bytearray()
    while pos < n:
        tag = data[pos]
        pos += 1
        typ = tag & 3
        if typ == 0:
            l = tag >> 2
            if l < 60:
                length = l + 1
            else:
                nb = l - 59
                length = int.from_bytes(data[pos:pos + nb], "little") + 1
                pos += nb
            out += data[pos:pos + length]
            pos += length
        elif typ == 1:
            length = ((tag >> 2) & 0x7) + 4
            offset = ((tag >> 5) << 8) | data[pos]
            pos += 1
            for _ in range(length):
                out.append(out[-offset])
        elif typ == 2:
            length = (tag >> 2) + 1
            offset = int.from_bytes(data[pos:pos + 2], "little")
            pos += 2
            for _ in range(length):
                out.append(out[-offset])
        else:
            length = (tag >> 2) + 1
            offset = int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
            for _ in range(length):
                out.append(out[-offset])
    return bytes(out)


def _ldb_parse_block(data, off, size):
    n = len(data)
    if off + size + 5 > n:
        return []
    blk = data[off:off + size]
    if data[off + size] == 1:
        try:
            blk = _snappy_decompress(blk)
        except Exception:
            return []
    pairs = []
    pos = 0
    prev = b""
    m = len(blk)
    guard = 0
    while pos < m and guard < 50000:
        guard += 1
        try:
            shared, p1 = _ldb_varint(blk, pos)
            unshared, p2 = _ldb_varint(blk, p1)
            vlen, p3 = _ldb_varint(blk, p2)
        except IndexError:
            break
        if p3 + unshared + vlen > m:
            break
        key = prev[:shared] + blk[p3:p3 + unshared]
        val = blk[p3 + unshared:p3 + unshared + vlen]
        prev = key
        pairs.append((key, val))
        pos = p3 + unshared + vlen
    return pairs


def _ldb_parse_file(data):
    n = len(data)
    if n < 48:
        return []
    footer = data[n - 48:]
    if footer[-8:] != struct.pack("<Q", 0xdb4775248b80fb57):
        return []
    try:
        pos = 0
        _, pos = _ldb_varint(footer, pos)
        _, pos = _ldb_varint(footer, pos)
        idx_off, pos = _ldb_varint(footer, pos)
        idx_size, pos = _ldb_varint(footer, pos)
    except IndexError:
        return []
    out = []
    for k, v in _ldb_parse_block(data, idx_off, idx_size):
        try:
            off, p = _ldb_varint(v, 0)
            size, p = _ldb_varint(v, p)
        except Exception:
            continue
        if off + size + 5 > n or size < 5:
            continue
        out.extend(_ldb_parse_block(data, off, size))
    return out


def find_browser_usertoken(deadline=12.0):
    """从 Edge/Chrome 的 localStorage(leveldb) 自动提取 platform.deepseek.com 的
    userToken，并用官网接口验证，返回第一个验证通过的 token；超时/失败返回 None。
    全程只读、限时，避免卡顿。"""
    t0 = time.time()
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    cands = []
    for vendor in ("Microsoft/Edge", "Google/Chrome"):
        ud = local / vendor / "User Data"
        try:
            if not ud.is_dir():
                continue
            for profile in ud.iterdir():
                lb = profile / "Local Storage" / "leveldb"
                try:
                    if not lb.is_dir():
                        continue
                except OSError:
                    continue
                for f in lb.glob("*.ldb"):
                    try:
                        if f.stat().st_size > 40 * 1024 * 1024:
                            continue
                        for k, v in _ldb_parse_file(f.read_bytes()):
                            if b"platform.deepseek" in k and b"userToken" in k and v:
                                raw = v[1:] if v[:1] == b"\x01" else v
                                try:
                                    obj = json.loads(raw.decode("utf-8", "ignore"))
                                    val = obj.get("value") if isinstance(obj, dict) else None
                                except Exception:
                                    val = None
                                if isinstance(val, str) and len(val) > 20 and val != "null":
                                    cands.append(val)
                    except OSError:
                        continue
        except OSError:
            continue
    seen = set()
    for tok in cands:
        if time.time() - t0 > deadline:
            return None
        if tok in seen:
            continue
        seen.add(tok)
        ok, _ = verify_usage_token(tok)
        if ok:
            return tok
    return None



# -*- coding: utf-8 -*-
"""手机远程控制台 —— WebView2 管理面板（pywebview 宿主 + 桥接）

架构（与 docs/Tkinter转WebView2界面-迁移指南 的三层一致）：
    界面层  panel/webui/{index.html,style.css,app.js}   HTML/CSS/JS
    桥接层  panel/host.py（Api 类：只做转发 + 线程 + 错误包装）
    核心层  console_core.py（从 gui.pyw 抽出的纯逻辑，不依赖 tkinter）

约定：
  - 所有桥方法返回可 JSON 序列化的 dict，形状 {'ok': bool, 'msg': str, ...}
  - 长任务（启动/停止/重启隧道）起线程后立刻返回，进度由 JS 轮询 poll()
  - 异常一律包装成 {'ok': False, 'msg': ...}，不让 Promise reject
"""
import datetime
import io
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)          # console_core / server / sessions 都在这层


def _dirs():
    """源码运行 / PyInstaller 打包 两种情况的资源路径"""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        bundle = getattr(sys, '_MEIPASS', exe_dir)
        for base in (bundle, exe_dir):
            ui = os.path.join(base, 'webui')
            if os.path.isfile(os.path.join(ui, 'index.html')):
                return exe_dir, ui
        return exe_dir, os.path.join(bundle, 'webui')
    return PKG, os.path.join(HERE, 'webui')


ROOT, UI_DIR = _dirs()
UI_FILE = os.path.join(UI_DIR, 'index.html')

import console_core as core  # noqa: E402  核心层（无 tkinter）

try:
    import webview  # noqa: E402
except Exception:  # pragma: no cover
    webview = None

try:
    import qrcode  # noqa: E402
    import qrcode.image.svg  # noqa: E402
except Exception:  # pragma: no cover
    qrcode = None

PORT = core.PORT
APP_TITLE = '手机远程控制台'


# ---------------------------------------------------------------- 状态

class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.busy = False
        self.status = '就绪'
        self.done = 0
        self.total = 0
        self.logs = []

    def log(self, msg, kind=''):
        with self.lock:
            self.logs.append({'t': time.strftime('%H:%M:%S'), 'm': str(msg)[:300], 'k': kind or ''})
            if len(self.logs) > 300:
                del self.logs[:150]

    def start(self, status):
        with self.lock:
            self.busy = True
            self.status = status

    def finish(self, status='就绪'):
        with self.lock:
            self.busy = False
            self.status = status

    def snap(self):
        with self.lock:
            return {'busy': self.busy, 'status': self.status,
                    'done': self.done, 'total': self.total,
                    'logs': list(self.logs[-80:])}


ST = State()
_PIN = {'v': ''}


def pin():
    if not _PIN['v']:
        try:
            _PIN['v'] = core.read_or_create_pin()
        except Exception:
            _PIN['v'] = ''
    return _PIN['v']


def tunnel_url():
    try:
        return core.get_tunnel_url() or ''
    except Exception:
        return ''


def access_url():
    """手机端优先公网隧道 → Tailscale 固定地址 → 局域网（与旧 Tk 面板一致）"""
    u = tunnel_url()
    if u:
        return u + '?pin=' + pin()
    try:
        ts = [ip for ip in core.session_tailscale_ips() if ip in core.lan_ips()]
    except Exception:
        ts = []
    if ts:
        return 'http://%s:%d?pin=%s' % (ts[0], PORT, pin())
    ips = core.lan_ips()
    if ips:
        return 'http://%s:%d?pin=%s' % (ips[0], PORT, pin())
    return ''


_LAST = {'pid': None, 'pid_ts': 0.0, 'dsh': '', 'dsh_ts': 0.0}


def snapshot():
    running = False
    pid = None
    try:
        running = bool(core.is_running(PORT))
        if running:
            now = time.time()
            if _LAST['pid'] is None or now - _LAST['pid_ts'] > 8:
                _LAST['pid'] = core.find_listener_pid(PORT)
                _LAST['pid_ts'] = now
            pid = _LAST['pid']
        else:
            _LAST['pid'] = None
    except Exception:
        pass

    dsh = ''
    if running:
        now = time.time()
        if _LAST['dsh'] and now - _LAST['dsh_ts'] < 10:
            dsh = _LAST['dsh']
        else:
            try:
                dsh = core.dsh_target_text(core.read_dsh_target()) or ''
            except Exception:
                dsh = ''
            if dsh:
                _LAST['dsh'], _LAST['dsh_ts'] = dsh, now

    u = tunnel_url()
    connected = False
    try:
        connected = bool(core.tunnel_connected())
    except Exception:
        pass

    snap = ST.snap()
    snap.update({
        'ok': True,
        'server': {'running': running, 'pid': pid, 'port': PORT},
        'tunnel': {'url': u, 'connected': connected},
        'pin': pin(),
        'accessUrl': access_url(),
        'lanIps': [],
        'dshTarget': dsh,
        'dataDir': str(core.data_dir()),
        'ts': time.time(),
    })
    try:
        snap['lanIps'] = core.lan_ips()[:4]
    except Exception:
        pass
    return snap


# ---------------------------------------------------------------- 用量统计

_TOK = {'state': 'none', 'msg': '', 'token': '', 'pending': False}
_RANGES = ('近7天', '近30天', '本月', '上月', '全部')
_COST = {'v': None, 'ts': 0.0}


def _token_state():
    if not _TOK['token']:
        try:
            t = core.load_usage_token() or ''
        except Exception:
            t = ''
        _TOK['token'] = t
        if t and _TOK['state'] == 'none':
            _TOK['state'] = 'saved'
            _TOK['msg'] = '已保存'
    return {'ok': True, 'has': bool(_TOK['token']), 'state': _TOK['state'],
            'msg': _TOK['msg'], 'pending': _TOK['pending'],
            'tail': (_TOK['token'][-6:] if _TOK['token'] else '')}


def _cost():
    now = time.time()
    if _COST['v'] is not None and now - _COST['ts'] < 30:
        return _COST['v']
    v = 0.0
    try:
        cj = json.loads((core.official_usage_dir() / 'cost.json').read_text(encoding='utf-8'))
        v = float(cj.get('cost') or 0)
    except Exception:
        v = 0.0
    _COST.update({'v': v, 'ts': now})
    return v


def _range_sel(per_day, rng, cfrom='', cto=''):
    """与 Tk 面板同口径的区间过滤。返回汇总 dict 或 None。"""
    if not per_day:
        return None
    if rng in ('', '全部'):
        sel = dict(per_day)
    elif rng == '自定义':
        if not cfrom or not cto:
            return None
        sel = {d: v for d, v in per_day.items() if cfrom <= d <= cto}
    else:
        today = datetime.date.today()
        start = end = None
        if rng == '近7天':
            start = today - datetime.timedelta(days=6)
        elif rng == '近30天':
            start = today - datetime.timedelta(days=29)
        elif rng == '本月':
            start = today.replace(day=1)
        elif rng == '上月':
            last = today.replace(day=1) - datetime.timedelta(days=1)
            start, end = last.replace(day=1), last
        sel = {}
        for d, v in per_day.items():
            try:
                ds = datetime.date.fromisoformat(d)
            except ValueError:
                continue
            if start and ds < start:
                continue
            if end and ds > end:
                continue
            sel[d] = v
    if not sel:
        return None
    return {'hit': sum(x.get('hit', 0) for x in sel.values()),
            'miss': sum(x.get('miss', 0) for x in sel.values()),
            'output': sum(x.get('output', 0) for x in sel.values()),
            'requests': sum(x.get('requests', 0) for x in sel.values()),
            'days': sorted(sel),
            'per_day': {d: sel[d] for d in sorted(sel)}}


def _usage_payload(rng='全部', cfrom='', cto=''):
    o = core.load_official_usage() or {}
    per_day = o.get('per_day') or {}
    # 官网导出的 CSV/接口偶尔会带「今天之后」的行（例如把账期尾日也算进去），
    # 不裁掉的话「最近 7 天明细」会显示未来日期、趋势图也会多出一截。
    today = time.strftime('%Y-%m-%d')
    future_days = [d for d in per_day if str(d)[:10] > today]
    if future_days:
        per_day = {d: v for d, v in per_day.items() if str(d)[:10] <= today}
    sel = _range_sel(per_day, rng, cfrom, cto)
    hit = sel['hit'] if sel else 0
    miss = sel['miss'] if sel else 0
    out = sel['output'] if sel else 0
    req = sel['requests'] if sel else 0
    rate = (hit / (hit + miss) * 100.0) if (hit + miss) else 0.0
    series = []
    if sel:
        for d in sel['days']:
            v = sel['per_day'][d]
            series.append({'d': d, 'hit': v.get('hit', 0), 'miss': v.get('miss', 0),
                           'output': v.get('output', 0), 'requests': v.get('requests', 0)})
    # 导入过的文件 + 待导入候选（下载目录里新的 amount-*.csv / zip）
    imported_list = []
    try:
        files = (core.load_imported_state() or {}).get('files', {}) or {}
        imported_list = [k for k, _ in sorted(files.items())[-8:]]
    except Exception:
        pass
    cands = []
    try:
        files = (core.load_imported_state() or {}).get('files', {}) or {}
        for item in (core.find_official_downloads() or [])[:6]:
            p, mt = item if isinstance(item, (tuple, list)) else (item, 0)
            name = getattr(p, 'name', str(p))
            cands.append({'name': name, 'imported': files.get(name) == round(mt or 0)})
    except Exception:
        pass
    return {
        'ok': True,
        'range': rng, 'from': cfrom, 'to': cto,
        'ranges': list(_RANGES) + ['自定义'],
        'source': 'official' if sel else 'none',
        'futureDropped': len(future_days),
        'hasOfficial': bool(per_day),
        'coverage': {'days': len(per_day),
                     'first': min(per_day) if per_day else '',
                     'last': max(per_day) if per_day else ''},
        'totals': {'hit': hit, 'miss': miss, 'output': out, 'requests': req,
                   'tokens': hit + miss + out, 'rate': rate},
        'series': series,
        'cost': _cost(),
        'tokenState': _token_state(),
        'candidates': cands,
        'imported': imported_list,
    }


# ---------------------------------------------------------------- 桥

class Api:
    """JS 通过 window.pywebview.api.xxx() 调用；每个方法都返回 dict。"""

    # ---- 状态
    def poll(self):
        try:
            return snapshot()
        except Exception as e:
            return {'ok': False, 'msg': str(e)}

    def qr_svg(self):
        """访问地址的二维码：返回 SVG 字符串（不转 base64，前端直接 innerHTML）"""
        try:
            url = access_url()
            if not url:
                return {'ok': True, 'url': '', 'svg': ''}
            if qrcode is None:
                return {'ok': False, 'msg': '缺少 qrcode 依赖', 'url': url}
            img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
            buf = io.BytesIO()
            img.save(buf)
            return {'ok': True, 'url': url, 'svg': buf.getvalue().decode('utf-8', 'replace')}
        except Exception as e:
            return {'ok': False, 'msg': str(e)}

    # ---- 界面侧诊断 -------------------------------------------------------
    def ui_log(self, msg):
        """前端诊断写入 console_data/panel.log（视口尺寸 / JS 错误），同时也进面板日志。"""
        try:
            line = '[ui] ' + str(msg)[:500]
            ST.log(line)
            path = core.data_dir() / 'panel.log'
            with open(path, 'a', encoding='utf-8') as fh:
                fh.write(time.strftime('%Y-%m-%d %H:%M:%S ') + line + '\n')
            return {'ok': True}
        except Exception as exc:
            return {'ok': False, 'msg': str(exc)}
    # ---- 长任务（线程 + 轮询）
    def _bg(self, name, fn):
        if ST.busy:
            return {'ok': False, 'msg': '还有任务在执行'}
        ST.start(name)
        ST.log(name)

        def run():
            ok = True
            try:
                fn()
            except Exception as e:
                ok = False
                ST.log('%s失败：%s' % (name, e), 'err')
            ST.finish('就绪')
            if ok:
                ST.log('%s完成' % name, 'ok')

        threading.Thread(target=run, daemon=True, name='panel-task').start()
        return {'ok': True}

    def start_all(self):
        def work():
            need_server = not core.is_running(PORT)
            need_tunnel = not tunnel_url()
            err = {}

            def start_srv():
                try:
                    ST.log('启动电脑端服务…')
                    ok, msg = core.start_server(pin())
                    if not ok:
                        err['server'] = msg
                        return
                    for _ in range(40):
                        time.sleep(0.25)
                        if core.is_running(PORT):
                            break
                    if not core.is_running(PORT):
                        err['server'] = '服务没起来（详见 console_data/server.err.log）'
                        return
                    ST.log('服务已启动 · 端口 %d' % PORT, 'ok')
                except Exception as exc:
                    err['server'] = str(exc)

            srv_thread = None
            if need_server:
                srv_thread = threading.Thread(target=start_srv, daemon=True, name='panel-start-server')
                srv_thread.start()

            # 隧道和 server 同时申请：cloudflared 起来后会自己重试连本地端口，
            # 不用等 server 先就绪（顺序执行白白多等 2~4 秒）
            if need_tunnel:
                ST.log('申请隧道地址…')
                ok, msg = core.start_tunnel(allow_before_server=True)
                if not ok and 'already' not in str(msg):
                    err['tunnel'] = msg
                else:
                    for _ in range(120):
                        time.sleep(0.5)
                        u = tunnel_url()
                        if u:
                            core._save_phone_address(u, pin())
                            ST.log('隧道就绪：%s' % u, 'ok')
                            break
                    else:
                        err['tunnel'] = '隧道 60 秒内没拿到地址'

            if srv_thread is not None:
                srv_thread.join(timeout=70)

            if err.get('server'):
                raise RuntimeError('服务启动失败：%s' % err['server'])
            if err.get('tunnel'):
                raise RuntimeError('隧道启动失败：%s' % err['tunnel'])
            if not core.is_running(PORT):
                raise RuntimeError('服务没起来（详见 console_data/server.err.log）')
            ST.status = '运行中'

        return self._bg('启动（服务 + 隧道）', work)

    def stop_all(self):
        def work():
            ST.log('停止隧道…')
            core.stop_tunnel()
            ST.log('停止服务…')
            core.stop_server()
            ST.status = '已停止'
            ST.log('已停止', 'ok')

        return self._bg('停止（服务 + 隧道）', work)

    def start_tunnel_only(self):
        def work():
            if tunnel_url():
                ST.log('隧道已存在：%s' % tunnel_url())
                return
            core.start_tunnel()
            for _ in range(120):
                time.sleep(0.5)
                if tunnel_url():
                    core._save_phone_address(tunnel_url(), pin())
                    ST.log('隧道就绪：%s' % tunnel_url(), 'ok')
                    return
            raise RuntimeError('隧道 60 秒内没拿到地址')

        return self._bg('只启动隧道', work)

    def restart_tunnel(self):
        def work():
            ST.log('重启隧道…')
            core.restart_cloudflared_tunnel()
            for _ in range(120):
                time.sleep(0.5)
                if tunnel_url():
                    ST.log('隧道就绪：%s' % tunnel_url(), 'ok')
                    return
            raise RuntimeError('隧道 60 秒内没拿到地址')

        return self._bg('重启隧道', work)

    def open_phone_page(self):
        try:
            url = access_url()
            if not url:
                return {'ok': False, 'msg': '还没有可用的访问地址'}
            import webbrowser
            webbrowser.open(url)
            return {'ok': True, 'url': url}
        except Exception as e:
            return {'ok': False, 'msg': str(e)}

    def copy_access_url(self):
        try:
            return {'ok': True, 'url': access_url()}
        except Exception as e:
            return {'ok': False, 'msg': str(e)}

    def save_phone_address(self):
        try:
            u = tunnel_url()
            if not u:
                return {'ok': False, 'msg': '还没有隧道地址'}
            core._save_phone_address(u, pin())
            return {'ok': True, 'path': str(core.data_dir() / 'phone-address.txt')}
        except Exception as e:
            return {'ok': False, 'msg': str(e)}

    def open_data_dir(self):
        try:
            os.startfile(str(core.data_dir()))
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'msg': str(e)}

    # ---------------- 用量统计 ----------------
    def usage(self, rng='近30天', cfrom='', cto=''):
        """官网用量汇总（按区间过滤）。纯读本地文件，不联网。"""
        try:
            return _usage_payload(rng, cfrom, cto)
        except Exception as e:
            return {'ok': False, 'msg': str(e)}

    def usage_pull(self):
        """用已保存的官网 Token 拉取最新用量（长任务：线程 + 轮询）"""
        def work():
            tok = _UTOK.get('token') or ''
            if not tok:
                try:
                    tok = core.find_browser_usertoken(deadline=8.0) or ''
                except Exception:
                    tok = ''
            if not tok:
                raise RuntimeError('没有官网 Token（先设置，或在浏览器登录过官网）')
            ST.log('用官网 Token 拉取用量…')
            per_day = None
            try:
                fetched = core.fetch_official_usage_api(tok)
                per_day = fetched.get('per_day') if isinstance(fetched, dict) else fetched
            except Exception:
                per_day = None
            if per_day:
                core.save_api_usage(per_day)
                ST.log('官网用量已更新：%d 天' % len(per_day), 'ok')
            else:
                raise RuntimeError('拉取失败（Token 可能失效，或网络不通）')

        return self._bg('拉取官网用量', work)

    def usage_import(self):
        """选择官网导出的 amount-*.csv / zip 导入"""
        try:
            win = webview.windows[0]
            res = win.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False,
                file_types=('用量数据 (*.csv;*.zip)', 'CSV (*.csv)', 'ZIP (*.zip)'))
            path = (res[0] if isinstance(res, (list, tuple)) else res) or ''
            if not path:
                return {'ok': True, 'canceled': True}
            parsed = core.parse_official_usage_any(path)
            if not parsed:
                return {'ok': False, 'msg': '没解析出用量数据，请选官网「用量」页下载的 amount-*.csv / zip'}
            try:
                core.save_official_usage(path)
            except OSError:
                pass
            core.mark_imported(path)
            days = parsed.get('days') or []
            span = ('%s ~ %s' % (days[0], days[-1])) if days else ''
            ST.log('已导入官网用量 %s' % span, 'ok')
            return {'ok': True, 'span': span, 'days': len(days),
                    'hit': parsed.get('hit', 0), 'miss': parsed.get('miss', 0),
                    'output': parsed.get('output', 0), 'name': os.path.basename(path)}
        except Exception as e:
            return {'ok': False, 'msg': str(e)}

    def usage_token_state(self):
        try:
            return _token_state()
        except Exception as e:
            return {'ok': False, 'msg': str(e)}

    def usage_set_token(self, token):
        """验证并保存官网 Token（后台线程验证，结果通过 usage() 的 tokenState 轮询）"""
        tok = (token or '').strip()
        if len(tok) < 20:
            return {'ok': False, 'msg': 'Token 太短，请确认复制的是 userToken'}
        if _TOK['pending']:
            return {'ok': False, 'msg': '正在验证上一个 Token…'}
        _TOK.update({'pending': True, 'state': 'verifying', 'msg': '验证中…', 'token': tok})

        def work():
            ok, msg = False, ''
            try:
                ok, msg = core.verify_usage_token(tok)
            except Exception as e:
                ok, msg = False, str(e)
            if ok:
                try:
                    core.save_usage_token(tok)
                    _TOK.update({'state': 'ok', 'msg': '已保存（验证通过）', 'token': tok})
                    ST.log('官网 Token 已保存', 'ok')
                except OSError as e:
                    _TOK.update({'state': 'err', 'msg': '保存失败：%s' % e})
            else:
                _TOK.update({'state': 'err', 'msg': msg or 'Token 无效'})
                ST.log('官网 Token 验证失败：%s' % (msg or ''), 'err')
            _TOK['pending'] = False

        threading.Thread(target=work, daemon=True, name='panel-token').start()
        return {'ok': True, 'pending': True}

    def usage_clear_token(self):
        try:
            core.usage_token_path().unlink(missing_ok=True)
            _TOK.update({'state': 'none', 'msg': '已清除', 'token': '', 'pending': False})
            ST.log('已清除官网 Token')
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'msg': str(e)}

    def usage_clipboard(self):
        """把剪贴板内容当 Token 验证保存（前端 navigator.clipboard 读到后直接传进来）"""
        return {'ok': False, 'msg': '请在输入框粘贴 Token'}

    def open_topup(self):
        try:
            import webbrowser
            webbrowser.open('https://platform.deepseek.com/top_up')
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'msg': str(e)}


# ---------------------------------------------------------------- 隧道看门狗

_WD = {'last': 0.0, 'fails': 0}


def _tunnel_watchdog():
    """服务在跑但隧道掉了就自动重连（旧 GUI 有这个能力，新面板之前漏了）。

    触发条件：
      1) 隧道进程已死（pid 文件对应进程不存在）
      2) 进程活着但日志里最后一次状态是断连（tunnel_connected() 为假）
    每 20 秒检查一次；连续失败会退避，避免疯狂重启。
    """
    while True:
        time.sleep(20)
        try:
            if ST.busy:
                # 正在启动/停止：隧道可能还没注册好，别把它当掉线重启（会把启动拖到 1 分钟以上）
                continue
            if not core.is_running(PORT):
                continue
            alive = False
            try:
                alive = bool(core._tunnel_alive())
            except Exception:
                alive = False
            if alive:
                try:
                    if core.tunnel_connected():
                        _WD['fails'] = 0
                        continue
                except Exception:
                    pass
                reason = '隧道连接已断'
            else:
                reason = '隧道进程已退出'
            now = time.time()
            if now - _WD['last'] < 45:
                continue
            _WD['last'] = now
            ST.log('%s，自动重连…' % reason, '')
            try:
                core.restart_cloudflared_tunnel()
                ST.log('已自动重启隧道，等待新地址…')
            except Exception as e:
                ST.log('自动重连失败：%s' % e, 'err')
        except Exception:
            pass

# ---------------------------------------------------------------- 入口

def _single_instance():
    try:
        import ctypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        _k32 = k32
        k32.CreateMutexW(None, False, 'Global\\PhoneConsolePanel_SingleInstance')
        if ctypes.get_last_error() == 183:
            return False
    except Exception:
        pass
    return True


def main():
    if webview is None:
        print('缺少 pywebview：python -m pip install pywebview')
        return 1
    if sys.platform == 'win32' and not _single_instance():
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, '手机远程控制台面板已经在运行了。', APP_TITLE, 0x40)
        except Exception:
            pass
        return 0

    api = Api()
    ST.log('面板已启动', 'ok')
    threading.Thread(target=_tunnel_watchdog, daemon=True, name='tunnel-watchdog').start()
    ST.log('隧道看门狗已启动（每 20 秒检查，掉线自动重连）')
    window = webview.create_window(
        APP_TITLE, url=UI_FILE, js_api=api,
        width=1280, height=860, min_size=(1040, 680),
        background_color='#0f1117', text_select=True,
        zoomable=False,          # 别让 Ctrl+滚轮 缩放整个界面
    )
    webview.start(debug=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())

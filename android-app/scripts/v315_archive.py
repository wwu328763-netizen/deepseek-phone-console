# -*- coding: utf-8 -*-
"""v3.1.5
1) APK 发送的文件落到「该会话自己的工作区」（thread.workdir / session.cwd），不再全丢到全局 root
2) 手机侧边栏加会话归档（本地归档，可取消）
3) 电脑端已归档的会话仍然不显示（沿用 workspace.json 过滤），手机归档的默认也隐藏
"""
import io
import os

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
SRV = os.path.join(PHONE, 'server.py')
APP = os.path.join(PHONE, 'webapp', 'src', 'app.tsx')
API = os.path.join(PHONE, 'webapp', 'src', 'api.ts')
CSS = os.path.join(PHONE, 'webapp', 'src', 'styles.css')


def read(p):
    return io.open(p, encoding='utf-8').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


# ============================================================ 服务端
s = read(SRV)

# 1) 会话上传 → 会话自己的 cwd
if 'def session_workdir' not in s:
    anchor = '    def save_upload(state, filename, data):'
    add = '''    def session_workdir(self, sid):
        """电脑端会话对应的工作目录（DSH 的 cwd）；拿不到就回退到根目录。"""
        try:
            for s in self.dsh.list_sessions():
                if s.get("sessionId") == sid and s.get("cwd"):
                    return str(s["cwd"])
        except Exception:
            pass
        return str(self.workdir_root)

    def save_upload(state, filename, data):'''
    assert anchor in s
    s = s.replace(anchor, add, 1)

# sessions upload 使用 session_workdir
s = s.replace("                result = self.app.save_upload_to(str(self.app.workdir_root), filename, data)",
              "                result = self.app.save_upload_to(self.app.session_workdir(sid), filename, data)")

# 2) 本地归档存储 + API
if 'def local_archived' not in s:
    anchor2 = '    # -- sessions -----------------------------------------------------------'
    add2 = '''    # -- 手机端归档（本地） --------------------------------------------------
    def _archive_file(self):
        return self.data_dir / "archived.json"

    def local_archived(self):
        """{kind: [id,...]}：手机侧边栏归档过的会话。"""
        try:
            raw = self._archive_file().read_text(encoding="utf-8")
            data = json.loads(raw or "{}")
        except Exception:
            data = {}
        out = {}
        for k in ("thread", "session"):
            v = data.get(k) or []
            out[k] = [str(x) for x in v]
        return out

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

''' + anchor2
    assert anchor2 in s
    s = s.replace(anchor2, add2, 1)

# GET /api/archived
if '"/api/archived"' not in s:
    anchor3 = '        if path == "/api/threads":\n            self._json({"threads": self.app.list_threads()})'
    add3 = '''        if path == "/api/archived":
            self._json(self.app.local_archived())
            return

''' + anchor3
    assert anchor3 in s, 'GET threads anchor'
    s = s.replace(anchor3, add3, 1)

# POST /api/archive
if '"/api/archive"' not in s:
    anchor4 = '        if path == "/api/bg":\n            data = self._read_json()'
    add4 = '''        if path == "/api/archive":
            data = self._read_json()
            kind = "session" if str(data.get("kind")) == "session" else "thread"
            ident = str(data.get("id") or "").strip()
            if not ident:
                self._json({"error": "empty id"}, 400)
                return
            out = self.app.set_archived(kind, ident, bool(data.get("archived")))
            self._json({"ok": True, "archived": out.get(kind, [])})
            return

''' + anchor4
    assert anchor4 in s, 'POST bg anchor'
    s = s.replace(anchor4, add4, 1)

write(SRV, s)
print('server.py: 会话工作区上传 + 本地归档 API')

# ============================================================ 前端 api.ts
a = read(API)
if 'export async function getArchived' not in a:
    a += '''

/* ---- 手机端归档 ---- */
export async function getArchived(): Promise<{ thread: string[]; session: string[] }> {
  return json<{ thread: string[]; session: string[] }>('/api/archived');
}

export async function setArchived(kind: 'thread' | 'session', id: string, archived: boolean) {
  return json<{ ok: boolean; archived: string[] }>('/api/archive', {
    method: 'POST',
    body: JSON.stringify({ kind, id, archived }),
  });
}
'''
    write(API, a)
    print('api.ts: getArchived / setArchived')

# ============================================================ 前端 Drawer
d = read(APP)

# import
d = d.replace("  makeDir, setModel, setPin, stream, blobUrl, cachedBlobUrl, downloadRaw, getBg, saveBg,",
              "  makeDir, setModel, setPin, stream, blobUrl, cachedBlobUrl, downloadRaw, getBg, saveBg,\n  getArchived, setArchived,")

# 图标：归档箱
if '\n  archive:' not in d:
    d = d.replace("  up: <path d=\"M12 19V5M5.5 11.5 12 5l6.5 6.5\" />,",
                  "  up: <path d=\"M12 19V5M5.5 11.5 12 5l6.5 6.5\" />,\n  archive: <path d=\"M3 7h18v4H3zM5 11v9h14v-9M10 15h4\" />,", 1)

start = d.index('function Drawer(props: {')
end = d.index('/* ────────────────────────── 设置 ────────────────────────── */', start)
new_drawer = '''function Drawer(props: {
  open: boolean; onClose: () => void;
  onPick: (kind: 'thread' | 'session', id: string, title: string) => void;
  onNew: () => void; active: string | null;
}) {
  const s = useStore();
  const [tab, setTab] = useState<'thread' | 'session'>('thread');
  const [showArch, setShowArch] = useState(false);
  const [arch, setArch] = useState<{ thread: string[]; session: string[] }>({ thread: [], session: [] });

  useEffect(() => {
    if (!props.open) return;
    getArchived().then(setArch).catch(() => null);
  }, [props.open]);

  const archSet = new Set((tab === 'thread' ? arch.thread : arch.session) || []);
  const all = (tab === 'thread' ? s.threads : s.sessions) || [];
  const list = all.filter((it: any) => (showArch ? archSet.has(String(it.id)) : !archSet.has(String(it.id))));
  const archCount = all.filter((it: any) => archSet.has(String(it.id))).length;

  const toggleArchive = async (id: string, ev: any) => {
    ev.stopPropagation();
    const next = !archSet.has(id);
    try {
      await setArchived(tab, id, next);
      const fresh = await getArchived();
      setArch(fresh);
      toast(next ? '已归档' : '已取消归档', 'ok');
    } catch (e) {
      toast('归档失败：' + (e as Error).message, 'err');
    }
  };

  return (
    <div class={'drawer' + (props.open ? ' open' : '')}>
      <div class="drawer-mask" onClick={props.onClose} />
      <aside class="drawer-panel">
        <div class="drawer-head">
          <b>{showArch ? '已归档' : '会话'}</b>
          <button class="ghost-btn" onClick={props.onNew}><Icon name="plus" /></button>
        </div>
        <div class="seg">
          <button class={tab === 'thread' ? 'on' : ''} onClick={() => setTab('thread')}>手机任务</button>
          <button class={tab === 'session' ? 'on' : ''} onClick={() => setTab('session')}>电脑端</button>
        </div>
        <div class="drawer-list">
          {list.length === 0 ? <div class="drawer-empty">{showArch ? '没有归档的会话' : '还没有会话'}</div> : null}
          {list.map((it: any) => {
            const id = it.id;
            const title = it.name || it.cwd || id;
            const active = props.active === tab + ':' + id;
            return (
              <div key={id} class={'row-wrap'}>
                <button class={'row' + (active ? ' active' : '')}
                  onClick={() => { props.onPick(tab, id, title); }}>
                  <span class={'row-dot' + (it.running ? ' run' : '')} />
                  <span class="row-title">{title}</span>
                  <span class="row-time">{relativeTime(it.created_at || it.updated)}</span>
                </button>
                <button class="row-arch" title={showArch ? '取消归档' : '归档'}
                  onClick={(ev) => toggleArchive(id, ev)}>
                  <Icon name="archive" size={14} />
                </button>
              </div>
            );
          })}
        </div>
        <button class="drawer-arch-toggle" onClick={() => setShowArch(!showArch)}>
          {showArch ? '返回会话列表' : `查看已归档${archCount ? '（' + archCount + '）' : ''}`}
        </button>
      </aside>
    </div>
  );
}

'''
d = d[:start] + new_drawer + d[end:]
write(APP, d)
print('app.tsx: 侧边栏归档（归档/取消、已归档列表）')

# ============================================================ CSS
c = read(CSS)
c += '''

/* ══════════ v3.1.5：侧边栏归档 ══════════ */
.row-wrap { position: relative; display: flex; align-items: center; }
.row-wrap > .row { flex: 1; min-width: 0; }
.row-arch {
  flex: none; width: 30px; height: 30px; margin-right: 4px; border-radius: 8px;
  display: grid; place-items: center; color: var(--faint);
}
.row-arch:active { background: rgba(127, 127, 127, .16); color: var(--text); }
.drawer-arch-toggle {
  margin: 8px 12px 12px; padding: 10px; border-radius: 10px;
  border: 1px solid var(--line-2); color: var(--muted); font-size: 13px;
}
.drawer-arch-toggle:active { background: rgba(127, 127, 127, .12); }
'''
write(CSS, c)
print('styles.css: 归档按钮样式')

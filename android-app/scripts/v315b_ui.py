# -*- coding: utf-8 -*-
"""v3.1.5 前端部分：侧边栏归档（归档/取消、已归档列表）"""
import io
import os

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
APP = os.path.join(PHONE, 'webapp', 'src', 'app.tsx')
API = os.path.join(PHONE, 'webapp', 'src', 'api.ts')
CSS = os.path.join(PHONE, 'webapp', 'src', 'styles.css')


def read(p):
    return io.open(p, encoding='utf-8').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


# ---------------- api.ts
a = read(API)
if 'getArchived' not in a:
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
    print('api.ts OK')

# ---------------- app.tsx
d = read(APP)

# import 注入
if 'getArchived' not in d:
    anchor = "  makeDir, setModel, setPin, stream, blobUrl, cachedBlobUrl, downloadRaw, getBg, saveBg,"
    assert anchor in d, 'import anchor'
    d = d.replace(anchor, anchor + "\n  getArchived, setArchived,", 1)

# 图标：archive
if '\n  archive:' not in d:
    anchor = "  up: <path d=\"M12 19V5M5.5 11.5 12 5l6.5 6.5\" />,"
    assert anchor in d, 'icon anchor'
    d = d.replace(anchor, anchor + "\n  archive: <path d=\"M3 7h18v4H3zM5 11v9h14v-9M10 15h4\" />,", 1)

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
    setShowArch(false);
    getArchived().then(setArch).catch(() => null);
  }, [props.open]);

  const archSet = new Set((tab === 'thread' ? arch.thread : arch.session) || []);
  const all = (tab === 'thread' ? s.threads : s.sessions) || [];
  const list = all.filter((it: any) => (showArch ? archSet.has(String(it.id)) : !archSet.has(String(it.id))));
  const archCount = all.filter((it: any) => archSet.has(String(it.id))).length;

  const toggleArchive = async (id: string, ev: any) => {
    ev.stopPropagation();
    const next = !archSet.has(String(id));
    try {
      await setArchived(tab, id, next);
      setArch(await getArchived());
      toast(next ? '已归档，可在「查看已归档」里找回' : '已取消归档', 'ok');
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
              <div key={id} class="row-wrap">
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
          {showArch ? '返回会话列表' : '查看已归档' + (archCount ? '（' + archCount + '）' : '')}
        </button>
      </aside>
    </div>
  );
}

'''
d = d[:start] + new_drawer + d[end:]
write(APP, d)
print('app.tsx OK（侧边栏归档）')

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
'''
write(CSS, c)
print('styles.css OK')

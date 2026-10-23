# -*- coding: utf-8 -*-
"""v3.1.8：手机端「用量与计费」弹窗（余额/官方用量/近7天明细）
入口：侧边栏底部 + 设置里的「用量与余额」区
"""
import io
import os

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
APP = os.path.join(PHONE, 'webapp', 'src', 'app.tsx')
CSS = os.path.join(PHONE, 'webapp', 'src', 'styles.css')

s = io.open(APP, encoding='utf-8').read()

# ---------------- 工具 + UsageSheet 组件（插在 Drawer 之前）
component = '''
/* ────────────────────────── 用量与计费 ────────────────────────── */
function compactNum(n: number): string {
  n = Number(n) || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return String(Math.round(n));
}

function UsageSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [usage, setUsage] = useState<any>(null);
  const [bal, setBal] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setBusy(true);
    Promise.all([
      getUsage().then(setUsage).catch(() => null),
      getBalance().then(setBal).catch(() => null),
    ]).finally(() => setBusy(false));
  };
  useEffect(() => { if (open) load(); }, [open]);

  if (!open) return null;
  const o = usage?.official;
  const days: string[] = (o?.days || []).slice();
  const per: Record<string, any> = o?.per_day || {};
  const last7 = days.slice(-7);
  const sumOf = (d: string) => {
    const r = per[d] || {};
    return (r.hit || 0) + (r.miss || 0) + (r.output || 0);
  };
  const maxV = Math.max(1, ...last7.map(sumOf));
  const coin = bal?.balance_infos?.[0];
  const totalTokens = o ? (o.hit || 0) + (o.miss || 0) + (o.output || 0) : 0;

  return (
    <div class="sheet-wrap">
      <div class="sheet-mask" onClick={onClose} />
      <div class="sheet">
        <div class="sheet-grab" />
        <div class="sheet-head">
          <b>用量与计费</b>
          <div class="row-actions">
            <button class="ghost-btn" onClick={load} title="刷新">{busy ? '…' : '刷新'}</button>
            <button class="ghost-btn" onClick={onClose}><Icon name="close" /></button>
          </div>
        </div>

        <div class="usage-hero">
          <div class="usage-hero-label">DeepSeek 账户余额</div>
          <div class="usage-hero-value">
            {coin ? (coin.currency === 'CNY' ? '¥' : '') + coin.total_balance : '—'}
          </div>
          <div class="usage-hero-sub">
            {coin ? (coin.currency === 'CNY' ? '人民币' : coin.currency) + ' · 已充值 ' + (coin.topped_up_balance ?? '—') : (bal && bal.is_available === false ? '未配置 API Token，去桌面端面板设置' : '读取中…')}
          </div>
          <a class="primary-btn" href="https://platform.deepseek.com/top_up" target="_blank" rel="noopener">去充值</a>
        </div>

        <div class="field">
          <label>官方用量（全部时间）</label>
          <div class="usage-grid">
            <div><span>覆盖</span><b>{days.length} 天</b></div>
            <div><span>请求</span><b>{(o?.requests || 0).toLocaleString()}</b></div>
            <div><span>总 tokens</span><b>{compactNum(totalTokens)}</b></div>
            <div><span>缓存命中率</span><b>{o ? Number(o.hit_rate || 0).toFixed(2) + '%' : '—'}</b></div>
            <div><span>命中缓存</span><b>{compactNum(o?.hit || 0)}</b></div>
            <div><span>未命中</span><b>{compactNum(o?.miss || 0)}</b></div>
            <div><span>输出</span><b>{compactNum(o?.output || 0)}</b></div>
            <div><span>统计区间</span><b>{days.length ? days[0].slice(5) + ' ~ ' + days[days.length - 1].slice(5) : '—'}</b></div>
          </div>
        </div>

        <div class="field">
          <label>近 7 天</label>
          {last7.length ? (
            <div class="usage-bars">
              {last7.map((d) => (
                <div class="usage-bar" key={d}>
                  <div class="usage-bar-track">
                    <i style={{ height: Math.max(3, Math.round(sumOf(d) / maxV * 72)) + 'px' }} />
                  </div>
                  <div class="usage-bar-label">{d.slice(5)}</div>
                </div>
              ))}
            </div>
          ) : <div class="hint">还没有官方用量数据</div>}
          <div class="usage-list">
            {last7.slice().reverse().map((d) => {
              const r = per[d] || {};
              return (
                <div class="usage-row" key={d}>
                  <span class="usage-date">{d.slice(5)}</span>
                  <span>{compactNum(sumOf(d))}</span>
                  <span class="usage-muted">命中 {compactNum(r.hit || 0)}</span>
                  <span class="usage-muted">{(r.requests || 0).toLocaleString()} 次</span>
                </div>
              );
            })}
          </div>
        </div>
        <div class="hint">数据来自电脑端 console_data/usage 的官网用量 CSV，由桌面面板定时拉取。</div>
      </div>
    </div>
  );
}

'''
anchor = 'function Drawer(props: {'
assert anchor in s
s = s.replace(anchor, component + anchor, 1)

# ---------------- Drawer 底部入口
d_start = s.index('function Drawer(props: {')
d_end = s.index('/* ────────────────────────── 设置 ────────────────────────── */', d_start)
drawer = s[d_start:d_end]
drawer = drawer.replace("  const [arch, setArch] = useState<{ thread: string[]; session: string[] }>({ thread: [], session: [] });",
                        "  const [arch, setArch] = useState<{ thread: string[]; session: string[] }>({ thread: [], session: [] });\n"
                        "  const [usageOpen, setUsageOpen] = useState(false);")
drawer = drawer.replace('''        <button class="drawer-arch-toggle" onClick={() => setShowArch(!showArch)}>''',
                        '''        <button class="drawer-usage-btn" onClick={() => setUsageOpen(true)}>
          <Icon name="archive" size={14} />
          <span>用量与计费</span>
        </button>
        <button class="drawer-arch-toggle" onClick={() => setShowArch(!showArch)}>''')
drawer = drawer.replace('''      </aside>
    </div>
  );
}''', '''      </aside>
      <UsageSheet open={usageOpen} onClose={() => setUsageOpen(false)} />
    </div>
  );
}''')
s = s[:d_start] + drawer + s[d_end:]

# ---------------- Settings 里加“查看详细”入口
s = s.replace('''          <div class="row-actions">
            <a class="outline-btn" href="https://platform.deepseek.com/top_up" target="_blank" rel="noopener">去充值</a>''',
              '''          <div class="row-actions">
            <button class="outline-btn" onClick={() => setUsageOpen(true)}>查看详细用量与计费</button>
            <a class="outline-btn" href="https://platform.deepseek.com/top_up" target="_blank" rel="noopener">去充值</a>''')

# Settings 增加 usageOpen 状态并在 at 末尾渲染
s = s.replace("  const [busy, setBusy] = useState(false);\n  const [picker, setPicker] = useState(false);",
              "  const [busy, setBusy] = useState(false);\n  const [picker, setPicker] = useState(false);\n  const [usageOpen, setUsageOpen] = useState(false);")
s = s.replace('''        {picker ? (
          <ModelSheet open={picker} onClose={() => setPicker(false)} models={models}''',
              '''        {usageOpen ? <UsageSheet open={usageOpen} onClose={() => setUsageOpen(false)} /> : null}
        {picker ? (
          <ModelSheet open={picker} onClose={() => setPicker(false)} models={models}''')

io.open(APP, 'w', encoding='utf-8', newline='\n').write(s)
print('app.tsx: 用量与计费弹窗 + 两个入口')

# ---------------- CSS
c = io.open(CSS, encoding='utf-8').read()
c += '''

/* ══════════ v3.1.8：用量与计费 ══════════ */
.drawer-usage-btn {
  margin: 6px 12px 0; padding: 11px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center; gap: 6px;
  border: 1px solid var(--line-2); color: var(--muted); font-size: 13px;
}
.usage-hero {
  border: 1px solid var(--line-2); border-radius: 14px; padding: 14px;
  margin-bottom: 6px; background: linear-gradient(160deg, rgba(77,107,254,.10), transparent 70%);
}
.usage-hero-label { font-size: 12px; color: var(--muted); }
.usage-hero-value { font-size: 30px; font-weight: 700; letter-spacing: -.02em; margin: 4px 0 2px; }
.usage-hero-sub { font-size: 11.5px; color: var(--faint); margin-bottom: 10px; }
.usage-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.usage-grid > div { display: flex; flex-direction: column; gap: 2px; padding: 9px 11px; border-radius: 10px; background: var(--bg-2); }
.usage-grid span { font-size: 11px; color: var(--muted); }
.usage-grid b { font-size: 14.5px; }
.usage-bars { display: flex; align-items: flex-end; gap: 8px; height: 96px; padding: 6px 2px 0; }
.usage-bar { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px; }
.usage-bar-track { width: 100%; height: 76px; display: flex; align-items: flex-end; }
.usage-bar-track i { display: block; width: 100%; border-radius: 6px 6px 2px 2px; background: linear-gradient(180deg, #5b7bff, #4d6bfe); }
.usage-bar-label { font-size: 9.5px; color: var(--faint); }
.usage-list { margin-top: 8px; display: flex; flex-direction: column; }
.usage-row { display: flex; gap: 10px; align-items: center; padding: 7px 2px; border-bottom: 1px solid var(--line); font-size: 12.5px; }
.usage-date { width: 46px; color: var(--muted); flex: none; }
.usage-muted { color: var(--faint); }
'''
io.open(CSS, 'w', encoding='utf-8', newline='\n').write(c)
print('styles.css: 用量弹窗样式')

# -*- coding: utf-8 -*-
"""v3.1.7：设置里的模型/强度改成弹窗选择（复用输入栏的 ModelSheet）"""
import io
import os

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
APP = os.path.join(PHONE, 'webapp', 'src', 'app.tsx')
CSS = os.path.join(PHONE, 'webapp', 'src', 'styles.css')


def read(p):
    return io.open(p, encoding='utf-8').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


s = read(APP)

# 1) Settings 增加 picker 状态 + 弹窗应用函数
anchor = "  const [busy, setBusy] = useState(false);\n  const [bg, setBg] = useState<BgState>(() => readBg());"
assert anchor in s, 'settings state anchor'
s = s.replace(anchor,
              "  const [busy, setBusy] = useState(false);\n  const [picker, setPicker] = useState(false);\n"
              "  const [bg, setBg] = useState<BgState>(() => readBg());", 1)

# 2) 用 applyPick 替换 applyModel（弹窗里点一下即生效，并刷新本地状态）
old_apply = '''  const applyModel = async () => {
    if (!active || !canSwitch) { toast('先打开一段会话再切换模型', 'err'); return; }
    const provider = providerOf(modelId);
    if (!provider) return;
    setBusy(true);
    try {
      await setModel(active.kind, active.id, provider, modelId, effort || undefined);
      toast('已切换：' + modelId + (effort ? ' · ' + effort : ''), 'ok');
    } catch (e) {
      toast('切换失败：' + (e as Error).message, 'err');
    } finally { setBusy(false); }
  };'''
new_apply = '''  const applyPick = async (provider: string, mid: string, eff: string) => {
    if (!active || !canSwitch) { toast('先打开一段会话再切换模型', 'err'); return; }
    setBusy(true);
    try {
      await setModel(active.kind, active.id, provider, mid, eff || undefined);
      toast('已切换：' + mid + (eff ? ' · ' + eff : ''), 'ok');
      const m = await getModels(active.kind, active.id).catch(() => null);
      if (m) {
        setModels(m);
        setModelId(m.current?.model || mid);
        setEffort(m.current?.reasoningEffort || '');
      }
    } catch (e) {
      toast('切换失败：' + (e as Error).message, 'err');
    } finally { setBusy(false); }
  };'''
assert old_apply in s, 'applyModel anchor'
s = s.replace(old_apply, new_apply, 1)

# 3) 两个 <select> → 一个弹窗入口
old_ui = '''        <div class="field">
          <label>模型{active ? '（对当前会话生效）' : ''}</label>
          <select class="select" value={modelId} disabled={!allModels.length}
            onChange={(e) => { setModelId((e.currentTarget as HTMLSelectElement).value); setEffort(''); }}>
            {allModels.length ? allModels.map((m) => <option key={m.id} value={m.id}>{m.name || m.id}</option>)
              : <option value="">{active ? '加载中…' : '先打开会话'}</option>}
          </select>
          <label style="margin-top:10px">思考强度</label>
          <select class="select" value={effort} disabled={!efforts.length}
            onChange={(e) => setEffort((e.currentTarget as HTMLSelectElement).value)}>
            {efforts.length ? efforts.map((x) => <option key={x.id} value={x.id}>{x.name || x.id}</option>)
              : <option value="">默认</option>}
          </select>
          <button class="outline-btn" style="margin-top:10px" disabled={!canSwitch || busy} onClick={applyModel}>
            {busy ? '切换中…' : canSwitch ? '应用到当前会话' : '打开会话后可切换'}
          </button>
        </div>'''
new_ui = '''        <div class="field">
          <label>模型与思考强度{active ? '（对当前会话生效）' : ''}</label>
          <button class="picker-row" disabled={!canSwitch || busy} onClick={() => setPicker(true)}>
            <span class="picker-main">{curModel?.name || modelId || (active ? '加载中…' : '先打开会话')}</span>
            <span class="picker-sub">强度 · {efforts.find((x) => x.id === effort)?.name || effort || '默认'}</span>
            <span class="picker-arrow"><Icon name="chevron" size={14} /></span>
          </button>
          {!canSwitch ? <div class="hint">{active ? '当前会话不支持切换模型' : '打开一段会话后可以切换'}</div> : null}
        </div>
        {picker ? (
          <ModelSheet open={picker} onClose={() => setPicker(false)} models={models}
            modelId={modelId} effort={effort} onApply={applyPick} busy={busy} />
        ) : null}'''
assert old_ui in s, 'settings model ui anchor'
s = s.replace(old_ui, new_ui, 1)

write(APP, s)
print('app.tsx: 设置里的模型/强度改为弹窗')

c = read(CSS)
c += '''

/* ══════════ v3.1.7：设置里的模型选择入口（弹窗触发器） ══════════ */
.picker-row {
  width: 100%; display: flex; align-items: center; gap: 8px;
  padding: 12px 14px; border-radius: 12px;
  border: 1px solid var(--line-2); background: var(--surface);
  text-align: left;
}
.picker-row:disabled { opacity: .55; }
.picker-main { font-size: 14.5px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.picker-sub { font-size: 12px; color: var(--muted); flex: none; }
.picker-arrow { color: var(--faint); display: inline-flex; transform: rotate(180deg); }
'''
write(CSS, c)
print('styles.css: picker-row')

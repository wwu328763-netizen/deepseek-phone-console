# -*- coding: utf-8 -*-
"""v3.0.6：把模型 / 思考强度放到输入栏（ChatGPT 风格）+ 设置里加「返回登录界面」"""
import io
import os

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
APP = os.path.join(PHONE, 'webapp', 'src', 'app.tsx')

s = io.open(APP, encoding='utf-8').read()

# ---------------------------------------------------------------- 1) Composer 增加模型/强度 chips
old_sig = """function Composer(props: {
  disabled: boolean; running: boolean;
  onSend: (text: string, images: string[], files: string[]) => Promise<void>;"""
new_sig = """function Composer(props: {
  disabled: boolean; running: boolean;
  modelName?: string; effortName?: string; onOpenModel?: () => void;
  onSend: (text: string, images: string[], files: string[]) => Promise<void>;"""
assert old_sig in s, 'composer signature anchor'
s = s.replace(old_sig, new_sig, 1)

old_end = """        )}
      </div>
    </div>
  );
}"""
new_end = """        )}
      </div>
      <div class="composer-meta">
        <button class="meta-chip" type="button" onClick={() => props.onOpenModel?.()}>
          <Icon name="spark" size={12} />{props.modelName || '选择模型'}
        </button>
        <button class="meta-chip" type="button" onClick={() => props.onOpenModel?.()}>
          强度 · {props.effortName || '默认'}
        </button>
      </div>
    </div>
  );
}"""
assert old_end in s, 'composer end anchor'
s = s.replace(old_end, new_end, 1)

# ---------------------------------------------------------------- 2) ModelSheet 组件（输入栏弹出）
sheet = '''
/* ────────────────────────── 模型 / 强度选择（输入栏弹出，ChatGPT 式） ────────────────────────── */
function ModelSheet(props: {
  open: boolean; onClose: () => void;
  models: ModelsPayload | null;
  modelId: string; effort: string;
  onApply: (provider: string, modelId: string, effort: string) => Promise<void>;
  busy: boolean;
}) {
  const groups = props.models?.catalog?.groups || [];
  const all = groups.reduce<ModelInfo[]>((acc, g) => acc.concat(g.models || []), []);
  const cur = all.find((m) => m.id === props.modelId);
  const efforts = cur?.reasoning?.efforts || [];
  const [localEffort, setLocalEffort] = useState(props.effort);
  useEffect(() => { setLocalEffort(props.effort); }, [props.effort, props.modelId]);
  const providerOf = (mid: string) => {
    for (const g of groups) { if ((g.models || []).some((x) => x.id === mid)) return g.id; }
    return '';
  };
  if (!props.open) return null;
  return (
    <div class="sheet-wrap">
      <div class="sheet-mask" onClick={props.onClose} />
      <div class="sheet">
        <div class="sheet-grab" />
        <div class="sheet-head"><b>模型与思考强度</b>
          <button class="ghost-btn" onClick={props.onClose}><Icon name="close" /></button>
        </div>
        {!all.length ? <div class="hint">先打开一段会话，才能切换模型</div> : null}
        <div class="model-list">
          {groups.map((g) => (
            <div class="model-group" key={g.id}>
              <div class="model-group-title">{g.name || g.id}</div>
              {(g.models || []).map((m) => (
                <button key={m.id}
                  class={'model-row' + (m.id === props.modelId ? ' on' : '')}
                  disabled={props.busy}
                  onClick={() => props.onApply(providerOf(m.id), m.id, '')}>
                  <span class="model-row-name">{m.name || m.id}</span>
                  {m.id === props.modelId ? <span class="model-row-tag">当前</span> : null}
                </button>
              ))}
            </div>
          ))}
        </div>
        {efforts.length ? (
          <div class="field">
            <label>思考强度</label>
            <div class="seg">
              {efforts.map((x) => (
                <button key={x.id} class={localEffort === x.id ? 'on' : ''}
                  onClick={() => {
                    setLocalEffort(x.id);
                    props.onApply(providerOf(props.modelId), props.modelId, x.id);
                  }}>{x.name || x.id}</button>
              ))}
            </div>
          </div>
        ) : null}
        <div class="hint">点击模型立即对当前会话生效；「思考强度」跟随所选模型。</div>
      </div>
    </div>
  );
}

'''
anchor_comp = "/* ────────────────────────── 主应用 ────────────────────────── */"
assert anchor_comp in s
s = s.replace(anchor_comp, sheet + anchor_comp, 1)

# ---------------------------------------------------------------- 3) App：状态 + 加载 + 应用 + 渲染
old_state = """  const pendingSend = useRef<null | { text: string; images: string[]; files: string[] }>(null);"""
new_state = """  const pendingSend = useRef<null | { text: string; images: string[]; files: string[] }>(null);
  /* 模型 / 强度（输入栏） */
  const [models, setModels] = useState<ModelsPayload | null>(null);
  const [modelOpen, setModelOpen] = useState(false);
  const [modelBusy, setModelBusy] = useState(false);"""
assert old_state in s
s = s.replace(old_state, new_state, 1)

# 加载 models：打开会话时
anchor_effect = "  /* running 由 true → false：把排队中的消息发出去 */"
new_effect = """  /* 打开会话 → 拉模型目录（输入栏显示当前模型/强度） */
  useEffect(() => {
    const a = s.active;
    if (!a) { setModels(null); return; }
    getModels(a.kind, a.id).then(setModels).catch(() => null);
  }, [s.active?.kind, s.active?.id]);

  const modelGroups = models?.catalog?.groups || [];
  const allModelInfos = modelGroups.reduce<ModelInfo[]>((acc, g) => acc.concat(g.models || []), []);
  const curModelInfo = allModelInfos.find((m) => m.id === (models?.current?.model || ''));
  const curEfforts = curModelInfo?.reasoning?.efforts || [];
  const curEffortInfo = curEfforts.find((x) => x.id === (models?.current?.reasoningEffort || ''));

  const applyModelChoice = useCallback(async (provider: string, mid: string, eff: string) => {
    const a = stateRef.current.active;
    if (!a) { toast('先打开一段会话', 'err'); return; }
    setModelBusy(true);
    try {
      await setModel(a.kind, a.id, provider, mid, eff || undefined);
      toast('已切换：' + mid + (eff ? ' · ' + eff : ''), 'ok');
      const m = await getModels(a.kind, a.id).catch(() => null);
      if (m) setModels(m);
    } catch (e) {
      toast('切换失败：' + (e as Error).message, 'err');
    } finally { setModelBusy(false); }
  }, []);

"""
assert anchor_effect in s
s = s.replace(anchor_effect, new_effect + anchor_effect, 1)

# Composer 传参
old_comp_use = '      <Composer disabled={!s.active} running={s.running} onSend={send} onStop={stop} upload={upload} />'
new_comp_use = """      <Composer disabled={!s.active} running={s.running} onSend={send} onStop={stop} upload={upload}
        modelName={allModelInfos.find((m) => m.id === (models?.current?.model || ''))?.name
          || models?.current?.model || ''}
        effortName={curEffortInfo?.name || models?.current?.reasoningEffort || ''}
        onOpenModel={() => setModelOpen(true)} />"""
assert old_comp_use in s
s = s.replace(old_comp_use, new_comp_use, 1)

# ModelSheet 渲染
old_settings_render = "      <Settings open={settings} onClose={() => setSettings(false)} active={s.active} />"
new_settings_render = """      <Settings open={settings} onClose={() => setSettings(false)} active={s.active} />
      <ModelSheet open={modelOpen} onClose={() => setModelOpen(false)} models={models}
        modelId={models?.current?.model || ''} effort={models?.current?.reasoningEffort || ''}
        onApply={applyModelChoice} busy={modelBusy} />"""
assert old_settings_render in s
s = s.replace(old_settings_render, new_settings_render, 1)

# ---------------------------------------------------------------- 4) 设置里加「返回登录界面」
old_logout = """          <button class="outline-btn" onClick={() => { localStorage.removeItem('console_pin'); location.reload(); }}>
            清除 PIN 并退出
          </button>"""
new_logout = """          <button class="outline-btn" onClick={() => {
              const app = (window as any).PhoneConsole;
              if (app && typeof app.toSettings === 'function') {
                // APK：回原生连接/登录页（可以重新扫码或改地址）
                try { app.toSettings(); return; } catch (e) { /* 落回浏览器逻辑 */ }
              }
              localStorage.removeItem('console_pin');
              location.reload();   // 浏览器：回到网页登录页
            }}>
            返回登录界面
          </button>
          <button class="outline-btn" onClick={() => { localStorage.removeItem('console_pin'); location.reload(); }}>
            清除 PIN 并退出
          </button>"""
assert old_logout in s
s = s.replace(old_logout, new_logout, 1)

io.open(APP, 'w', encoding='utf-8', newline='\n').write(s)
print('app.tsx: 输入栏模型/强度 chips + ModelSheet + 返回登录界面')

# ---------------------------------------------------------------- 5) CSS
CSS = os.path.join(PHONE, 'webapp', 'src', 'styles.css')
c = io.open(CSS, encoding='utf-8').read()
if '.composer-meta' not in c:
    c += '''

/* 输入栏下方的模型 / 强度 chips（ChatGPT 式） */
.composer-meta { display: flex; gap: 8px; align-items: center; padding: 6px 10px 0; }
.meta-chip {
  display: inline-flex; align-items: center; gap: 5px;
  height: 26px; padding: 0 10px; border-radius: 99px; border: 1px solid rgba(0,0,0,.1);
  background: rgba(0,0,0,.03); color: #555; font-size: 12px;
}
:root[data-theme="dark"] .meta-chip { border-color: rgba(255,255,255,.14); background: rgba(255,255,255,.06); color: #ddd; }
.meta-chip:active { transform: scale(.97); }

/* 模型选择列表 */
.model-list { display: flex; flex-direction: column; gap: 4px; max-height: 46vh; overflow: auto; }
.model-group-title { font-size: 11px; color: #8a8f9c; margin: 10px 2px 2px; letter-spacing: .04em; }
.model-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 11px 12px; border-radius: 12px; border: 1px solid rgba(0,0,0,.07);
  background: rgba(0,0,0,.02); font-size: 14px; color: inherit; text-align: left;
}
.model-row.on { border-color: #4d6bfe; background: rgba(77,107,254,.08); }
.model-row-tag { font-size: 11px; color: #4d6bfe; }
'''
    io.open(CSS, 'w', encoding='utf-8', newline='\n').write(c)
    print('styles.css: chips / 模型列表样式')

# -*- coding: utf-8 -*-
"""v3.0.2：手机端输入体验
1) 回车换行（手机软键盘的"换行"不再直接发送）：仅桌面端 Enter 发送 / Ctrl(⌘)+Enter 发送
2) 繁忙时发送改为「排队」：当前回答结束后自动发出；按钮同时保留「停止」
"""
import io
import os

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
APP = os.path.join(PHONE, 'webapp', 'src', 'app.tsx')

s = io.open(APP, encoding='utf-8').read()

# ---------- 1) 设备判定 + Enter 语义 ----------
if 'COARSE_POINTER' not in s:
    anchor = "function Composer(props: {"
    add = ("/* 手机/平板（粗指针）：回车换行，发送只走按钮或 Ctrl+Enter */\n"
           "const COARSE_POINTER = typeof window !== 'undefined' && !!window.matchMedia\n"
           "  && window.matchMedia('(pointer: coarse)').matches;\n\n"
           "function Composer(props: {")
    assert anchor in s
    s = s.replace(anchor, add, 1)

old_key = """          onKeyDown={(e) => {
            if ((e.key === 'Enter' && !e.shiftKey) && !(e as any).isComposing) { e.preventDefault(); doSend(); }
          }} />"""
new_key = """          onKeyDown={(e) => {
            if ((e as any).isComposing) return;
            // Ctrl/⌘+Enter 任何设备都发送；桌面端裸 Enter 发送；
            // 手机（粗指针）裸 Enter = 换行，绝不误发。
            const withMod = e.ctrlKey || e.metaKey;
            if (e.key === 'Enter' && (withMod || (!COARSE_POINTER && !e.shiftKey))) {
              e.preventDefault();
              doSend();
            }
          }} />"""
assert old_key in s, 'keydown anchor missing'
s = s.replace(old_key, new_key, 1)

# ---------- 2) 繁忙时：停止 + 排队发送 ----------
old_btns = """        {props.running ? (
          <button class="composer-send stop" onClick={props.onStop} title="停止"><Icon name="stop" /></button>
        ) : (
          <button class="composer-send" onClick={doSend}
            disabled={props.disabled || uploading || (!text.trim() && !ready.length)} title="发送">
            <Icon name="send" />
          </button>
        )}"""
new_btns = """        {props.running ? (
          <div class="composer-actions">
            <button class="composer-send stop" onClick={props.onStop} title="停止"><Icon name="stop" /></button>
            <button class="composer-send queue" onClick={doSend}
              disabled={props.disabled || uploading || (!text.trim() && !ready.length)}
              title="排队发送：当前回答结束后自动发出">
              <Icon name="send" />
            </button>
          </div>
        ) : (
          <button class="composer-send" onClick={doSend}
            disabled={props.disabled || uploading || (!text.trim() && !ready.length)} title="发送">
            <Icon name="send" />
          </button>
        )}"""
assert old_btns in s, 'buttons anchor missing'
s = s.replace(old_btns, new_btns, 1)

# 输入框 placeholder 里提示手机端语义
s = s.replace("placeholder={props.disabled ? '先选择一个会话…' : uploading ? '附件上传中…' : '发消息给智能体…'}",
              "placeholder={props.disabled ? '先选择一个会话…' : uploading ? '附件上传中…'\n            : (props.running ? '正在回答…可输入，点发送会排队' : '发消息给智能体…（回车换行）')}")

# ---------- 3) 主应用：排队发送 ----------
if 'pendingSend' not in s:
    s = s.replace("  const [viewer, setViewer] = useState<{ path: string; name: string } | null>(null);",
                  "  const [viewer, setViewer] = useState<{ path: string; name: string } | null>(null);\n"
                  "  const pendingSend = useRef<null | { text: string; images: string[]; files: string[] }>(null);\n"
                  "  const stateRef = useRef(s);\n  stateRef.current = s;\n  const prevRunning = useRef(false);")

    old_head = """  const send = useCallback(async (text: string, images: string[], files: string[]) => {
    if (!state.active) return;"""
    new_head = """  const send = useCallback(async (text: string, images: string[], files: string[]) => {
    const st0 = stateRef.current;
    if (!st0.active) return;
    // 繁忙时排队：当前回答结束后自动发出（手机上没有"再点一次"的负担）
    if (st0.running) {
      pendingSend.current = { text, images, files };
      toast('已排队，当前回答结束后自动发送', 'ok');
      return;
    }"""
    assert old_head in s, 'send head anchor missing'
    s = s.replace(old_head, new_head, 1)

    # send 内部其余 state.active / state.items 用最新值
    s = s.replace("      await api.send(state.active.kind, state.active.id, text, images, files);\n      const d = await api.snapshot(state.active.kind, state.active.id).catch(() => null);",
                  "      await api.send(st0.active.kind, st0.active.id, text, images, files);\n      const d = await api.snapshot(st0.active.kind, st0.active.id).catch(() => null);")
    s = s.replace("    set({ items: (state.items || []).concat([echo]), busy: true });",
                  "    set({ items: (st0.items || []).concat([echo]), busy: true });")
    s = s.replace("      set({ items: (state.items || []).filter((x) => x.id !== echo.id) });",
                  "      set({ items: (stateRef.current.items || []).filter((x) => x.id !== echo.id) });")

    # 运行结束 → flush 排队消息
    anchor2 = "  const stop = useCallback(async () => {"
    flush = """  /* running 由 true → false：把排队中的消息发出去 */
  useEffect(() => {
    const was = prevRunning.current;
    prevRunning.current = !!s.running;
    if (was && !s.running && pendingSend.current) {
      const p = pendingSend.current;
      pendingSend.current = null;
      setTimeout(() => { send(p.text, p.images, p.files).catch((e) => toast('排队消息发送失败：' + (e as Error).message, 'err')); }, 120);
    }
  }, [s.running, s.active]);

"""
    assert anchor2 in s
    s = s.replace(anchor2, flush + anchor2, 1)

io.open(APP, 'w', encoding='utf-8', newline='\n').write(s)
print('app.tsx: 回车换行 + 繁忙排队发送')

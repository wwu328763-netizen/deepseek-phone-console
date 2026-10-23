# -*- coding: utf-8 -*-
"""v3.0.9：发送/停止回到第一行；排队改成真正的队列（可见、可删、会被发送）＋繁忙时提供「插入」
布局：
  第一行  文字区 ……… ⏹停止 / ⚡插入 / ➤发送
  第二行  ＋  模型  强度
排队消息显示在输入框上方，点 ✕ 可取消。
"""
import io
import os

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
APP = os.path.join(PHONE, 'webapp', 'src', 'app.tsx')
CSS = os.path.join(PHONE, 'webapp', 'src', 'styles.css')

s = io.open(APP, encoding='utf-8').read()

# ---------------------------------------------------------------- ICON: bolt
s = s.replace("  dot: (", "  bolt: (\n    <>\n      <path d=\"M13 2 4.5 13.5H11l-1 8.5 8.5-11.5H12l1-8.5Z\" />\n    </>\n  ),\n  dot: (", 1) \
    if "bolt:" not in s else s

# ---------------------------------------------------------------- Composer props + 队列 UI
s = s.replace("""  modelName?: string; effortName?: string; onOpenModel?: () => void;""",
              """  modelName?: string; effortName?: string; onOpenModel?: () => void;
  queue?: { text: string; images: string[]; files: string[] }[];
  onDropQueue?: (i: number) => void;
  onInsert?: (text: string, images: string[], files: string[]) => Promise<void>;""")

# Composer 顶部：排队条 + 第一行按钮结构调整
old_box = s[s.index('      <div class="composer-box">'):s.index('        </div>\n      </div>\n    </div>\n  );\n}')]
new_box = '''      {props.queue && props.queue.length ? (
        <div class="queue-row">
          {props.queue.map((q, i) => (
            <span class="queue-chip" key={i}>
              <b>排队 {i + 1}</b>
              <span class="queue-text">{(q.text || (q.images.length || q.files.length ? '[附件]' : '')).slice(0, 24)}</span>
              <button class="queue-x" onClick={() => props.onDropQueue?.(i)}>✕</button>
            </span>
          ))}
        </div>
      ) : null}
      <div class="composer-box">
        <div class="composer-top">
          <textarea ref={ta} rows={2} value={text} disabled={props.disabled}
            placeholder={props.disabled ? '先选择一个会话…' : uploading ? '附件上传中…'
              : (props.running ? '正在回答…发送会排队，⚡ 立即插入' : '发消息给智能体…（回车换行）')}
            onInput={(e) => setText((e.currentTarget as HTMLTextAreaElement).value)}
            onKeyDown={(e) => {
              if ((e as any).isComposing) return;
              const withMod = e.ctrlKey || e.metaKey;
              if (e.key === 'Enter' && (withMod || (!COARSE_POINTER && !e.shiftKey))) {
                e.preventDefault();
                doSend();
              }
            }} />
          <div class="composer-btns">
            {props.running ? (
              <>
                <button class="composer-send stop" onClick={props.onStop} title="停止"><Icon name="stop" /></button>
                <button class="composer-send insert" title="插入：立刻中止当前回答并发出"
                  disabled={props.disabled || uploading || (!text.trim() && !ready.length)}
                  onClick={() => {
                    const t = text.trim();
                    const images = ready.filter((a) => a.image).map((a) => a.path as string);
                    const files = ready.filter((a) => !a.image).map((a) => a.path as string);
                    if (!t && !images.length && !files.length) return;
                    const placeholder = images.length ? '[图片附件]' : files.length ? '[文件附件]' : '';
                    props.onInsert?.(t || placeholder, images, files);
                    setText(''); setAttach([]);
                  }}>
                  <Icon name="bolt" />
                </button>
              </>
            ) : null}
            <button class={'composer-send' + (props.running ? ' queue' : '')} onClick={doSend}
              disabled={props.disabled || uploading || (!text.trim() && !ready.length)}
              title={props.running ? '排队发送：当前回答结束后自动发出' : '发送'}>
              <Icon name="send" />
            </button>
          </div>
        </div>
        <div class="composer-bar">
          <button class="composer-btn" title="添加图片/文件" disabled={props.disabled}
            onClick={() => fileInput.current?.click()}>
            <Icon name="clip" />
          </button>
          <input ref={fileInput} type="file" hidden multiple
            onChange={(e) => { pick((e.currentTarget as HTMLInputElement).files); (e.currentTarget as HTMLInputElement).value = ''; }} />
          <button class="meta-chip" type="button" onClick={() => props.onOpenModel?.()}>
            {props.modelName || '选择模型'}
          </button>
          <button class="meta-chip" type="button" onClick={() => props.onOpenModel?.()}>
            强度 · {props.effortName || '默认'}
          </button>
        </div>
'''
s = s.replace(old_box, new_box, 1)

# ---------------------------------------------------------------- App：队列状态与发送逻辑
s = s.replace("  const pendingSend = useRef<null | { text: string; images: string[]; files: string[] }>(null);",
              "  const [queue, setQueue] = useState<{ text: string; images: string[]; files: string[] }[]>([]);\n"
              "  const queueRef = useRef<{ text: string; images: string[]; files: string[] }[]>([]);\n"
              "  queueRef.current = queue;")

start = s.index('  const send = useCallback(async (text: string, images: string[], files: string[]) => {')
end = s.index('  /* 打开会话 → 拉模型目录', start)
new_send = '''  /* 真正发出去（不做繁忙判断） */
  const sendNow = useCallback(async (text: string, images: string[], files: string[]) => {
    const st0 = stateRef.current;
    if (!st0.active) return;
    const atts = images.map((p) => ({ name: baseName(p), path: p, image: true }))
      .concat(files.map((p) => ({ name: baseName(p), path: p, image: false })));
    const echo: Item = {
      id: 'local-' + Date.now(), kind: 'user', text, local: true,
      images, files, attachments: atts,
    };
    echoes.current = echoes.current.concat([echo]);
    set({ items: (st0.items || []).concat([echo]), busy: true });
    try {
      await api.send(st0.active.kind, st0.active.id, text, images, files);
      const d = await api.snapshot(st0.active.kind, st0.active.id).catch(() => null);
      if (d) set({ items: withEcho(d.items || []), running: !!d.running });
    } catch (e) {
      echoes.current = echoes.current.filter((x) => x.id !== echo.id);
      set({ items: (stateRef.current.items || []).filter((x) => x.id !== echo.id) });
      if ((e as any)?.status === 409) {
        setQueue((q) => q.concat([{ text, images, files }]));
        toast('当前回答还没结束，已排队', 'ok');
        return;
      }
      throw e;
    } finally { set({ busy: false }); }
  }, []);

  /* 对外 send：空闲直接发，繁忙进队列 */
  const send = useCallback(async (text: string, images: string[], files: string[]) => {
    const st0 = stateRef.current;
    if (!st0.active) return;
    if (st0.running) {
      setQueue((q) => q.concat([{ text, images, files }]));
      toast('已排队（' + (queueRef.current.length + 1) + ' 条），回答结束后自动发送', 'ok');
      return;
    }
    await sendNow(text, images, files);
  }, []);

  /* 插入：先中止当前回答，再立刻发出 */
  const sendInsert = useCallback(async (text: string, images: string[], files: string[]) => {
    const st0 = stateRef.current;
    if (!st0.active) return;
    try { await api.stop(st0.active.kind, st0.active.id); } catch (e) { /* 忽略 */ }
    await new Promise((r) => setTimeout(r, 250));
    await sendNow(text, images, files).catch((e) => toast('发送失败：' + (e as Error).message, 'err'));
  }, []);

  const dropQueue = useCallback((i: number) => {
    setQueue((q) => q.filter((_, idx) => idx !== i));
    toast('已取消排队', 'ok');
  }, []);

'''
s = s[:start] + new_send + s[end:]

# flush 逻辑：running 结束 → 发队首；stop 之后也补发
old_flush = s[s.index('  /* running 由 true → false：把排队中的消息发出去 */'):s.index('  const stop = useCallback(async () => {')]
new_flush = '''  /* running 由 true → false：把队首消息发出去（队列空了就停） */
  useEffect(() => {
    const was = prevRunning.current;
    prevRunning.current = !!s.running;
    if (was && !s.running && queueRef.current.length) {
      const first = queueRef.current[0];
      setQueue((q) => q.slice(1));
      setTimeout(() => {
        sendNow(first.text, first.images, first.files)
          .catch((e) => toast('排队消息发送失败：' + (e as Error).message, 'err'));
      }, 150);
    }
  }, [s.running, s.active?.kind, s.active?.id]);

'''
s = s.replace(old_flush, new_flush, 1)

old_stop = s[s.index('  const stop = useCallback(async () => {'):s.index('  /* 新建')] if '  /* 新建' in s else None
if old_stop:
    new_stop = '''  const stop = useCallback(async () => {
    const st0 = stateRef.current;
    if (!st0.active) return;
    await api.stop(st0.active.kind, st0.active.id).catch(() => null);
    toast('已发送停止', 'ok');
    setTimeout(() => {
      if (queueRef.current.length) {
        const first = queueRef.current[0];
        setQueue((q) => q.slice(1));
        sendNow(first.text, first.images, first.files)
          .catch((e) => toast('排队消息发送失败：' + (e as Error).message, 'err'));
      }
    }, 900);
  }, []);

'''
    s = s.replace(old_stop, new_stop, 1)

# Composer 传参：队列 / 删除 / 插入
s = s.replace("""        onOpenModel={() => setModelOpen(true)} />""",
              """        onOpenModel={() => setModelOpen(true)}
        queue={queue} onDropQueue={dropQueue} onInsert={sendInsert} />""")

io.open(APP, 'w', encoding='utf-8', newline='\n').write(s)
print('app.tsx: 队列可见可删 + 插入按钮 + 第一行发送/停止')

# ---------------------------------------------------------------- CSS
c = io.open(CSS, encoding='utf-8').read()
c += '''

/* ══════════ v3.0.9：第一行 = 文字 + 发送/停止/插入；第二行 = 工具 ══════════ */
.composer-top { display: flex; align-items: flex-end; gap: 8px; }
.composer-top > textarea { flex: 1; min-width: 0; }
.composer-btns { display: flex; align-items: center; gap: 6px; padding-bottom: 2px; }
.composer-send.insert { background: color-mix(in srgb, #4d6bfe 14%, var(--bg-2)); color: #4d6bfe; }

/* 排队条（输入框上方） */
.queue-row {
  max-width: 720px; margin: 0 auto 6px; display: flex; gap: 6px;
  overflow-x: auto; padding: 0 2px;
}
.queue-chip {
  flex: none; display: inline-flex; align-items: center; gap: 6px;
  max-width: 62vw; padding: 5px 8px 5px 10px; border-radius: 99px;
  border: 1px solid var(--line-2); background: var(--surface); font-size: 12px;
}
.queue-chip b { color: #4d6bfe; font-weight: 600; }
.queue-text { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.queue-x { color: var(--faint); padding: 0 2px; }
'''
io.open(CSS, 'w', encoding='utf-8', newline='\n').write(c)
print('styles.css: 第一行布局 + 排队条')

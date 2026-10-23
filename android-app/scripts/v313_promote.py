# -*- coding: utf-8 -*-
"""v3.1.3：排队消息支持「插队」—— 点一下立即中止当前回答并优先发这条"""
import io

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
APP = PHONE + r'\webapp\src\app.tsx'
CSS = PHONE + r'\webapp\src\styles.css'

s = io.open(APP, encoding='utf-8').read()

# 1) Composer props: onPromoteQueue
s = s.replace("  onDropQueue?: (i: number) => void;",
              "  onDropQueue?: (i: number) => void;\n  onPromoteQueue?: (i: number) => void;")

# 2) 队列 chip 上加「插队」按钮
old_chip = """            <span class="queue-chip" key={i}>
              <b>排队 {i + 1}</b>
              <span class="queue-text">{(q.text || (q.images.length || q.files.length ? '[附件]' : '')).slice(0, 24)}</span>
              <button class="queue-x" onClick={() => props.onDropQueue?.(i)}>✕</button>
            </span>"""
new_chip = """            <span class="queue-chip" key={i}>
              <b>排队 {i + 1}</b>
              <span class="queue-text">{(q.text || (q.images.length || q.files.length ? '[附件]' : '')).slice(0, 24)}</span>
              <button class="queue-go" title="插队：立即中止当前回答并发送这条"
                onClick={() => props.onPromoteQueue?.(i)}>
                <Icon name="bolt" size={12} />
              </button>
              <button class="queue-x" title="取消排队" onClick={() => props.onDropQueue?.(i)}>✕</button>
            </span>"""
assert old_chip in s, 'queue chip anchor'
s = s.replace(old_chip, new_chip, 1)

# 3) App: promoteQueue 实现
anchor = "  const dropQueue = useCallback((i: number) => {"
if 'const promoteQueue' not in s:
    imp = """  /* 插队：把队列里这条拎出来，立刻中止当前回答并发送 */
  const promoteQueue = useCallback(async (i: number) => {
    const item = queueRef.current[i];
    if (!item) return;
    setQueue((q) => q.filter((_, idx) => idx !== i));
    toast('插队发送中…', 'ok');
    await sendInsert(item.text, item.images, item.files);
  }, []);

"""
    assert anchor in s
    s = s.replace(anchor, imp + anchor, 1)

# 4) Composer 传参
s = s.replace("queue={queue} onDropQueue={dropQueue} onInsert={sendInsert} />",
              "queue={queue} onDropQueue={dropQueue} onInsert={sendInsert} onPromoteQueue={promoteQueue} />")

io.open(APP, 'w', encoding='utf-8', newline='\n').write(s)
print('app.tsx: 队列 chip 增加插队按钮')

c = io.open(CSS, encoding='utf-8').read()
if '.queue-go' not in c:
    c += '''

/* 队列 chip 的「插队」按钮 */
.queue-go {
  display: inline-grid; place-items: center;
  width: 22px; height: 22px; border-radius: 6px;
  color: #4d6bfe; background: rgba(77, 107, 254, .12);
}
.queue-go:active { background: rgba(77, 107, 254, .24); }
'''
    io.open(CSS, 'w', encoding='utf-8', newline='\n').write(c)
    print('styles.css: queue-go 样式')

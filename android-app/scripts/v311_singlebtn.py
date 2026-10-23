# -*- coding: utf-8 -*-
"""v3.1.1：繁忙时只留一个按钮（对齐 DSH 的观感）
- 空闲： ➤ 发送
- 繁忙且输入为空： ⏹ 停止
- 繁忙且已输入文字： ➤ 排队（长按 ➤ = 立即插入：先中断当前回答再发出）
队列 chip 仍在上方可见、可点 ✕ 取消。
"""
import io

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
APP = PHONE + r'\webapp\src\app.tsx'

s = io.open(APP, encoding='utf-8').read()

start = s.index('          <div class="composer-btns">')
end = s.index('          </div>\n        </div>\n        <div class="composer-bar">', start)
old = s[start:end]

new = '''          <div class="composer-btns">
            {/* 只留一个按钮：DSH 风格 —— 忙时输入为空=停止，有文字=排队，长按=立即插入 */}
            <button
              class={'composer-send' + (props.running && !text.trim() && !ready.length ? ' stop' : (props.running ? ' queue' : ''))}
              disabled={props.disabled || uploading || (!props.running && !text.trim() && !ready.length)}
              title={props.running
                ? (text.trim() || ready.length ? '排队发送（长按 = 立即插入）' : '停止')
                : '发送'}
              onPointerDown={() => {
                if (!props.running) return;
                if (!text.trim() && !ready.length) return;
                (window as any).__holdTimer = setTimeout(() => {
                  (window as any).__holdTimer = 0;
                  const t = text.trim();
                  const images = ready.filter((a) => a.image).map((a) => a.path as string);
                  const files = ready.filter((a) => !a.image).map((a) => a.path as string);
                  const placeholder = images.length ? '[图片附件]' : files.length ? '[文件附件]' : '';
                  props.onInsert?.(t || placeholder, images, files);
                  setText(''); setAttach([]);
                  toast('已插入：中止当前回答并立即发送', 'ok');
                }, 620);
              }}
              onPointerUp={() => {
                const t = (window as any).__holdTimer;
                if (t) { clearTimeout(t); (window as any).__holdTimer = 0; }
              }}
              onPointerLeave={() => {
                const t = (window as any).__holdTimer;
                if (t) { clearTimeout(t); (window as any).__holdTimer = 0; }
              }}
              onClick={() => {
                if (props.running && !text.trim() && !ready.length) { props.onStop(); return; }
                doSend();
              }}>
              {props.running && !text.trim() && !ready.length ? <Icon name="stop" /> : <Icon name="send" />}
            </button>
'''
s = s[:start] + new + s[end:]
io.open(APP, 'w', encoding='utf-8', newline='\n').write(s)
print('app.tsx: 单按钮（停止/排队/长按插入）')

# placeholder 文案同步
s2 = io.open(APP, encoding='utf-8').read()
s2 = s2.replace(": (props.running ? '正在回答…发送会排队，⚡ 立即插入' : '发消息给智能体…（回车换行）')}",
                ": (props.running ? '正在回答…输入后点 ➤ 排队（长按=立即插入）' : '发消息给智能体…（回车换行）')}")
io.open(APP, 'w', encoding='utf-8', newline='\n').write(s2)
print('placeholder 已更新')

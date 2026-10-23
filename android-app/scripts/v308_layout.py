# -*- coding: utf-8 -*-
"""v3.0.8：输入框布局重排
- 文字区在最上面（两行高）
- 一条工具栏：＋(添加文件) · 模型 · 强度 ……… 停止/发送 都在同一行
- 模型/强度 chip 去掉底图（纯文字，无背景无边框）
"""
import io
import os

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
APP = os.path.join(PHONE, 'webapp', 'src', 'app.tsx')
CSS = os.path.join(PHONE, 'webapp', 'src', 'styles.css')

s = io.open(APP, encoding='utf-8').read()

start = s.index('      <div class="composer-box">')
end = s.index('        </div>\n      </div>\n    </div>\n  );\n}', start)
# 定位到 composer-foot 结束（含）
end2 = s.index('        </div>\n      </div>\n    </div>\n  );\n}', start)
old = s[start:end2]

new = '''      <div class="composer-box">
        <textarea ref={ta} rows={2} value={text} disabled={props.disabled}
          placeholder={props.disabled ? '先选择一个会话…' : uploading ? '附件上传中…'
            : (props.running ? '正在回答…可输入，点发送会排队' : '发消息给智能体…（回车换行）')}
          onInput={(e) => setText((e.currentTarget as HTMLTextAreaElement).value)}
          onKeyDown={(e) => {
            if ((e as any).isComposing) return;
            // Ctrl/⌘+Enter 任何设备都发送；桌面端裸 Enter 发送；
            // 手机（粗指针）裸 Enter = 换行，绝不误发。
            const withMod = e.ctrlKey || e.metaKey;
            if (e.key === 'Enter' && (withMod || (!COARSE_POINTER && !e.shiftKey))) {
              e.preventDefault();
              doSend();
            }
          }} />
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
          <span class="composer-spacer" />
          {props.running ? (
            <>
              <button class="composer-send stop" onClick={props.onStop} title="停止"><Icon name="stop" /></button>
              <button class="composer-send queue" onClick={doSend}
                disabled={props.disabled || uploading || (!text.trim() && !ready.length)}
                title="排队发送：当前回答结束后自动发出">
                <Icon name="send" />
              </button>
            </>
          ) : (
            <button class="composer-send" onClick={doSend}
              disabled={props.disabled || uploading || (!text.trim() && !ready.length)} title="发送">
              <Icon name="send" />
            </button>
          )}
'''
s = s[:start] + new + s[end2:]
io.open(APP, 'w', encoding='utf-8', newline='\n').write(s)
print('app.tsx: 工具栏一行（＋ 模型 强度 … 发送）/ 文字区置顶')

# ---------------- CSS
c = io.open(CSS, encoding='utf-8').read()
c += '''

/* ══════════ v3.0.8：输入框布局（文字区在上，工具一条行） ══════════ */
.composer-box {
  display: flex; flex-direction: column; align-items: stretch;
  padding: 9px 9px 7px; gap: 2px;
}
.composer-box > textarea {
  width: 100%; min-height: 62px; max-height: 168px;
  padding: 6px 4px 4px; font-size: 15.5px; line-height: 1.5;
  border: 0; outline: none; background: none; resize: none; color: inherit;
}
.composer-bar {
  display: flex; align-items: center; gap: 4px;
  min-height: 36px;
}
.composer-spacer { flex: 1; }

/* 模型 / 强度：无底图、纯文字按钮 */
.meta-chip {
  height: 30px; padding: 0 8px; border: 0; border-radius: 8px;
  background: transparent; color: var(--muted);
  font-size: 12.5px; display: inline-flex; align-items: center;
  max-width: 42vw; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.meta-chip:active { background: rgba(127, 127, 127, .14); }
.meta-chip::after { content: ""; }

/* 工具行里的按钮间距略收 */
.composer-bar .composer-btn, .composer-bar .composer-send { width: 32px; height: 32px; }
.composer-bar .composer-send.stop { margin-right: 2px; }
'''
io.open(CSS, 'w', encoding='utf-8', newline='\n').write(c)
print('styles.css: 工具行 + 无底图 chip')

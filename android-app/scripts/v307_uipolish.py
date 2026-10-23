# -*- coding: utf-8 -*-
"""v3.0.7
- 输入框加高，模型/强度塞进输入框内部（ChatGPT 式）
- 文件消息显示文件类型徽标（PDF/DOCX/ZIP…），图片仍显示缩略图
- 从其它 App 返回不再白屏（onResume 恢复 WebView + configChanges 防止重建）
- 去掉「底色深浅」滑块
"""
import io
import os

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
APP = os.path.join(PHONE, 'webapp', 'src', 'app.tsx')
CSS = os.path.join(PHONE, 'webapp', 'src', 'styles.css')

s = io.open(APP, encoding='utf-8').read()

# ---------------------------------------------------------------- 1) Composer 结构：把 chips 塞进输入框
old_box_start = """      <div class="composer-box">
        <button class="composer-btn" title="添加图片/文件" disabled={props.disabled}"""
new_box_start = """      <div class="composer-box">
        <div class="composer-row">
        <button class="composer-btn" title="添加图片/文件" disabled={props.disabled}"""
assert old_box_start in s
s = s.replace(old_box_start, new_box_start, 1)

old_box_end = """        )}
      </div>
      <div class="composer-meta">
        <button class="meta-chip" type="button" onClick={() => props.onOpenModel?.()}>
          {props.modelName || '选择模型'}
        </button>
        <button class="meta-chip" type="button" onClick={() => props.onOpenModel?.()}>
          强度 · {props.effortName || '默认'}
        </button>
      </div>
    </div>
  );
}"""
new_box_end = """        )}
        </div>
        <div class="composer-foot">
          <button class="meta-chip" type="button" onClick={() => props.onOpenModel?.()}>
            {props.modelName || '选择模型'}
          </button>
          <button class="meta-chip" type="button" onClick={() => props.onOpenModel?.()}>
            强度 · {props.effortName || '默认'}
          </button>
        </div>
      </div>
    </div>
  );
}"""
assert old_box_end in s, 'composer end anchor'
s = s.replace(old_box_end, new_box_end, 1)

# ---------------------------------------------------------------- 2) 文件消息：类型徽标
old_file_chip = """              <button class="att-chip" key={(a.path || '') + i} title="点击下载"
                onClick={() => { downloadRaw(a.path, a.name).catch(() => toast('下载失败', 'err')); }}>
                <Icon name="clip" size={11} />
                <span class="att-name">{a.name}</span>
              </button>"""
new_file_chip = """              <button class="file-card" key={(a.path || '') + i} title={'下载 ' + a.name}
                onClick={() => { downloadRaw(a.path, a.name).catch(() => toast('下载失败', 'err')); }}>
                <span class="file-badge">{extOf(a.name)}</span>
                <span class="file-meta">
                  <span class="file-name">{a.name}</span>
                  <span class="file-sub">点一下下载</span>
                </span>
              </button>"""
assert old_file_chip in s, 'bubble file chip anchor'
s = s.replace(old_file_chip, new_file_chip, 1)

# extOf 辅助
anchor = "const IMG_EXT = /\\.(png|jpe?g|webp|gif|bmp)$/i;"
helper = anchor + """
const extOf = (name: string): string => {
  const m = String(name || '').match(/\\.([A-Za-z0-9]{1,6})$/);
  return m ? m[1].toUpperCase() : 'FILE';
};
const isDocType = (ext: string) => ['PDF', 'DOC', 'DOCX', 'TXT', 'MD', 'CSV', 'XLS', 'XLSX', 'PPT', 'PPTX'].includes(ext);"""
assert anchor in s
s = s.replace(anchor, helper, 1)

# ---------------------------------------------------------------- 3) 去掉底色深浅
old_shade = """          <label>底色深浅（{bg.shade}%）</label>
          <input class="range" type="range" min={0} max={30} value={bg.shade}
            onInput={(e) => changeBg({ shade: +(e.currentTarget as HTMLInputElement).value })} />
"""
assert old_shade in s, 'shade anchor'
s = s.replace(old_shade, '', 1)

io.open(APP, 'w', encoding='utf-8', newline='\n').write(s)
print('app.tsx: 输入框内嵌 chips / 文件类型徽标 / 去掉底色深浅')

# ---------------------------------------------------------------- 4) CSS
c = io.open(CSS, encoding='utf-8').read()
c += '''

/* ══════════ v3.0.7：输入框加高 + chips 内嵌 + 文件类型卡 ══════════ */
.composer-box {
  flex-direction: column; align-items: stretch; gap: 0;
  padding: 8px 8px 6px;
}
.composer-row { display: flex; align-items: flex-end; gap: 6px; }
.composer-box textarea {
  min-height: 58px;          /* 输入框加高：一行字也有呼吸感 */
  max-height: 168px;
  padding: 10px 2px 6px;
  font-size: 15.5px;
}
.composer-foot {
  display: flex; gap: 8px; align-items: center;
  padding: 4px 2px 0 2px;
}
.meta-chip {
  height: 26px; padding: 0 11px; border-radius: 99px;
  border: 1px solid var(--line-2); background: var(--bg-2);
  color: var(--muted); font-size: 12px; display: inline-flex; align-items: center; gap: 4px;
  max-width: 45vw; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.meta-chip:active { transform: scale(.97); }

/* 文件消息卡片：左边类型徽标，右边文件名 */
.file-card {
  display: flex; align-items: center; gap: 10px; max-width: 100%;
  padding: 8px 12px 8px 8px; border-radius: 12px;
  border: 1px solid var(--line-2); background: var(--surface);
  text-align: left;
}
.file-badge {
  flex: none; width: 40px; height: 40px; border-radius: 9px;
  display: grid; place-items: center; font-size: 10px; font-weight: 700; letter-spacing: .02em;
  background: rgba(77, 107, 254, .12); color: #4d6bfe;
}
.file-meta { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.file-name { font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-sub { font-size: 11px; color: var(--faint); }
'''
io.open(CSS, 'w', encoding='utf-8', newline='\n').write(c)
print('styles.css: 输入框/文件卡样式')

# ---------------------------------------------------------------- 5) MainActivity：返回不白屏
ma = os.path.join(PHONE, 'android-app', 'app', 'src', 'main', 'java', 'com', 'home', 'phoneconsole', 'MainActivity.java')
m = io.open(ma, encoding='utf-8').read()
if 'onResume() {' not in m.split('private void fadeInWeb')[0] or 'web.onResume();' not in m:
    anchor_resume = "    @Override\n    protected void onResume() {\n        super.onResume();"
    new_resume = """    @Override
    protected void onResume() {
        super.onResume();
        // 从别的 App 回来时，部分 ROM 会把 WebView 的渲染层丢掉 → 白屏。
        // 这里主动恢复渲染与计时器，并在页面异常时重新加载一次。
        try {
            if (web != null) {
                web.onResume();
                web.resumeTimers();
                web.invalidate();
                if (web.getUrl() == null) loadConsole();
            }
        } catch (Throwable ignored) {
        }"""
    if anchor_resume in m:
        m = m.replace(anchor_resume, new_resume, 1)

# onPause 对应暂停（省电，也让回来时恢复流程一致）
if 'web.onPause();' not in m:
    m = m.replace("""    @Override
    protected void onResume() {""", """    @Override
    protected void onPause() {
        super.onPause();
        try {
            if (web != null) { web.onPause(); web.pauseTimers(); }
        } catch (Throwable ignored) {
        }
    }

    @Override
    protected void onResume() {""", 1)
io.open(ma, 'w', encoding='utf-8', newline='\n').write(m)
print('MainActivity: onResume/onPause 恢复 WebView')

# manifest：configChanges 防止 Activity 重建
mf = os.path.join(PHONE, 'android-app', 'app', 'src', 'main', 'AndroidManifest.xml')
x = io.open(mf, encoding='utf-8').read()
if 'configChanges' not in x:
    x = x.replace('android:name="com.home.phoneconsole.MainActivity"',
                  'android:name="com.home.phoneconsole.MainActivity"\n            android:configChanges="orientation|screenSize|screenLayout|keyboardHidden|smallestScreenSize|uiMode"')
    io.open(mf, 'w', encoding='utf-8', newline='\n').write(x)
    print('manifest: MainActivity 加 configChanges')

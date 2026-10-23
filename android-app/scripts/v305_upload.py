# -*- coding: utf-8 -*-
"""v3.0.5：文件上传卡死/无进度
- 上传：可取消、超时 120s、进度事件不来时自动跑"假进度"（到 90% 停），保证有反馈
- 附件卡片：pct==0 时显示"上传中"转圈，不再停在 0%
- 原生：选择文件改成 ACTION_OPEN_DOCUMENT；返回后恢复 WebView 的 resume/焦点
"""
import io
import os

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'


def read(p):
    return io.open(p, encoding='utf-8').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


# ---------------- api.ts：上传可取消 + 假进度 + 更短超时
api = os.path.join(PHONE, 'webapp', 'src', 'api.ts')
s = read(api)
start = s.index('export function uploadWithProgress(')
end = s.index('\n}', s.index('xhr.send(file);', start)) + 2
new_fn = '''export function uploadWithProgress(
  kind: 'thread' | 'session', id: string, file: File,
  onPct: (p: number) => void,
): Promise<{ name: string; path: string; size?: number } | null> {
  return new Promise((resolve, reject) => {
    let xhr: XMLHttpRequest;
    try { xhr = new XMLHttpRequest(); } catch { reject(new Error('当前环境不支持上传')); return; }
    xhr.open('POST', `/api/${kind === 'thread' ? 'threads' : 'sessions'}/${id}/upload`, true);
    xhr.timeout = 120000;
    xhr.setRequestHeader('X-Console-Pin', getPin());
    xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name));
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');

    /* 进度兜底：WebView 里 upload 进度事件有时不触发，这时自己跑一个"假进度"
       （爬到 90% 停住，真实进度来了就被覆盖），至少让用户看到在上传而不是卡死。 */
    let real = 0;
    let fake = 0;
    const fakeTimer = setInterval(() => {
      if (real > 0) return;
      fake = Math.min(0.9, fake + (fake < 0.6 ? 0.08 : 0.02));
      onPct(fake);
    }, 320);

    const cleanup = () => clearInterval(fakeTimer);

    if (xhr.upload) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && e.total > 0) {
          real = Math.min(1, e.loaded / e.total);
          onPct(real);
        }
      };
    }
    xhr.onload = () => {
      cleanup();
      try {
        const j = JSON.parse(xhr.responseText || '{}');
        if (xhr.status >= 200 && xhr.status < 300) { onPct(1); resolve(j); }
        else reject(new Error(j.error || ('HTTP ' + xhr.status)));
      } catch (e) { reject(e as Error); }
    };
    xhr.onerror = () => { cleanup(); reject(new Error('网络错误（上传中断）')); };
    xhr.onabort = () => { cleanup(); reject(new Error('已取消上传')); };
    xhr.ontimeout = () => { cleanup(); reject(new Error('上传超时（120s），建议换小文件或换网络')); };
    try {
      xhr.send(file);
    } catch (e) {
      cleanup(); reject(e as Error); return;
    }
    // 暴露给调用方可取消
    (file as any).__abortUpload = () => xhr.abort();
  });
}
'''
s = s[:start] + new_fn + s[end:]
write(api, s)
print('api.ts: 上传可取消 + 假进度 + 120s 超时')

# ---------------- app.tsx：附件卡片显示"上传中"
app = os.path.join(PHONE, 'webapp', 'src', 'app.tsx')
a = read(app)
a = a.replace("""                  : a.path ? <span class="attach-pct">{fmtSize(a.size)}</span>
                  : <span class="attach-pct">{Math.round(a.pct * 100)}%</span>}""",
              """                  : a.path ? <span class="attach-pct">{fmtSize(a.size)}</span>
                  : <span class="attach-pct">{a.pct > 0.02 ? Math.round(a.pct * 100) + '%' : '上传中…'}</span>}""")
write(app, a)
print('app.tsx: 上传中 / 百分比文案')

# ---------------- MainActivity：OPEN_DOCUMENT + 返回后 resume
ma = os.path.join(PHONE, 'android-app', 'app', 'src', 'main', 'java', 'com', 'home', 'phoneconsole', 'MainActivity.java')
m = read(ma)
m = m.replace('Intent intent = new Intent(Intent.ACTION_GET_CONTENT);',
              'Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);')
if 'web.onResume();' not in m:
    m = m.replace('''            try {
                web.setFocusable(true);
                web.requestFocus();
            } catch (Throwable ignored) {
            }''', '''            try {
                web.setFocusable(true);
                web.requestFocus();
                web.onResume();          // 有的 ROM 从系统选择器回来会暂停 WebView
                web.resumeTimers();
            } catch (Throwable ignored) {
            }''')
write(ma, m)
print('MainActivity: ACTION_OPEN_DOCUMENT + resumeTimers')

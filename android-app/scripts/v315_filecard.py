# -*- coding: utf-8 -*-
"""v3.1.5：文件展示更明确
- 气泡里的文件卡：彩色类型徽标（PDF/DOC/XLS/ZIP/代码/其它）+ 文件名 + 类型/大小
- 输入框里的待发送附件：也从"回形针"改成类型徽标（小号）
"""
import io

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
APP = PHONE + r'\webapp\src\app.tsx'
CSS = PHONE + r'\webapp\src\styles.css'

s = io.open(APP, encoding='utf-8').read()

# 1) 类型 → 颜色分类
if 'function badgeKind' not in s:
    anchor = "const isDocType = (ext: string) =>"
    add = """const badgeKind = (ext: string): string => {
  if (ext === 'PDF') return 'pdf';
  if (['DOC', 'DOCX', 'RTF', 'TXT', 'MD'].includes(ext)) return 'doc';
  if (['XLS', 'XLSX', 'CSV'].includes(ext)) return 'sheet';
  if (['PPT', 'PPTX'].includes(ext)) return 'slide';
  if (['ZIP', 'RAR', '7Z', 'GZ', 'TAR'].includes(ext)) return 'zip';
  if (['JS', 'TS', 'TSX', 'JSX', 'PY', 'JAVA', 'KT', 'GO', 'RS', 'C', 'CPP', 'H', 'JSON', 'YAML', 'YML', 'HTML', 'CSS', 'SH', 'XML'].includes(ext)) return 'code';
  if (['PNG', 'JPG', 'JPEG', 'WEBP', 'GIF', 'BMP', 'SVG', 'HEIC'].includes(ext)) return 'img';
  return 'generic';
};
"""
    s = s.replace(anchor, add + anchor, 1)

# 2) 气泡文件卡：彩色徽标 + 类型/大小
old_bubble = """                <span class="file-badge">{extOf(a.name)}</span>
                <span class="file-meta">
                  <span class="file-name">{a.name}</span>
                  <span class="file-sub">点一下下载</span>
                </span>"""
new_bubble = """                <span class={'file-badge ' + badgeKind(extOf(a.name))}>{extOf(a.name)}</span>
                <span class="file-meta">
                  <span class="file-name">{a.name}</span>
                  <span class="file-sub">{badgeKind(extOf(a.name)).toUpperCase()} · 点一下下载</span>
                </span>"""
assert old_bubble in s, 'bubble badge anchor'
s = s.replace(old_bubble, new_bubble, 1)

# 3) 输入框待发送附件：回形针 → 类型小徽标
old_att = """              <Icon name="clip" size={11} />
              <span class="attach-col">"""
new_att = """              <span class={'attach-badge ' + badgeKind(extOf(a.name))}>{extOf(a.name)}</span>
              <span class="attach-col">"""
assert old_att in s, 'attach chip anchor'
s = s.replace(old_att, new_att, 1)

io.open(APP, 'w', encoding='utf-8', newline='\n').write(s)
print('app.tsx: 彩色文件类型徽标（气泡 + 输入框）')

# 4) CSS
c = io.open(CSS, encoding='utf-8').read()
c += '''

/* ══════════ v3.1.5：文件类型彩色徽标 ══════════ */
.file-badge, .attach-badge {
  display: inline-grid; place-items: center; flex: none;
  font-weight: 700; letter-spacing: .02em; text-transform: uppercase;
  background: rgba(120, 130, 145, .16); color: #6b7280;
}
.file-badge { width: 44px; height: 44px; border-radius: 10px; font-size: 10px; }
.attach-badge { width: 26px; height: 26px; border-radius: 7px; font-size: 8.5px; }

.file-badge.pdf, .attach-badge.pdf { background: rgba(226, 74, 74, .14); color: #e24a4a; }
.file-badge.doc, .attach-badge.doc { background: rgba(58, 122, 226, .14); color: #3a7ae2; }
.file-badge.sheet, .attach-badge.sheet { background: rgba(34, 160, 96, .14); color: #22a060; }
.file-badge.slide, .attach-badge.slide { background: rgba(232, 130, 40, .14); color: #e88228; }
.file-badge.zip, .attach-badge.zip { background: rgba(160, 110, 230, .16); color: #a06ee6; }
.file-badge.code, .attach-badge.code { background: rgba(60, 180, 200, .14); color: #2aa6bc; }
.file-badge.img, .attach-badge.img { background: rgba(200, 90, 170, .14); color: #c85aaa; }
.file-badge.generic, .attach-badge.generic { background: rgba(120, 130, 145, .16); color: #6b7280; }

/* 气泡里的文件卡更醒目一点 */
.file-card { padding: 9px 13px 9px 9px; border-radius: 14px; }
.file-name { font-size: 14px; font-weight: 500; }
.file-sub { font-size: 11px; color: var(--faint); letter-spacing: .02em; }
'''
io.open(CSS, 'w', encoding='utf-8', newline='\n').write(c)
print('styles.css: 类型配色')

# -*- coding: utf-8 -*-
"""修复：手机发图片后，服务端回传的 user 消息只有 "[图片] .uploads/xxx.png（可用 READ_IMAGE 查看）" 文本，
没有 attachments → 前端先显示本地缩略图、随后被这条消息替换成一串路径文字。

做法：在返回快照前统一归一化 user 消息：
- 从文本里解析 [图片] / [附带文件] 标记
- 还原成 attachments/images/files（相对路径按会话目录解析）
- displayText 去掉标记，前端显示干净原文
"""
import io
import os
import re

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
SRV = os.path.join(PHONE, 'server.py')


def read(p):
    return io.open(p, encoding='utf-8').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


s = read(SRV)

if 'def normalize_user_items' not in s:
    anchor = '    def create_thread(self, name, workdir, prompt=None):'
    assert anchor in s
    helper = '''    def normalize_user_items(self, items, base_dir=None):
        """把 user 消息里的 [图片]/[附带文件] 标记还原成附件字段。

        DSH 回传的 user 文本是追加过标记的（"\n\n[图片] .uploads/x.png（可用 READ_IMAGE 查看）"），
        手机端如果拿它直接渲染，就会把图片显示成一串路径文字。这里统一清洗：
        - displayText = 去掉标记后的原文（前端优先显示它）
        - attachments/images/files = 还原出的文件（相对路径按 base_dir 解析）
        """
        if not items:
            return items
        base = Path(base_dir) if base_dir else self.workdir_root
        img_re = re.compile(r"\\n\\n\\[图片\\]\\s*(.+?)(?:（可用 READ_IMAGE 查看）|$)", re.S)
        file_re = re.compile(r"\\n\\n\\[附带文件\\]\\s*(.+?)(?:（请按需读取这些文件）|$)", re.S)

        def resolve(p):
            p = p.strip().strip(",")
            if not p:
                return None
            path = Path(p)
            if not path.is_absolute():
                path = base / path
            try:
                return path.resolve()
            except OSError:
                return path

        for it in items:
            if (it.get("kind") or "").lower() != "user":
                continue
            text = it.get("text") or ""
            imgs, files = [], []
            m = img_re.search(text)
            if m:
                for piece in re.split(r"[,，]", m.group(1)):
                    rp = resolve(piece)
                    if rp:
                        imgs.append(rp)
            m2 = file_re.search(text)
            if m2:
                for piece in re.split(r"[,，]", m2.group(1)):
                    rp = resolve(piece)
                    if rp:
                        files.append(rp)
            if not imgs and not files:
                continue
            clean = img_re.sub("", text)
            clean = file_re.sub("", clean).strip()
            atts = [{"name": p.name, "path": str(p), "image": True} for p in imgs]
            atts += [{"name": p.name, "path": str(p), "image": False} for p in files]
            it["displayText"] = clean
            it["attachments"] = atts
            it["images"] = [str(p) for p in imgs]
            it["files"] = [str(p) for p in files]
        return items

''' + anchor
    s = s.replace(anchor, helper, 1)

# GET 会话详情：归一化 items
old_detail = '''            if len(parts) == 4:
                detail = self.app.session_detail(sid)
                if detail is None:
                    self._json({"error": "session not found"}, 404)
                    return
                self._json(detail)
                return'''
new_detail = '''            if len(parts) == 4:
                detail = self.app.session_detail(sid)
                if detail is None:
                    self._json({"error": "session not found"}, 404)
                    return
                try:
                    detail["items"] = self.app.normalize_user_items(
                        detail.get("items") or [], detail.get("cwd") or self.app.session_workdir(sid))
                except Exception:
                    pass
                self._json(detail)
                return'''
assert old_detail in s, 'detail anchor'
s = s.replace(old_detail, new_detail, 1)

# GET 线程详情：归一化 items
old_thread = '''            if len(parts) == 4:
                self._json(state.to_public())
                return'''
new_thread = '''            if len(parts) == 4:
                pub = state.to_public()
                try:
                    pub["items"] = self.app.normalize_user_items(pub.get("items") or [], state.workdir)
                except Exception:
                    pass
                self._json(pub)
                return'''
if old_thread in s:
    s = s.replace(old_thread, new_thread, 1)
    print('  线程详情已归一化')

write(SRV, s)
print('server.py: normalize_user_items 已加')

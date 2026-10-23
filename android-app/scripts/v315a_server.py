# -*- coding: utf-8 -*-
"""v3.1.5（重写版，锚点已按实际文件核对）"""
import io
import os

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
SRV = os.path.join(PHONE, 'server.py')
APP = os.path.join(PHONE, 'webapp', 'src', 'app.tsx')
API = os.path.join(PHONE, 'webapp', 'src', 'api.ts')
CSS = os.path.join(PHONE, 'webapp', 'src', 'styles.css')


def read(p):
    return io.open(p, encoding='utf-8').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


s = read(SRV)

# 1) session_workdir 方法
if 'def session_workdir' not in s:
    anchor = '    def save_upload(state, filename, data):'
    assert anchor in s
    s = s.replace(anchor, '''    def session_workdir(self, sid):
        """电脑端会话的工作目录（DSH cwd）；取不到就回退根目录。"""
        try:
            for item in self.dsh.list_sessions():
                if item.get("sessionId") == sid and item.get("cwd"):
                    return str(item["cwd"])
        except Exception:
            pass
        return str(self.workdir_root)

''' + anchor, 1)

# 2) sessions 上传落到会话目录
old_up = "                result = self.app.save_upload_to(str(self.app.workdir_root), filename, data)"
if old_up in s:
    s = s.replace(old_up,
                  "                result = self.app.save_upload_to(self.app.session_workdir(sid), filename, data)", 1)

# 3) 归档存储方法
if 'def local_archived' not in s:
    anchor2 = '    # -- sessions -----------------------------------------------------------'
    assert anchor2 in s
    s = s.replace(anchor2, '''    # -- 手机端归档（本地文件 archived.json） --------------------------------
    def _archive_file(self):
        return self.data_dir / "archived.json"

    def local_archived(self):
        try:
            data = json.loads(self._archive_file().read_text(encoding="utf-8") or "{}")
        except Exception:
            data = {}
        return {k: [str(x) for x in (data.get(k) or [])] for k in ("thread", "session")}

    def set_archived(self, kind, ident, archived):
        data = self.local_archived()
        cur = set(data.get(kind) or [])
        if archived:
            cur.add(str(ident))
        else:
            cur.discard(str(ident))
        data[kind] = sorted(cur)
        try:
            self._archive_file().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        self.sessions_cache = None
        return data

''' + anchor2, 1)

# 4) GET /api/archived
if '"/api/archived"' not in s:
    anchor3 = '        if path == "/api/sessions":\n            self._json({"sessions": self.app.list_sessions()})'
    assert anchor3 in s, 'GET sessions anchor'
    s = s.replace(anchor3, '''        if path == "/api/archived":
            self._json(self.app.local_archived())
            return

''' + anchor3, 1)

# 5) POST /api/archive
if '"/api/archive"' not in s:
    anchor4 = '        if path == "/api/bg":\n            data = self._read_json()'
    assert anchor4 in s, 'POST bg anchor'
    s = s.replace(anchor4, '''        if path == "/api/archive":
            data = self._read_json()
            kind = "session" if str(data.get("kind")) == "session" else "thread"
            ident = str(data.get("id") or "").strip()
            if not ident:
                self._json({"error": "empty id"}, 400)
                return
            out = self.app.set_archived(kind, ident, bool(data.get("archived")))
            self._json({"ok": True, "archived": out.get(kind, [])})
            return

''' + anchor4, 1)

write(SRV, s)
print('server.py OK（会话目录上传 + 归档 API）')

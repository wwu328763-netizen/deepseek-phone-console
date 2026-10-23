# -*- coding: utf-8 -*-
"""v3.1.6：手机任务目录对齐 DSH 会话工作区
规则：
- 新建任务指定了工作目录 → DSH 会话直接 cwd=该目录（三方一致：手机任务目录 / DSH 会话 cwd / 上传落盘）
- 没指定 → 用「手机任务」工作区目录并以 workspaceId 建会话（电脑端仍归组在“手机任务”工作区）
"""
import io
import os

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
SRV = os.path.join(PHONE, 'server.py')


def read(p):
    return io.open(p, encoding='utf-8').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


s = read(SRV)

old = '''        # 每个手机任务一个独立会话。为了让 harness 把它归到「手机任务」工作区，
        # 必须用 workspaceId 建会话（workspaceId 与 cwd 只能二选一），
        # 会话 cwd 因此是该工作区目录；用户另选的工作目录会写进首条指令里。
        wid = self.phone_workspace_id()
        session_cwd = None
        if wid:
            sid = self.dsh.create_session(workspace_id=wid, agent_preset=self.agent_preset)
            session_cwd = self.phone_workspace_path()
        else:
            sid = self.dsh.create_session(cwd=workdir, agent_preset=self.agent_preset)
            session_cwd = str(Path(workdir).resolve())'''

new = '''        # 每个手机任务一个独立会话。关键：会话 cwd 必须等于手机任务目录，
        # 否则「手机任务目录 / DSH 会话工作区 / 上传落盘」三处对不上（真机反馈）。
        # - 指定了工作目录：直接 cwd=该目录（三方一致；电脑端按该路径归组）
        # - 没指定：用「手机任务」工作区目录 + workspaceId（电脑端仍归在“手机任务”）
        chosen = str(Path(workdir).resolve())
        ws_path = self.phone_workspace_path()
        ws_path = str(Path(ws_path).resolve()) if ws_path else None
        wid = self.phone_workspace_id()
        session_cwd = None
        if wid and ws_path and chosen == ws_path:
            sid = self.dsh.create_session(workspace_id=wid, agent_preset=self.agent_preset)
            session_cwd = ws_path
        else:
            sid = self.dsh.create_session(cwd=chosen, agent_preset=self.agent_preset)
            session_cwd = chosen'''

assert old in s, 'create_thread anchor'
s = s.replace(old, new, 1)

# 首条指令里的目录提示：现在 cwd 已经等于 chosen，不需要再追加；保留兜底（万一 cwd 被降级）
old2 = '''        if prompt:
            # 会话 cwd 是「手机任务」工作区目录：把用户另选的工作目录附在首条指令里
            chosen = str(Path(workdir).resolve())
            if session_cwd and chosen != str(Path(session_cwd).resolve()):
                prompt = prompt + "\\n\\n（本任务的工作目录是：%s，请在其中工作）" % workdir
            self.start_turn(tid, prompt)'''
new2 = '''        if prompt:
            # 正常情况下 session_cwd == chosen；只有 harness 降级时才把目录写进指令兜底
            if session_cwd and str(Path(session_cwd).resolve()) != chosen:
                prompt = prompt + "\\n\\n（本任务的工作目录是：%s，请在其中工作）" % chosen
            self.start_turn(tid, prompt)'''
if old2 in s:
    s = s.replace(old2, new2, 1)
    print('  首条指令兜底逻辑已更新')

# 让 _dsh_prompt 里的相对路径以“会话自己的目录”为基准
old3 = '        text, image_parts = self._split_content(prompt, images, files)'
new3 = '        text, image_parts = self._split_content(prompt, images, files, base_dir=getattr(state, "workdir", None))'
if old3 in s:
    s = s.replace(old3, new3, 1)
    print('  相对路径基准改为会话目录')

# 未指定目录时默认用「手机任务」工作区目录（让电脑端能归组）
old4 = '''            workdir = self._resolve_workdir(data.get("workdir"))
            if workdir is None:
                workdir = str(self.app.workdir_root)'''
new4 = '''            workdir = self._resolve_workdir(data.get("workdir"))
            if workdir is None:
                # 手机端没选目录：默认落到「手机任务」工作区，电脑端能看到同一目录
                workdir = self.app.phone_workspace_path() or str(self.app.workdir_root)'''
if old4 in s:
    s = s.replace(old4, new4, 1)
    print('  默认工作目录改为「手机任务」工作区')

write(SRV, s)
print('server.py: create_thread 目录对齐完成')

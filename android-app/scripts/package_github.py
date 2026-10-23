# -*- coding: utf-8 -*-
"""把 phone-console 打包成一个干净的、可直接推送 GitHub 的仓库目录。"""
import io
import os
import re
import shutil
from pathlib import Path

SRC = Path(r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console')
OUT = Path(r'C:\Agent\https-www-npmjs-com-package-deep\work\phone-console-release')

SKIP_DIRS = {
    '__pycache__', 'node_modules', '.git', '.gradle', 'build', '.uploads', 'console_data',
    '.jdk17', '.android-sdk', '_tools', '_verify', 'sessions', 'usage-backup', 'vendor',
}
SKIP_FILES = {
    'gui.pyw.bak-tk', 'console.keystore', 'local.properties',
    'cloudflared.exe', 'natapp.exe', 'ConsolePanel.exe',
    'build-log-assembleRelease.txt', 'build-log-clean-build.txt',
    '手机远程控制台-v3.1.9.apk', 'phone-console-v3.1.9.apk',  # dist 里单独放
}

# 需要打包的顶层条目（白名单，避免把运行数据/密钥/大二进制带进去）
TOP = [
    'server.py', 'console_core.py', 'dsh_client.py', 'sessions.py',
    'run.ps1', 'start-all.ps1', 'start-console.bat', 'start-tunnel.ps1',
    'stop-all.bat', 'stop-server.ps1', 'manager.bat', 'manager.vbs',
    'console.ico', '.gitignore',
    'panel', 'webapp', 'web', 'android-app', 'tests',
]

# 截图精选
SHOTS = {
    '手机端-登录页.png': 'screenshots/01-登录.png',
    '手机端-聊天浅色.png': 'screenshots/02-聊天-浅色.png',
    '手机端-聊天深色.png': 'screenshots/03-聊天-深色.png',
    '手机端-侧栏.png': 'screenshots/04-会话侧栏.png',
    '手机端-设置.png': 'screenshots/05-设置.png',
    '新版-聊天.png': 'screenshots/06-聊天-新界面.png',
    '新版-设置.png': 'screenshots/07-设置-新界面.png',
    '图标-电脑与手机一致.png': 'screenshots/08-图标.png',
}


def copy_tree(src: Path, dst: Path):
    if not src.exists():
        return
    for root, dirs, files in os.walk(src):
        rp = Path(root)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = rp.relative_to(src)
        target = dst / rel
        target.mkdir(parents=True, exist_ok=True)
        for f in files:
            if f in SKIP_FILES or f.endswith(('.pyc', '.keystore', '.jks', '.exe')):
                continue
            if f.startswith('.upgrade-backup'):
                continue
            shutil.copy2(rp / f, target / f)


def redact(paths):
    """去掉硬编码的第三方 token / 本机 PIN。"""
    pat = [
        (r'NATAUTHToken\s*=\s*"[0-9a-f]{16}"', 'NATAUTHToken = os.environ.get("NATAPP_TOKEN", "")'),
        (r'\b14850517\b', '00000000'),
    ]
    hits = []
    for p in paths:
        try:
            s = p.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        old = s
        for a, b in pat:
            s = re.sub(a, b, s)
        if s != old:
            p.write_text(s, encoding='utf-8', newline='\n')
            hits.append(p.relative_to(OUT))
    return hits


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    for item in TOP:
        src = SRC / item
        if src.is_dir():
            copy_tree(src, OUT / item)
        elif src.is_file():
            shutil.copy2(src, OUT / item)
    print('copied top-level')

    # 截图
    (OUT / 'screenshots').mkdir(exist_ok=True)
    for src_name, dst in SHOTS.items():
        s = SRC / 'screenshots' / src_name
        if s.exists():
            shutil.copy2(s, OUT / dst)
    print('copied screenshots:', len(list((OUT / 'screenshots').glob('*.png'))))

    # APK + 扫码图
    dist = OUT / 'dist'
    dist.mkdir(exist_ok=True)
    apk = SRC / 'web' / 'phone-console.apk'
    if apk.exists():
        shutil.copy2(apk, dist / '手机远程控制台-v3.1.9.apk')
        shutil.copy2(apk, dist / 'phone-console-v3.1.9.apk')
    qr = SRC / 'dist' / '扫码-新隧道地址.png'
    if qr.exists():
        shutil.copy2(qr, dist / '二维码示例.png')
    print('copied dist')

    # 清理/补全
    for junk in ('android-app/README-构建.md', 'panel/README.md', 'webapp/README.md', 'docs'):
        p = OUT / junk
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()

    files = [p for p in OUT.rglob('*') if p.is_file()]
    hits = redact(files)
    print('redacted:', hits)
    return len(files)


if __name__ == '__main__':
    n = main()
    print('files:', n)
    total = sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file())
    print('size MB:', round(total / 1024 / 1024, 2))

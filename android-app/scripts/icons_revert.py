# -*- coding: utf-8 -*-
"""v3.0.0 图标回退：用电脑端旧界面那枚图标做全套（APK / PWA / 面板 / exe）"""
import io
import os
from PIL import Image

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
OLD = os.path.join(PHONE, 'android', 'res', 'mipmap-xxxhdpi', 'ic_launcher.png')
RES = os.path.join(PHONE, 'android-app', 'app', 'src', 'main', 'res')
WEB = os.path.join(PHONE, 'web', 'icons')

old = Image.open(OLD).convert('RGBA')
W, H = old.size
# 取一个不透明像素做底色（旧图标是深青底）
bg = None
for y in range(H):
    for x in range(W):
        r, g, b, a = old.getpixel((x, y))
        if a > 250:
            bg = (r, g, b, 255)
            break
    if bg:
        break

def on_solid(img):
    base = Image.new('RGBA', img.size, bg)
    return Image.alpha_composite(base, img)

solid = on_solid(old)

def save(img, path, size=None):
    if size and img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, 'PNG', optimize=True)
    print('  %-62s %4dx%-4d %6d B' % (os.path.relpath(path, PHONE), img.size[0], img.size[1],
                                      os.path.getsize(path)))


# legacy mipmaps：原图直接缩（保留圆角透明）
for name, px in {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}.items():
    save(old, os.path.join(RES, 'mipmap-' + name, 'ic_launcher.png'), px)
    save(old, os.path.join(RES, 'mipmap-' + name, 'ic_launcher_round.png'), px)

# adaptive：背景用"实心旧图"，前景透明（形状交给启动器裁切）
transparent = Image.new('RGBA', (108, 108), (0, 0, 0, 0))
for name, px in {'mdpi': 108, 'hdpi': 162, 'xhdpi': 216, 'xxhdpi': 324, 'xxxhdpi': 432}.items():
    save(solid, os.path.join(RES, 'mipmap-' + name, 'ic_launcher_background.png'), px)
    save(transparent, os.path.join(RES, 'mipmap-' + name, 'ic_launcher_foreground.png'), px)

xml = ('<?xml version="1.0" encoding="utf-8"?>\n'
       '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
       '    <background android:drawable="@mipmap/ic_launcher_background" />\n'
       '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />\n'
       '</adaptive-icon>\n')
for fn in ('ic_launcher.xml', 'ic_launcher_round.xml'):
    p = os.path.join(RES, 'mipmap-anydpi-v26', fn)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(xml)
    print('  %-62s adaptive-icon' % os.path.relpath(p, PHONE))

# 手机网页 PWA 图标
save(old, os.path.join(WEB, 'icon-192.png'), 192)
save(solid, os.path.join(WEB, 'icon-512.png'), 512)
save(solid, os.path.join(WEB, 'icon-maskable-512.png'), 512)
save(old, os.path.join(WEB, 'apple-touch-icon.png'), 180)
save(old, os.path.join(WEB, 'favicon.png'), 32)

# 电脑端面板 + exe 图标
save(old, os.path.join(PHONE, 'panel', 'webui', 'icon.png'), 192)
save(old, os.path.join(PHONE, 'console.ico'), 256)
print('DONE: 图标已回到旧版')

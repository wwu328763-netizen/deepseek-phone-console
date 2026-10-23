# -*- coding: utf-8 -*-
"""图标回到"电脑端旧界面"那一版：深色圆角砖 + 白色手机机身 + 薄荷绿 >_
（之前误把新版薄荷 >_ 当成旧版，这次按原始设计重画）
生成：APK mipmap、PWA、面板 icon.png、console.ico
"""
import io
import os
from PIL import Image, ImageDraw, ImageFilter

PHONE = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
RES = os.path.join(PHONE, 'android-app', 'app', 'src', 'main', 'res')
WEB = os.path.join(PHONE, 'web', 'icons')
S = 1024

GRAD_TOP = (24, 38, 40)
GRAD_BOT = (8, 13, 14)
MINT = (63, 220, 149)
MINT_DARK = (34, 184, 119)
WHITE = (238, 241, 242)
SCREEN = (10, 15, 16)


def lerp(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def rounded_mask(size, ratio):
    m = Image.new('L', (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * ratio), fill=255)
    return m


def gradient(size):
    img = Image.new('RGB', (1, size))
    for y in range(size):
        img.putpixel((0, y), lerp(GRAD_TOP, GRAD_BOT, y / max(1, size - 1)))
    return img.resize((size, size), Image.NEAREST)


def glow(size, center, radius, color, alpha):
    layer = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    cx, cy = center
    ImageDraw.Draw(layer).ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color + (alpha,))
    return layer.filter(ImageFilter.GaussianBlur(radius * 0.6))


def master(size=S, rounded=True):
    img = gradient(size).convert('RGBA')
    img = Image.alpha_composite(img, glow(size, (size * 0.66, size * 0.74), size * 0.30, MINT, 70))

    d = ImageDraw.Draw(img)
    # 手机机身（白色描边圆角矩形）
    pw = size * 0.44          # 机身宽
    ph = size * 0.70          # 机身高
    px = (size - pw) / 2
    py = (size - ph) / 2
    pr = size * 0.085         # 机身圆角
    stroke = max(2, int(size * 0.030))
    d.rounded_rectangle((px, py, px + pw, py + ph), radius=pr, outline=WHITE, width=stroke)
    # 屏幕（内部深色，留出边框）
    inset = stroke * 2.1
    d.rounded_rectangle((px + inset, py + inset, px + pw - inset, py + ph - inset),
                        radius=pr * 0.72, fill=SCREEN)
    # 顶部听筒小横条
    slot_w, slot_h = size * 0.075, size * 0.014
    sx = (size - slot_w) / 2
    sy = py + inset * 0.55
    d.rounded_rectangle((sx, sy, sx + slot_w, sy + slot_h), radius=slot_h / 2,
                        fill=(120, 132, 134))
    # 屏内薄荷绿 >_ （居中偏下一点）
    cx, cy = size / 2, size * 0.545
    sw = max(2, int(size * 0.052))          # 笔画
    cw, ch = size * 0.115, size * 0.105     # 尖角半宽/半高
    x0 = cx - size * 0.075
    pts = [(x0, cy - ch), (x0 + cw * 1.5, cy), (x0, cy + ch)]
    d.line(pts, fill=MINT + (255,), width=sw, joint='curve')
    r = sw / 2
    for x, y in pts:
        d.ellipse((x - r, y - r, x + r, y + r), fill=MINT + (255,))
    ux0, ux1 = cx + size * 0.012, cx + size * 0.105
    uy = cy + ch
    d.line([(ux0, uy), (ux1, uy)], fill=MINT_DARK + (255,), width=sw)
    for x in (ux0, ux1):
        d.ellipse((x - r, uy - r, x + r, uy + r), fill=MINT_DARK + (255,))

    if not rounded:
        return img
    out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), rounded_mask(size, 0.226))
    ring = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(ring).rounded_rectangle((1, 1, size - 2, size - 2), radius=int(size * 0.226),
                                           outline=(255, 255, 255, 28), width=max(2, size // 340))
    return Image.alpha_composite(out, ring)


def save(img, path, size=None):
    if size and img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, 'PNG', optimize=True)
    print('  %-64s %4dx%-4d %6d B' % (os.path.relpath(path, PHONE), img.size[0], img.size[1],
                                      os.path.getsize(path)))


def main():
    m = master()
    for name, px in {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}.items():
        save(m, os.path.join(RES, 'mipmap-' + name, 'ic_launcher.png'), px)
        save(m, os.path.join(RES, 'mipmap-' + name, 'ic_launcher_round.png'), px)
    save(m, os.path.join(WEB, 'icon-192.png'), 192)
    save(m, os.path.join(WEB, 'icon-512.png'), 512)
    save(master(rounded=True), os.path.join(WEB, 'icon-maskable-512.png'), 512)
    save(m, os.path.join(WEB, 'apple-touch-icon.png'), 180)
    save(m, os.path.join(WEB, 'favicon.png'), 32)
    save(m, os.path.join(PHONE, 'panel', 'webui', 'icon.png'), 192)
    save(m, os.path.join(PHONE, 'console.ico'))
    print('DONE')


if __name__ == '__main__':
    main()

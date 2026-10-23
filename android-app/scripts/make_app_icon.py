# -*- coding: utf-8 -*-
"""生成手机端全套图标：APK launcher（legacy + adaptive）与手机网页 PWA 图标。

设计：深色圆角砖 + 薄荷绿 `>_` 终端提示符（与电脑端面板同色系；去掉旧版机身描边，
      让 48px 下也能一眼认出）。渲染 1024px 再 LANCZOS 缩小，保证小尺寸锐利。
"""
import io
import os
from PIL import Image, ImageDraw, ImageFilter

ROOT = r'C:\Agent\https-www-npmjs-com-package-deep\work\dsh-project\phone-console'
RES = os.path.join(ROOT, 'android-app', 'app', 'src', 'main', 'res')
WEB_ICONS = os.path.join(ROOT, 'web', 'icons')

BG_TOP = (24, 35, 48)
BG_BOT = (8, 12, 18)
ACCENT = (63, 220, 149)
ACCENT_2 = (34, 184, 119)
S = 1024


def vertical_gradient(size, top, bot):
    img = Image.new('RGB', (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        img.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bot)))
    return img.resize((size, size), Image.NEAREST)


def rounded_mask(size, radius_ratio=0.226):
    m = Image.new('L', (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1),
                                        radius=int(size * radius_ratio), fill=255)
    return m


def radial_glow(size, center, radius, color, alpha):
    layer = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    cx, cy = center
    ImageDraw.Draw(layer).ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                                  fill=color + (alpha,))
    return layer.filter(ImageFilter.GaussianBlur(radius * 0.6))


def glyph_layer(size, scale=1.0):
    """画 >_ 到透明层，再按 bbox 居中。scale 相对 1024 基准。"""
    layer = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    u = size / 1024.0 * scale
    cx, cy = size / 2.0, size / 2.0
    sw = max(2, int(92 * u))
    chev_x = cx - 240 * u
    chev_top = cy - 172 * u
    chev_mid = cx - 60 * u
    chev_bot = cy + 172 * u
    pts = [(chev_x, chev_top), (chev_mid, cy), (chev_x, chev_bot)]
    d.line(pts, fill=ACCENT + (255,), width=sw, joint='curve')
    for x, y in pts:
        d.ellipse((x - sw / 2, y - sw / 2, x + sw / 2, y + sw / 2), fill=ACCENT + (255,))
    ux0, ux1 = cx + 10 * u, cx + 190 * u
    uy = chev_bot
    d.line([(ux0, uy), (ux1, uy)], fill=ACCENT_2 + (255,), width=sw)
    for x in (ux0, ux1):
        d.ellipse((x - sw / 2, uy - sw / 2, x + sw / 2, uy + sw / 2), fill=ACCENT_2 + (255,))
    box = layer.getbbox()
    if not box:
        return layer
    crop = layer.crop(box)
    out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    out.alpha_composite(crop, ((size - crop.width) // 2, (size - crop.height) // 2))
    return out


def background(size, radius_ratio=None):
    img = vertical_gradient(size, BG_TOP, BG_BOT).convert('RGBA')
    img = Image.alpha_composite(img, radial_glow(size, (size * 0.62, size * 0.68),
                                                size * 0.30, ACCENT, 85))
    img = Image.alpha_composite(img, radial_glow(size, (size * 0.30, size * 0.16),
                                                size * 0.42, (90, 160, 220), 40))
    if radius_ratio is not None:
        out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        out.paste(img, (0, 0), rounded_mask(size, radius_ratio))
        ring = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(ring).rounded_rectangle(
            (1, 1, size - 2, size - 2), radius=int(size * radius_ratio),
            outline=(255, 255, 255, 30), width=max(2, size // 320))
        return Image.alpha_composite(out, ring)
    return img


def make_icon(size, radius_ratio=0.226, glyph_scale=1.0):
    base = background(size, radius_ratio)
    return Image.alpha_composite(base, glyph_layer(size, glyph_scale))


def make_round(size):
    base = background(size, 0.5)
    return Image.alpha_composite(base, glyph_layer(size, 0.92))


def make_foreground(size):
    return glyph_layer(size, 0.62)


def save(img, path, size=None):
    if size and img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, 'PNG', optimize=True)
    print('  %-64s %4dx%-4d %6d B' % (os.path.relpath(path, ROOT), img.size[0], img.size[1],
                                      os.path.getsize(path)))


def main():
    master = make_icon(S)
    for name, px in {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}.items():
        save(master, os.path.join(RES, 'mipmap-' + name, 'ic_launcher.png'), px)
        save(make_round(S), os.path.join(RES, 'mipmap-' + name, 'ic_launcher_round.png'), px)

    for name, px in {'mdpi': 108, 'hdpi': 162, 'xhdpi': 216, 'xxhdpi': 324, 'xxxhdpi': 432}.items():
        save(background(S), os.path.join(RES, 'mipmap-' + name, 'ic_launcher_background.png'), px)
        save(make_foreground(S), os.path.join(RES, 'mipmap-' + name, 'ic_launcher_foreground.png'), px)

    xml = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
           '    <background android:drawable="@mipmap/ic_launcher_background" />\n'
           '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />\n'
           '</adaptive-icon>\n')
    for fn in ('ic_launcher.xml', 'ic_launcher_round.xml'):
        p = os.path.join(RES, 'mipmap-anydpi-v26', fn)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        io.open(p, 'w', encoding='utf-8', newline='\n').write(xml)
        print('  %-64s adaptive-icon xml' % os.path.relpath(p, ROOT))

    save(master, os.path.join(WEB_ICONS, 'icon-192.png'), 192)
    save(master, os.path.join(WEB_ICONS, 'icon-512.png'), 512)
    save(make_icon(S, radius_ratio=0.5, glyph_scale=0.72),
         os.path.join(WEB_ICONS, 'icon-maskable-512.png'), 512)
    save(master, os.path.join(WEB_ICONS, 'apple-touch-icon.png'), 180)
    save(master, os.path.join(WEB_ICONS, 'favicon.png'), 32)

    # 电脑端面板 / 快捷方式沿用同一枚图标（品牌一致）
    save(master, os.path.join(ROOT, 'panel', 'webui', 'icon.png'), 192)
    save(master, os.path.join(ROOT, 'console.ico'), 256)
    print('DONE')


if __name__ == '__main__':
    main()

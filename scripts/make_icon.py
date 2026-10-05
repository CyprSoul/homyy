"""Малює іконку Хомі (agent/assets/homyy.ico і .png). Запуск: python scripts/make_icon.py"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

S = 2048                                     # малюємо великим, потім зменшуємо — гладкі краї
OUT = Path(__file__).resolve().parent.parent / "agent" / "assets"


def lerp(a, b, t):
    return a + (b - a) * t


def squircle_mask(size, n=5.0, pad=0.04):
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    u = (x - size / 2) / (size / 2 * (1 - pad))
    v = (y - size / 2) / (size / 2 * (1 - pad))
    return (np.abs(u) ** n + np.abs(v) ** n) <= 1


def background():
    y, x = np.mgrid[0:S, 0:S].astype(np.float32) / S
    t = np.clip((x * 0.45 + y * 0.55), 0, 1)[..., None]
    top, bottom = np.array([24, 22, 64]), np.array([76, 22, 120])
    col = lerp(top, bottom, t)
    hl = np.exp(-(((x - 0.3) ** 2 + (y - 0.15) ** 2) / 0.08))[..., None]   # м'яке світло зверху
    col = col + np.array([90, 80, 200]) * hl * 0.35
    vign = np.clip(np.hypot(x - 0.5, y - 0.5) * 1.4, 0, 1)[..., None]
    col = col * (1 - 0.35 * vign ** 2)
    img = np.dstack([np.clip(col, 0, 255), squircle_mask(S) * 255]).astype(np.uint8)
    return Image.fromarray(img, "RGBA")


def orb(radius):
    size = int(radius * 2)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    nx, ny = (x - radius) / radius, (y - radius) / radius
    r = np.hypot(nx, ny)
    nz = np.sqrt(np.clip(1 - nx ** 2 - ny ** 2, 0, 1))
    L = np.array([-0.5, -0.6, 0.62]); L /= np.linalg.norm(L)
    d = np.clip(nx * L[0] + ny * L[1] + nz * L[2], 0, 1)
    dark, base, light = np.array([60, 20, 140]), np.array([150, 100, 250]), np.array([235, 225, 255])
    col = lerp(dark, base, d[..., None] ** 0.8)
    col = lerp(col, light, np.clip(d - 0.7, 0, 1)[..., None] * 2.2)
    cyan = np.exp(-(((nx - 0.35) ** 2 + (ny - 0.45) ** 2) / 0.18))[..., None]
    col = col + np.array([30, 180, 220]) * cyan * 0.55
    col = col + 255 * (d ** 60)[..., None] * 0.9
    alpha = np.clip((1 - r) * radius, 0, 1) * 255
    return Image.fromarray(np.dstack([np.clip(col, 0, 255), alpha]).astype(np.uint8), "RGBA")


def glow(radius, color, strength=1.0):
    size = int(radius * 2)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    r = np.hypot(x - radius, y - radius) / radius
    a = np.clip(1 - r, 0, 1) ** 2.4 * 255 * strength
    rgb = np.ones((size, size, 3)) * np.array(color)
    return Image.fromarray(np.dstack([rgb, a]).astype(np.uint8), "RGBA")


def ring(width_r, height_r, thickness, angle, part):
    """Орбіта навколо сфери. part='back' — верхня половина (за сферою), 'front' — нижня."""
    layer = Image.new("RGBA", (S, S))
    d = ImageDraw.Draw(layer)
    box = [S / 2 - width_r, S / 2 - height_r, S / 2 + width_r, S / 2 + height_r]
    start, end = (180, 360) if part == "back" else (0, 180)
    for i, (w, a) in enumerate(((thickness * 5, 40), (thickness * 2.4, 110), (thickness, 255))):
        d.arc(box, start, end, fill=(120, 230, 255, a) if part == "front" else (190, 160, 255, a), width=int(w))
    layer = layer.filter(ImageFilter.GaussianBlur(2))
    return layer.rotate(angle, resample=Image.BICUBIC, center=(S / 2, S / 2))


def waveform(cx, cy, h, bar_w, gap):
    layer = Image.new("RGBA", (S, S))
    d = ImageDraw.Draw(layer)
    heights = [0.32, 0.62, 1.0, 0.62, 0.32]
    total = len(heights) * bar_w + (len(heights) - 1) * gap
    x0 = cx - total / 2
    for i, k in enumerate(heights):
        x = x0 + i * (bar_w + gap)
        hh = h * k
        d.rounded_rectangle([x, cy - hh / 2, x + bar_w, cy + hh / 2], radius=bar_w / 2, fill=(255, 255, 255, 240))
    shadow = layer.filter(ImageFilter.GaussianBlur(18))
    out = Image.new("RGBA", (S, S))
    out.alpha_composite(Image.fromarray(np.dstack([np.zeros((S, S, 3), np.uint8),
                                                   (np.array(shadow)[..., 3] * 0.45).astype(np.uint8)]), "RGBA"))
    out.alpha_composite(layer)
    return out


def sparkle(cx, cy, r):
    layer = Image.new("RGBA", (S, S))
    d = ImageDraw.Draw(layer)
    pts = [(cx, cy - r), (cx + r * 0.22, cy - r * 0.22), (cx + r, cy), (cx + r * 0.22, cy + r * 0.22),
           (cx, cy + r), (cx - r * 0.22, cy + r * 0.22), (cx - r, cy), (cx - r * 0.22, cy - r * 0.22)]
    d.polygon(pts, fill=(255, 255, 255, 235))
    return Image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(10)), layer)


def main():
    img = background()
    R = S * 0.25
    img.alpha_composite(glow(R * 1.9, (150, 100, 255), 0.9), (int(S / 2 - R * 1.9), int(S / 2 - R * 1.9)))
    img.alpha_composite(ring(S * 0.40, S * 0.12, S * 0.012, 18, "back"))
    img.alpha_composite(orb(R), (int(S / 2 - R), int(S / 2 - R)))
    img.alpha_composite(waveform(S / 2, S / 2 + R * 0.05, R * 0.95, R * 0.13, R * 0.09))
    img.alpha_composite(ring(S * 0.40, S * 0.12, S * 0.012, 18, "front"))
    img.alpha_composite(sparkle(S * 0.77, S * 0.24, S * 0.055))
    img.alpha_composite(sparkle(S * 0.84, S * 0.33, S * 0.025))
    mask = Image.fromarray((squircle_mask(S) * 255).astype(np.uint8))
    img.putalpha(Image.fromarray(np.minimum(np.array(img)[..., 3], np.array(mask))))
    OUT.mkdir(parents=True, exist_ok=True)
    png = img.resize((512, 512), Image.LANCZOS)
    png.save(OUT / "homyy.png")
    img.resize((256, 256), Image.LANCZOS).save(OUT / "homyy.ico",
                                               sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return png


if __name__ == "__main__":
    main()

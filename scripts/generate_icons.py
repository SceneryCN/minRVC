"""一次性生成 placeholder 应用图标到 src-tauri/icons/。

设计：
- 圆角矩形 1024×1024 ：渐变 indigo → cyan，对齐 UI 主题色
- 中央白色「声波」logo：5 根递增竖条，呼应 lucide AudioWaveform
- 输出全部格式：32 / 128 / 256（@2x）/ 512 / 1024 PNG + .icns + .ico

依赖：仅 Pillow。.icns 用 iconutil（macOS 系统命令）合成；非 macOS 上跳过。

> 这是 placeholder。发布前替换为正式品牌图标。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = ROOT / "src-tauri" / "icons"
ICONS_DIR.mkdir(parents=True, exist_ok=True)

CANVAS = 1024
RADIUS = 220
GRAD_TOP = (99, 102, 241)   # indigo-500
GRAD_BOT = (6, 182, 212)    # cyan-500


def make_master() -> Image.Image:
    """生成 1024×1024 主图（圆角渐变 + 声波 logo）。"""
    # 1) 渐变底
    bg = Image.new("RGB", (CANVAS, CANVAS), GRAD_TOP)
    for y in range(CANVAS):
        t = y / (CANVAS - 1)
        r = int(GRAD_TOP[0] * (1 - t) + GRAD_BOT[0] * t)
        g = int(GRAD_TOP[1] * (1 - t) + GRAD_BOT[1] * t)
        b = int(GRAD_TOP[2] * (1 - t) + GRAD_BOT[2] * t)
        for x in range(CANVAS):
            bg.putpixel((x, y), (r, g, b))

    # 2) 圆角 mask
    mask = Image.new("L", (CANVAS, CANVAS), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, CANVAS - 1, CANVAS - 1), RADIUS, fill=255)

    out = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    out.paste(bg, (0, 0), mask)

    # 3) 声波 logo：5 根竖条，从短到长再到短
    d = ImageDraw.Draw(out)
    cx = CANVAS // 2
    cy = CANVAS // 2
    bar_w = 60
    spacing = 100
    heights = [180, 320, 480, 320, 180]
    for i, h in enumerate(heights):
        x = cx + (i - 2) * spacing - bar_w // 2
        d.rounded_rectangle(
            (x, cy - h // 2, x + bar_w, cy + h // 2),
            radius=bar_w // 2,
            fill=(255, 255, 255, 235),
        )
    return out


def gen_pngs(master: Image.Image) -> None:
    sizes = {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "icon.png": 512,
        # Windows store / linux 桌面常见尺寸；放进去无害
        "Square30x30Logo.png": 30,
        "Square44x44Logo.png": 44,
        "Square71x71Logo.png": 71,
        "Square89x89Logo.png": 89,
        "Square107x107Logo.png": 107,
        "Square142x142Logo.png": 142,
        "Square150x150Logo.png": 150,
        "Square284x284Logo.png": 284,
        "Square310x310Logo.png": 310,
        "StoreLogo.png": 50,
    }
    for name, sz in sizes.items():
        img = master.resize((sz, sz), Image.LANCZOS)
        img.save(ICONS_DIR / name, "PNG")
        print(f"  ✓ {name} ({sz}×{sz})")


def gen_ico(master: Image.Image) -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [master.resize((s, s), Image.LANCZOS) for s in sizes]
    images[0].save(ICONS_DIR / "icon.ico", format="ICO", sizes=[(s, s) for s in sizes])
    print("  ✓ icon.ico (multi-res)")


def gen_icns(master: Image.Image) -> None:
    if sys.platform != "darwin":
        print("  · 非 macOS，跳过 .icns 生成（用 PIL 兜底）")
        # PIL >= 9.4 直接支持写 .icns
        master.save(ICONS_DIR / "icon.icns", "ICNS")
        return

    iconset = ICONS_DIR / "icon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir()

    spec = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]
    for name, sz in spec:
        master.resize((sz, sz), Image.LANCZOS).save(iconset / name, "PNG")
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(ICONS_DIR / "icon.icns")],
        check=True,
    )
    shutil.rmtree(iconset)
    print("  ✓ icon.icns (via iconutil)")


def main() -> None:
    print(f"生成 placeholder 图标到 {ICONS_DIR}")
    master = make_master()
    master.save(ICONS_DIR / "icon-source.png", "PNG")
    print("  ✓ icon-source.png (master 1024×1024)")
    gen_pngs(master)
    gen_ico(master)
    gen_icns(master)
    print("完成。要替换为正式品牌图标，重跑此脚本或换 master 源图。")


if __name__ == "__main__":
    main()

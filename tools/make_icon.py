# -*- coding: utf-8 -*-
"""从源 PNG 生成透明多尺寸图标。

用法：
    python tools/make_icon.py [源PNG]

默认读取 image/configBak.png，生成：
    image/icon.ico   多尺寸（16~256），供 exe 与窗口标题栏使用
    image/icon.png   512x512，供 Tk 窗口图标与 README 使用

依赖 Pillow（pip install pillow）。
"""
import sys
from pathlib import Path

from PIL import Image, ImageFilter

BASE = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "image" / "configBak.png"
ICO = BASE / "image" / "icon.ico"
PNG = BASE / "image" / "icon.png"

# Windows 常用图标尺寸；16/24/32 是任务栏与资源管理器最常取的尺寸
SIZES = [(256, 256), (128, 128), (96, 96), (64, 64), (48, 48),
         (40, 40), (32, 32), (24, 24), (20, 20), (16, 16)]


def load_master() -> Image.Image:
    im = Image.open(SRC).convert("RGBA")
    # 去掉四周几乎全透明的空白，只保留一点辉光
    mask = im.getchannel("A").point(lambda v: 255 if v >= 8 else 0)
    bbox = mask.getbbox()
    if bbox:
        pad = 6
        left = max(0, bbox[0] - pad)
        top = max(0, bbox[1] - pad)
        right = min(im.width, bbox[2] + pad)
        bottom = min(im.height, bbox[3] + pad)
        im = im.crop((left, top, right, bottom))
    # 补成正方形，避免缩放时变形
    side = max(im.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    return canvas


def main() -> None:
    if not SRC.is_file():
        sys.exit(f"找不到源图: {SRC}")

    master = load_master()
    # ICO 由 Pillow 统一做 LANCZOS 缩放，PyInstaller 兼容性最好
    master.save(ICO, format="ICO", sizes=SIZES)

    # 窗口图标 / README 用 512 PNG；小尺寸略微锐化，保证边缘清晰
    png_img = master.resize((512, 512), Image.LANCZOS)
    png_img.save(PNG, format="PNG", optimize=True)

    print(f"源图: {SRC}")
    print(f"裁剪后: {master.size[0]}x{master.size[1]}")
    print(f"已生成: {ICO}  ({ICO.stat().st_size} 字节, {len(SIZES)} 个尺寸)")
    print(f"已生成: {PNG}  ({PNG.stat().st_size} 字节, 512x512)")


if __name__ == "__main__":
    main()

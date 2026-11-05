#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公众号长图文字替换器
- 输出宽度固定 1000PX，PNG，高度按模板等比
- 仅替换文字：擦除指定矩形区域（用周边背景色填充），再绘制新文字
- 不改动模板中的图形、图标、色块、边框、背景、装饰元素
- 支持模块复制：copy_rect 可把模板中一个图形模块复制到目标位置后填字

布局文件 layout.json 结构（数组，每个元素一个文字块）：
[
  {
    "rect": [x, y, w, h],          // 目标文字区域（1000PX 宽坐标系下）
    "text": "新文字内容",            // 空字符串则仅擦除
    "font_size": 34,                // 可省略，默认 30
    "weight": 400,                  // 100-900，标题用 700-900
    "color": "#231815",             // 默认深色
    "align": "left",                // left|center|right，默认 left
    "valign": "top",                // top|center，默认 top
    "line_spacing": 1.6,            // 行距倍数 1.5-1.8
    "copy_rect": [x, y, w, h]       // 可选：先复制模板该区域到 rect 位置（模块复用）
  }
]

坐标系：脚本先把模板等比缩放到宽 1000PX，layout 中的坐标均基于缩放后的图。
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FONT_PATH = ASSETS / "fonts" / "NotoSansSC-VF.ttf"
TARGET_W = 1000


def load_font(size: int, weight: int = 400):
    if not FONT_PATH.exists():
        raise SystemExit(
            f"缺少字体：{FONT_PATH}\n"
            "字体随包提供，缺失说明文件被删。恢复：git checkout -- assets/fonts/；联网重下：bash scripts/setup_fonts.sh"
        )
    try:
        f = ImageFont.truetype(str(FONT_PATH), size)
        try:
            f.set_variation_by_axes([max(100, min(900, weight))])
        except Exception:
            pass
        return f
    except Exception:
        return ImageFont.load_default()


def hex2rgb(s, default=(35, 24, 21)):
    s = (s or "").strip()
    if not s.startswith("#") or len(s) != 7:
        return default
    try:
        return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))
    except Exception:
        return default


def sample_bg(img, rect, pad=6):
    """取文字区域四周一圈像素的中位色作为背景填充色（应对纯色/轻微渐变底）。"""
    x, y, w, h = rect
    W, H = img.size
    px = img.load()
    samples = []
    for i in range(max(0, x), min(W, x + w), max(1, w // 20)):
        for yy in (max(0, y - pad), min(H - 1, y + h + pad)):
            samples.append(px[i, yy])
    for j in range(max(0, y), min(H, y + h), max(1, h // 20)):
        for xx in (max(0, x - pad), min(W - 1, x + w + pad)):
            samples.append(px[xx, j])
    if not samples:
        return (255, 255, 255)
    n = len(samples)
    return tuple(sorted(s[k] for s in samples)[n // 2] for k in range(3))


def wrap_text(draw, text, font, max_w):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        b = draw.textbbox((0, 0), cur + ch, font=font)
        if b[2] - b[0] > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def render_block(img, draw, block):
    rect = block["rect"]
    x, y, w, h = rect

    # 1) 可选：复制模块图形（模块复用，不新造图形）
    if "copy_rect" in block:
        cx, cy, cw, ch_ = block["copy_rect"]
        region = img.crop((cx, cy, cx + cw, cy + ch_))
        img.paste(region, (x, y))

    # 2) 擦除原文字：用周边采样背景色填充
    bg = sample_bg(img, rect)
    draw.rectangle([x, y, x + w, y + h], fill=bg)

    text = block.get("text", "")
    if not text.strip():
        return

    # 3) 绘制新文字，字号自动收缩防溢出
    size = block.get("font_size", 30)
    weight = block.get("weight", 400)
    color = hex2rgb(block.get("color"))
    spacing = float(block.get("line_spacing", 1.6))
    align = block.get("align", "left")
    valign = block.get("valign", "top")
    pad = 8

    while size >= 14:
        font = load_font(size, weight)
        lines = wrap_text(draw, text, font, w - pad * 2)
        line_h = int(size * spacing)
        total = line_h * len(lines)
        if total <= h - pad * 2 or size <= 16:
            break
        size -= 2
    font = load_font(size, weight)
    lines = wrap_text(draw, text, font, w - pad * 2)
    line_h = int(size * spacing)
    total = line_h * len(lines)

    ty = y + pad if valign != "center" else y + max(pad, (h - total) // 2)
    for line in lines:
        lw = draw.textbbox((0, 0), line, font=font)[2]
        tx = x + pad if align == "left" else (
            x + (w - lw) // 2 if align == "center" else x + w - pad - lw)
        draw.text((tx, ty), line, font=font, fill=color)
        ty += line_h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True, help="长图模板路径")
    ap.add_argument("--layout", required=True, help="布局 JSON 文件路径")
    ap.add_argument("--out", required=True, help="输出 PNG 路径")
    args = ap.parse_args()

    tpl = Path(args.template)
    if not tpl.exists():
        print(f"ERROR: 模板不存在: {tpl}", file=sys.stderr)
        sys.exit(1)

    img = Image.open(tpl).convert("RGB")
    # 等比缩放到宽 1000PX
    if img.width != TARGET_W:
        nh = int(img.height * TARGET_W / img.width)
        img = img.resize((TARGET_W, nh), Image.LANCZOS)

    blocks = json.loads(Path(args.layout).read_text(encoding="utf-8"))
    draw = ImageDraw.Draw(img)
    for b in blocks:
        render_block(img, draw, b)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    print(f"OK 长图已生成: {out} ({TARGET_W}x{img.height}, 共 {len(blocks)} 个文字块)")


if __name__ == "__main__":
    main()

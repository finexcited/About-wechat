#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公众号封面合成器 v3（AI 背景 + 程序排版混合模式）
工作流：ImageGen 生成无文字创意背景 → 本脚本裁切到 900x383 → 叠加半透明文字衬板
→ 精准排版标题/副标题/LOGO → 输出 PNG

价值：AI 提供设计感和新颖构图，程序保证中文标题零错字、LOGO 位置精确、尺寸合规。

用法：
  python3 compose_cover.py --bg AI背景.png --title "大四才开始考公\n来得及吗" \
      --subtitle "时间线帮你算清楚了" --keywords "国考|省考|时间线" \
      --panel left --out 封面.png

参数：
  --bg        AI 生成的背景图（任意尺寸，自动裁切到 900x383，可选 --focus_x 控制裁切重心）
  --title     主标题，\\n 分行，深色大字（程序绘制，不会错字）
  --subtitle  副标题，灰色小字
  --keywords  底部关键词条，| 分隔（辅色底白字，同 v2）
  --panel     文字衬板位置：left（左半，默认）/ center（居中）/ bottom（下半通栏）
  --panel_alpha 衬板不透明度 0-255，默认 235（留一点背景透出）
  --focus_x   背景裁切水平重心 0.0-1.0，默认 0.5（用于保住背景主体不被裁掉）
  --no_panel  不加衬板，文字直接压在背景上（背景够干净时用）
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brand import LOGO_DISABLED, LOGO_PATH, warn_text_fit, ACCENT, ACCENT_ALT  # noqa: E402
from glyph import clean_many  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FONT_PATH = ASSETS / "fonts" / "NotoSansSC-VF.ttf"

PRIMARY = (238, 120, 0)
SECONDARY = (0, 126, 92)
WHITE = (255, 255, 255)
DARK = (35, 24, 21)
GRAY = (107, 114, 128)

W, H = 900, 383
BAR_H = 48
PAD = 56


def load_font(size: int, weight: int = 400):
    if not FONT_PATH.exists():
        raise SystemExit(
            f"缺少字体：{FONT_PATH}\n"
            "字体随包提供，缺失说明文件被删。恢复：git checkout -- assets/fonts/；联网重下：bash scripts/setup_fonts.sh"
        )
    try:
        f = ImageFont.truetype(str(FONT_PATH), size)
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
        return f
    except Exception:
        return ImageFont.load_default()


def text_w(d, text, font) -> int:
    b = d.textbbox((0, 0), text, font=font)
    return b[2] - b[0]


def crop_to_cover(bg: Image.Image, focus_x: float = 0.5) -> Image.Image:
    """任意尺寸背景 → 900x383 等比裁切（cover）。focus_x 控制水平裁切重心。"""
    if bg.width != W or bg.height != H:
        scale = max(W / bg.width, H / bg.height)
        nw, nh = int(bg.width * scale + 0.5), int(bg.height * scale + 0.5)
        bg = bg.resize((nw, nh), Image.LANCZOS)
        x = int((nw - W) * focus_x)
        x = max(0, min(nw - W, x))
        y = max(0, (nh - H) // 2)   # 垂直居中裁切，保住主体
        bg = bg.crop((x, y, x + W, y + H))
    return bg


def panel_layer(mode: str, alpha: int, color=(248, 245, 240)):
    """半透明米白衬板：left 左圆角卡、center 居中圆角卡、bottom 下半通栏。"""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fill = (color[0], color[1], color[2], alpha)
    if mode == "left":
        d.rounded_rectangle([24, 24, W * 0.52, H - BAR_H - 20], radius=20, fill=fill)
    elif mode == "center":
        d.rounded_rectangle([W * 0.14, 30, W * 0.86, H - BAR_H - 24], radius=20, fill=fill)
    else:  # bottom
        d.rectangle([0, int(H * 0.42), W, H - BAR_H], fill=fill)
    return layer.filter(ImageFilter.GaussianBlur(0.5))


def place_logo(img, pill: bool = True):
    """LOGO 角标：右上角、24px 安全边距、高度固定、宽度随比例。

    宽度必须有上下限——原来只有 `lw = 比例 × 高度`：
    600×60（10:1）会被拉成 560px 宽的白条横跨右上半屏，60×120（1:2）会缩成
    28×56 的一条竖线。两种都能「合成成功」且零警告，只能靠出片才发现。
    """
    # Q8b 选项 3：有意不显示 LOGO，静默跳过（不打印 WARN——这不是故障）
    if LOGO_DISABLED:
        return
    logo_path = LOGO_PATH
    if not logo_path.exists():
        print(f"WARN: LOGO 缺失（{logo_path}）", file=sys.stderr)
        return
    logo = Image.open(logo_path).convert("RGBA")
    lh = 56
    lw = int(round(logo.width / logo.height * lh))
    max_w, min_w, max_h = int(W * 0.28), 40, 84
    note = ""
    if lw > max_w:                    # 过宽：压到宽度上限，高度随比例回落
        lw = max_w
        lh = max(1, int(round(lw / (logo.width / logo.height))))
        note = f"LOGO 宽高比 {logo.width / logo.height:.0f}:1，压到角标只剩 {lh}px 高，建议换 3:1 左右的图"
    elif lw < min_w:                  # 过窄：抬到宽度下限，高度随比例升高
        lw = min_w
        lh = int(round(lw / (logo.width / logo.height)))
        note = f"LOGO 宽高比约 1:{logo.height / logo.width:.0f}，压到角标只剩 {lw}px 宽，建议换 3:1 左右的图"
    if lh > max_h:                    # 过窄且很长：再压一次高度，别把衬底撑出画面
        lh = max_h
        lw = max(1, int(round(logo.width / logo.height * lh)))
    lw, lh = max(1, min(lw, max_w)), max(1, lh)
    if note:
        print(f"WARN: {note}", file=sys.stderr)
    logo = logo.resize((lw, lh), Image.LANCZOS)
    lx, ly = W - 24 - lw, 20
    if pill:
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([lx - 12, ly - 6, lx + lw + 12, ly + lh + 6],
                            radius=10, fill=(255, 255, 255, 235))
    img.paste(logo, (lx, ly), logo)


def hex2rgb(s, default):
    try:
        s = s.lstrip("#")
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def keywords_bar(img, keywords, bar=SECONDARY, accent=PRIMARY, bar_ink=WHITE):
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - BAR_H, W, H], fill=bar)
    if not keywords:
        return
    items = [k.strip() for k in keywords.split("|") if k.strip()]
    if not items:
        return
    font = load_font(22, 500)
    sepf = load_font(22, 400)
    sep = " | "
    total = sum(text_w(d, it, font) for it in items) + text_w(d, sep, sepf) * (len(items) - 1)
    dot_r = 5
    total += (dot_r * 2 + 30) * 2
    x = (W - total) // 2
    y = H - BAR_H + (BAR_H - 22) // 2 - 2
    d.ellipse([x, y + 6, x + dot_r * 2, y + 6 + dot_r * 2], fill=accent)
    x += dot_r * 2 + 30
    for i, it in enumerate(items):
        d.text((x, y), it, font=font, fill=bar_ink)
        x += text_w(d, it, font)
        if i < len(items) - 1:
            d.text((x, y), sep, font=sepf, fill=bar_ink)
            x += text_w(d, sep, sepf)
    x += 30
    d.ellipse([x - dot_r * 2, y + 6, x, y + 6 + dot_r * 2], fill=accent)


def fit_lines(d, lines, max_w, base_size, weight=900):
    size = base_size
    while size >= 34:
        font = load_font(size, weight)
        if all(text_w(d, l, font) <= max_w for l in lines if l):
            return font, size
        size -= 4
    return load_font(34, weight), 34


def draw_title_block(img, mode, title, subtitle, accent=PRIMARY, ink=DARK):
    d = ImageDraw.Draw(img)
    lines = [l for l in title.split("\n") if l.strip()]
    if mode == "left":
        tx, max_w, base = PAD + 10, int(W * 0.52) - PAD - 20, 58
    elif mode == "center":
        tx, max_w, base = int(W * 0.14) + 28, int(W * 0.72) - 56, 58
    else:
        tx, max_w, base = PAD, W - PAD * 2, 62
    font, size = fit_lines(d, lines, max_w, base)
    for _l in lines:
        warn_text_fit("标题行", _l, font, max_w)
    line_h = int(size * 1.22)

    total_h = line_h * len(lines) + (58 if subtitle else 0)
    ty = (H - BAR_H - total_h) // 2 - 10 if mode == "left" else (
        int(H * 0.42) + 24 if mode == "bottom" else (H - BAR_H - total_h) // 2 - 6)

    # 文字只做单层实色渲染，不加阴影、描边等任何特效（避免重影）
    for i, line in enumerate(lines):
        d.text((tx, ty), line, font=font, fill=ink)
        ty += line_h
    if subtitle:
        _sf = load_font(26, 400)
        warn_text_fit("副标题", subtitle, _sf, max_w)
        d.text((tx, ty + 10), subtitle, font=_sf, fill=GRAY)
    # 辅色下划点缀（纯色块，非文字效果）：置于副标题下方留 10px 空隙，不与文字相压
    bar_y = ty + (54 if subtitle else 6)
    d.rectangle([tx + 2, bar_y, tx + 2 + 72, bar_y + 6], fill=accent)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bg", required=True, help="AI 背景图路径")
    ap.add_argument("--title", required=True, help="主标题，\\n 分行")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--keywords", default="", help="底部关键词，| 分隔")
    ap.add_argument("--panel", default="left", choices=["left", "center", "bottom"])
    ap.add_argument("--panel_alpha", type=int, default=235)
    ap.add_argument("--focus_x", type=float, default=0.5)
    ap.add_argument("--no_panel", action="store_true")
    ap.add_argument("--accent", default=ACCENT, help="点缀色（下划线/圆点），默认 WX_ACCENT")
    ap.add_argument("--bar", default=ACCENT_ALT, help="底部关键词条底色，默认 WX_ACCENT_ALT")
    ap.add_argument("--bar_ink", default="#FFFFFF",
                    help="关键词条上的字色，默认 #FFFFFF。条底色偏浅时必须改成深色，"
                         "否则白字糊在浅底上；用 pick_palette.py --check <条底> <字色> 验一遍")
    ap.add_argument("--panel_color", default="#F8F5F0", help="衬板底色")
    ap.add_argument("--ink", default="#231815", help="标题字色")
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-emoji", action="store_true",
                    help="保留字体渲染不出的字符（emoji 等）——默认会剥离，因为封面上它们会印成叉框")
    args = ap.parse_args()

    args.title = args.title.replace("\\n", "\n")

    # 与 make_cover.py 同一套处理：PIL 单字体、无回退，emoji 印成叉框，默认剥离并说明
    fields = ("title", "subtitle", "keywords")
    cleaned, _dropped = clean_many([getattr(args, f) for f in fields],
                                   where="封面", keep=args.keep_emoji)
    for field, val in zip(fields, cleaned):
        setattr(args, field, val)

    bg_path = Path(args.bg)
    if not bg_path.exists():
        print(f"ERROR: 背景图不存在: {bg_path}", file=sys.stderr)
        sys.exit(1)

    accent_c = hex2rgb(args.accent, PRIMARY)
    bar_c = hex2rgb(args.bar, SECONDARY)
    panel_c = hex2rgb(args.panel_color, (248, 245, 240))
    ink_c = hex2rgb(args.ink, DARK)

    img = crop_to_cover(Image.open(bg_path).convert("RGB"), args.focus_x).convert("RGBA")

    if not args.no_panel:
        img = Image.alpha_composite(img, panel_layer(args.panel, args.panel_alpha, panel_c))
    else:
        # 无衬板时加深底部渐变保证文字可读
        grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        for i in range(H):
            a = int(90 * i / H)
            gd.line([(0, i), (W, i)], fill=(35, 24, 21, a))
        img = Image.alpha_composite(img, grad)

    img = img.convert("RGB")
    draw_title_block(img, args.panel, args.title, args.subtitle, accent_c, ink_c)
    keywords_bar(img, args.keywords, bar_c, accent_c, hex2rgb(args.bar_ink, WHITE))
    place_logo(img)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    print(f"OK 封面已合成: {out} (900x383, AI背景+程序排版)")


if __name__ == "__main__":
    main()

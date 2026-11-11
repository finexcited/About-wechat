#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公众号封面生成器 v2（设计感版）
- 尺寸 900x383 PX，PNG 输出
- 色系：主色/辅色由 WX_ACCENT / WX_ACCENT_ALT 注入（示例预设 #EE7800 / #007E5C），另有 #FFFFFF（白）#231815（深），米白底 #F8F5F0
- 固定元素：LOGO 角标（$WX_LOGO 或 assets/logo.png，右上角）；深色/辅色底自动加白色衬底（不改 LOGO 本体）
- 不出现公众号名称、二维码
- 字体：Noto Sans SC（OFL 免费商用），可变字重
- 4 套版式：1 对比式 / 2 大字焦点式 / 3 标签卡片式 / 4 辅色满底问答式

用法：
  python3 make_cover.py --title "选调生\n普通公务员" --vs "vs" \
      --subtitle "大学生该冲哪一个？" --icons "check,doc" \
      --keywords "门槛|考试|发展|适合人群" --variant 1 --out 封面.png

参数说明：
  --title     主标题，\n 分行；多行自动辅色/主色交替着色
  --vs        在第 1、2 行之间插入的小字（如 vs、和、还是）
  --subtitle  副标题/引导语（版式1 显示在右侧，版式2/3/4 显示在标题下方）
  --icons     逗号分隔图标卡片：doc,check,cal,search,cap,flag（版式1 用，最多 2 个）
  --icon_labels 图标下方小字，逗号分隔，与 icons 对应
  --keywords  底部关键词条，用 | 分隔；不传则无底部条
  --focus     大字焦点字符（版式2 用，如 "3"、"vs"、"？"）
  --tag       主色标签文字（版式3 用）
  --variant   1-4 或 auto
  --keep-emoji 保留字体渲染不出的字符（emoji 等）。默认剥离并打 WARN——
              本脚本只用 Noto Sans SC 一个字体、无字体回退，emoji 会印成叉框。
"""
import argparse
import hashlib
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brand import BRAND_NAME, LOGO_DISABLED, LOGO_PATH, warn_text_fit, resolve_accent  # noqa: E402
from glyph import clean_many  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FONT_PATH = ASSETS / "fonts" / "NotoSansSC-VF.ttf"

# 主色/辅色由 WX_ACCENT / WX_ACCENT_ALT 注入；变量名沿用历史，实际值可自定义
PRIMARY = resolve_accent("orange", as_rgb=True)   # 主色
SECONDARY = resolve_accent("green", as_rgb=True)     # 辅色
WHITE = (255, 255, 255)
DARK = (35, 24, 21)         # #231815
GRAY = (107, 114, 128)
LIGHT = (245, 245, 245)
YELLOW = (242, 201, 76)     # #F2C94C
CREAM = (248, 245, 240)     # 米白底（接近 #F5F5F5 暖调）

W, H = 900, 383
BAR_H = 48                  # 底部关键词条高度


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


def place_logo(img, pill: bool = False, height: int = 64):
    """LOGO 角标，右上角，24PX 安全边距；pill=True 时垫白色圆角衬底（不改 LOGO 本体）。

    宽度有上下限：原来只按比例算宽度，600×60 会被拉成整条白横幅、60×120 会缩成
    一条竖线，而脚本照样报「合成成功」。
    """
    # Q8b 选项 3「不显示任何 LOGO」：整块跳过，**不退化成文字角标**。
    # 文字角标是「图丢了」的兜底，不是「我要素封面」的实现——两者混在一起，
    # 使用者选了不显示，封面上反而多出一行品牌名。
    if LOGO_DISABLED:
        return
    logo_path = LOGO_PATH
    if not logo_path.exists():
        d = ImageDraw.Draw(img)
        font = load_font(20, 500)
        badge = BRAND_NAME
        tw = text_w(d, badge, font)
        d.rounded_rectangle([W - 24 - tw - 28, 24, W - 24, 62], radius=8,
                            fill=WHITE, outline=GRAY, width=1)
        d.text((W - 24 - tw - 14, 30), badge, font=font, fill=DARK)
        print(f"WARN: LOGO 缺失（{logo_path}），已用文字角标替代", file=sys.stderr)
        return
    logo = Image.open(logo_path).convert("RGBA")
    ratio = logo.width / logo.height
    lh, lw = height, int(round(ratio * height))
    max_w, min_w, max_h = int(W * 0.28), 40, 96
    note = ""
    if lw > max_w:                    # 过宽：压到宽度上限
        lw = max_w
        lh = max(1, int(round(lw / ratio)))
        note = f"LOGO 宽高比 {ratio:.0f}:1，压到角标只剩 {lh}px 高，建议换 3:1 左右的图"
    elif lw < min_w:                  # 过窄：抬到宽度下限
        lw = min_w
        lh = int(round(lw / ratio))
        note = f"LOGO 宽高比约 1:{1 / ratio:.0f}，压到角标只剩 {lw}px 宽，建议换 3:1 左右的图"
    if lh > max_h:
        lh = max_h
        lw = max(1, int(round(ratio * lh)))
    lw, lh = max(1, min(lw, max_w)), max(1, lh)
    if note:
        print(f"WARN: {note}", file=sys.stderr)
    logo = logo.resize((lw, lh), Image.LANCZOS)
    lx, ly = W - 24 - lw, 24
    if pill:
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([lx - 14, ly - 8, lx + lw + 14, ly + lh + 8],
                            radius=12, fill=WHITE)
    img.paste(logo, (lx, ly), logo)


def speckle(d, cx, cy, radius, color, seed, n=60):
    """角落喷溅装饰：随机小圆点，模拟参考图的喷点效果。"""
    rnd = random.Random(seed)
    for _ in range(n):
        a = rnd.uniform(0, 2 * math.pi)
        r = radius * (rnd.random() ** 0.6)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        s = rnd.uniform(1.5, 5) * (1 - r / (radius * 1.2))
        if s > 0.5:
            d.ellipse([x - s, y - s, x + s, y + s], fill=color)


def fit_lines(d, lines, max_w, base_size, weight=900):
    """标题自适应：整体缩字号直到每行都不溢出。"""
    size = base_size
    while size >= 34:
        font = load_font(size, weight)
        if all(text_w(d, l, font) <= max_w for l in lines if l):
            return font, size
        size -= 4
    return load_font(34, weight), 34


def draw_mixed_title(d, x, y, lines, max_w, base_size, colors, vs=None, line_gap=0.22):
    """多行混色标题（逐行取色），可选在第 1、2 行之间插小字 vs。返回结束 y。"""
    font, size = fit_lines(d, lines, max_w, base_size)
    line_h = int(size * (1 + line_gap))
    vs_font = load_font(max(24, int(size * 0.42)), 700)
    for i, line in enumerate(lines):
        d.text((x, y), line, font=font, fill=colors[i % len(colors)])
        y += line_h
        if vs and i == 0 and len(lines) > 1:
            d.text((x + 6, y - 4), vs, font=vs_font, fill=DARK)
            y += int(line_h * 0.42)
    return y


def keywords_bar(d, keywords, bg=SECONDARY, fg=WHITE):
    """底部关键词条：辅色底白字，| 分隔，两端主色圆点。"""
    d.rectangle([0, H - BAR_H, W, H], fill=bg)
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
    d.ellipse([x, y + 6, x + dot_r * 2, y + 6 + dot_r * 2], fill=PRIMARY)
    x += dot_r * 2 + 30
    for i, it in enumerate(items):
        d.text((x, y), it, font=font, fill=fg)
        x += text_w(d, it, font)
        if i < len(items) - 1:
            d.text((x, y), sep, font=sepf, fill=fg)
            x += text_w(d, sep, sepf)
    x += 30
    d.ellipse([x - dot_r * 2, y + 6, x, y + 6 + dot_r * 2], fill=PRIMARY)


# ---------- 线性小图标（描边风格，图标卡片用） ----------
def _lw(scale=1):
    return max(3, int(4 * scale))


def icon_doc(d, cx, cy, s, color):
    d.rounded_rectangle([cx - s, cy - s * 1.2, cx + s, cy + s * 1.2], radius=8,
                        outline=color, width=_lw())
    for i, w_ in enumerate((1.2, 1.2, 0.7)):
        y = cy - s * 0.6 + i * s * 0.55
        d.line([cx - s * 0.55, y, cx - s * 0.55 + s * w_, y], fill=color, width=_lw())


def icon_check(d, cx, cy, s, color):
    d.ellipse([cx - s, cy - s, cx + s, cy + s], outline=color, width=_lw())
    d.line([cx - s * 0.5, cy, cx - s * 0.1, cy + s * 0.4, cx + s * 0.6, cy - s * 0.45],
           fill=color, width=_lw(1.2), joint="curve")


def icon_cal(d, cx, cy, s, color):
    d.rounded_rectangle([cx - s, cy - s * 0.8, cx + s, cy + s], radius=6,
                        outline=color, width=_lw())
    d.line([cx - s, cy - s * 0.3, cx + s, cy - s * 0.3], fill=color, width=_lw())
    d.line([cx - s * 0.4, cy - s * 1.1, cx - s * 0.4, cy - s * 0.6], fill=color, width=_lw())
    d.line([cx + s * 0.4, cy - s * 1.1, cx + s * 0.4, cy - s * 0.6], fill=color, width=_lw())


def icon_search(d, cx, cy, s, color):
    d.ellipse([cx - s, cy - s, cx + s * 0.4, cy + s * 0.4], outline=color, width=_lw(1.2))
    d.line([cx + s * 0.25, cy + s * 0.25, cx + s * 0.9, cy + s * 0.9], fill=color, width=_lw(1.4))


def icon_cap(d, cx, cy, s, color):
    d.polygon([(cx, cy - s), (cx + s * 1.2, cy - s * 0.2), (cx, cy + s * 0.6),
               (cx - s * 1.2, cy - s * 0.2)], outline=color, width=_lw())
    d.line([cx + s * 0.8, cy + s * 0.1, cx + s * 0.8, cy + s * 1.1], fill=color, width=_lw())


def icon_flag(d, cx, cy, s, color):
    d.line([cx - s * 0.6, cy - s * 1.1, cx - s * 0.6, cy + s * 1.1], fill=color, width=_lw())
    d.polygon([(cx - s * 0.6, cy - s), (cx + s, cy - s * 0.5), (cx - s * 0.6, cy)],
              outline=color, width=_lw())


ICONS = {"doc": icon_doc, "check": icon_check, "cal": icon_cal,
         "search": icon_search, "cap": icon_cap, "flag": icon_flag}


def icon_card(d, x, y, w, h, icon, label, color):
    """圆角描边卡片 + 线性图标 + 下方标签。"""
    d.rounded_rectangle([x, y, x + w, y + h], radius=16, outline=color, width=3)
    fn = ICONS.get(icon)
    if fn:
        fn(d, x + w // 2, y + int(h * 0.36), int(h * 0.17), color)
    if label:
        font = load_font(20, 700)
        lw_ = text_w(d, label, font)
        d.text((x + (w - lw_) // 2, y + h - 38), label, font=font, fill=DARK)


# ---------- 版式 ----------

def variant_1(img, d, args):
    """对比式（参考图风格）：米白底，左侧标题辅色/主色混排，竖分隔线，右侧引导语+图标卡片，底部关键词条。"""
    d.rectangle([0, 0, W, H], fill=CREAM)
    speckle(d, 30, 30, 130, (243, 178, 120), seed=42)
    speckle(d, W - 20, 150, 90, (230, 200, 160), seed=7)

    lines = [l for l in args.title.split("\n") if l.strip()]
    colors = [SECONDARY, PRIMARY, SECONDARY]
    for _l in lines:
        warn_text_fit("版式1 标题行", _l, load_font(74, 900), 470)
    draw_mixed_title(d, 56, 76, lines, 470, 74, colors, vs=args.vs)

    div_x = 556
    d.rectangle([div_x, 76, div_x + 3, H - BAR_H - 36], fill=SECONDARY)

    rx = div_x + 32
    if args.subtitle:
        font, _ = fit_lines(d, [args.subtitle], W - rx - 40, 32, 900)
        warn_text_fit("版式1 副标题", args.subtitle, font, W - rx - 40)
        d.text((rx, 84), args.subtitle, font=font, fill=SECONDARY)
    icons = [i.strip() for i in args.icons.split(",") if i.strip()][:2]
    labels = [l.strip() for l in args.icon_labels.split(",")] if args.icon_labels else []
    cw, ch, gap = 128, 148, 22
    iy = 148
    for k, icon in enumerate(icons):
        label = labels[k] if k < len(labels) else ""
        icon_card(d, rx + k * (cw + gap), iy, cw, ch, icon, label,
                  SECONDARY if k % 2 == 0 else PRIMARY)

    keywords_bar(d, args.keywords)
    place_logo(img)


def variant_2(img, d, args):
    """大字焦点式：米白底 + 超大焦点字符水印 + 标题混排。"""
    d.rectangle([0, 0, W, H], fill=CREAM)
    focus = args.focus or ""
    if focus:
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((W - 430, 10), focus, font=load_font(300, 900), fill=PRIMARY + (45,))
        img.paste(Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB"), (0, 0))
        d = ImageDraw.Draw(img)

    lines = [l for l in args.title.split("\n") if l.strip()]
    colors = [DARK, PRIMARY, SECONDARY]
    end_y = draw_mixed_title(d, 56, 84, lines, 620, 72, colors, vs=args.vs)
    if args.subtitle:
        _f = load_font(26, 400)
        warn_text_fit("副标题", args.subtitle, _f, W - 58 - 28)
        d.text((58, end_y + 10), args.subtitle, font=_f, fill=GRAY)

    keywords_bar(d, args.keywords)
    place_logo(img)


def variant_3(img, d, args):
    """标签卡片式：白底，左上主色标签，大辅色标题 + 主色下划色块，副标题。"""
    d.rectangle([0, 0, W, H], fill=WHITE)
    d.rectangle([0, 0, W, 10], fill=PRIMARY)
    speckle(d, W - 40, H - BAR_H - 60, 110, (200, 230, 215), seed=11)

    y = 44
    if args.tag:
        font = load_font(22, 700)
        tw = text_w(d, args.tag, font)
        d.rounded_rectangle([56, y, 56 + tw + 40, y + 44], radius=22, fill=PRIMARY)
        d.text((76, y + 8), args.tag, font=font, fill=WHITE)
        y += 68

    lines = [l for l in args.title.split("\n") if l.strip()]
    font, size = fit_lines(d, lines, W - 112, 68)
    for line in lines:
        d.text((56, y), line, font=font, fill=SECONDARY)
        y += int(size * 1.24)
    d.rectangle([58, y + 2, 58 + min(200, int(size * 2.2)), y + 12], fill=PRIMARY)
    y += 26
    if args.subtitle:
        _f = load_font(26, 400)
        warn_text_fit("副标题", args.subtitle, _f, W - 58 - 28)
        d.text((58, y + 4), args.subtitle, font=_f, fill=GRAY)

    keywords_bar(d, args.keywords)
    place_logo(img)


def variant_4(img, d, args):
    """辅色满底问答式：辅色底白/浅色标题，大问号水印，深色关键词条。"""
    d.rectangle([0, 0, W, H], fill=SECONDARY)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text((W - 320, -30), "？", font=load_font(280, 900), fill=WHITE + (28,))
    img.paste(Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB"), (0, 0))
    d = ImageDraw.Draw(img)

    lines = [l for l in args.title.split("\n") if l.strip()]
    colors = [WHITE, YELLOW, WHITE]
    end_y = draw_mixed_title(d, 56, 90, lines, 600, 70, colors, vs=args.vs)
    if args.subtitle:
        _f = load_font(26, 400)
        warn_text_fit("副标题", args.subtitle, _f, W - 58 - 28)
        d.text((58, end_y + 8), args.subtitle, font=_f,
               fill=(220, 235, 228))

    keywords_bar(d, args.keywords, bg=DARK)
    place_logo(img, pill=True)


VARIANTS = [variant_1, variant_2, variant_3, variant_4]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True, help="主标题，\\n 分行")
    ap.add_argument("--vs", default="", help="第 1、2 行之间的小字，如 vs")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--tag", default="", help="主色标签文字（版式3）")
    ap.add_argument("--icons", default="", help="图标卡片，逗号分隔：doc,check,cal,search,cap,flag")
    ap.add_argument("--icon_labels", default="", help="图标下方标签，逗号分隔")
    ap.add_argument("--keywords", default="", help="底部关键词，用 | 分隔")
    ap.add_argument("--focus", default="", help="大字焦点字符（版式2）")
    ap.add_argument("--variant", default="auto")
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-emoji", action="store_true",
                    help="保留字体渲染不出的字符（emoji 等）——默认会剥离，因为封面上它们会印成叉框")
    args = ap.parse_args()
    # 兼容 shell 传入的字面量 \n
    args.title = args.title.replace("\\n", "\n")

    # 封面上每个 emoji 都会印成叉框（PIL 单字体、无回退）。默认剥离并说明；
    # 只有 HTML 版不受影响，那边保留原样。六七个字段合并成一条告警，别刷屏。
    fields = ("title", "subtitle", "tag", "focus", "icon_labels", "keywords")
    cleaned, dropped = clean_many([getattr(args, f) for f in fields],
                                  where="封面", keep=args.keep_emoji)
    for field, val in zip(fields, cleaned):
        setattr(args, field, val)

    if args.variant == "auto":
        idx = int(hashlib.md5(args.title.encode()).hexdigest(), 16) % 4
    else:
        idx = max(0, min(3, int(args.variant) - 1))

    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    VARIANTS[idx](img, d, args)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    print(f"OK 封面已生成: {out} (版式 {idx + 1}, 900x383)")


if __name__ == "__main__":
    main()

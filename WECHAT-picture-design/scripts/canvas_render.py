# -*- coding: utf-8 -*-
"""canvas_render.py — 按「设计哲学」渲染贴图配图（HTML/CSS → PNG）。

与旧版的区别：旧版只有一套写死的设计语言（Margin Notes），30 篇共用 5 个
版式；本版从 assets/design-philosophies/ 读取多套完整设计语言，每篇按
philosophy.assign() 轮抽一套 —— 配色、栏网格、字号节奏、图像处理、版式原型
整体切换，篇与篇之间视觉指纹不同。

设计约束（硬性）：
  1. 严禁抄袭：参考图只取风格，不复制画面；生成后用 dHash 与参考图比对，距离过近即报警。
  2. 每页版式必须不同：版式由所属哲学的 layout 列表轮换，manifest 记录每页原型与变化点。
  3. 内容贴人群：配图风格由所属哲学的 photo_style 决定，与 prompts 阶段同源。

流水线：拼 HTML → ego-browser 以 1080×1440 截图 → Pillow 叠 LOGO → 写 design-report.md
"""
import base64
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import compose_images
import philosophy

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_MEASURE = "/System/Library/Fonts/Hiragino Sans GB.ttc"

VARIANT_LABEL = {
    "cover-hero-bleed": "封面·全幅压字",
    "cover-photo-top": "封面·上图下文",
    "cover-split-diagonal": "封面·斜切分栏",
    "cover-mosaic": "封面·双窗拼贴",
    "cover-stacked-strip": "封面·顶部窄带",
    "inner-editorial": "内页·编辑栏",
    "inner-photo-top": "内页·上图下文",
    "inner-quote-band": "内页·观点页",
    "inner-side-band": "内页·侧栏图",
    "inner-mosaic": "内页·拼贴窗",
    "inner-stacked-strip": "内页·窄带留白",
}
VARIANT_CHANGE = {
    "cover-hero-bleed": "巨型标题压左栏，图片自底部全出血，色条切分图文",
    "cover-photo-top": "图片占上半幅，标题落到纸面下半，视觉重心下移",
    "cover-split-diagonal": "图片贴右满高、左缘斜切，标题独占左半幅，出现斜向动势",
    "cover-mosaic": "一大一小两扇图窗错位叠放，标题压在下方纸面，信息层次最多",
    "cover-stacked-strip": "细长图带置顶，标题漂浮在大留白中，节奏最慢",
    "inner-editorial": "描边巨型页码＋色条＋正文压栏，信息密度最高",
    "inner-photo-top": "图片占上半幅，标题与要点压在纸面下半，先图后文",
    "inner-quote-band": "大字观点居中，细线围框，图片收成底部窄带，节奏最慢",
    "inner-side-band": "右侧全高窄图＋竖排标签，文字独占左侧，杂志内页感",
    "inner-mosaic": "两扇错位图窗＋色块填空，文字压在下缘，版面最碎",
    "inner-stacked-strip": "顶部细图带、中部大留白，只留一句标题，克制到极简",
}

# 每种版式对「照片该怎么构图」的要求：生图提示词据此写，图才不会和版式打架。
ARCH_HINT = {
    "cover-hero-bleed": "主体压在画面下三分之二，上部留大片干净空间（标题叠在上方纸面）",
    "cover-photo-top": "单一主体居中偏上，画面下缘保持干净，便于下半幅压字",
    "cover-split-diagonal": "主体偏右、竖向构图，左侧三分之一留空（会被斜边切掉）",
    "cover-mosaic": "单一主体居中，四周留出余量（画面会被裁成一横一竖两扇窗）",
    "cover-stacked-strip": "横向宽幅构图，主体水平居中，上下都留余量（只取中间一条）",
    "inner-editorial": "主体偏下，画面上部简洁干净",
    "inner-photo-top": "单一主体居中，构图紧凑（取上半幅）",
    "inner-quote-band": "横向宽幅，主体居中偏下（只取底部一条窄带）",
    "inner-side-band": "竖向长构图，主体居中，左右两侧留余量（取右侧竖条）",
    "inner-mosaic": "主体居中，四周留足余量（要裁两扇窗）",
    "inner-stacked-strip": "横向宽幅，主体水平居中（只取顶部一条窄带）",
}


# ---------------- 基础工具 ----------------

def load_tokens():
    """兼容旧调用：返回当前第一套哲学（等价于旧 design-tokens.json）。"""
    phils, _ = philosophy.load_all(common.load_config())
    return phils[0]


def resolve_philosophies():
    cfg = common.load_config()
    phils, index = philosophy.load_all(cfg)
    return cfg, phils, index


def _font(size, bold=True):
    return ImageFont.truetype(FONT_MEASURE, size, index=2 if bold else 0)


def wrap_for(text, size, width, bold=True):
    fnt = _font(size, bold)
    tmp = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    return compose_images.wrap_cjk(text, fnt, width, tmp)


def fit_title(text, width, max_size=148, min_size=92):
    segs = []
    for i, ch in enumerate(text):
        if ch in "，。、；：！？" and i < len(text) - 1:
            segs.append((text[:i + 1], text[i + 1:]))
    if segs:
        best = min(segs, key=lambda s: max(len(s[0]), len(s[1])))
        unit = max(len(best[0]), len(best[1]))
    else:
        unit = (len(text) + 1) // 2
    size = int(width / max(1, unit))
    return max(min_size, min(max_size, size))


def esc(t):
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def focus_pct(img_path, box_h, box_w):
    """按行方向的细节能量定位主体中心，返回 object-position 的纵向百分比。

    生成图的构图经常把主体压在画面偏下，object-fit:cover 直接居中裁会切掉主体，
    这里让裁剪窗口跟着画面细节重心走（0=顶部，100=底部）。
    """
    try:
        with Image.open(img_path) as im:
            iw, ih = im.size
            g = im.convert("L").resize((64, 96), Image.LANCZOS)
    except Exception:
        return 50
    px = list(g.getdata())
    rows = []
    for y in range(96):
        base = y * 64
        rows.append(sum(abs(px[base + x] - px[base + x - 1]) for x in range(1, 64)) + 1)
    total = float(sum(rows))
    acc, center = 0.0, 0.5
    for y, e in enumerate(rows):
        acc += e
        if acc >= total * 0.5:
            center = (y + 0.5) / 96
            break
    scale = max(box_w / float(iw), box_h / float(ih))
    vis = min(1.0, box_h / (ih * scale))
    if vis >= 0.999:
        return 50
    p = (center - vis / 2.0) / (1.0 - vis)
    return int(round(max(0.0, min(1.0, p)) * 100))


def img_b64(path, trim_ratio=0.045):
    """读图并裁掉底边（模型生成的「AI生成」角标碎片），再转 base64 内嵌。"""
    import io
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        t = int(h * trim_ratio)
        if t > 0:
            im = im.crop((0, 0, w, h - t))
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def hl(text, word, accent):
    if not word or word not in text:
        return esc(text)
    pre, post = text.split(word, 1)
    return '%s<em style="color:%s;font-style:normal">%s</em>%s' % (
        esc(pre), accent, esc(word), esc(post))


def img_tag(c, t, h, w, pos=None):
    """图片标签：object-fit cover + 焦点跟随，滤镜来自所属哲学。"""
    f = (t.get("photo") or {}).get("filter", "none")
    p = pos if pos is not None else focus_pct(c.get("img_path", ""), h, w)
    return ('<img src="%s" style="width:100%%;height:100%%;object-fit:cover;display:block;'
            'filter:%s;object-position:50%% %d%%">' % (c.get("img_data", ""), f, int(p)))


def photo_div(c, t, x, y, w, h, pos=None, extra=""):
    return ('<div class="photo" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx;%s">%s</div>'
            % (x, y, w, h, extra, img_tag(c, t, h, w, pos)))


def bar(t, x, y, w, h=None, color=None):
    h = h if h is not None else t["rules"]["accent_bar"]
    return ('<div class="bar" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx;%s"></div>'
            % (x, y, w, h, ("background:%s" % color) if color else ""))


# ---------------- 样式表 ----------------

def base_css(t, W, H):
    p = t["palette"]
    m = t["grid"]["margin"]
    tf = (t.get("photo") or {}).get("filter", "none")
    g = t.get("grain", 0.05)
    pb = (t.get("skin") or {}).get("photo_border", "0")
    return """
  html,body{margin:0;padding:0;width:%(W)spx;height:%(H)spx;overflow:hidden;background:%(paper)s;}
  body{font-family:"Hiragino Sans GB","PingFang SC",sans-serif;color:%(ink)s;-webkit-font-smoothing:antialiased;}
  .page{position:relative;width:%(W)spx;height:%(H)spx;overflow:hidden;}
  .meta{position:absolute;left:%(m)spx;right:%(m)spx;top:%(meta_top)spx;display:flex;justify-content:space-between;
        font-family:ui-monospace,Menlo,monospace;font-size:%(meta)spx;letter-spacing:%(mtrack)s;color:%(muted)s;}
  .hair{position:absolute;left:%(m)spx;right:%(m)spx;top:%(hair_top)spx;background:%(line)s;}
  .eyebrow{position:absolute;font-family:ui-monospace,Menlo,monospace;font-size:%(meta)spx;
           letter-spacing:.14em;color:%(accent)s;}
  .photo{position:absolute;overflow:hidden;border:%(pb)s;}
  .photo img{width:100%%;height:100%%;object-fit:cover;display:block;filter:%(tf)s;}
  .bar{position:absolute;background:%(accent)s;}
  .cap{position:absolute;font-family:ui-monospace,Menlo,monospace;font-size:17px;
       letter-spacing:.13em;color:%(muted)s;}
  .numeral{position:absolute;font-weight:700;line-height:1;color:transparent;
           -webkit-text-stroke:1px %(line)s;}
  .rule{position:absolute;background:%(accent)s;}
  .grain{position:absolute;inset:0;opacity:%(grain)s;background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/></filter><rect width='120' height='120' filter='url(%%23n)'/></svg>");}
""" % {"W": W, "H": H, "paper": p["paper"], "ink": p["ink"], "muted": p["muted"],
       "line": p["line"], "accent": p["accent"], "m": m,
       "meta": t["type"]["meta"], "mtrack": t["type"]["meta_tracking"],
       "meta_top": m - 6, "hair_top": m + 54, "tf": tf, "grain": g, "pb": pb}


def meta_row(c, t, W, m):
    out = ['<div class="meta"><span>%s</span><span>%02d / %02d</span></div>'
           % (esc(c.get("meta_left", "YOUR BRAND")), c["page_no"], c["total"])]
    if (t.get("skin") or {}).get("show_hair", True):
        out.append('<div class="hair" style="height:%dpx"></div>' % t["rules"]["hairline"])
    return out


# ---------------- 文字块 ----------------

def title_lh(t):
    """标题实际使用的行高。有色块底时必须更松，否则 CJK 字形会顶出块边。"""
    lh = t["type"]["title_line_height"]
    if (t.get("skin") or {}).get("title_bg"):
        lh = max(lh, 1.08)
    return lh


def title_pad(t):
    """色块底的上下内边距合计，算后续元素位置时要一起加上。"""
    return 36 if (t.get("skin") or {}).get("title_bg") else 0


def title_block(c, t, p, x, y, w, size, lines=None, color=None):
    tl = t["type"]
    skin = t.get("skin") or {}
    lines = lines or wrap_for(c.get("title_text", ""), size, w)
    extra = ""
    if skin.get("title_bg"):
        extra = "background:%s;color:%s;padding:18px 16px;box-sizing:border-box;" % (
            skin["title_bg"], skin.get("title_fg", p["paper"]))
    fg = color or (skin.get("title_fg") if skin.get("title_bg") else p["ink"])
    accent = skin.get("title_fg") if skin.get("title_bg") else p["accent"]
    lh = title_lh(t)
    return ('<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;font-weight:700;'
            'font-size:%dpx;line-height:%s;letter-spacing:-0.02em;color:%s;%s">%s</div>'
            % (x, y, w, size, lh, fg, extra,
               "<br>".join(hl(l, c.get("highlight", ""), accent) for l in lines)))


def headline_block(c, t, p, x, y, w, size=None, tracking="-0.01em", align="left"):
    tl = t["type"]
    size = size or tl["headline"]
    return ('<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;font-weight:700;'
            'font-size:%dpx;line-height:1.16;letter-spacing:%s;text-align:%s">%s</div>'
            % (x, y, w, size, tracking, align,
               hl(c.get("headline", ""), c.get("highlight", ""), p["accent"])))


def body_block(c, t, p, x, y, w, size=None, lh=None, color=None, text=None, align="left"):
    tl = t["type"]
    size = size or tl["body"]
    lh = lh or tl["body_line_height"]
    color = color or p["body"]
    text = text if text is not None else c.get("body_text", "")
    lines = wrap_for(text, size, w)
    return ('<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;font-size:%dpx;'
            'line-height:%s;color:%s;text-align:%s">%s</div>'
            % (x, y, w, size, lh, color, align, "<br>".join(esc(l) for l in lines))), len(lines)


def sub_block(c, t, p, x, y, w, size=None):
    size = size or max(28, int(t["type"]["body"] * 1.02))
    return ('<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;font-size:%dpx;'
            'line-height:1.45;color:%s">%s</div>'
            % (x, y, w, size, p["sub"], esc(c.get("sub", ""))))


def cap_block(c, x, y, align="right"):
    return '<div class="cap" style="%s:%dpx;%s:%dpx">%s</div>' % (
        "right" if align == "right" else "left",
        (x if align == "right" else x), "top", y, esc(c.get("caption", "")))


def sticker_row(c, t, p, x, y):
    m = t["grid"]["margin"]
    return ('<div style="position:absolute;left:%dpx;bottom:%dpx;display:flex;align-items:center;'
            'font-family:ui-monospace,Menlo,monospace;font-size:19px;letter-spacing:.16em;color:%s">'
            '<span style="display:block;width:26px;height:6px;background:%s;margin-right:14px"></span>%s</div>'
            % (x, m - 8, p["muted"], p["accent"], esc(c.get("sticker", ""))))


# ---------------- 版式原型：封面 ----------------

def arch_cover_hero(c, t, p, W, H, m):
    tl = t["type"]
    aw = W - 2 * m
    size = fit_title(c.get("title_text", ""), aw, tl["title_max"], tl["title_min"])
    lines = wrap_for(c.get("title_text", ""), size, aw)
    title_h = int(size * title_lh(t)) * len(lines)
    sub_top = m + 132 + title_h + title_pad(t) + 26
    photo_top = min(int(H * 0.70), max(int(H * 0.46), sub_top + 120))
    bar_h = t["rules"]["accent_bar"]
    return [
        '<div class="eyebrow" style="left:%dpx;top:%dpx">%s</div>' % (m, m + 84, esc(c.get("eyebrow", ""))),
        title_block(c, t, p, m, m + 132, aw, size, lines),
        sub_block(c, t, p, m, sub_top, aw - 80),
        photo_div(c, t, 0, photo_top, W, H - photo_top),
        bar(t, 0, photo_top - bar_h, W, bar_h),
        cap_block(c, m, photo_top - 38),
    ]


def arch_cover_photo_top(c, t, p, W, H, m):
    tl = t["type"]
    aw = W - 2 * m
    ph = int(H * 0.54)
    size = min(fit_title(c.get("title_text", ""), aw, tl["title_max"], tl["title_min"]), 104)
    lines = wrap_for(c.get("title_text", ""), size, aw)
    sub_top = ph + 122 + int(size * title_lh(t)) * len(lines) + title_pad(t) + 26
    bar_h = t["rules"]["accent_bar"]
    return [
        photo_div(c, t, 0, 0, W, ph),
        bar(t, 0, ph - bar_h, W, bar_h),
        cap_block(c, m + 120, ph + 24),
        '<div class="eyebrow" style="left:%dpx;top:%dpx">%s</div>' % (m, ph + 76, esc(c.get("eyebrow", ""))),
        title_block(c, t, p, m, ph + 120, aw, size, lines),
        sub_block(c, t, p, m, sub_top, aw - 80),
    ]


def arch_cover_split_diagonal(c, t, p, W, H, m):
    """图片贴右满高、左缘斜切；标题独占左半幅。斜向边缘制造动势。"""
    tl = t["type"]
    img_left = W - int(W * 0.46)
    tw = img_left - m - 52
    size = fit_title(c.get("title_text", ""), tw, min(tl["title_max"], 132), tl["title_min"])
    lines = wrap_for(c.get("title_text", ""), size, tw)
    title_y = int(H * 0.30)
    title_h = int(size * title_lh(t)) * len(lines)
    sub_top = title_y + title_h + title_pad(t) + 30
    clip = "polygon(16% 0, 100% 0, 100% 100%, 0 100%)"
    bar_h = t["rules"]["accent_bar"]
    return [
        '<div class="eyebrow" style="left:%dpx;top:%dpx">%s</div>' % (m, title_y - 74, esc(c.get("eyebrow", ""))),
        title_block(c, t, p, m, title_y, tw, size, lines),
        '<div class="rule" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx"></div>'
        % (m, sub_top - 6, 72, bar_h),
        sub_block(c, t, p, m, sub_top + 30, tw),
        '<div style="position:absolute;left:%dpx;top:0;width:%dpx;height:%dpx;clip-path:%s;overflow:hidden">%s</div>'
        % (img_left, W - img_left, H, clip, img_tag(c, t, H, W - img_left)),
        '<div class="rule" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx"></div>'
        % (img_left - 30, int(H * 0.24), 4, int(H * 0.30)),
        cap_block(c, m, H - m - 96, align="left"),
    ]


def arch_cover_mosaic(c, t, p, W, H, m):
    """一大一小两扇图窗错位，色块填空，标题压下方纸面。"""
    tl = t["type"]
    aw = W - 2 * m
    top0 = m + 132
    big_w, big_h = int(aw * 0.60), int(H * 0.44)
    sm_w, sm_h = int(aw * 0.34), int(H * 0.31)
    sm_x = m + big_w + t["grid"]["gutter"]
    sm_y = top0 + int(H * 0.16)
    size = fit_title(c.get("title_text", ""), int(aw * 0.72), min(tl["title_max"], 118), tl["title_min"])
    lines = wrap_for(c.get("title_text", ""), size, int(aw * 0.72))
    title_y = top0 + big_h + 86
    skin = t.get("skin") or {}
    rot = ""
    if skin.get("duotone"):
        rot = "transform:rotate(-2.2deg);"
    return [
        '<div class="eyebrow" style="left:%dpx;top:%dpx">%s</div>' % (m, top0 - 56, esc(c.get("eyebrow", ""))),
        '<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;height:%dpx;background:%s"></div>'
        % (m - 14, top0 - 14, big_w + 28, big_h + 28, p["accent"]),
        photo_div(c, t, m, top0, big_w, big_h),
        photo_div(c, t, sm_x, sm_y, sm_w, sm_h, pos=30, extra=rot),
        bar(t, sm_x, sm_y - 20, sm_w, 10),
        title_block(c, t, p, m, title_y, int(aw * 0.78), size, lines),
        sub_block(c, t, p, m, title_y + int(size * title_lh(t)) * len(lines) + title_pad(t) + 26, int(aw * 0.62)),
    ]


def arch_cover_stacked_strip(c, t, p, W, H, m):
    """细长图带置顶，标题漂浮在大留白中。节奏最慢的一种。"""
    tl = t["type"]
    aw = W - 2 * m
    strip_y = m + 104
    strip_h = int(H * 0.30)
    size = fit_title(c.get("title_text", ""), aw, tl["title_max"], tl["title_min"])
    lines = wrap_for(c.get("title_text", ""), size, aw)
    title_y = strip_y + strip_h + 176
    title_h = int(size * title_lh(t)) * len(lines)
    return [
        photo_div(c, t, m, strip_y, aw, strip_h),
        bar(t, m, strip_y + strip_h, 96, t["rules"]["accent_bar"]),
        cap_block(c, m, strip_y + strip_h + 30, align="left"),
        '<div class="eyebrow" style="left:%dpx;top:%dpx">%s</div>' % (m, title_y - 58, esc(c.get("eyebrow", ""))),
        title_block(c, t, p, m, title_y, aw, size, lines),
        sub_block(c, t, p, m, title_y + title_h + title_pad(t) + 34, int(aw * 0.74)),
        '<div class="numeral" style="right:%dpx;top:%dpx;font-size:200px">%02d</div>'
        % (m, H - m - 170, c["page_no"]),
    ]


# ---------------- 版式原型：内页 ----------------

def arch_inner_editorial(c, t, p, W, H, m):
    tl = t["type"]
    aw = W - 2 * m
    bar_h = t["rules"]["accent_bar"]
    size = tl["headline"]
    # 巨型描边数字会横穿标题区，按数字实际占宽预留出右侧空白
    nsize = min(tl["numeral"], 300)
    digits = max(2, len(str(c["page_no"])))
    reserve = min(int(aw * 0.46), int(nsize * 0.62 * digits)) + 24
    tw = aw - reserve
    head_lines = wrap_for(c.get("headline", ""), size, tw)
    head_h = int(size * 1.16) * max(1, len(head_lines))
    head_top = m + 190
    rule_top = head_top + head_h + 22
    _, body_n = body_block(c, t, p, m, 0, tw)
    body_h = body_n * int(tl["body"] * tl["body_line_height"])
    photo_top = max(int(H * 0.44), min(int(H * 0.80), rule_top + 40 + body_h + 96))
    return [
        '<div class="numeral" style="right:%dpx;top:%dpx;font-size:%dpx">%02d</div>'
        % (m, m + 24, nsize, c["page_no"]),
        '<div class="eyebrow" style="left:%dpx;top:%dpx">%s</div>' % (m, m + 130, esc(c.get("eyebrow", ""))),
        headline_block(c, t, p, m, head_top, tw, size),
        '<div class="rule" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx"></div>' % (m, rule_top, 96, bar_h),
        body_block(c, t, p, m, rule_top + 34, tw)[0],
        photo_div(c, t, 0, photo_top, W, H - photo_top),
        bar(t, 0, photo_top - bar_h, W, bar_h),
        cap_block(c, m, photo_top - 38),
    ]


def arch_inner_photo_top(c, t, p, W, H, m):
    tl = t["type"]
    aw = W - 2 * m
    bar_h = t["rules"]["accent_bar"]
    ph = int(H * 0.50)
    hs = tl["headline"] - 6
    _, body_n = body_block(c, t, p, m, 0, aw - 40)
    body_h = body_n * int(tl["body"] * tl["body_line_height"])
    block_h = 46 + int(hs * 1.14) + 22 + bar_h + 40 + body_h
    start = ph + max(40, int((H - ph - block_h - m) / 2))
    rule_top = start + 46 + int(hs * 1.14) + 22
    return [
        photo_div(c, t, 0, 0, W, ph),
        bar(t, 0, ph - bar_h, W, bar_h),
        cap_block(c, m + 120, ph + 24),
        headline_block(c, t, p, m, start, aw, hs),
        '<div class="rule" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx"></div>' % (m, rule_top, 96, bar_h),
        body_block(c, t, p, m, rule_top + 40, aw - 40)[0],
        sticker_row(c, t, p, m, 0),
    ]


def arch_inner_quote(c, t, p, W, H, m):
    tl = t["type"]
    aw = W - 2 * m
    bar_h = t["rules"]["accent_bar"]
    q = c.get("quote") or c.get("body_text", "")[:80]
    n = max(8, len(q))
    qs = max(44, min(84, int(aw * 2.15 / n)))
    qlines = wrap_for(q, qs, aw)[:6]
    block_h = len(qlines) * int(qs * 1.45)
    top = max(210, int(150 + (H * 0.70 - 150 - block_h - 70) / 2))
    ph = int(H * 0.70)
    return [
        '<div class="hair" style="height:1px;top:%dpx"></div>' % (m + 78),
        '<div class="rule" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx"></div>' % (m, top - 44, 96, bar_h),
        '<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;font-size:%dpx;line-height:1.45;'
        'font-weight:700;letter-spacing:-.01em">%s</div>'
        % (m, top, aw, qs, "<br>".join(hl(l, c.get("highlight", ""), p["accent"]) for l in qlines)),
        '<div class="eyebrow" style="left:%dpx;top:%dpx">%s</div>'
        % (m, top + block_h + 40, esc(c.get("eyebrow", ""))),
        photo_div(c, t, 0, ph, W, H - ph),
        bar(t, 0, ph - bar_h, W, bar_h),
        cap_block(c, m, ph - 38),
    ]


def arch_inner_side_band(c, t, p, W, H, m):
    """右侧全高窄图＋竖排标签，文字独占左侧。杂志内页的经典分栏。"""
    tl = t["type"]
    band_w = int(W * 0.30)
    band_left = W - band_w
    tw = band_left - m - 56
    size = tl["headline"]
    head_lines = wrap_for(c.get("headline", ""), size, tw)
    head_h = int(size * 1.16) * max(1, len(head_lines))
    _, body_n = body_block(c, t, p, m, 0, tw)
    body_h = body_n * int(tl["body"] * tl["body_line_height"])
    bar_h = t["rules"]["accent_bar"]
    # 正文短时整块居中，避免页面中部塌出一大片空白
    block_h = 52 + head_h + 26 + bar_h + 38 + body_h
    head_top = max(m + 140, int((H - block_h) / 2) - 30)
    rule_top = head_top + head_h + 26
    body_top = rule_top + 38
    return [
        photo_div(c, t, band_left, 0, band_w, H),
        '<div style="position:absolute;left:%dpx;top:%dpx;writing-mode:vertical-rl;'
        'font-family:ui-monospace,Menlo,monospace;font-size:17px;letter-spacing:.34em;color:%s">%s</div>'
        % (band_left - 44, m + 6, p["muted"], esc(c.get("caption", ""))),
        '<div class="eyebrow" style="left:%dpx;top:%dpx">%s</div>' % (m, head_top - 52, esc(c.get("eyebrow", ""))),
        headline_block(c, t, p, m, head_top, tw, size),
        '<div class="rule" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx"></div>' % (m, rule_top, 96, bar_h),
        body_block(c, t, p, m, body_top, tw)[0],
        sticker_row(c, t, p, m, 0),
    ]


def arch_inner_mosaic(c, t, p, W, H, m):
    """两扇错位图窗＋色块填空，文字压在下缘。版面最碎的一种。"""
    tl = t["type"]
    aw = W - 2 * m
    top0 = m + 186
    big_w, big_h = int(aw * 0.58), int(H * 0.38)
    sm_w, sm_h = int(aw * 0.36), int(H * 0.26)
    sm_x = m + big_w + t["grid"]["gutter"]
    sm_y = top0 + int(big_h * 0.42)
    size = tl["headline"] - 4
    head_top = top0 + big_h + 96
    return [
        '<div class="eyebrow" style="left:%dpx;top:%dpx">%s</div>' % (m, top0 - 54, esc(c.get("eyebrow", ""))),
        '<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;height:%dpx;background:%s;opacity:.16"></div>'
        % (m + big_w + 12, sm_y - 24, sm_w - 24, sm_h + 24, p["accent"]),
        photo_div(c, t, m, top0, big_w, big_h),
        photo_div(c, t, sm_x, sm_y, sm_w, sm_h, pos=34),
        '<div class="numeral" style="right:%dpx;top:%dpx;font-size:%dpx">%02d</div>'
        % (m, top0 - 20, tl["numeral"], c["page_no"]),
        headline_block(c, t, p, m, head_top, aw - 80, size),
        body_block(c, t, p, m, head_top + int(size * 1.16) + 40, aw - 140)[0],
        sticker_row(c, t, p, m, 0),
    ]


def arch_inner_stacked_strip(c, t, p, W, H, m):
    """顶部细图带、中部大留白，只留一句标题。克制到极简。"""
    tl = t["type"]
    aw = W - 2 * m
    strip_y = m + 96
    strip_h = int(H * 0.17)
    head_y = int(H * 0.50)
    size = tl["headline"] + 4
    body_y = int(H * 0.70)
    return [
        photo_div(c, t, m, strip_y, aw, strip_h),
        '<div class="rule" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx"></div>'
        % (m, strip_y + strip_h + 26, 72, t["rules"]["accent_bar"]),
        '<div class="eyebrow" style="left:%dpx;top:%dpx">%s</div>' % (m, strip_y + strip_h + 54, esc(c.get("eyebrow", ""))),
        headline_block(c, t, p, m, head_y, int(aw * 0.86), size, tracking=".02em"),
        body_block(c, t, p, m, body_y, int(aw * 0.74))[0],
        '<div class="numeral" style="right:%dpx;bottom:%dpx;font-size:150px">%02d</div>'
        % (m, m - 30, c["page_no"]),
        cap_block(c, m, H - m - 26, align="left"),
    ]


# 每个原型实际留给图片的窗口比例。生图必须按这个比例出，否则 3:4 竖图塞进
# 横向窗口会被 cover 裁掉一半——测试里漏斗的下半截就是这么没的。
ARCH_WINDOW = {
    "cover-hero-bleed": ("3:2", "横向", "主体居中，上下各留 15% 可裁余量"),
    "cover-photo-top": ("3:2", "横向", "主体居中偏上，下缘留可裁余量"),
    "cover-split-diagonal": ("1:3", "竖向长条", "主体必须竖向居中，左右各留 35% 可裁余量"),
    "cover-mosaic": ("1:1", "方形", "主体居中，四边留余量（会裁成一大一小两窗）"),
    "cover-stacked-strip": ("2:1", "横向长条", "主体水平居中，上下留大余量（只取中间一条）"),
    "inner-editorial": ("2:1", "横向", "主体居中，上下留余量"),
    "inner-photo-top": ("3:2", "横向", "主体居中，构图紧凑"),
    "inner-quote-band": ("5:2", "横向长条", "主体水平居中，上下留大余量（只取底部一条）"),
    "inner-side-band": ("1:4", "竖向长条", "主体竖向居中，左右留大余量（取右侧竖条）"),
    "inner-mosaic": ("1:1", "方形", "主体居中，四边留足余量"),
    "inner-stacked-strip": ("4:1", "横向细条", "主体水平居中，上下留极大余量（只取顶部一条）"),
}


ARCH = {
    "cover-hero-bleed": arch_cover_hero,
    "cover-photo-top": arch_cover_photo_top,
    "cover-split-diagonal": arch_cover_split_diagonal,
    "cover-mosaic": arch_cover_mosaic,
    "cover-stacked-strip": arch_cover_stacked_strip,
    "inner-editorial": arch_inner_editorial,
    "inner-photo-top": arch_inner_photo_top,
    "inner-quote-band": arch_inner_quote,
    "inner-side-band": arch_inner_side_band,
    "inner-mosaic": arch_inner_mosaic,
    "inner-stacked-strip": arch_inner_stacked_strip,
}


def page_html(ctx):
    t = ctx["tokens"]
    p = t["palette"]
    W, H = t["canvas"]["width"], t["canvas"]["height"]
    m = t["grid"]["margin"]
    v = ctx["variant"]
    fn = ARCH.get(v)
    if fn is None:
        fn = arch_cover_hero if v.startswith("cover") else arch_inner_editorial
    parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>',
             base_css(t, W, H), "</style></head><body>",
             '<div class="page">']
    parts += meta_row(ctx, t, W, m)
    parts += fn(ctx, t, p, W, H, m)
    parts.append('<div class="grain"></div></div></body></html>')
    return "".join(parts)


# ---------------- 分配与上下文 ----------------

def assign_variants(note_idx, pages_n, phil):
    lay = (phil.get("layout") or {})
    covers = lay.get("cover") or ["cover-hero-bleed", "cover-photo-top"]
    inners = lay.get("inner") or ["inner-editorial", "inner-quote-band", "inner-photo-top"]
    plan = [covers[(note_idx - 1) % len(covers)]]
    for i in range(2, pages_n + 1):
        plan.append(inners[((note_idx - 1) + (i - 2)) % len(inners)])
    return plan


def build_note_pages(note_idx, note, spec, copy_obj, phil, note_dir, cfg):
    total = spec["image_count"].get("chosen") or 6
    page_specs = copy_obj.get("pages") or []
    plan = assign_variants(note_idx, total, phil)
    brand = cfg.get("brand", {})
    cap_prefix = copy_obj.get("caption_prefix") or brand.get("caption_prefix", "YOUR BRAND")
    pages = []
    for p in range(1, total + 1):
        src = os.path.join(note_dir, "images", "page-%02d.png" % p)
        if not os.path.exists(src):
            continue
        ctx = {"tokens": phil, "page_no": p, "total": total,
               "img_data": img_b64(src), "img_path": src,
               "variant": plan[p - 1],
               "caption": "%s · %02d" % (cap_prefix, p),
               "sticker": copy_obj.get("sticker", ""),
               "meta_left": copy_obj.get("meta_left") or brand.get("meta_left", "YOUR BRAND"),
               "title_text": copy_obj.get("title", ""),
               "sub": copy_obj.get("cover_line", ""),
               "eyebrow": copy_obj.get("eyebrow", ""),
               "highlight": copy_obj.get("highlight", "")}
        if p == 1:
            ctx["eyebrow"] = copy_obj.get("eyebrow", "")
        else:
            ps = page_specs[p - 2] if p - 2 < len(page_specs) else {}
            ctx.update({"headline": ps.get("headline", ""),
                        "body_text": ps.get("body", ""),
                        "quote": ps.get("quote", ""),
                        "highlight": ps.get("highlight") or copy_obj.get("highlight", ""),
                        "eyebrow": ps.get("eyebrow") or ctx["eyebrow"]})
        pages.append((ctx["variant"], ctx))
    return pages


# ---------------- 浏览器渲染 ----------------

def render_with_browser(jobs):
    payload = json.dumps(jobs, ensure_ascii=False)
    js = """
const task = await taskSpace("xh-canvas-render");
const page = task.page("p1");
await page.cdp("Emulation.setDeviceMetricsOverride",
  { width: 1080, height: 1440, deviceScaleFactor: 1, mobile: false });
const jobs = %s;
for (const j of jobs) {
  await page.goto("file://" + j.html, { timeout: 20000 });
  await page.waitForTimeout(350);
  await page.screenshot({ path: j.png });
}
await task.finish({ keep: [] });
console.log("rendered " + jobs.length);
""" % payload
    proc = subprocess.run(["ego-browser", "nodejs"], input=js, text=True,
                          capture_output=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip()[:400])
    return proc.stdout.strip()


# ---------------- 反抄袭与报告 ----------------

def dhash(path, size=9):
    im = Image.open(path).convert("L").resize((size, size), Image.LANCZOS)
    px = list(im.getdata())
    bits, idx = 0, 0
    for r in range(size - 1):
        for c in range(size - 1):
            if px[r * size + c] < px[r * size + c + 1]:
                bits |= (1 << idx)
            idx += 1
    return bits


def hamming(a, b):
    return bin(a ^ b).count("1")


def image_similarity(page_path, ref_paths):
    if not ref_paths:
        return None, None
    h = dhash(page_path)
    best, best_ref = 999, None
    for r in ref_paths:
        try:
            d = hamming(h, dhash(r))
        except Exception:
            continue
        if d < best:
            best, best_ref = d, r
    return best, best_ref


def write_design_report(run_root, meta, spec, cfg, manifests, refs_by_note, sim_rows):
    industry = cfg.get("industry", {})
    aud = cfg["design"]["audience"]
    brief = common.read_text(os.path.join(run_root, "data", "audience-brief.md"), "")
    lines = ["# design-report.md — 设计执行说明", ""]

    lines += ["## 1. 行业与受众分析", "",
              "- 行业：%s（基调：%s）" % (industry.get("name", "-"), industry.get("sub_tone", "-")),
              "- 关键词：%s" % "、".join(industry.get("keywords", [])),
              "- 目标人群：%s（%s 岁）" % (aud["name"], aud["age"]),
              "- 人群特征：%s" % "、".join(aud["traits"]),
              "- 设计含义：%s" % aud["implication"], ""]
    if brief.strip():
        lines += ["> 补充的受众简报（data/audience-brief.md）：", ""]
        lines += ["> " + l for l in brief.strip().split("\n")[:12]] + [""]

    used = []
    for mf in manifests:
        pid = mf.get("philosophy")
        if pid and pid not in [u[0] for u in used]:
            used.append((pid, mf.get("philosophy_zh", ""), mf.get("philosophy_claim", "")))
    lines += ["## 2. 本批采用的设计哲学", "",
              "| 哲学 | 中文名 | 主张 |", "|---|---|---|"]
    for pid, zh, claim in used:
        lines.append("| `%s` | %s | %s |" % (pid, zh, claim))
    lines.append("")

    lines += ["## 3. 参考来源（风格借鉴，不复制画面）", "",
              "| 篇 | 哲学 | 来源渠道 | 素材标题 | 参考图 | 说明 |", "|---|---|---|---|---|---|"]
    for idx, note in enumerate(meta["notes"], 1):
        refs = refs_by_note.get(idx, [])
        local = "`%s`" % os.path.relpath(refs[0], run_root) if refs else "—"
        lines.append("| %d | %s | %s | %s | %s | %s |"
                     % (idx, manifests[idx - 1].get("philosophy", "-"), note.get("channel"),
                        (note["title"] or "")[:22], local,
                        "有参考图，仅取构图与色调" if refs else "无参考图，自主设计"))
    lines.append("")

    lines += ["## 4. 版式变化（每页不同）", "",
              "| 篇 | 页 | 原型 | 版式 | 变化点 |", "|---|---|---|---|---|"]
    for mf in manifests:
        for pg in mf["pages"]:
            lines.append("| %d | %02d | `%s` | %s | %s |"
                         % (mf["index"], pg["page"], pg["variant"], pg.get("layout", "-"),
                            pg.get("change", "-")))
    lines.append("")

    # 视觉指纹：相邻篇的颜色分布差异，用来验证「不模式化」
    lines += ["## 5. 相邻篇视觉差异", "",
              "同一配色体系连发会显模板感，这里给相邻两篇封面的平均色距（越大越不像同一套模板）。", "",
              "| 相邻 | 色距 | 判定 |", "|---|---|---|"]
    for a, b in zip(manifests, manifests[1:]):
        try:
            d = _palette_dist(a["pages"][0]["file"], b["pages"][0]["file"], run_root)
            lines.append("| %d→%d | %.1f | %s |" % (a["index"], b["index"], d,
                                                   "过近⚠️" if d < 12 else "通过"))
        except Exception:
            lines.append("| %d→%d | — | 无法读取 |" % (a["index"], b["index"]))
    lines.append("")

    th = cfg["design"].get("anti_copy", {}).get("dhash_similarity_max", 12)
    lines += ["## 6. 反抄袭核验", "",
              "- 文案：与源素材连续 5–8 字重合率见 `data/textcheck.json`（阈值 15%）",
              "- 图像：生成页与参考图 dHash 汉明距离（< %d 视为过近，需重绘）" % th, "",
              "| 篇 | 页 | 最小距离 | 最相近参考 | 判定 |", "|---|---|---|---|---|"]
    for row in sim_rows:
        if row["dist"] is None:
            verdict = "无参考图（自主设计）"
        else:
            verdict = "过近⚠️" if row["dist"] < th else "通过"
        lines.append("| %d | %02d | %s | %s | %s |"
                     % (row["note"], row["page"],
                        row["dist"] if row["dist"] is not None else "—",
                        os.path.basename(row["ref"]) if row["ref"] else "—", verdict))
    lines.append("")
    common.write_text(os.path.join(run_root, "data", "design-report.md"), "\n".join(lines))


def _palette_dist(fa, fb, run_root):
    """两张图缩到 32×32 比平均色，返回 0–255 尺度的距离。"""
    pa = os.path.join(run_root, fa)
    pb = os.path.join(run_root, fb)
    ca = Image.open(pa).convert("RGB").resize((32, 32), Image.LANCZOS).resize((1, 1), Image.LANCZOS)
    cb = Image.open(pb).convert("RGB").resize((32, 32), Image.LANCZOS).resize((1, 1), Image.LANCZOS)
    a, b = ca.getpixel((0, 0)), cb.getpixel((0, 0))
    return (sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5)


def collect_refs(meta, run_root):
    refs = {}
    for idx, note in enumerate(meta["notes"], 1):
        p = os.path.join(run_root, "data", "covers", "%s.img" % note["id"])
        refs[idx] = [p] if os.path.exists(p) else []
    return refs


# ---------------- 主流程 ----------------

def run(run_root, log=None):
    cfg, phils, index = resolve_philosophies()
    meta = common.load_run(run_root)
    spec = common.jload(os.path.join(run_root, "data", "spec.json"))
    if spec is None:
        common.die("缺少 spec.json，请先执行 spec 阶段")
    logo_img = Image.open(spec["logo"]["path"]).convert("RGBA")
    busy_threshold = cfg["defaults"]["logo_busy_edge_threshold"]
    refs_by_note = collect_refs(meta, run_root)

    n = len(meta["notes"])
    plan_ids = philosophy.plan(n, phils, index)
    common.jdump(os.path.join(run_root, "data", "philosophy-plan.json"),
                 {"plan": [{"index": i + 1, "philosophy": pid} for i, pid in enumerate(plan_ids)],
                  "pool": [p["id"] for p in phils], "stride": index.get("stride")})
    print("  " + philosophy.summary(phils, index, n))

    manifests, sim_rows = [], []
    for idx, note in enumerate(meta["notes"], start=1):
        nd = common.note_dir(run_root, idx)
        copy_obj = common.jload(os.path.join(nd, "copy.json"))
        if copy_obj is None:
            raise RuntimeError("第%d篇缺少 copy.json（阶段3 未完成）" % idx)
        phil = philosophy.assign(idx, phils, index)
        out_dir = os.path.join(nd, "composed")
        html_dir = os.path.join(nd, "canvas")
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(html_dir, exist_ok=True)

        pages = build_note_pages(idx, note, spec, copy_obj, phil, nd, cfg)
        if not pages:
            raise RuntimeError("第%d篇没有可用配图（notes/%02d/images 为空）" % (idx, idx))
        jobs = []
        for p, (variant, ctx) in enumerate(pages, start=1):
            html_path = os.path.abspath(os.path.join(html_dir, "page-%02d.html" % p))
            png_path = os.path.abspath(os.path.join(out_dir, "page-%02d.png" % p))
            common.write_text(html_path, page_html(ctx))
            jobs.append({"html": html_path, "png": png_path})
        render_with_browser(jobs)

        manifest = {"index": idx, "note_id": note["id"],
                    "size": [phil["canvas"]["width"], phil["canvas"]["height"]],
                    "engine": "canvas-philosophy",
                    "philosophy": phil["id"], "philosophy_zh": phil.get("name_zh", ""),
                    "philosophy_claim": phil.get("claim", ""),
                    "philosophy_palette": phil["palette"],
                    "design_theme": phil.get("name", ""),
                    "pages": [], "missing_pages": [], "placeholder": False}
        for p, (variant, ctx) in enumerate(pages, start=1):
            png_path = os.path.join(out_dir, "page-%02d.png" % p)
            with Image.open(png_path) as im:
                canvas = im.convert("RGBA")
                if canvas.size != (phil["canvas"]["width"], phil["canvas"]["height"]):
                    canvas = canvas.resize((phil["canvas"]["width"], phil["canvas"]["height"]),
                                           Image.LANCZOS)
            # LOGO 固定在右下角：跨篇统一品牌位，也避让内页左下角的刊头字
            logo_spec = json.loads(json.dumps(spec))
            logo_spec["logo"]["position"] = "bottom-right"
            logo_spec["logo"]["fallback_positions"] = []
            canvas, logo_info = compose_images.place_logo(canvas, logo_img, logo_spec,
                                                          busy_threshold, 0)
            canvas.convert("RGB").save(png_path, "PNG")

            dist, ref = image_similarity(png_path, refs_by_note.get(idx, []))
            manifest["pages"].append({"page": p, "variant": variant,
                                      "layout": VARIANT_LABEL.get(variant, variant),
                                      "change": VARIANT_CHANGE.get(variant, ""),
                                      "philosophy": phil["id"],
                                      "file": os.path.relpath(png_path, run_root),
                                      "band_h": 0, "band_capped": False,
                                      "ref_dist": dist, "logo": logo_info})
            sim_rows.append({"note": idx, "page": p, "dist": dist, "ref": ref})
            th = cfg["design"].get("anti_copy", {}).get("dhash_similarity_max", 12)
            if dist is not None and dist < th:
                common.log_event(run_root, "S4",
                                 "第%d篇第%d页与参考图过于相似（dHash=%d），建议重绘" % (idx, p, dist),
                                 "warn")
        common.jdump(os.path.join(nd, "compose-manifest.json"), manifest)
        manifests.append(manifest)
        refs = refs_by_note.get(idx, [])
        print("  #%d 哲学：%s｜参考：%s｜版式：%s"
              % (idx, phil.get("name_zh") or phil["name"],
                 ("抓取参考（%s）" % os.path.basename(refs[0])) if refs else "自主设计",
                 "、".join("%02d:%s" % (pg["page"], pg["variant"]) for pg in manifest["pages"])))
        if log:
            log("S4", "canvas 渲染第%d篇 %d 页，哲学=%s，版式：%s"
                % (idx, len(pages), phil["id"],
                   "、".join(VARIANT_LABEL.get(v, v) for v, _ in pages)))

    write_design_report(run_root, meta, spec, cfg, manifests, refs_by_note, sim_rows)
    return manifests


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    print("rendered notes:", len(run(a.run)))

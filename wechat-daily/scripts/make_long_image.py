#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公众号长图生成器 v3（无模板时的自创版式）
- 宽度固定 1000PX，高度按内容自动计算，PNG
- 输入：文章 Markdown（# 标题 / ## 小标题 / 段落 / **加粗** / 整段加粗=重点卡片 / > 来源备注）
- 版式：公众号阅读习惯——字号分级、左对齐、留白充足
- 设计感 v3（图文并茂）：
  * 头部横幅插画 --art：置于头部米白区下方，通栏圆角卡片（与文章内容呼应的 AI 插画）
  * 中段插图卡 --insert：可传多张，均匀插入各章节之间（圆角卡片 + 细边框 + 上下留白）
  * 章节序号徽章（01/02… 主色/辅色交替）+ 小标题主题线性图标 + 小标题点线
  * 整段加粗自动渲染为重点句卡片（浅色底 + 主题色左条 + 圆角）
  * 头部品牌双色带 + 装饰圆点 + 标题双色下划线 + 底部备注区
- 文字零特效：单层实色渲染，无阴影无重影

用法：
  python3 make_long_image.py --md 文章.md --out 长图.png \
      [--accent orange|green] [--art 头部插画.png] [--insert 图1.png,图2.png] \
      [--keep-emoji]

  --keep-emoji：保留字体渲染不出的字符（emoji、藏文、扩展汉字等）。
  **默认会剥离**并打 WARN 逐字列出——本脚本只用 Noto Sans SC 一个字体，
  没有字体回退，那些字符会被画成带叉的方框（.notdef）。
  HTML 版不受影响，那边保留原样。
"""
import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 复用封面脚本里的线性图标库（doc/check/cal/search/cap/flag）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_cover import ICONS  # noqa: E402
from brand import resolve_accent, accent_pair, hex_rgb  # noqa: E402
from glyph import clean_for_png  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FONT_PATH = ASSETS / "fonts" / "NotoSansSC-VF.ttf"

# 主色/辅色由 WX_ACCENT / WX_ACCENT_ALT 注入；变量名沿用历史，实际值可自定义
PRIMARY = resolve_accent("orange", as_rgb=True)   # 主色
SECONDARY = resolve_accent("green", as_rgb=True)     # 辅色
WHITE = (255, 255, 255)
DARK = (35, 24, 21)         # #231815
GRAY = (107, 114, 128)
CREAM = (248, 245, 240)
LIGHT = (245, 245, 245)

W = 1000
MARGIN = 72
CONTENT_W = W - MARGIN * 2

# 字号分级
TITLE_SIZE = 54
SECTION_SIZE = 36
CARD_SIZE = 31        # 重点句卡片
BODY_SIZE = 29
FOOTER_SIZE = 22

LINE_SP = 1.7
PARA_SP = 26
SECTION_SP = 44
SECTION_AFTER = 24
FOOTER_H = 130

BANNER_H = 320        # 头部横幅插画高度
IMG_MAX_H = 440       # 中段插图卡最大高度
IMG_SP = 36           # 插图卡上下留白


def load_font(size, weight=400):
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


def tint(color, ratio=0.88):
    return tuple(int(c + (255 - c) * ratio) for c in color)


def _is_table_row(line):
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and "|" in s[1:]


def _is_table_sep(line):
    s = line.strip().strip("|")
    return bool(re.fullmatch(r"[\s:\-|]+", s)) and "-" in s


def _split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_md(path: Path, keep_unsafe: bool = False):
    text = path.read_text(encoding="utf-8")
    # keep 模式也要过一遍：静默印叉框是事故，静默「保留了会印成叉框的字」同样是
    text, _ = clean_for_png(text, where="长图", keep=keep_unsafe)
    lines = text.splitlines()
    blocks = []
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i].rstrip()
        if not raw.strip() or raw.strip() == "---":
            i += 1
            continue
        if raw.startswith("# "):
            blocks.append(("title", raw[2:].strip()))
            i += 1
        elif raw.startswith("## "):
            blocks.append(("section", raw[3:].strip()))
            i += 1
        elif raw.startswith("> "):
            blocks.append(("footer", raw[2:].strip()))
            i += 1
        elif re.fullmatch(r"\*\*.+\*\*", raw.strip()):
            blocks.append(("card", raw.strip()[2:-2]))
            i += 1
        elif _is_table_row(raw) and i + 1 < n and _is_table_sep(lines[i + 1]):
            rows = [_split_row(raw)]
            i += 2
            while i < n and _is_table_row(lines[i].rstrip()):
                rows.append(_split_row(lines[i].rstrip()))
                i += 1
            blocks.append(("table", rows))
        else:
            blocks.append(("para", raw.strip()))
            i += 1
    return blocks


def split_runs(text):
    runs = []
    for i, seg in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if seg:
            runs.append((seg, i % 2 == 1))
    return runs or [(text, False)]


def wrap_runs(d, runs, font_bold, font_reg, max_w):
    lines, cur_runs, cur_w = [], [], 0
    for text, bold in runs:
        font = font_bold if bold else font_reg
        for ch in text:
            cw = d.textbbox((0, 0), ch, font=font)[2]
            if cur_w + cw > max_w and cur_runs:
                lines.append((cur_runs, cur_w))
                cur_runs, cur_w = [], 0
            cur_runs.append((ch, bold))
            cur_w += cw
    if cur_runs:
        lines.append((cur_runs, cur_w))
    return lines


def draw_runs(d, x, y, runs, font_bold, font_reg, fill_bold, fill_reg):
    for ch, bold in runs:
        font = font_bold if bold else font_reg
        d.text((x, y), ch, font=font, fill=fill_bold if bold else fill_reg)
        x += d.textbbox((0, 0), ch, font=font)[2]


def load_cover_img(path, box_w, box_h):
    """等比裁切到指定盒子（cover），返回 PIL 对象。"""
    im = Image.open(path).convert("RGB")
    scale = max(box_w / im.width, box_h / im.height)
    nw, nh = int(im.width * scale + 0.5), int(im.height * scale + 0.5)
    im = im.resize((nw, nh), Image.LANCZOS)
    x = (nw - box_w) // 2
    y = (nh - box_h) // 2
    return im.crop((x, y, x + box_w, y + box_h))


def paste_rounded(img, im, x, y, radius=18, border=(225, 220, 213)):
    """把 im 以圆角卡片形式贴到 img 上（细边框）。"""
    mask = Image.new("L", im.size, 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=radius, fill=255)
    img.paste(im, (x, y), mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x, y, x + im.width - 1, y + im.height - 1],
                        radius=radius, outline=border, width=2)


def table_layout(rows, w, name=None):
    """计算表格块尺寸（与 HTML 路线视觉一致：圆角卡片+品牌色描边、顶部表名胶囊、表头品牌色带、首列强调、数据区纵向浅渐层）。"""
    ncols = max(len(r) for r in rows)
    rows_p = [r + [""] * (ncols - len(r)) for r in rows]
    pad = 16
    fs_head = 28
    fs_body = 24
    lh_head = int(fs_head * 1.35)
    lh_body = int(fs_body * 1.5)
    border = 3
    radius = 14
    title_h = 56 if name else 0          # 顶部表名胶囊占用高度（含上下留白）
    col_w = (w - (ncols + 1) * border) / ncols
    text_w = col_w - pad * 2
    f_head = load_font(fs_head, 700)
    f_body = load_font(fs_body, 400)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    head_lines = [wrap_runs(probe, [(c, True)], f_head, f_head, int(text_w)) for c in rows_p[0]]
    body_lines = [[wrap_runs(probe, [(c, False)], f_body, f_body, int(text_w)) for c in r] for r in rows_p[1:]]
    header_h = max(len(l) for l in head_lines) * lh_head + pad * 2
    body_hs = [max(len(l) for l in r) * lh_body + pad * 2 for r in body_lines]
    total = title_h + header_h + sum(body_hs)
    return dict(ncols=ncols, col_w=col_w, pad=pad, lh=lh_body,
                border=border, header_h=header_h, body_hs=body_hs,
                head_lines=head_lines, body_lines=body_lines, total=total,
                fs_head=fs_head, fs_body=fs_body, lh_head=lh_head, radius=radius,
                title_h=title_h, has_title=bool(name))


_SEC_NUM = re.compile(r"^\s*(?:[（(][一二三四五六七八九十]+[）)]|[一二三四五六七八九十]+[、.]|\d+[、.．])\s*")


def _strip_sec_num(text: str) -> str:
    """去掉「一、」「1.」「（二）」这类章序号，胶囊里只留标题本体。"""
    return _SEC_NUM.sub("", text or "").strip()


def draw_table(d, x, y, w, rows, accent, name=None):
    if name:
        name = _strip_sec_num(name) or None
    L = table_layout(rows, w, name)
    ncols, col_w, pad, lh = L["ncols"], L["col_w"], L["pad"], L["lh"]
    border, radius = L["border"], L["radius"]
    fs_head, fs_body, lh_head = L["fs_head"], L["fs_body"], L["lh_head"]
    f_head = load_font(fs_head, 700)
    f_body = load_font(fs_body, 400)
    f_body_b = load_font(fs_body, 700)   # 首列强调
    f_pill = load_font(22, 700)
    a = accent
    card_h = L["total"]
    # 圆角卡片底 + 品牌色描边
    d.rounded_rectangle([x, y, x + w, y + card_h], radius=radius,
                        fill=WHITE, outline=a, width=3)
    yt = y
    # 顶部表名胶囊（居中），仅当 name 存在
    if L["has_title"]:
        pill_h = 30
        pw = d.textbbox((0, 0), name, font=f_pill)[2] + 36
        px0 = x + (w - pw) // 2
        py0 = y + (L["title_h"] - pill_h) // 2
        d.rounded_rectangle([px0, py0, px0 + pw, py0 + pill_h], radius=pill_h // 2, fill=a)
        tw = d.textbbox((0, 0), name, font=f_pill)[2]
        d.text((px0 + (pw - tw) // 2, py0 + (pill_h - 22) // 2 - 1), name,
               font=f_pill, fill=WHITE)
        yt += L["title_h"]
    # 表头品牌色带（顶部即卡片顶时需上圆角；有胶囊时内部为方角）
    hb_top = yt
    hb_y1 = yt + L["header_h"]
    d.rounded_rectangle([x + border, hb_top + border, x + w - border, hb_y1],
                        radius=radius if not L["has_title"] else 0, fill=a)
    if not L["has_title"]:
        d.rectangle([x + border, hb_y1 - radius, x + w - border, hb_y1], fill=a)
    # 表头文字
    for ci in range(ncols):
        cx = x + border + ci * (col_w + border)
        ty = hb_top + border + pad
        for ln in L["head_lines"][ci]:
            draw_runs(d, cx + pad, ty, ln[0], f_head, f_head, WHITE, WHITE)
            ty += lh_head
    # 数据区纵向浅渐层（白 → 极浅米），替代硬斑马纹
    body_top = hb_y1
    body_bot = y + card_h
    top_c, bot_c = (255, 255, 255), (247, 244, 239)
    span = max(1, body_bot - body_top)
    for yy in range(body_top, body_bot):
        t = (yy - body_top) / span
        col = tuple(int(top_c[k] + (bot_c[k] - top_c[k]) * t) for k in range(3))
        d.line([x + border, yy, x + w - border, yy], fill=col)
    # 数据行（渐层作底，直接绘文字）
    cy = body_top
    for ri, r in enumerate(rows[1:]):
        h = L["body_hs"][ri]
        for ci in range(ncols):
            cx = x + border + ci * (col_w + border)
            ty = cy + pad
            for ln in L["body_lines"][ri][ci]:
                if ci == 0:
                    # 首列：加粗 + 品牌色，作"标签列"
                    draw_runs(d, cx + pad, ty, ln[0], f_body_b, f_body_b, a, a)
                else:
                    draw_runs(d, cx + pad, ty, ln[0], f_body, f_body, DARK, DARK)
                ty += lh
        cy += h
    # 网格线（仅数据区竖向，避免压到表头色带）
    for ci in range(ncols + 1):
        gx = x + border + ci * (col_w + border)
        d.line([gx, body_top, gx, body_bot], fill=(225, 220, 213), width=1)
    # 表头下分隔（品牌色加粗）
    d.line([x, hb_y1, x + w, hb_y1], fill=a, width=3)
    # 行分隔
    hy = body_top
    for hs in L["body_hs"]:
        hy += hs
        d.line([x, hy, x + w, hy], fill=(225, 220, 213), width=1)
    return card_h


def build_blocks_with_images(blocks, inserts):
    """把插图卡均匀插入各章节之间。inserts 为图片路径列表。"""
    if not inserts:
        return blocks
    sec_positions = [i for i, (k, _) in enumerate(blocks) if k == "section"]
    if not sec_positions:
        return blocks
    n_slots = len(sec_positions)
    result = list(blocks)
    # 每张图放在第 round(k*(n+1)/(m+1)) 个章节前
    placed = []
    for k in range(len(inserts)):
        slot = sec_positions[min(n_slots - 1,
                                 round((k + 1) * n_slots / (len(inserts) + 1)) - 1)]
        placed.append((slot, ("imgcard", inserts[k])))
    for slot, blk in sorted(placed, key=lambda t: -t[0]):
        result.insert(slot, blk)
    return result


def measure(d, blocks, accent):
    f_title = load_font(TITLE_SIZE, 900)
    f_sec = load_font(SECTION_SIZE, 800)
    f_card_b = load_font(CARD_SIZE, 700)
    f_card_r = load_font(CARD_SIZE, 400)
    f_bold = load_font(BODY_SIZE, 700)
    f_reg = load_font(BODY_SIZE, 400)
    heights = []
    last_sec = None
    for kind, content in blocks:
        if kind == "title":
            n = len(wrap_runs(d, split_runs(content), f_title, f_title, CONTENT_W))
            heights.append(int(TITLE_SIZE * LINE_SP) * n + 8)
        elif kind == "section":
            last_sec = content
            heights.append(SECTION_SP + int(SECTION_SIZE * LINE_SP) + SECTION_AFTER)
        elif kind == "card":
            n = len(wrap_runs(d, [(content, True)], f_card_b, f_card_b, CONTENT_W - 72))
            heights.append(n * int(CARD_SIZE * LINE_SP) + 52)
        elif kind == "imgcard":
            im = Image.open(content)
            iw = CONTENT_W
            ih = min(IMG_MAX_H, int(im.height * iw / im.width))
            heights.append(ih + IMG_SP * 2)
        elif kind == "footer":
            heights.append(0)
        elif kind == "table":
            heights.append(int(table_layout(content, CONTENT_W)["total"]) + PARA_SP)
        else:
            n = len(wrap_runs(d, split_runs(content), f_bold, f_reg, CONTENT_W))
            heights.append(n * int(BODY_SIZE * LINE_SP) + PARA_SP)
    return heights


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--accent", default="orange",
                    help="主色：orange（=WX_ACCENT）/ green（=WX_ACCENT_ALT）/ 任意 #RRGGBB")
    ap.add_argument("--art", default="", help="可选头部横幅插画（通栏圆角卡，置于标题区下方）")
    ap.add_argument("--insert", default="", help="可选中段插图，逗号分隔多张，均匀插入章节间")
    ap.add_argument("--keep-emoji", action="store_true",
                    help="保留字体渲染不出的字符（emoji 等）——默认会剥离，因为 PNG 上它们会印成叉框")
    args = ap.parse_args()

    md_path = Path(args.md)
    if not md_path.exists():
        print(f"ERROR: Markdown 不存在: {md_path}", file=sys.stderr)
        sys.exit(1)

    blocks = parse_md(md_path, keep_unsafe=args.keep_emoji)
    inserts = [p.strip() for p in args.insert.split(",") if p.strip()]
    for p in inserts + ([args.art] if args.art else []):
        if not Path(p).exists():
            print(f"ERROR: 插图不存在: {p}", file=sys.stderr)
            sys.exit(1)
    blocks = build_blocks_with_images(blocks, inserts)

    # 任意十六进制都支持：主色定下来，辅色自动取另一支，保证两色交替
    _a, _b = accent_pair(args.accent)
    accent, second = hex_rgb(_a), hex_rgb(_b)

    has_art = bool(args.art)
    # 头部：色带 + 米白标题区 +（可选）通栏插画
    art_pad = (BANNER_H + 44) if has_art else 0
    header_h = 200 + art_pad

    probe = Image.new("RGB", (W, 100))
    pd = ImageDraw.Draw(probe)
    heights = measure(pd, blocks, accent)
    H = header_h + sum(heights) + FOOTER_H + 48

    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    # ---------- 头部 ----------
    d.rectangle([0, 0, W, 14], fill=accent)
    d.rectangle([0, 14, W, 20], fill=second)
    cream_h = 200 - 30
    d.rectangle([0, 20, W, cream_h], fill=CREAM)
    for i, (dx, dy, r) in enumerate([(860, 46, 9), (895, 74, 13), (842, 92, 6), (918, 40, 7)]):
        d.ellipse([dx - r, dy - r, dx + r, dy + r],
                  fill=accent if i % 2 == 0 else second)

    # 头部横幅插画（通栏圆角卡）
    if has_art:
        banner = load_cover_img(args.art, CONTENT_W, BANNER_H)
        paste_rounded(img, banner, MARGIN, cream_h + 26, radius=20)
        # 插画下小三角装饰
        d.polygon([(W // 2 - 10, cream_h + 26 + BANNER_H + 8),
                   (W // 2 + 10, cream_h + 26 + BANNER_H + 8),
                   (W // 2, cream_h + 26 + BANNER_H + 16)], fill=second)

    # ---------- 内容 ----------
    y = header_h
    f_title = load_font(TITLE_SIZE, 900)
    f_sec = load_font(SECTION_SIZE, 800)
    f_num = load_font(22, 800)
    f_card_b = load_font(CARD_SIZE, 700)
    f_card_r = load_font(CARD_SIZE, 400)
    f_bold = load_font(BODY_SIZE, 700)
    f_reg = load_font(BODY_SIZE, 400)
    f_foot = load_font(FOOTER_SIZE, 400)
    sec_idx = 0
    last_sec = None
    icon_keys = ["doc", "check", "cal", "search", "cap", "flag"]

    for (kind, content), h in zip(blocks, heights):
        if kind == "title":
            lines = wrap_runs(d, split_runs(content), f_title, f_title, CONTENT_W)
            for runs, _ in lines:
                draw_runs(d, MARGIN, y, runs, f_title, f_title, DARK, DARK)
                y += int(TITLE_SIZE * LINE_SP)
            d.rectangle([MARGIN, y - 14, MARGIN + 120, y - 2], fill=accent)
            d.rectangle([MARGIN + 132, y - 11, MARGIN + 180, y - 5], fill=second)
            y += 8
        elif kind == "section":
            y += SECTION_SP
            sec_idx += 1
            last_sec = content
            sec_accent = accent if sec_idx % 2 == 1 else second
            badge = f"{sec_idx:02d}"
            d.rounded_rectangle([MARGIN, y + 2, MARGIN + 44, y + 46], radius=10, fill=sec_accent)
            bw = d.textbbox((0, 0), badge, font=f_num)[2]
            d.text((MARGIN + (44 - bw) // 2, y + 12), badge, font=f_num, fill=WHITE)
            d.text((MARGIN + 60, y), content, font=f_sec, fill=SECONDARY)
            fn = ICONS.get(icon_keys[(sec_idx - 1) % len(icon_keys)])
            if fn:
                fn(d, W - MARGIN - 24, y + 24, 20, sec_accent)
            for dx in range(MARGIN + 60, W - MARGIN - 70, 18):
                d.ellipse([dx, y + 52, dx + 4, y + 56], fill=(210, 205, 198))
            y += int(SECTION_SIZE * LINE_SP) + SECTION_AFTER
        elif kind == "card":
            lines = wrap_runs(d, [(content, True)], f_card_b, f_card_b, CONTENT_W - 72)
            ch_ = len(lines) * int(CARD_SIZE * LINE_SP) + 52
            d.rounded_rectangle([MARGIN, y + 4, W - MARGIN, y + ch_], radius=14,
                                fill=tint(accent, 0.86))
            d.rectangle([MARGIN, y + 16, MARGIN + 8, y + ch_ - 12], fill=accent)
            ty = y + 26
            for runs, _ in lines:
                draw_runs(d, MARGIN + 30, ty, runs, f_card_b, f_card_r, DARK, DARK)
                ty += int(CARD_SIZE * LINE_SP)
            y += ch_ + PARA_SP
        elif kind == "imgcard":
            im = Image.open(content)
            iw = CONTENT_W
            ih = min(IMG_MAX_H, int(im.height * iw / im.width))
            card = load_cover_img(content, iw, ih)
            y += IMG_SP
            paste_rounded(img, card, MARGIN, y, radius=18)
            y += ih + IMG_SP
        elif kind == "footer":
            pass
        elif kind == "table":
            th = draw_table(d, MARGIN, y, CONTENT_W, content, accent)
            y += th + PARA_SP
        else:
            lines = wrap_runs(d, split_runs(content), f_bold, f_reg, CONTENT_W)
            for runs, _ in lines:
                draw_runs(d, MARGIN, y, runs, f_bold, f_reg, DARK, (60, 52, 48))
                y += int(BODY_SIZE * LINE_SP)
            y += PARA_SP

    # ---------- 底部备注区 ----------
    d.rectangle([0, H - FOOTER_H, W, H], fill=LIGHT)
    d.rectangle([0, H - FOOTER_H, W, H - FOOTER_H + 6], fill=second)
    footers = [c for k, c in blocks if k == "footer"]
    fy = H - FOOTER_H + 30
    for fc in footers:
        for runs, _ in wrap_runs(d, [(fc, False)], f_foot, f_foot, CONTENT_W):
            draw_runs(d, MARGIN, fy, runs, f_foot, f_foot, GRAY, GRAY)
            fy += int(FOOTER_SIZE * LINE_SP)
    d.ellipse([MARGIN, H - 34, MARGIN + 10, H - 24], fill=SECONDARY)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    n_img = len(inserts) + (1 if has_art else 0)
    print(f"OK 长图已生成: {out} ({W}x{H}, 自创版式v3, 含 {n_img} 张插画)")


if __name__ == "__main__":
    main()

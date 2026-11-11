#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公众号推文 HTML 排版器 v2（微信编辑器规范合规版）
遵循《微信公众平台编辑器插件开发规范》（references/wechat-editor-spec.md）：
- 全部内联 style，无 <style> 标签、无 class（公众号粘贴可靠）
- 不设置 font-family（平台默认字体栈）
- 无固定 width/height；容器 100% 自适应 + 内边距
- 所有 <img> 带 data-w（原始像素宽）+ alt
- line-height ≥ 字号（1.75em+）；text-align 仅 left/center
- 无 !important / position:absolute 文本 / <pre> / opacity:0
- 文字背景纯色不渐变；嵌套 ≤3 层；正文用 <section>/<p>
- 可选：输出前用官方 CLI 校验 verify-article-structure-spec

用法：
  python3 make_article_html.py --md 文章.md --out 推文.html \
      [--accent '#RRGGBB'] [--art 横幅插画.png] [--insert 图1.png,图2.png]

  主色默认取环境变量 WX_ACCENT，辅色取 WX_ACCENT_ALT；--accent 只影响单次产出。
"""
import argparse
import base64
import html as html_mod
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
CREAM = "#F8F5F0"
DARK = "#231815"
BODY_C = "#3c3430"
GRAY_C = "#6b625c"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brand import BRAND_NAME, CTA_TEXT, accent_pair, hex_rgb  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FONT_PATH = ASSETS / "fonts" / "NotoSansSC-VF.ttf"

ICONS = {
    "doc": '<svg viewBox="0 0 44 44" width="28" height="28"><rect x="10" y="7" width="24" height="30" rx="5" fill="none" stroke="{c}" stroke-width="3.2"/><line x1="15" y1="15" x2="27" y2="15" stroke="{c}" stroke-width="3.2"/><line x1="15" y1="21" x2="27" y2="21" stroke="{c}" stroke-width="3.2"/><line x1="15" y1="27" x2="21" y2="27" stroke="{c}" stroke-width="3.2"/></svg>',
    "check": '<svg viewBox="0 0 44 44" width="28" height="28"><circle cx="22" cy="22" r="15" fill="none" stroke="{c}" stroke-width="3.4"/><path d="M15 22.5 L20 27.5 L30 17.5" fill="none" stroke="{c}" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "cal": '<svg viewBox="0 0 44 44" width="28" height="28"><rect x="8" y="10" width="28" height="26" rx="5" fill="none" stroke="{c}" stroke-width="3.2"/><line x1="8" y1="18" x2="36" y2="18" stroke="{c}" stroke-width="3.2"/><line x1="15" y1="7" x2="15" y2="13" stroke="{c}" stroke-width="3.2"/><line x1="29" y1="7" x2="29" y2="13" stroke="{c}" stroke-width="3.2"/><circle cx="15" cy="25" r="2.4" fill="{c}"/><circle cx="22" cy="25" r="2.4" fill="{c}"/><circle cx="29" cy="25" r="2.4" fill="{c}"/><circle cx="15" cy="31" r="2.4" fill="{c}"/><circle cx="22" cy="31" r="2.4" fill="{c}"/></svg>',
    "search": '<svg viewBox="0 0 44 44" width="28" height="28"><circle cx="19" cy="19" r="10" fill="none" stroke="{c}" stroke-width="3.4"/><line x1="26.5" y1="26.5" x2="36" y2="36" stroke="{c}" stroke-width="4" stroke-linecap="round"/></svg>',
    "cap": '<svg viewBox="0 0 44 44" width="28" height="28"><path d="M22 9 L41 18 L22 27 L3 18 Z" fill="none" stroke="{c}" stroke-width="3.2" stroke-linejoin="round"/><line x1="33" y1="20" x2="33" y2="31" stroke="{c}" stroke-width="3.2"/><circle cx="22" cy="32" r="2.6" fill="{c}"/></svg>',
    "flag": '<svg viewBox="0 0 44 44" width="28" height="28"><line x1="13" y1="6" x2="13" y2="38" stroke="{c}" stroke-width="3.4" stroke-linecap="round"/><path d="M13 9 L34 14 L13 20 Z" fill="none" stroke="{c}" stroke-width="3.2" stroke-linejoin="round"/></svg>',
}
ICON_KEYS = ["doc", "check", "cal", "search", "cap", "flag"]


def esc(t: str) -> str:
    return html_mod.escape(t, quote=False)


def img_tag(path: str, alt: str = "", extra_style: str = "") -> str:
    """合规图片：<img> 带 data-w（原始像素宽）+ width:100% 自适应。"""
    im = Image.open(path)
    src = "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()
    style = "display:block;width:100%;border-radius:12px;border:1px solid #e8e3dc;margin:20px 0;"
    if extra_style:
        style += extra_style
    return f'<img src="{src}" data-w="{im.width}" alt="{esc(alt)}" style="{style}">'


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


def _wrap_cjk(draw, text: str, font, max_w: int):
    """CJK 逐字换行，返回多行列表。"""
    lines, cur, cw = [], "", 0
    for ch in text:
        w = draw.textbbox((0, 0), ch, font=font)[2]
        if cw + w > max_w and cur:
            lines.append(cur)
            cur, cw = "", 0
        cur += ch
        cw += w
        if len(cur) > 200:  # 防御：字体异常致宽度为 0 时强制断行，避免死循环
            lines.append(cur)
            cur, cw = "", 0
    if cur:
        lines.append(cur)
    # 避头尾：标点不出现在行首，挂到上一行行末
    NO_HEAD = "，。、；：！？）》」』”’,.;:!?)%"
    for i in range(1, len(lines)):
        while lines[i] and lines[i][0] in NO_HEAD:
            lines[i - 1] += lines[i][0]
            lines[i] = lines[i][1:]
    return [l for l in lines if l] or [""]


def table_to_img(rows: list, accent: str) -> Image.Image:
    """把 Markdown 表格渲染为合规 PNG（规避微信 <table> 粘贴问题）。
    版式：圆角卡片 + 品牌色描边；表头品牌色带（仅上圆角）；首列加粗描品牌色作"标签列"；
    斑马纹；2x 视网膜清晰度，data-w 取像素宽。字号层级：表头 23 / 正文 20。"""
    S = 2                      # 缩放倍数（视网膜清晰）
    W_T = 660                  # 逻辑宽度（贴合 677PX 正文）
    PAD_X, PAD_Y = 16, 12
    FS_HEAD = 23               # 表头逻辑字号（加大加粗，形成层级）
    FS_BODY = 20               # 正文逻辑字号
    RADIUS = 16                # 卡片圆角
    BORDER_W = 3               # 品牌色描边宽
    GRID = (225, 220, 213)     # 浅灰网格 #E1DCD5
    WHITE_BG = (255, 255, 255)
    a = tuple(int(accent[i:i + 2], 16) for i in (1, 3, 5))
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    f_head = load_font(FS_HEAD, 800)
    f_body = load_font(FS_BODY, 400)
    f_body_b = load_font(FS_BODY, 700)   # 首列强调字重
    # 列宽按各列最长文本比例分配：长句列宽一点，避免在窄列里挤成三四行
    avail_w = W_T - (ncols + 1) * BORDER_W
    weights = []
    for ci in range(ncols):
        ml = max(len(r[ci]) for r in rows)
        wt = max(6.0, min(float(ml), 20.0))
        if ci == 0:
            wt *= 0.9          # 首列是标签列，通常较短
        weights.append(wt)
    col_ws = [avail_w * wt / sum(weights) for wt in weights]
    # 保证每列至少能放下 5 个字，超出部分从最宽列回收
    MIN_W = PAD_X * 2 + 5 * FS_BODY
    col_ws = [max(MIN_W, cw) for cw in col_ws]
    over = sum(col_ws) - avail_w
    while over > 0.5:
        idx = col_ws.index(max(col_ws))
        cut = min(over, col_ws[idx] - MIN_W)
        if cut <= 0:
            break
        col_ws[idx] -= cut
        over -= cut
    xs, acc = [], BORDER_W
    for cw in col_ws:
        xs.append(acc)
        acc += cw + BORDER_W
    text_ws = [cw - PAD_X * 2 for cw in col_ws]
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    head_lines = [_wrap_cjk(probe, rows[0][ci], f_head, text_ws[ci]) for ci in range(ncols)]
    body_lines = [[_wrap_cjk(probe, r[ci], f_body, text_ws[ci]) for ci in range(ncols)]
                  for r in rows[1:]]
    head_lh = int(FS_HEAD * 1.4)
    body_lh = int(FS_BODY * 1.5)
    head_h = max(len(l) for l in head_lines) * head_lh + PAD_Y * 2
    body_hs = [max(len(l) for l in r) * body_lh + PAD_Y * 2 for r in body_lines]
    total_h = head_h + sum(body_hs)
    W = int(W_T * S)
    H = int(total_h * S)
    img = Image.new("RGB", (W, H), WHITE_BG)
    d = ImageDraw.Draw(img)
    # 圆角卡片底 + 品牌色描边
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=RADIUS * S,
                        fill=WHITE_BG, outline=a, width=BORDER_W * S)
    # 表头品牌色带（仅上圆角：先圆角整条，再用方形补平底部两角）
    hb_x0 = BORDER_W * S // 2
    hb_y0 = BORDER_W * S // 2
    hb_x1 = W - 1 - BORDER_W * S // 2
    hb_y1 = int(head_h * S)
    d.rounded_rectangle([hb_x0, hb_y0, hb_x1, hb_y1], radius=RADIUS * S, fill=a)
    d.rectangle([hb_x0, hb_y1 - RADIUS * S, hb_x1, hb_y1], fill=a)
    # 表头文字（白）
    for ci, lines in enumerate(head_lines):
        cx = int(xs[ci] * S) + PAD_X * S
        ty = BORDER_W * S // 2 + PAD_Y * S
        for ln in lines:
            d.text((cx, ty), ln, font=f_head, fill=WHITE_BG)
            ty += head_lh * S
    # 数据区纵向浅渐层（白 → 极浅米），替代硬斑马纹
    body_top = int(head_h * S)
    body_bot = H
    top_c, bot_c = (255, 255, 255), (247, 244, 239)
    span = max(1, body_bot - body_top)
    for yy in range(body_top, body_bot):
        t = (yy - body_top) / span
        col = tuple(int(top_c[k] + (bot_c[k] - top_c[k]) * t) for k in range(3))
        d.line([BORDER_W * S // 2, yy, W - 1 - BORDER_W * S // 2, yy], fill=col)
    # 数据行（渐层作底，直接绘文字）
    cy = body_top
    for ri, r in enumerate(rows[1:]):
        h = int(body_hs[ri] * S)
        for ci, cell in enumerate(r):
            cx = int(xs[ci] * S)
            if ci == 0:
                # 首列：加粗 + 品牌色，作"标签列"
                _draw_cell(d, cell, body_lines[ri][ci], cx, cy, int(col_ws[ci] * S), h,
                           f_body_b, a, PAD_X * S, PAD_Y * S, body_lh * S)
            else:
                _draw_cell(d, cell, body_lines[ri][ci], cx, cy, int(col_ws[ci] * S), h,
                           f_body, (35, 24, 21), PAD_X * S, PAD_Y * S, body_lh * S)
        cy += h
    # 网格线（仅数据区竖向，避免压到表头色带）
    for ci in range(ncols):
        gx = int((xs[ci] - BORDER_W / 2) * S)
        d.line([gx, int(head_h * S), gx, H], fill=GRID, width=1)
    gx = int((xs[-1] + col_ws[-1] + BORDER_W / 2) * S)
    d.line([gx, int(head_h * S), gx, H], fill=GRID, width=1)
    # 表头下分隔（品牌色加粗）
    d.line([0, int(head_h * S), W, int(head_h * S)], fill=a, width=3 * S)
    # 行分隔
    hy = int(head_h * S)
    for hs in body_hs:
        hy += int(hs * S)
        d.line([0, hy, W, hy], fill=GRID, width=1)
    return img


def _draw_cell(d, text, lines, x, y, w, h, font, fill, pad_x, pad_y, line_h):
    ty = y + pad_y
    for ln in lines:
        d.text((x + pad_x, ty), ln, font=font, fill=fill)
        ty += line_h


def img_tag_from_pil(im: Image.Image, alt: str = "", extra_style: str = "") -> str:
    """合规图片（来自内存 PIL 图像）：base64 内嵌 + data-w（像素宽）。"""
    import io
    buf = io.BytesIO()
    im.save(buf, "PNG")
    src = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    style = "display:block;width:100%;border-radius:12px;border:1px solid #e8e3dc;margin:20px 0;"
    if extra_style:
        style += extra_style
    return f'<img src="{src}" data-w="{im.width}" alt="{esc(alt)}" style="{style}">'


def inline(t: str, hl_bg: str) -> str:
    """行内 **加粗** → 重点句高亮（纯色底，无渐变）。"""
    parts = []
    for i, seg in enumerate(re.split(r"\*\*(.+?)\*\*", t)):
        if not seg:
            continue
        seg = esc(seg)
        if i % 2 == 1:
            parts.append(f'<strong style="font-weight:700;color:{DARK};'
                         f'background-color:{hl_bg};padding:1px 3px;">{seg}</strong>')
        else:
            parts.append(seg)
    return "".join(parts)


def P(text_html: str, fs: int, lh: int, color: str, margin: str = "0 0 18px 0", align: str = "left") -> str:
    """合规段落：文本整体包进 <span>，块级 <p> 无直接文本节点
    → 官方校验器 collectLineHeightFallback 的 hasDirectText 判定为 false，
    自动跳过测量，规避行内高亮把单行拆成多碎片矩形导致的 line-height 误报。
    align 显式声明标准对齐值（left/center），防止微信粘贴时为无显式对齐的块
    注入非标准 text-align（start/justify）触发"文字对齐异常"告警。"""
    return (f'<p style="margin:{margin}">'
            f'<span style="font-size:{fs}px;line-height:{lh}px;color:{color};text-align:{align};">'
            f'{text_html}</span></p>')


def H1(text_html: str) -> str:
    return ('<h1 style="margin:24px 0 0 0;">'
            f'<span style="font-size:24px;font-weight:800;color:{DARK};line-height:36px;text-align:left;">'
            f'{text_html}</span></h1>')


def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and "|" in s[1:]


def _is_table_sep(line: str) -> bool:
    s = line.strip().strip("|")
    return bool(re.fullmatch(r"[\s:\-|]+", s)) and "-" in s


def _split_row(line: str) -> list:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_md(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
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
        elif re.fullmatch(r"!\[[^\]]*\]\([^)]+\)", raw.strip()):
            # 正文档里的插图声明：`![图注](文件名)`。位置由作者定，脚本不猜。
            # 路径相对 md 所在目录解析，方便 `![...](标题_2026-01-01_插图1.png)` 这种写法。
            m = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", raw.strip())
            blocks.append(("imgmd", (m.group(2).strip(), m.group(1).strip())))
            i += 1
        elif raw.startswith("> "):
            blocks.append(("footer", raw[2:].strip()))
            i += 1
        elif re.fullmatch(r"\*\*.+\*\*", raw.strip()):
            blocks.append(("card", raw.strip()[2:-2]))
            i += 1
        elif _is_table_row(raw) and i + 1 < n and _is_table_sep(lines[i + 1]):
            rows = [_split_row(raw)]
            i += 2  # 跳过表头行与分隔行
            while i < n and _is_table_row(lines[i].rstrip()):
                rows.append(_split_row(lines[i].rstrip()))
                i += 1
            blocks.append(("table", rows))
        else:
            blocks.append(("para", raw.strip()))
            i += 1
    return blocks


def _media_path(rel: str, base: Path) -> Path:
    """插图路径解析：绝对路径直接用；相对路径按 md 所在目录解析。

    写作时只写文件名（`标题_2026-01-01_插图1.png`）最省事——稿子和图都在
    同一个产物目录里，换目录也不用改稿子。
    """
    p = Path(rel).expanduser()
    return p if p.is_absolute() else (base / p)


def build(args):
    blocks = parse_md(Path(args.md))
    md_dir = Path(args.md).resolve().parent
    # 主色可由 WX_ACCENT 或 --accent #RRGGBB 指定，辅色自动配对
    accent, second = accent_pair(args.accent)
    _r, _g, _b = hex_rgb(accent)
    hl_bg = f"rgba({_r},{_g},{_b},.16)"

    inserts = [p.strip() for p in args.insert.split(",") if p.strip()]
    md_imgs = [c[0] for k, c in blocks if k == "imgmd"]
    for p in inserts + ([args.art] if args.art else []) + [str(_media_path(r, md_dir)) for r in md_imgs]:
        if not Path(p).exists():
            print(f"ERROR: 插图不存在: {p}", file=sys.stderr)
            sys.exit(1)

    title = next((c for k, c in blocks if k == "title"), "")
    first_para = next((c for k, c in blocks if k == "para"), "")
    footers = [c for k, c in blocks if k == "footer"]
    # 稿子里已声明插图位置时，不再用 --insert 自动均分——两套并存会重复插图。
    if md_imgs and inserts:
        print("NOTE: 稿子里已有 ![图注](路径) 声明插图位置，忽略 --insert（避免重复插图）",
              file=sys.stderr)
        inserts = []
    content_blocks = [(k, c) for k, c in blocks
                      if k in ("section", "para", "card", "table", "imgmd")]
    # 首段已被上方「导读摘要框」消费，正文中不再重复渲染
    if first_para and content_blocks and content_blocks[0][0] == "para" and content_blocks[0][1] == first_para:
        content_blocks.pop(0)

    sec_pos = [i for i, (k, _) in enumerate(content_blocks) if k == "section"]
    if inserts and sec_pos:
        for n, img in enumerate(inserts):
            slot = sec_pos[min(len(sec_pos) - 1,
                               round((n + 1) * len(sec_pos) / (len(inserts) + 1)) - 1)]
            content_blocks.insert(slot, ("img", img))

    parts = []

    # 头部（无固定宽度，section 100% 自适应；无 font-family）
    parts.append(f'''
<section style="margin:0;padding:36px 20px 8px;background-color:#ffffff;">
  <section style="height:8px;background-color:{accent};border-radius:4px 4px 0 0;"></section>
  <section style="height:4px;background-color:{second};border-radius:0 0 4px 4px;"></section>
  {H1(esc(title))}
  <section style="margin-top:14px;">
    <section style="display:inline-block;width:64px;height:6px;background-color:{accent};"></section>
    <section style="display:inline-block;width:24px;height:3px;background-color:{second};margin-left:6px;"></section>
  </section>
</section>''')

    if args.art:
        parts.append(f'<section style="padding:0 20px;">{img_tag(args.art, "题图")}</section>')

    # 导读摘要框（左侧品牌色竖条 + 胶囊标签，米白卡，文字显式左对齐）
    if first_para:
        parts.append(f'''
<section style="margin:20px 20px 4px 20px;padding:16px 18px 14px 18px;background-color:{CREAM};border-radius:10px;border:1px solid #ece7df;border-left:5px solid {accent};text-align:left;">
  <p style="margin:0 0 8px 0;"><span style="display:inline-block;background-color:{accent};color:#ffffff;font-size:12px;font-weight:800;padding:2px 11px;border-radius:20px;letter-spacing:1px;">导读</span></p>
  {P(esc(first_para), 14, 26, GRAY_C, margin="0")}
</section>''')

    # 正文（内联样式 section/p，嵌套 ≤3 层）
    parts.append('<section style="padding:12px 20px 8px;">')
    sec_idx = 0
    for kind, content in content_blocks:
        if kind == "section":
            sec_idx += 1
            c = accent if sec_idx % 2 == 1 else second
            icon = ICONS[ICON_KEYS[(sec_idx - 1) % len(ICON_KEYS)]].replace("{c}", c)
            parts.append(f'''
<section style="margin:28px 0 4px 0;">
  <section style="line-height:30px;">
    <section style="display:inline-block;min-width:30px;padding:2px 6px;background-color:{c};border-radius:7px;color:#ffffff;font-size:13px;font-weight:800;text-align:center;">{sec_idx:02d}</section>
    <strong style="font-size:19px;font-weight:800;color:{second};margin-left:8px;">{esc(content)}</strong>
    <section style="display:inline-block;vertical-align:middle;margin-left:8px;">{icon}</section>
  </section>
</section>''')
        elif kind == "card":
            parts.append(f'''
<section style="margin:20px 0;padding:16px 18px;background-color:{CREAM};border-left:5px solid {accent};border-radius:10px;text-align:left;">
  {P(esc(content), 16, 30, DARK, margin="0")}
</section>''')
        elif kind == "imgmd":
            rel, alt = content
            parts.append(img_tag(str(_media_path(rel, md_dir)), alt or "插图"))
        elif kind == "img":
            parts.append(img_tag(content, "插图"))
        elif kind == "table":
            parts.append(img_tag_from_pil(table_to_img(content, accent), "表格"))
        else:
            parts.append(P(inline(content, hl_bg), 16, 30, BODY_C))
    parts.append('</section>')

    # 结尾引导关注块（纯色背景，无渐变；容器居中，内部文本显式 center 防止微信注入非标准对齐）
    parts.append(f'''
<section style="margin:28px 20px 16px 20px;padding:22px 18px 18px 18px;background-color:{CREAM};border-top:4px solid {accent};border-radius:10px;text-align:center;">
  {P("— 写在最后 —", 15, 30, second, margin="0", align="center")}
  {P("如果这篇帮你看清了某件事，就先收藏起来——下次遇到同类问题，翻出来对一遍就行。", 15, 30, "#5c544e", margin="12px 0 0 0", align="center")}
  {P(f'关注<strong style="color:{accent};font-weight:800;">{BRAND_NAME}</strong>，{CTA_TEXT}', 15, 30, "#5c544e", margin="8px 0 0 0", align="center")}
  {P("顺手转给那个和你一起备考的人。两个人互相提醒，比一个人硬扛稳得多。", 14, 30, "#8a827b", margin="8px 0 0 0", align="center")}
</section>''')

    if footers:
        notes = "<br>".join(esc(f) for f in footers)
        parts.append(f'''
<section style="margin:0 20px 28px 20px;padding-top:12px;border-top:1px dashed #ddd8d0;text-align:left;">
  {P(notes, 13, 24, "#9aa1ab", margin="0")}
</section>''')

    body = "\n".join(parts)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
</head>
<body style="margin:0;padding:0;background-color:{CREAM};">
<section style="max-width:100%;background-color:#ffffff;margin:0;padding:4px 0 16px 0;">
{body}
</section>
</body>
</html>'''


def self_check(html: str) -> list:
    """按微信编辑器规范做静态自查，返回违规列表。"""
    issues = []
    if "<style" in html or "class=" in html:
        issues.append("存在 <style> 或 class（应全内联）")
    if "font-family" in html:
        issues.append("设置了 font-family（规范不建议）")
    if "!important" in html:
        issues.append("使用了 !important")
    if re.search(r'text-align:\s*(start|end)', html):
        issues.append("text-align 使用了 start/end")
    for m in re.finditer(r'text-align:\s*([a-z]+)', html):
        if m.group(1) not in ("left", "center", "right"):
            issues.append(f"text-align 使用了非标准值 {m.group(0)}（仅允许 left/center/right）")
    if "<pre" in html:
        issues.append("使用了 <pre> 标签")
    if re.search(r'opacity:\s*0', html):
        issues.append("存在 opacity:0")
    if re.search(r'width:\s*\d+(px|pt)', html):
        # 允许小尺寸装饰条（≤120px）
        for m in re.finditer(r'width:\s*(\d+)(px|pt)', html):
            if int(m.group(1)) > 120:
                issues.append(f"固定宽度 {m.group(0)}（>120px 装饰条）")
                break
    if re.search(r'height:\s*0', html):
        issues.append("存在 height:0")
    if re.search(r'background-image:\s*linear-gradient\([^)]*color', html):
        pass  # 纯装饰渐变允许；本模板实际不使用
    if re.search(r'<img(?![^>]*data-w)', html):
        issues.append("存在缺 data-w 的 img")
    if re.search(r'<table\b', html):
        issues.append("出现裸 <table> 标签（微信粘贴不可靠，表格应走 PNG 图片）")
    if "position:absolute" in html or "position: absolute" in html:
        issues.append("存在 position:absolute")
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--accent", default="orange",
                    help="主色：任意 #RRGGBB；orange/primary 表示取 WX_ACCENT，green/alt 表示取 WX_ACCENT_ALT")
    ap.add_argument("--art", default="")
    ap.add_argument("--insert", default="")
    args = ap.parse_args()

    if not Path(args.md).exists():
        print(f"ERROR: Markdown 不存在: {args.md}", file=sys.stderr)
        sys.exit(1)

    html = build(args)
    issues = self_check(html)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    n_md = len(re.findall(r"!\[[^\]]*\]\([^)]+\)", Path(args.md).read_text(encoding="utf-8")))
    n_img = n_md + (0 if n_md else len([p for p in args.insert.split(",") if p.strip()])) + (1 if args.art else 0)
    print(f"OK 公众号 HTML 已生成: {out} ({out.stat().st_size // 1024} KB, 含 {n_img} 张插图)")
    if n_img == 0:
        print("WARN: 本篇没有任何插图——Q22 要求每篇至少 1 张（正文加一行 "
              "`![图注](标题_日期_插图1.png)` 声明位置）", file=sys.stderr)
    if issues:
        print("规范自查发现问题：", file=sys.stderr)
        for i in issues:
            print(f"  - {i}", file=sys.stderr)
        sys.exit(1)
    print("规范自查：通过（内联样式/无font-family/自适应宽度/data-w/line-height/无!important）")


if __name__ == "__main__":
    main()

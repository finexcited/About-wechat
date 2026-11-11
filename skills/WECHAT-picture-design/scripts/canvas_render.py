# -*- coding: utf-8 -*-
"""canvas_render.py — 用 canvas-design 的设计哲学渲染贴图配图（HTML/CSS → PNG）。

设计约束（硬性）：
  1. 严禁抄袭：参考图只取风格，不复制画面；生成后用 dHash 与参考图比对，距离过近即报警。
  2. 每页版式必须不同：封面两种、内页三种，按篇轮换，manifest 记录每页版式与变化点。
  3. 内容贴人群：版式与配图风格由 config.design（人群）与 config.industry（行业调性）决定。

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

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKENS_PATH = os.path.join(SKILL_DIR, "assets", "design-tokens.json")
FONT_MEASURE = "/System/Library/Fonts/Hiragino Sans GB.ttc"

VARIANT_LABEL = {
    "cover_type": "封面·文字主导",
    "cover_photo": "封面·图片主导",
    "inner_editorial": "内页·编辑栏（描边页码＋要点）",
    "inner_photo": "内页·图片主导（上图上文）",
    "inner_quote": "内页·观点页（大字＋窄图带）",
}
VARIANT_CHANGE = {
    "cover_type": "巨型标题压左栏，图片全出血做底，橙色横线切分图文",
    "cover_photo": "图片占上半幅，标题落到纸面下半，视觉重心下移",
    "inner_editorial": "描边巨型页码＋72px 橙条＋正文压栏，信息密度最高",
    "inner_photo": "图片占上半幅，标题与要点压在纸面下半，先图后文",
    "inner_quote": "大字观点居中，细线围框，图片收成底部窄带，节奏最慢",
}


def load_tokens():
    with open(TOKENS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


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


def img_style(ctx, box_h, box_w):
    return ' style="object-position:50%% %d%%"' % focus_pct(ctx.get("img_path", ""), box_h, box_w)


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


def base_css(t, W, H):
    p = t["palette"]
    m = t["grid"]["margin"]
    return """
  html,body{margin:0;padding:0;width:%(W)spx;height:%(H)spx;overflow:hidden;background:%(paper)s;}
  body{font-family:"Hiragino Sans GB","PingFang SC",sans-serif;color:%(ink)s;-webkit-font-smoothing:antialiased;}
  .page{position:relative;width:%(W)spx;height:%(H)spx;overflow:hidden;}
  .meta{position:absolute;left:%(m)spx;right:%(m)spx;top:%(meta_top)spx;display:flex;justify-content:space-between;
        font-family:ui-monospace,Menlo,monospace;font-size:%(meta)spx;letter-spacing:%(mtrack)s;color:%(muted)s;}
  .hair{position:absolute;left:%(m)spx;right:%(m)spx;top:%(hair_top)spx;height:1px;background:%(line)s;}
  .eyebrow{position:absolute;left:%(m)spx;font-family:ui-monospace,Menlo,monospace;font-size:%(meta)spx;
           letter-spacing:.14em;color:%(accent)s;}
  .photo{position:absolute;left:0;right:0;overflow:hidden;}
  .photo img{width:100%%;height:100%%;object-fit:cover;display:block;filter:saturate(.94) contrast(1.02);}
  .bar{position:absolute;left:0;width:100%%;background:%(accent)s;}
  .cap{position:absolute;right:%(m)spx;font-family:ui-monospace,Menlo,monospace;font-size:17px;
       letter-spacing:.13em;color:%(muted)s;}
  .numeral{position:absolute;right:%(m)spx;font-weight:700;line-height:1;color:transparent;
           -webkit-text-stroke:1px %(line)s;}
  .rule{position:absolute;left:%(m)spx;width:72px;background:%(accent)s;}
  .grain{position:absolute;inset:0;opacity:.05;background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/></filter><rect width='120' height='120' filter='url(%%23n)'/></svg>");}
""" % {"W": W, "H": H, "paper": p["paper"], "ink": p["ink"], "muted": p["muted"],
       "line": p["line"], "accent": p["accent"], "m": m,
       "meta": t["type"]["meta"], "mtrack": t["type"]["meta_tracking"],
       "meta_top": m - 6, "hair_top": m + 54}


def page_html(ctx):
    t, p = ctx["tokens"], ctx["tokens"]["palette"]
    W, H = t["canvas"]["width"], t["canvas"]["height"]
    m = t["grid"]["margin"]
    v = ctx["variant"]
    img = ctx.get("img_data", "")
    bar = t["rules"]["accent_bar"]
    parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>',
             base_css(t, W, H), "</style></head><body><div class=\"page\">",
             '<div class="meta"><span>%s</span><span>%02d / %02d</span></div>'
             % (esc(ctx.get("meta_left", "YOUR BRAND")), ctx["page_no"], ctx["total"]),
             '<div class="hair"></div>']

    if v == "cover_type":
        pt = ctx["photo_top"]
        parts += ['<div class="eyebrow" style="top:%dpx">%s</div>' % (m + 84, esc(ctx.get("eyebrow", ""))),
                  '<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;font-weight:700;font-size:%dpx;'
                  'line-height:%s;letter-spacing:-0.02em">%s</div>'
                  % (m, m + 132, W - 2 * m, ctx["title_size"], t["type"]["title_line_height"],
                     "<br>".join(hl(l, ctx.get("highlight", ""), p["accent"]) for l in ctx["title_lines"])),
                  '<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;font-size:34px;line-height:1.4;'
                  'color:#3B4A5A">%s</div>' % (m, ctx["sub_top"], W - 2 * m, esc(ctx.get("sub", ""))),
                  '<div class="photo" style="top:%dpx;height:%dpx"><img src="%s"%s></div>'
                  % (pt, H - pt, img, img_style(ctx, H - pt, W)),
                  '<div class="bar" style="top:%dpx;height:%dpx"></div>' % (pt - bar, bar),
                  '<div class="cap" style="top:%dpx">%s</div>' % (pt - 38, esc(ctx.get("caption", "")))]

    elif v == "cover_photo":
        ph = int(H * 0.54)
        ts = min(ctx["title_size"], 104)
        lines = wrap_for(ctx.get("title_text", ""), ts, W - 2 * m)
        sub_top = ph + 122 + int(ts * t["type"]["title_line_height"]) * len(lines) + 26
        parts += ['<div class="photo" style="top:0;height:%dpx"><img src="%s"%s></div>'
                  % (ph, img, img_style(ctx, ph, W)),
                  '<div class="bar" style="top:%dpx;height:%dpx"></div>' % (ph - bar, bar),
                  '<div class="cap" style="top:%dpx">%s</div>' % (ph + 24, esc(ctx.get("caption", ""))),
                  '<div class="eyebrow" style="top:%dpx">%s</div>' % (ph + 76, esc(ctx.get("eyebrow", ""))),
                  '<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;font-weight:700;font-size:%dpx;'
                  'line-height:%s;letter-spacing:-0.02em">%s</div>'
                  % (m, ph + 120, W - 2 * m, ts, t["type"]["title_line_height"],
                     "<br>".join(hl(l, ctx.get("highlight", ""), p["accent"]) for l in lines)),
                  '<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;font-size:32px;line-height:1.4;'
                  'color:#3B4A5A">%s</div>' % (m, sub_top, W - 2 * m, esc(ctx.get("sub", "")))]

    elif v == "inner_editorial":
        pt = ctx["photo_top"]
        parts += ['<div class="numeral" style="top:%dpx;font-size:%dpx">%02d</div>'
                  % (m + 40, t["type"]["numeral"], ctx["page_no"]),
                  '<div class="eyebrow" style="top:%dpx">%s</div>'
                  % (m + 138, esc(ctx.get("eyebrow", ""))),
                  '<div class="rule" style="top:%dpx;height:%dpx"></div>' % (ctx["rule_top"], bar),
                  '<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;font-weight:700;font-size:%dpx;'
                  'line-height:1.16;letter-spacing:-.01em">%s</div>'
                  % (m, m + 190, W - 2 * m - 190, t["type"]["headline"],
                     hl(ctx.get("headline", ""), ctx.get("highlight", ""), p["accent"])),
                  '<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;font-size:%dpx;line-height:%s;'
                  'color:#2E3B4A">%s</div>'
                  % (m, ctx["body_top"], W - 2 * m - 40, t["type"]["body"], t["type"]["body_line_height"],
                     "<br>".join(esc(l) for l in ctx["body_lines"])),
                  '<div class="photo" style="top:%dpx;height:%dpx"><img src="%s"%s></div>'
                  % (pt, H - pt, img, img_style(ctx, H - pt, W)),
                  '<div class="bar" style="top:%dpx;height:%dpx"></div>' % (pt - bar, bar),
                  '<div class="cap" style="top:%dpx">%s</div>' % (pt - 38, esc(ctx.get("caption", "")))]

    elif v == "inner_photo":
        ph = int(H * 0.50)
        hs = t["type"]["headline"] - 6
        body_h = len(ctx["body_lines"]) * int(t["type"]["body"] * t["type"]["body_line_height"])
        block_h = 46 + int(hs * 1.14) + 22 + bar + 34 + body_h
        # 剩余空间里把文字块垂直居中，避免底部塌出一大片空
        start = ph + max(40, int((H - ph - block_h - m) / 2))
        rule_top = start + 46 + int(hs * 1.14) + 22
        parts += ['<div class="photo" style="top:0;height:%dpx"><img src="%s"%s></div>'
                  % (ph, img, img_style(ctx, ph, W)),
                  '<div class="bar" style="top:%dpx;height:%dpx"></div>' % (ph - bar, bar),
                  '<div class="cap" style="top:%dpx">%s</div>' % (ph + 24, esc(ctx.get("caption", ""))),
                  '<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;font-weight:700;font-size:%dpx;'
                  'line-height:1.14;letter-spacing:-.01em">%s</div>'
                  % (m, start, W - 2 * m, hs,
                     hl(ctx.get("headline", ""), ctx.get("highlight", ""), p["accent"])),
                  '<div class="rule" style="top:%dpx;height:%dpx"></div>' % (rule_top, bar),
                  '<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;font-size:%dpx;line-height:%s;'
                  'color:#2E3B4A">%s</div>'
                  % (m, rule_top + 34, W - 2 * m - 40, t["type"]["body"], t["type"]["body_line_height"],
                     "<br>".join(esc(l) for l in ctx["body_lines"])),
                  # 底部落一个刊头字，给页码一个有意的收口
                  '<div style="position:absolute;left:%dpx;bottom:%dpx;display:flex;align-items:center;'
                  'font-family:ui-monospace,Menlo,monospace;font-size:19px;letter-spacing:.16em;color:%s">'
                  '<span style="display:block;width:26px;height:6px;background:%s;margin-right:14px"></span>%s</div>'
                  % (m, m - 8, p["muted"], p["accent"], esc(ctx.get("sticker", "")))]

    elif v == "inner_quote":
        q = ctx.get("quote") or "".join(ctx.get("body_lines", []))[:80]
        n = max(8, len(q))
        qs = max(48, min(84, int((W - 2 * m) * 2.15 / n)))
        qlines = wrap_for(q, qs, W - 2 * m)[:6]
        block_h = len(qlines) * int(qs * 1.45)
        top = max(210, int(150 + (H * 0.70 - 150 - block_h - 70) / 2))
        ph = int(H * 0.70)
        parts += ['<div style="position:absolute;left:%dpx;right:%dpx;top:%dpx;height:1px;background:%s"></div>'
                  % (m, m, 150, p["line"]),
                  '<div class="rule" style="top:%dpx;height:%dpx"></div>' % (top - 44, bar),
                  '<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;font-size:%dpx;line-height:1.45;'
                  'font-weight:700;letter-spacing:-.01em">%s</div>'
                  % (m, top, W - 2 * m, qs, "<br>".join(hl(l, ctx.get("highlight", ""), p["accent"])
                                                        for l in qlines)),
                  '<div class="eyebrow" style="top:%dpx">%s</div>'
                  % (top + block_h + 34, esc(ctx.get("eyebrow", ""))),
                  '<div class="photo" style="top:%dpx;height:%dpx"><img src="%s"%s></div>'
                  % (ph, H - ph, img, img_style(ctx, H - ph, W)),
                  '<div class="bar" style="top:%dpx;height:%dpx"></div>' % (ph - bar, bar),
                  '<div class="cap" style="top:%dpx">%s</div>' % (ph - 38, esc(ctx.get("caption", "")))]

    parts.append('<div class="grain"></div></div></body></html>')
    return "".join(parts)


def assign_variants(note_idx, pages_n, cfg):
    v = cfg["design"]["variants"]
    covers, inners = v["cover"], v["inner"]
    plan = [covers[(note_idx - 1) % len(covers)]]
    for i in range(2, pages_n + 1):
        plan.append(inners[((note_idx - 1) + (i - 2)) % len(inners)])
    return plan


def build_note_pages(note_idx, note, spec, copy_obj, tokens, note_dir, cfg):
    W, H = tokens["canvas"]["width"], tokens["canvas"]["height"]
    m = tokens["grid"]["margin"]
    total = spec["image_count"].get("chosen") or 6
    page_specs = copy_obj.get("pages") or []
    plan = assign_variants(note_idx, total, cfg)

    pages = []
    for p in range(1, total + 1):
        src = os.path.join(note_dir, "images", "page-%02d.png" % p)
        if not os.path.exists(src):
            continue
        img_data = img_b64(src)
        variant = plan[p - 1]
        brand = cfg.get("brand", {})
        cap_prefix = copy_obj.get("caption_prefix") or brand.get("caption_prefix", "YOUR BRAND")
        ctx = {"tokens": tokens, "page_no": p, "total": total, "img_data": img_data,
               "img_path": src, "variant": variant,
               "caption": "%s · %02d" % (cap_prefix, p),
               "sticker": copy_obj.get("sticker", ""),
               "meta_left": copy_obj.get("meta_left") or brand.get("meta_left", "YOUR BRAND")}
        if variant.startswith("cover"):
            title = copy_obj.get("title", "")
            size = fit_title(title, W - 2 * m)
            ctx.update({"title_text": title,
                        "title_lines": wrap_for(title, size, W - 2 * m), "title_size": size,
                        "sub": copy_obj.get("cover_line", ""),
                        "eyebrow": copy_obj.get("eyebrow", ""),
                        "highlight": copy_obj.get("highlight", "")})
            sub_top = m + 132 + int(size * tokens["type"]["title_line_height"]) * len(ctx["title_lines"]) + 26
            ctx["sub_top"] = sub_top
            ctx["photo_top"] = min(1010, max(640, sub_top + 80))
        else:
            ps = page_specs[p - 2] if p - 2 < len(page_specs) else {}
            body_lines = wrap_for(ps.get("body", ""), tokens["type"]["body"], W - 2 * m - 40)
            body_bottom = m + 300 + len(body_lines) * int(
                tokens["type"]["body"] * tokens["type"]["body_line_height"])
            ctx.update({
                "headline": ps.get("headline", ""), "body_lines": body_lines,
                "highlight": ps.get("highlight", ""), "eyebrow": ps.get("eyebrow", ""),
                "quote": ps.get("quote", ""),
                "rule_top": m + 190 + int(tokens["type"]["headline"] * 1.16) + 16,
                "body_top": m + 190 + int(tokens["type"]["headline"] * 1.16) + 48,
                "photo_top": max(620, min(1120, body_bottom + 110)),
            })
        pages.append((variant, ctx))
    return pages


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
              "- 设计含义：%s" % aud["implication"],
              "- 视觉语气：%s" % cfg["design"]["image_style"], ""]
    if brief.strip():
        lines += ["> 补充的受众简报（data/audience-brief.md）：", ""]
        lines += ["> " + l for l in brief.strip().split("\n")[:12]] + [""]

    lines += ["## 2. 参考来源（风格借鉴，不复制画面）", "",
              "| 篇 | 来源渠道 | 素材标题 | 参考图 | 说明 |", "|---|---|---|---|---|"]
    for idx, note in enumerate(meta["notes"], 1):
        refs = refs_by_note.get(idx, [])
        local = "`%s`" % os.path.relpath(refs[0], run_root) if refs else "—"
        lines.append("| %d | %s | %s | %s | %s |"
                     % (idx, note.get("channel"), (note["title"] or "")[:22], local,
                        "有参考图，仅取构图与色调" if refs else "无参考图，自主设计"))
    lines.append("")

    lines += ["## 3. 版式变化（每页不同）", "",
              "| 篇 | 页 | 版式 | 变化点 |", "|---|---|---|---|"]
    for mf in manifests:
        for pg in mf["pages"]:
            lines.append("| %d | %02d | %s | %s |"
                         % (mf["index"], pg["page"], pg.get("layout", "-"), pg.get("change", "-")))
    lines.append("")

    th = cfg["design"].get("anti_copy", {}).get("dhash_similarity_max", 12)
    lines += ["## 4. 反抄袭核验", "",
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


def collect_refs(meta, run_root):
    refs = {}
    for idx, note in enumerate(meta["notes"], 1):
        p = os.path.join(run_root, "data", "covers", "%s.img" % note["id"])
        refs[idx] = [p] if os.path.exists(p) else []
    return refs


def run(run_root, log=None):
    tokens = load_tokens()
    meta = common.load_run(run_root)
    cfg = common.load_config()
    spec = common.jload(os.path.join(run_root, "data", "spec.json"))
    if spec is None:
        common.die("缺少 spec.json，请先执行 spec 阶段")
    logo_img = Image.open(spec["logo"]["path"]).convert("RGBA")
    busy_threshold = cfg["defaults"]["logo_busy_edge_threshold"]
    refs_by_note = collect_refs(meta, run_root)

    manifests, sim_rows = [], []
    for idx, note in enumerate(meta["notes"], start=1):
        nd = common.note_dir(run_root, idx)
        copy_obj = common.jload(os.path.join(nd, "copy.json"))
        if copy_obj is None:
            raise RuntimeError("第%d篇缺少 copy.json（阶段3 未完成）" % idx)
        out_dir = os.path.join(nd, "composed")
        html_dir = os.path.join(nd, "canvas")
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(html_dir, exist_ok=True)

        pages = build_note_pages(idx, note, spec, copy_obj, tokens, nd, cfg)
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
                    "size": [tokens["canvas"]["width"], tokens["canvas"]["height"]],
                    "engine": "canvas-design", "design_theme": tokens["philosophy"],
                    "pages": [], "missing_pages": [], "placeholder": False}
        for p, (variant, ctx) in enumerate(pages, start=1):
            png_path = os.path.join(out_dir, "page-%02d.png" % p)
            with Image.open(png_path) as im:
                canvas = im.convert("RGBA")
                if canvas.size != (tokens["canvas"]["width"], tokens["canvas"]["height"]):
                    canvas = canvas.resize((tokens["canvas"]["width"], tokens["canvas"]["height"]),
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
                                      "layout": VARIANT_LABEL.get(variant),
                                      "change": VARIANT_CHANGE.get(variant),
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
        print("  #%d 参考来源：%s｜版式：%s"
              % (idx,
                 ("抓取参考（%s）" % os.path.basename(refs[0])) if refs else "自主设计（无参考图）",
                 "、".join("%02d:%s" % (pg["page"], pg["variant"]) for pg in manifest["pages"])))
        if log:
            log("S4", "canvas 渲染第%d篇 %d 页，版式：%s"
                % (idx, len(pages), "、".join(VARIANT_LABEL.get(v, v) for v, _ in pages)))

    write_design_report(run_root, meta, spec, cfg, manifests, refs_by_note, sim_rows)
    return manifests


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    print("rendered notes:", len(run(a.run)))

# -*- coding: utf-8 -*-
"""compose_images.py — 阶段 4：配图合成（人群驱动版式 + LOGO 嵌入）。

设计逻辑（youth-editorial，面向年轻读者的轻杂志版式）：
  · 顶部品牌色带作为「纸面」，标题压在色带上——对比度确定，不依赖底图明暗
  · 眉标（橙底白字小标签）+ 大字标题 + 关键词撞色 + 副标，形成层次
  · 内页带页序、要点小标题与短句；封面可挂一枚倾斜贴纸增加活泼感
  · 底部右下角 LOGO，按局部对比度加衬底

输入：notes/NN/images/page-XX.png（生图，或 --placeholder 测试底图）
      notes/NN/copy.json（阶段3 定稿，可含 eyebrow / highlight / sticker）
      data/spec.json（规范 + 设计令牌）
输出：notes/NN/composed/page-XX.png + compose-manifest.json
"""
import argparse
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FONT_BOLD = 2   # W6
FONT_REG = 0    # W3
WHITE = (255, 255, 255, 255)


def font(size, bold=False):
    return ImageFont.truetype(FONT_PATH, size, index=FONT_BOLD if bold else FONT_REG)


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def cover_crop(img, w, h):
    img = img.convert("RGB")
    sw, sh = img.size
    scale = max(w / float(sw), h / float(sh))
    nw, nh = int(round(sw * scale)), int(round(sh * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - w) // 2
    top = (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


# ---------------- 中文折行 ----------------

def wrap_cjk(text, fnt, max_width, draw):
    out = []
    for para in (text or "").split("\n"):
        para = para.strip()
        if para:
            out.extend(_wrap_para(para, fnt, max_width, draw))
    return out


def _wrap_by_segments(text, fnt, max_width, draw):
    """按分隔符整段换行，避免把「32/40」这类数据拆到两行。"""
    parts = re.split(r"(?<=[｜|·])", text)
    lines, cur = [], ""
    for part in parts:
        trial = cur + part
        if draw.textlength(trial, font=fnt) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = part
    if cur:
        lines.append(cur)
    lines = [ln.rstrip("｜|· ") for ln in lines]
    return [ln for ln in lines if ln]


def _wrap_para(text, fnt, max_width, draw):
    if draw.textlength(text, font=fnt) <= max_width:
        return [text]
    if any(sep in text for sep in "｜|"):
        return _wrap_by_segments(text, fnt, max_width, draw)
    for i in range(len(text) - 2, 0, -1):
        ch = text[i]
        if ch in "，。、；：！？":
            seg1, seg2 = text[:i + 1], text[i + 1:]
            if len(seg2) >= 2 and draw.textlength(seg1, font=fnt) <= max_width \
                    and draw.textlength(seg2, font=fnt) <= max_width:
                return [seg1, seg2]
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if draw.textlength(trial, font=fnt) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    if len(lines) == 2 and abs(len(lines[0]) - len(lines[1])) > 1 and len(lines[0]) + len(lines[1]) > 4:
        merged = lines[0] + lines[1]
        cut = (len(merged) + 1) // 2
        lines = [merged[:cut], merged[cut:]]
    PUNCT_HEAD = "，。、；：？！）》】”’%"
    for i in range(1, len(lines)):
        while lines[i] and lines[i][0] in PUNCT_HEAD and len(lines[i - 1]) > 2:
            lines[i - 1] += lines[i][0]
            lines[i] = lines[i][1:]
    if len(lines) > 1 and len(lines[-1]) == 1 and len(lines[-2]) > 3:
        merged = lines[-2] + lines[-1]
        cut = max(2, len(merged) // 2)
        lines[-2], lines[-1] = merged[:cut], merged[cut:]
    return [ln for ln in lines if ln]


# ---------------- 图形工具 ----------------

def text_width(draw, text, fnt, tracking=0):
    if not tracking:
        return draw.textlength(text, font=fnt)
    return sum(draw.textlength(ch, font=fnt) for ch in text) + tracking * max(0, len(text) - 1)


def draw_tracked(draw, xy, text, fnt, fill, tracking=0):
    x, y = xy
    if not tracking:
        draw.text((x, y), text, font=fnt, fill=fill)
        return x + draw.textlength(text, font=fnt)
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + tracking
    return x - tracking


def draw_shadowed(canvas, xy, text, fnt, fill, tracking=0, shadow=(8, 14, 26, 90)):
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    draw_tracked(d, (xy[0], xy[1] + max(2, fnt.size // 22)), text, fnt, shadow, tracking)
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(2)))
    d2 = ImageDraw.Draw(canvas)
    draw_tracked(d2, xy, text, fnt, fill, tracking)


def pill(canvas, xy, text, fnt, bg, fg, padx, pady, tracking=0):
    d = ImageDraw.Draw(canvas)
    tw = text_width(d, text, fnt, tracking)
    box = [xy[0], xy[1], xy[0] + tw + 2 * padx, xy[1] + fnt.size + 2 * pady]
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=bg)
    draw_tracked(ld, (box[0] + padx, box[1] + pady - int(fnt.size * 0.10)),
                 text, fnt, fg, tracking)
    canvas.alpha_composite(layer)
    return box


def draw_sticker(canvas, text, fnt, bg, fg, anchor_right, anchor_bottom, angle):
    d = ImageDraw.Draw(canvas)
    padx, pady = int(fnt.size * 0.55), int(fnt.size * 0.38)
    tw = d.textlength(text, font=fnt)
    w, h = int(tw + 2 * padx), int(fnt.size + 2 * pady)
    plate = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(plate)
    pd.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(h * 0.28), fill=bg)
    pd.text((padx, pady - int(fnt.size * 0.12)), text, font=fnt, fill=fg)
    plate = plate.rotate(angle, expand=True, resample=Image.BICUBIC)
    canvas.alpha_composite(plate, (max(0, anchor_right - plate.size[0]),
                                   max(0, anchor_bottom - plate.size[1] // 2)))


def edge_density(img, box):
    region = img.crop(box).convert("L")
    if region.size[0] < 4 or region.size[1] < 4:
        return 0.0
    return ImageStat.Stat(region.filter(ImageFilter.FIND_EDGES)).mean[0]


def placeholder_base(w, h, spec, seed=0):
    """测试底图：明亮通透的渐变 + 柔和色块（模拟生图色调，仅用于链路自测）。"""
    pal = spec["design"]["palette"]
    paper, accent_soft = hex_rgb(pal["paper"]), hex_rgb(pal["accent_soft"])
    primary = hex_rgb(pal["primary"])
    base = Image.new("RGB", (w, h), paper)
    dr = ImageDraw.Draw(base)
    for y in range(h):
        t = y / float(h)
        c = tuple(int(paper[i] * (1 - 0.22 * t) + primary[i] * 0.22 * t) for i in range(3))
        dr.line([(0, y), (w, y)], fill=c)
    blob = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blob)
    cx = int(w * (0.55 + 0.1 * ((seed % 3) - 1)))
    cy = int(h * 0.68)
    r = int(min(w, h) * 0.30)
    bd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent_soft + (120,))
    bd.ellipse([int(w * 0.10), int(h * 0.60), int(w * 0.44), int(h * 0.74)],
               fill=primary + (38,))
    blob = blob.filter(ImageFilter.GaussianBlur(radius=48))
    return Image.alpha_composite(base.convert("RGBA"), blob).convert("RGB")


# ---------------- 版式 ----------------

def band_measure(spec, texts, is_cover, W, H, draw):
    t = spec["design"]["tokens"]
    pad = int(W * 0.062)
    max_w = W - 2 * pad
    title_size = int(W * (t["title_size_cover"] if is_cover else t["title_size_page"]))
    f_title = font(title_size, bold=True)
    f_body = font(int(W * t["body_size"]))
    f_sub = font(int(W * t["subtitle_size"]))
    f_eye = font(int(W * t["eyebrow_size"]), bold=True)

    title_lines = wrap_cjk(texts.get("title", ""), f_title, max_w, draw)
    sub_lines = wrap_cjk(texts.get("subtitle", ""), f_sub, max_w, draw)
    body_lines = wrap_cjk(texts.get("body", ""), f_body, max_w, draw)

    eye_h = f_eye.size + 2 * int(f_eye.size * 0.30)
    title_lh = int(title_size * t["line_spacing"])
    body_lh = int(f_body.size * 1.5)
    sub_lh = int(f_sub.size * 1.5)

    need = pad + eye_h + int(H * 0.018) + len(title_lines) * title_lh
    if sub_lines:
        need += int(H * 0.012) + len(sub_lines) * sub_lh
    if body_lines:
        need += int(H * 0.016) + len(body_lines) * body_lh
    need += int(H * 0.038)

    base = int(H * (t["band_cover_ratio"] if is_cover else t["band_page_ratio"]))
    cap = int(H * (0.52 if is_cover else 0.44))
    band_h = min(max(base, need), cap)
    return {
        "band_h": band_h, "capped": need > band_h, "pad": pad,
        "title_lines": title_lines, "sub_lines": sub_lines, "body_lines": body_lines,
        "title_lh": title_lh, "body_lh": body_lh, "sub_lh": sub_lh, "eye_h": eye_h,
        "f_title": f_title, "f_body": f_body, "f_sub": f_sub, "f_eye": f_eye,
    }


def render_page(canvas, spec, texts, page_no, total, is_cover):
    W, H = canvas.size
    t = spec["design"]["tokens"]
    pal = spec["design"]["palette"]
    primary, accent, ink = hex_rgb(pal["primary"]), hex_rgb(pal["accent"]), hex_rgb(pal["ink"])

    draw = ImageDraw.Draw(canvas)
    m = band_measure(spec, texts, is_cover, W, H, draw)
    band_h = m["band_h"]

    # 品牌色带（上实色 → 下渐深），底缘一条强调色
    band = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    for y in range(band_h):
        k = y / float(max(1, band_h - 1))
        bd.line([(0, y), (W, y)],
                fill=tuple(int(primary[i] * (1 - 0.45 * k) + ink[i] * 0.45 * k) for i in range(3)) + (255,))
    canvas.alpha_composite(band, (0, 0))
    ImageDraw.Draw(canvas).rectangle([0, band_h - t["accent_rule"], W, band_h],
                                     fill=accent + (255,))

    # 色带上的巨型页序数字（仅封面；内页文字占满宽度，加数字会干扰阅读）
    f_ghost = font(int(H * 0.21), bold=True)
    ghost = "%02d" % page_no
    gw = draw.textlength(ghost, font=f_ghost)
    if is_cover:
        ghost_layer = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
        ImageDraw.Draw(ghost_layer).text((W - m["pad"] - gw + int(W * 0.012),
                                          band_h - int(H * 0.175)), ghost,
                                         font=f_ghost, fill=(255, 255, 255, 26))
        canvas.alpha_composite(ghost_layer)

    # 页序（右上）
    f_idx = font(int(W * t["page_index_size"]), bold=True)
    idx_text = "%02d / %02d" % (page_no, total)
    draw.text((W - m["pad"] - draw.textlength(idx_text, font=f_idx),
               m["pad"] + int(m["f_eye"].size * 0.1)), idx_text, font=f_idx,
              fill=(255, 255, 255, 170))

    # 眉标
    y = m["pad"]
    eyebrow = (texts.get("eyebrow") or "").strip()
    if eyebrow:
        pill(canvas, (m["pad"], y), eyebrow, m["f_eye"], accent + (255,), WHITE,
             int(m["f_eye"].size * 0.40), int(m["f_eye"].size * 0.28), t["eyebrow_tracking"])
    y += m["eye_h"] + int(H * 0.018)

    # 标题（关键词撞色）
    highlight = (texts.get("highlight") or "").strip()
    for ln in m["title_lines"]:
        x = m["pad"]
        if highlight and highlight in ln:
            pre, post = ln.split(highlight, 1)
            if pre:
                draw_shadowed(canvas, (x, y), pre, m["f_title"], WHITE, t["title_tracking"])
                x += draw.textlength(pre, font=m["f_title"])
            draw_shadowed(canvas, (x, y), highlight, m["f_title"], accent + (255,), t["title_tracking"])
            x += draw.textlength(highlight, font=m["f_title"])
            if post:
                draw_shadowed(canvas, (x, y), post, m["f_title"], WHITE, t["title_tracking"])
        else:
            draw_shadowed(canvas, (x, y), ln, m["f_title"], WHITE, t["title_tracking"])
        y += m["title_lh"]

    # 副标
    if m["sub_lines"]:
        y += int(H * 0.012)
        for ln in m["sub_lines"]:
            draw.text((m["pad"], y), ln, font=m["f_sub"], fill=(255, 255, 255, 238))
            y += m["sub_lh"]

    # 内页正文
    if m["body_lines"]:
        y += int(H * 0.016)
        for ln in m["body_lines"]:
            draw.text((m["pad"], y), ln, font=m["f_body"], fill=(255, 255, 255, 220))
            y += m["body_lh"]

    # 封面贴纸
    sticker = (texts.get("sticker") or "").strip()
    if sticker and is_cover:
        draw_sticker(canvas, sticker, font(int(W * 0.026), bold=True),
                     accent + (255,), WHITE, W - m["pad"], band_h + int(H * 0.014),
                     t["sticker_angle"])
    return canvas, band_h, m["capped"]


def place_logo(canvas, logo_img, spec, busy_threshold, keepout_bottom=0):
    W, H = canvas.size
    lg = spec["logo"]
    pad = int(min(W, H) * lg["padding_ratio"])
    target_w = int(W * lg["width_ratio"])

    def scaled(width):
        ratio = width / float(logo_img.size[0])
        return logo_img.resize((width, max(1, int(logo_img.size[1] * ratio))), Image.LANCZOS)

    def box_for(pos, img):
        lw, lh = img.size
        if pos == "bottom-right":
            return (W - pad - lw, H - pad - lh, W - pad, H - pad)
        if pos == "bottom-left":
            return (pad, H - pad - lh, pad + lw, H - pad)
        return ((W - lw) // 2, H - pad - lh, (W - lw) // 2 + lw, H - pad)

    logo = scaled(target_w)
    decision = {"position": None, "padding": pad, "width": logo.size[0],
                "scale_ratio": round(logo.size[0] / float(W), 4),
                "backing": None, "degraded": False, "busy": {}}

    for pos in [lg["position"]] + lg["fallback_positions"]:
        box = box_for(pos, logo)
        density = edge_density(canvas.convert("RGB"), box)
        decision["busy"][pos] = round(density, 2)
        if density <= busy_threshold and box[1] > keepout_bottom:
            decision["position"] = pos
            break
    force_plate = False
    if decision["position"] is None:
        # 三处都偏杂时不缩尺寸（缩到 11% 会看不清），改判为「原位 + 强制衬底」
        decision.update({"position": lg["position"], "degraded": True,
                         "degraded_reason": "三处候选区域均偏杂，改用衬底+原位放置"})
        force_plate = True

    box = box_for(decision["position"], logo)
    gray = logo.convert("L")
    alpha = logo.split()[-1]
    if alpha.getextrema()[0] < 255:
        hist = gray.histogram(mask=alpha)
        total = float(sum(hist)) or 1
        acc, lo_lum, hi_lum = 0, 0, 255
        for v, c in enumerate(hist):
            acc += c
            if lo_lum == 0 and acc / total >= 0.1:
                lo_lum = v
            if acc / total >= 0.9:
                hi_lum = v
                break
    else:
        lo_lum, hi_lum = gray.getextrema()
    bg_crop = canvas.convert("RGB").crop(box)
    bg_lum = ImageStat.Stat(bg_crop.convert("L")).mean[0]
    bg_rgb = ImageStat.Stat(bg_crop).mean
    bg_sat = 0.0 if max(bg_rgb) == 0 else (max(bg_rgb) - min(bg_rgb)) / float(max(bg_rgb))
    logo_lum = ImageStat.Stat(gray, mask=alpha).mean[0] if alpha.getextrema()[0] < 255 \
        else ImageStat.Stat(gray).mean[0]
    # 判据一：明暗差不足（含橙色 LOGO 落在橙色物体上的情况）
    low_contrast = abs(logo_lum - bg_lum) < 55 or (bg_sat > 0.42 and abs(logo_lum - bg_lum) < 95)
    # 亮底一律加白牌：橙色字标在浅底上尚可，但青色副标必须靠白牌才读得清
    need_light_backing = low_contrast or bg_lum > 150
    need_dark_backing = False
    if force_plate or need_light_backing or need_dark_backing:
        backing = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        bd = ImageDraw.Draw(backing)
        mm = int(pad * 0.30)
        bd.rounded_rectangle([box[0] - mm, box[1] - mm, box[2] + mm, box[3] + mm],
                             radius=int(min(logo.size) * 0.18),
                             fill=(255, 255, 255, 236) if need_light_backing else (12, 24, 40, 170))
        canvas.alpha_composite(backing)
        decision["backing"] = "light"

    canvas.alpha_composite(logo, (box[0], box[1]))
    decision["bbox"] = list(box)
    decision["short_side_margin_ratio"] = round(pad / float(min(W, H)), 4)
    return canvas, decision


def compose_note(run_root, idx, note, spec, cfg, placeholder=False):
    nd = common.note_dir(run_root, idx)
    copy_obj = common.jload(os.path.join(nd, "copy.json"))
    if copy_obj is None:
        raise RuntimeError("第%d篇缺少 copy.json（阶段3 未完成）" % idx)
    W, H = spec["image"]["width"], spec["image"]["height"]
    pages_target = (spec["image_count"].get("chosen") or spec["image_count"].get("fallback"))
    out_dir = os.path.join(nd, "composed")
    os.makedirs(out_dir, exist_ok=True)

    logo_img = Image.open(spec["logo"]["path"]).convert("RGBA")
    busy_threshold = cfg["defaults"]["logo_busy_edge_threshold"]
    manifest = {"index": idx, "note_id": note["id"], "size": [W, H],
                "design_theme": spec["design"]["theme"],
                "pages": [], "missing_pages": [], "placeholder": placeholder}

    page_specs = copy_obj.get("pages") or []
    for p in range(1, pages_target + 1):
        src = os.path.join(nd, "images", "page-%02d.png" % p)
        if os.path.exists(src):
            base = cover_crop(Image.open(src), W, H)
        elif placeholder:
            base = placeholder_base(W, H, spec, seed=p)
        else:
            manifest["missing_pages"].append(p)
            common.log_event(run_root, "S4",
                             "第%d篇第%d页配图缺失，已跳过，需人工补图" % (idx, p), "warn",
                             {"page": p, "expect_path": src})
            continue
        canvas = base.convert("RGBA")

        if p == 1:
            texts = {
                "eyebrow": copy_obj.get("eyebrow") or ("%s · 图文" % spec["keyword"]),
                "title": copy_obj.get("title", ""),
                "subtitle": copy_obj.get("cover_line", ""),
                "highlight": copy_obj.get("highlight", ""),
                "sticker": copy_obj.get("sticker", ""),
            }
        else:
            ps = page_specs[p - 2] if p - 2 < len(page_specs) else {}
            texts = {
                "eyebrow": ps.get("eyebrow") or ("要点 %02d" % (p - 1)),
                "title": ps.get("headline", ""),
                "body": ps.get("body", ""),
                "highlight": ps.get("highlight", ""),
            }
        canvas, band_h, capped = render_page(canvas, spec, texts, p, pages_target, p == 1)
        canvas, logo_info = place_logo(canvas, logo_img, spec, busy_threshold,
                                       keepout_bottom=band_h + 8)

        out = os.path.join(out_dir, "page-%02d.png" % p)
        canvas.convert("RGB").save(out, "PNG")
        manifest["pages"].append({"page": p, "file": os.path.relpath(out, run_root),
                                  "band_h": band_h, "band_capped": capped, "logo": logo_info})
        if capped:
            common.log_event(run_root, "S4", "第%d篇第%d页文字超出色带，已按上限压缩" % (idx, p), "warn")
        if logo_info["degraded"]:
            common.log_event(run_root, "S4", "第%d篇第%d页 LOGO 位置已降级处理" % (idx, p), "warn",
                             {"busy": logo_info["busy"]})
    if not manifest["pages"]:
        raise RuntimeError("第%d篇无任何可用配图（全部缺失）" % idx)
    common.jdump(os.path.join(nd, "compose-manifest.json"), manifest)
    return manifest


def run(run_root, placeholder=False):
    meta = common.load_run(run_root)
    cfg = common.load_config()
    spec = common.jload(os.path.join(run_root, "data", "spec.json"))
    if spec is None:
        common.die("缺少 spec.json，请先执行 spec 阶段")
    if not os.path.exists(spec["logo"]["path"]):
        common.die("LOGO 文件不存在：%s" % spec["logo"]["path"])
    manifests = []
    for idx, note in enumerate(meta["notes"], start=1):
        try:
            m = compose_note(run_root, idx, note, spec, cfg, placeholder)
            manifests.append(m)
            print("  #%d 合成 %d 张（%dx%d，主题 %s）%s"
                  % (idx, len(m["pages"]), spec["image"]["width"], spec["image"]["height"],
                     spec["design"]["theme"], "（占位底图模式）" if placeholder else ""))
        except Exception as e:
            common.jdump(os.path.join(common.note_dir(run_root, idx), "compose-manifest.json"),
                         {"index": idx, "failed": True, "error": str(e), "pages": []})
            common.log_event(run_root, "S4", "第%d篇合成失败：%s" % (idx, e), "error")
            print("  ✗ #%d 合成失败：%s" % (idx, e))
    return manifests


def main():
    ap = argparse.ArgumentParser(description="阶段4 配图合成")
    ap.add_argument("--run", required=True)
    ap.add_argument("--placeholder", action="store_true", help="缺图时用占位底图（仅用于链路自测）")
    args = ap.parse_args()
    ms = run(args.run, args.placeholder)
    if len(ms) == 0:
        sys.exit(1)
    common.ok("配图合成完成：%d 篇" % len(ms))


if __name__ == "__main__":
    main()

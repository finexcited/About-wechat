# -*- coding: utf-8 -*-
"""spec_extract.py — 阶段 2：平台规范基线 + 本次素材参考统计。

原则：
  · 尺寸、张数、标题/正文字数、话题格式等「硬规范」以微信公众号贴图（newspic）官方文档为准，
    不从抓取素材反向决定（素材来自公众号/小红书/热点，形态各异，不能拿来定平台规则）；
  · 抓取素材只用于「参考」：色彩倾向、版式密度、常见字数，写进 spec 供设计与改写参考；
  · 所有取舍都写进 spec-extracted.md，不静默处理。
"""
import argparse
import json
import os
import sys
from collections import Counter

from PIL import Image, ImageFilter, ImageStat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

COMMON_RATIOS = [(3, 4), (4, 3), (1, 1), (9, 16), (16, 9), (2, 3), (3, 2), (4, 5), (5, 4)]
STABLE_BLUE = "#1B3A5C"
TARGET_W, TARGET_H = 1080, 1440      # 3:4 竖版，满足平台最小边 ≥720

LAYOUT = {
    "skeleton_id": "PLATFORM-L1",
    "description": "顶部品牌色带压标题 + 中部主体场景 + 底部信息条",
    "title_align": "left",
    "title_font_ratio": 0.082,
    "body_font_ratio": 0.031,
    "line_spacing": 1.38,
    "bands": [
        {"name": "title", "top": 0.0, "height": 0.32, "align": "left"},
        {"name": "body", "top": 0.32, "height": 0.36, "align": "left"},
        {"name": "footer", "top": 0.86, "height": 0.14, "align": "left"},
    ],
}


def ratio_of(w, h):
    best, best_err = (w, h), 9e9
    for a, b in COMMON_RATIOS:
        err = abs((w / float(h)) - (a / float(b)))
        if err < best_err:
            best, best_err = (a, b), err
    return best, best_err


def dominant_color(img):
    small = img.convert("RGB").resize((64, 64))
    q = small.quantize(colors=8, method=Image.MEDIANCUT).convert("RGB")
    counts = Counter(q.getdata())
    best, best_weight = None, -1
    for rgb, cnt in counts.items():
        mx, mn = max(rgb), min(rgb)
        sat = 0 if mx == 0 else (mx - mn) / float(mx)
        if sat < 0.18 and 60 < mx < 220:
            continue
        weight = cnt * (0.4 + sat)
        if weight > best_weight:
            best, best_weight = rgb, weight
    if best is None:
        best = counts.most_common(1)[0][0]
    return "#%02X%02X%02X" % best


def dominant_color_alpha(img):
    rgba = img.convert("RGBA")
    pixels = [(r, g, b) for r, g, b, a in rgba.getdata() if a > 128]
    if not pixels:
        return None
    counts = Counter(pixels)
    best, best_weight = None, -1
    for rgb, cnt in counts.items():
        mx, mn = max(rgb), min(rgb)
        sat = 0 if mx == 0 else (mx - mn) / float(mx)
        if sat < 0.15 and mx > 235:
            continue
        weight = cnt * (0.4 + sat)
        if weight > best_weight:
            best, best_weight = rgb, weight
    if best is None:
        best = counts.most_common(1)[0][0]
    return "#%02X%02X%02X" % best


def hue_of(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return 0.0, 0.0
    d = mx - mn
    if mx == r:
        hh = ((g - b) / d) % 6
    elif mx == g:
        hh = (b - r) / d + 2
    else:
        hh = (r - g) / d + 4
    return hh * 60.0, (d / mx if mx else 0.0)


def ink_density(img):
    g = img.convert("L").resize((480, 640))
    return ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0]


def build_design(cfg, primary, accent):
    d = cfg["design"]
    palette = dict(d["palette"])
    palette["primary"] = primary
    palette["accent"] = accent
    return {"theme": d["theme"], "audience": d["audience"],
            "style_keywords": d["style_keywords"], "image_style": d["image_style"],
            "tokens": d["tokens"], "palette": palette}


def extract(run_root, layout_json=None, images_per_note=None, log=None):
    meta = common.load_run(run_root)
    cfg = common.load_config()
    platform = cfg["platform"]
    policy = cfg["text_policy"]

    # ---- 素材参考统计（仅参考，不定规则）----
    ref_images, colors, chars = [], [], []
    for note in meta["notes"]:
        cover = os.path.join(run_root, "data", "covers", "%s.img" % note["id"])
        rec = {"note_id": note["id"], "channel": note.get("channel"), "title": note["title"]}
        if os.path.exists(cover):
            try:
                with Image.open(cover) as im:
                    im.load()
                    w, h = im.size
                    rec.update({"width": w, "height": h})
                    rec["ratio"] = "%d:%d" % ratio_of(w, h)[0]
                    colors.append(dominant_color(im))
            except Exception as e:
                rec["error"] = "封面解析失败：%s" % e
                if log:
                    log("S2", "封面解析失败 %s：%s" % (note["id"], e), "warn")
        else:
            rec["error"] = "无封面（该渠道不提供封面）"
        chars.append(len(note.get("desc") or ""))
        ref_images.append(rec)

    valid = [r for r in ref_images if r.get("width")]
    ref_ratio = Counter(r["ratio"] for r in valid).most_common(1)[0][0] if valid else None
    color_counter = Counter(colors)
    observed = [{"hex": c, "count": n} for c, n in color_counter.most_common(5)]

    warm = 0
    for c, n in color_counter.items():
        h, s = hue_of(c)
        if s > 0.35 and (h < 60 or h > 330):
            warm += n
    total = sum(color_counter.values()) or 1
    switch_reason = None
    if warm / float(total) >= 0.6 and len(valid) >= 4:
        primary = color_counter.most_common(1)[0][0]
        switch_reason = "参考封面中 %d%% 为暖色调（%d 个样本），切换为实测主色 %s" % (
            round(100 * warm / total), len(valid), primary)
    else:
        primary = STABLE_BLUE
        if warm / float(total) >= 0.6:
            switch_reason = None
            if log:
                log("S2", "暖色样本仅 %d 个（少于 4 个），不切换主色，沿用品牌蓝" % len(valid), "warn")

    logo_path = meta["logo"]["path"]
    accent, logo_aspect = STABLE_BLUE, None
    try:
        with Image.open(logo_path) as lg:
            logo_aspect = round(lg.size[0] / float(lg.size[1]), 2)
            accent = dominant_color_alpha(lg) or accent
    except Exception:
        pass
    if logo_aspect and logo_aspect >= 2.2:
        logo_width_ratio = 0.18
        logo_width_reason = "LOGO 宽高比 %.2f（横版字标），取规范上限 18%% 保证可读" % logo_aspect
    else:
        logo_width_ratio = 0.15
        logo_width_reason = "LOGO 宽高比适中，取规范中值 15%%"

    if layout_json:
        layout = json.load(open(layout_json, "r", encoding="utf-8"))
        layout.setdefault("degraded", False)
    else:
        layout = dict(LAYOUT)

    count = images_per_note or cfg["defaults"]["images_per_note"]
    count = max(platform["image_count_min"], min(platform["image_count_max"], count))

    spec = {
        "spec_id": meta["run_id"] + "-spec",
        "keyword": meta["keyword"],
        "n": meta["n"],
        "generated_at": common.now_str(),
        "platform": {
            "name": platform["name"], "doc": platform["doc"],
            "image_count": [platform["image_count_min"], platform["image_count_max"]],
            "title_max": platform["title_max"], "content_max_chars": platform["content_max_chars"],
            "image_min_px": platform["image_min_px"], "image_max_mb": platform["image_max_mb"],
            "image_formats": platform["image_formats"],
            "cover_crop_ratios": platform["cover_crop_ratios"],
            "image_source": platform["image_source"], "topic_format": platform["topic_format"],
        },
        "image": {
            "aspect": "3:4", "width": TARGET_W, "height": TARGET_H,
            "baseline": "platform",
            "reason": "公众号贴图竖版 3:4，最小边 ≥%dpx；统一 1080×1440 兼顾清晰度与体积（≤%dMB）"
                      % (platform["image_min_px"], platform["image_max_mb"]),
            "reference": {"ratio_mode": ref_ratio, "samples": valid, "ref_note": "仅参考，不参与定规则"},
        },
        "image_count": {
            "platform_min": platform["image_count_min"],
            "platform_max": platform["image_count_max"],
            "chosen": count,
            "recommend": [4, 9],
            "basis": "本次按 --images-per-note 设定；平台硬上限 %d 张，首图即封面"
                     % platform["image_count_max"],
            "cover_note": "第 1 张为封面；cover_info 可裁 1_1 / 16_9 / 2.35_1",
        },
        "text": {
            "char_target": policy["body_target"],
            "char_limit_min": policy["body_min"],
            "char_limit_max": policy["body_max"],
            "char_basis": "platform_policy",
            "char_basis_reason": "公众号贴图是「图 + 短文案」，正文建议 %d–%d 字（平台上限 %d 字符）"
                                 % (policy["body_min"], policy["body_max"], platform["content_max_chars"]),
            "title_max": policy["title_max"],
            "title_target_max": policy["title_target_max"],
            "title_min": policy["title_min"],
            "topics_min": policy["topics_min"],
            "topics_max": policy["topics_max"],
            "per_image_text_max": policy["per_image_text_max"],
            "platform_hard_limit": platform["content_max_chars"],
            "text_policy_source": policy["source"],
            "reference_char_median": sorted(chars)[len(chars) // 2] if chars else 0,
            "reference_note": "素材正文字数中位数仅作语气参考；实际以贴图短文案口径为准",
        },
        "layout": layout,
        "color": {
            "primary": primary, "accent": accent,
            "rule": "默认稳重蓝 #1B3A5C + LOGO 主色强调；仅暖色调品类切换",
            "observed": observed, "switch_reason": switch_reason,
        },
        "design": build_design(cfg, primary, accent),
        "logo": {
            "path": logo_path, "position": "bottom-right", "padding_ratio": 0.07,
            "width_ratio": logo_width_ratio, "width_ratio_reason": logo_width_reason,
            "aspect": logo_aspect, "fallback_positions": ["bottom-left", "bottom-center"],
        },
    }
    common.jdump(os.path.join(run_root, "data", "spec.json"), spec)
    write_md(run_root, spec)
    if log:
        log("S2", "规范基线：%dx%d %s｜正文 %d–%d 字｜%d 张/篇"
                  % (TARGET_W, TARGET_H, spec["image"]["aspect"],
                     policy["body_min"], policy["body_max"], count))
    return spec


def write_md(run_root, spec):
    p, img, txt, col, lg = spec["platform"], spec["image"], spec["text"], spec["color"], spec["logo"]
    ic, lay, des = spec["image_count"], spec["layout"], spec["design"]

    lines = ["# spec-extracted.md — 阶段 2 规范（平台基线 + 素材参考）", "",
             "- 关键词：%s｜素材篇数：%d" % (spec["keyword"], spec["n"]),
             "- 生成时间：%s" % spec["generated_at"], ""]

    lines += ["## 1. 平台规范基线（硬规则）", "",
              "来源：[微信官方 draft/add 文档](%s) —— `article_type=newspic`（图片消息＝贴图）" % p["doc"], "",
              "| 项 | 平台规则 | 本次执行 |", "|---|---|---|",
              "| 图片张数 | %d–%d 张，首张为封面 | **%d 张** |" % (p["image_count"][0], p["image_count"][1], ic["chosen"]),
              "| 图片尺寸 | 最小边 ≥%dpx，单图 ≤%dMB，%s | **%d×%d（%s）** |"
              % (p["image_min_px"], p["image_max_mb"], "/".join(p["image_formats"]).upper(),
                 img["width"], img["height"], img["aspect"]),
              "| 标题 | ≤%d 字 | 目标 ≤%d 字 |" % (p["title_max"], txt["title_target_max"]),
              "| 正文 | ≤%d 字符，纯文本 | 目标 %d–%d 字 |"
              % (p["content_max_chars"], txt["char_limit_min"], txt["char_limit_max"]),
              "| 话题 | %s | %d–%d 个 |" % (p["topic_format"], txt["topics_min"], txt["topics_max"]),
              "| 封面裁剪 | %s | %s |" % ("/".join(p["cover_crop_ratios"]), "1_1"),
              "| 图片素材 | %s | 逐张上传为永久素材 |" % p["image_source"], ""]

    lines += ["## 2. 本次执行参数", "",
              "- 尺寸依据：%s" % img["reason"],
              "- 张数依据：%s" % ic["basis"],
              "- 封面说明：%s" % ic["cover_note"], ""]

    lines += ["## 3. 素材参考统计（不参与定规则）", ""]
    if img["reference"]["ratio_mode"]:
        lines += ["- 素材封面常见比例：%s（%d 个可测样本）"
                  % (img["reference"]["ratio_mode"], len(img["reference"]["samples"]))]
    lines += ["- 素材正文中位数：%d 字（%s）" % (txt["reference_char_median"], txt["reference_note"]), ""]
    lines += ["| # | 渠道 | 素材 | 尺寸 |", "|---|---|---|---|"]
    for i, r in enumerate(img["reference"]["samples"], 1):
        lines.append("| %d | %s | %s | %d×%d |" % (i, r.get("channel") or "-",
                                                  (r["title"] or "")[:18], r["width"], r["height"]))
    lines.append("")

    lines += ["## 4. 版式骨架", "",
              "- 骨架：`%s` — %s" % (lay.get("skeleton_id"), lay.get("description", "")),
              "- 标题对齐：%s；标题字宽比 %.3f；正文字宽比 %.3f；行距 %.2f"
              % (lay.get("title_align"), lay.get("title_font_ratio"), lay.get("body_font_ratio"), lay.get("line_spacing")),
              "- 分区：%s" % "；".join("`%s` 顶部 %.0f%%" % (b["name"], b["top"] * 100) for b in lay.get("bands", [])), ""]

    lines += ["## 5. 字数与话题", "",
              "- 正文目标：**%d 字**，允许 **%d–%d 字**（%s）"
              % (txt["char_target"], txt["char_limit_min"], txt["char_limit_max"], txt["char_basis"]),
              "- 依据：%s" % txt["char_basis_reason"],
              "- 标题：≤%d 字（平台上限 %d，建议 %d–%d 更利于信息流展示）"
              % (txt["title_target_max"], txt["title_max"], txt["title_min"], txt["title_target_max"]),
              "- 话题：%d–%d 个，写在正文内 `#话题名#`" % (txt["topics_min"], txt["topics_max"]),
              "- 单图文字：≤%d 字" % txt["per_image_text_max"],
              "- 口径来源：%s" % txt["text_policy_source"], ""]

    lines += ["## 6. 色系", "",
              "- 主色：`%s`；强调色（LOGO 主色）：`%s`" % (col["primary"], col["accent"]),
              "- 规则：%s" % col["rule"],
              "- 素材封面主色分布：%s" % "、".join("%s×%d" % (o["hex"], o["count"]) for o in col["observed"])]
    if col["switch_reason"]:
        lines.append("- 切换理由：%s" % col["switch_reason"])
    lines += ["", "## 7. 设计方向（人群驱动）", "",
              "- 目标人群：%s（%s 岁）" % (des["audience"]["name"], des["audience"]["age"]),
              "- 人群特征：%s" % "、".join(des["audience"]["traits"]),
              "- 设计含义：%s" % des["audience"]["implication"],
              "- 主题：`%s`；风格关键词：%s" % (des["theme"], des["style_keywords"]),
              "- 配图语气：%s" % des["image_style"],
              "- 色板：墨 `%s` / 主 `%s` / 强调 `%s` / 浅强调 `%s` / 纸 `%s`"
              % (des["palette"]["ink"], des["palette"]["primary"], des["palette"]["accent"],
                 des["palette"]["accent_soft"], des["palette"]["paper"]), ""]

    lines += ["## 8. LOGO 规则", "",
              "- 位置：%s（备选：%s）" % (lg["position"], " → ".join(lg["fallback_positions"])),
              "- 边距：短边 %.0f%%；宽度：图宽 %.0f%%（%s）"
              % (lg["padding_ratio"] * 100, lg["width_ratio"] * 100, lg.get("width_ratio_reason", "")), ""]

    common.write_text(os.path.join(run_root, "data", "spec-extracted.md"), "\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description="阶段2 平台规范基线")
    ap.add_argument("--run", required=True)
    ap.add_argument("--layout-json", default=None)
    ap.add_argument("--images-per-note", type=int, default=None)
    args = ap.parse_args()
    meta = common.load_run(args.run)
    log = lambda s, m, lv="info": common.log_event(args.run, s, m, lv)
    spec = extract(args.run, args.layout_json, args.images_per_note or meta.get("images_per_note"), log)
    common.ok("spec 已写入 %s" % os.path.join(args.run, "data", "spec-extracted.md"))
    print("  → %dx%d %s｜正文 %d–%d 字｜%d 张/篇"
          % (spec["image"]["width"], spec["image"]["height"], spec["image"]["aspect"],
             spec["text"]["char_limit_min"], spec["text"]["char_limit_max"],
             spec["image_count"]["chosen"]))


if __name__ == "__main__":
    main()

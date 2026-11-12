# -*- coding: utf-8 -*-
"""check_compliance.py — 阶段 5 合规自检（六项，全部通过才允许进入阶段 6）。

① 字数合规 ② 去重合规 ③ 尺寸合规 ④ LOGO 在位 ⑤ 图片数量合规 ⑥ 色系合规
任何一项 FAIL → 退出码 1，草稿阶段拒绝执行。
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageStat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import spec_extract


def logo_present(page_path, logo_path, bbox):
    """按 LOGO 不透明像素做颜色回比，判断 LOGO 是否真的落在该区域。"""
    with Image.open(page_path) as page:
        page = page.convert("RGB")
        region = page.crop(tuple(bbox))
    with Image.open(logo_path) as lg:
        lg = lg.convert("RGBA").resize(region.size, Image.LANCZOS)
    alpha = lg.split()[-1]
    mask = alpha.point(lambda v: 255 if v > 128 else 0)
    if mask.getbbox() is None:
        return False, 999.0
    m1 = ImageStat.Stat(region, mask=mask).mean
    m2 = ImageStat.Stat(lg.convert("RGB"), mask=mask).mean
    diff = sum(abs(a - b) for a, b in zip(m1, m2)) / 3.0
    return diff < 28.0, round(diff, 2)


def _lum(hexcolor):
    h = (hexcolor or "#FFFFFF").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except Exception:
        return 0.0

    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def artifact_sig(nd, manifest, run_root):
    """产物签名：copy.json + 全部合成图，用于草稿阶段判定自检是否仍对应当前产物。"""
    import hashlib
    h = hashlib.sha1()
    for p in [os.path.join(nd, "copy.json")] + [common.resolve(run_root, pg["file"]) for pg in manifest["pages"]]:
        if os.path.exists(p):
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()[:16]


def check_note(run_root, idx, note, spec, cfg):
    nd = common.note_dir(run_root, idx)
    items = []

    tc = common.jload(os.path.join(nd, "textcheck.json"))
    if tc is None:
        items.append({"id": "1-字数", "status": "FAIL", "detail": "缺少 textcheck.json"})
        items.append({"id": "2-去重", "status": "FAIL", "detail": "缺少 textcheck.json"})
    else:
        t_ok = tc.get("title_ok", True)
        detail = "正文 %d 字（允许 %d–%d，%s）；标题 %d/%d 字；话题 %d 个" % (
            tc["char_count"], tc["char_target"]["min"], tc["char_target"]["max"],
            tc["char_target"].get("basis", "-"), tc.get("title_chars", 0),
            tc.get("title_max", 32), tc.get("topics_count", 0))
        if tc.get("page_text_over_limit"):
            detail += "；单图文字超限：%s" % "、".join(
                "第%d页%d字" % (p["page"], p["chars"]) for p in tc["page_text_over_limit"])
        items.append({"id": "1-文案", "status": "PASS" if (tc["char_ok"] and t_ok and tc.get("topics_ok", True)) else "FAIL",
                      "detail": detail})
        items.append({"id": "2-去重", "status": "PASS" if tc["dedupe_ok"] else "FAIL",
                      "detail": "与源文最大连续 5-8 字重合 %.1f%%（阈值 %.0f%%）"
                                % (tc["max_overlap"] * 100,
                                   common.load_config()["defaults"]["max_overlap"] * 100)})

    manifest = common.jload(os.path.join(nd, "compose-manifest.json"))
    W, H = spec["image"]["width"], spec["image"]["height"]
    if manifest is None or not manifest.get("pages"):
        reason = "缺少 compose-manifest.json" if manifest is None else (
            "合成失败：%s" % manifest.get("error") if manifest.get("failed") else "无任何合成产物")
        for i in ("3-尺寸", "4-LOGO", "5-张数"):
            items.append({"id": i, "status": "FAIL", "detail": reason})
    else:
        bad = []
        for p in manifest["pages"]:
            with Image.open(common.resolve(run_root, p["file"])) as im:
                if im.size != (W, H):
                    bad.append("page-%02d %s" % (p["page"], im.size))
        items.append({"id": "3-尺寸", "status": "PASS" if not bad else "FAIL",
                      "detail": "全部 %d 张均 %dx%d" % (len(manifest["pages"]), W, H) if not bad
                                else "尺寸不符：%s" % "；".join(bad)})

        logo_cfg = spec["logo"]
        problems, degraded = [], 0
        for p in manifest["pages"]:
            li = p["logo"]
            if li["degraded"]:
                degraded += 1
            present, diff = logo_present(common.resolve(run_root, p["file"]), logo_cfg["path"], li["bbox"])
            li["verified_diff"] = diff
            ratio = li["scale_ratio"]
            margin = li["short_side_margin_ratio"]
            ok_w = 0.12 <= ratio <= 0.18 or li["degraded"]
            ok_m = 0.05 <= margin <= 0.08 or li["degraded"]
            ok_pos = li["position"] in ([logo_cfg["position"]] + logo_cfg["fallback_positions"])
            if not (present and ok_w and ok_m and ok_pos):
                problems.append("page-%02d present=%s w=%.3f margin=%.3f pos=%s"
                                % (p["page"], present, ratio, margin, li["position"]))
        if problems:
            items.append({"id": "4-LOGO", "status": "FAIL", "detail": "；".join(problems)})
        elif degraded:
            items.append({"id": "4-LOGO", "status": "PASS",
                          "detail": "%d/%d 张为降级处理（原位+衬底），其余合规"
                                    % (degraded, len(manifest["pages"]))})
        else:
            items.append({"id": "4-LOGO", "status": "PASS",
                          "detail": "全部 %d 张在位，位置/尺寸/边距合规" % len(manifest["pages"])})

        target = spec["image_count"].get("chosen") or spec["image_count"].get("fallback")
        count = len(manifest["pages"])
        ok_count = abs(count - target) <= 1
        missing = manifest.get("missing_pages") or []
        detail = "%d 张 / 本次设定 %d 张（平台上限 %d）" % (
            count, target, spec["image_count"].get("platform_max", 20))
        if missing:
            detail += "；第 %s 页配图缺失，需人工补图" % "、".join(str(m) for m in missing)
        items.append({"id": "5-张数", "status": "PASS" if ok_count else "FAIL",
                      "detail": detail})

    # 第六项：配色可读性
    # 启用设计哲学后，每篇底色/墨色都不同（酸性黄、牛皮纸、纯白…），
    # 再按「必须偏蓝」判会把合规的哲学误杀；改为校验纸底与正文的对比度，
    # 这才是自定义哲学时真正会踩的坑（配色好看但字看不清）。
    pal = (manifest or {}).get("philosophy_palette")
    if pal:
        cr = _contrast(pal.get("paper", "#FFFFFF"), pal.get("body") or pal.get("ink", "#000000"))
        ok = cr >= 4.5
        detail = "纸底 %s / 正文 %s，对比度 %.1f:1" % (
            pal.get("paper"), pal.get("body") or pal.get("ink"), cr)
        items.append({"id": "6-色系", "status": "PASS" if ok else "FAIL",
                      "detail": detail + ("" if ok else "（低于 4.5:1，正文会看不清）")})
    else:
        col = spec["color"]
        hue, sat = spec_extract.hue_of(col["primary"])
        blue_ok = 195 <= hue <= 250
        if blue_ok or col.get("switch_reason"):
            detail = "主色 %s（色相 %.0f°）" % (col["primary"], hue)
            if col.get("switch_reason"):
                detail += "；已记录切换理由"
            items.append({"id": "6-色系", "status": "PASS", "detail": detail})
        else:
            items.append({"id": "6-色系", "status": "FAIL",
                          "detail": "主色 %s 不在稳重蓝色族且未记录切换理由" % col["primary"]})

    sig = artifact_sig(nd, manifest, run_root) if manifest else None
    return {"index": idx, "note_id": note["id"], "items": items,
            "artifact_sig": sig,
            "pass": all(i["status"] == "PASS" for i in items)}


def run(run_root):
    meta = common.load_run(run_root)
    spec = common.jload(os.path.join(run_root, "data", "spec.json"))
    if spec is None:
        common.die("缺少 spec.json")
    cfg = common.load_config()
    result = {"checked_at": common.now_str(), "notes": [], "all_pass": True}
    for idx, note in enumerate(meta["notes"], start=1):
        r = check_note(run_root, idx, note, spec, cfg)
        result["notes"].append(r)
        result["all_pass"] = result["all_pass"] and r["pass"]
        common.log_event(run_root, "S5", "第%d篇自检 %s" % (idx, "PASS" if r["pass"] else "FAIL"),
                         "info" if r["pass"] else "warn",
                         {"items": r["items"]})
        print("  #%d %s" % (idx, "PASS" if r["pass"] else "FAIL"))
        for it in r["items"]:
            mark = "✓" if it["status"] == "PASS" else "✗"
            print("     %s %s：%s" % (mark, it["id"], it["detail"]))
    common.jdump(os.path.join(run_root, "data", "selfcheck.json"), result)
    write_md(run_root, result, spec)
    return result


def write_md(run_root, result, spec):
    lines = ["# selfcheck.md — 阶段 5 合规自检（公众号贴图）", "",
             "- 时间：%s" % result["checked_at"],
             "- 结论：**%s**" % ("全部通过" if result["all_pass"] else "存在未通过项，禁止进入草稿阶段"),
             "", "| 篇 | " + " | ".join(["①文案", "②去重", "③尺寸", "④LOGO", "⑤张数", "⑥色系"]) + " | 结论 |",
             "|---|" + "---|" * 6 + "---|"]
    for r in result["notes"]:
        cells = [("✓" if i["status"] == "PASS" else "✗") for i in r["items"]]
        lines.append("| %d | %s | %s |" % (r["index"], " | ".join(cells),
                                           "PASS" if r["pass"] else "FAIL"))
    lines.append("")
    for r in result["notes"]:
        lines.append("## 第 %d 篇" % r["index"])
        for i in r["items"]:
            lines.append("- %s **%s**：%s" % ("✓" if i["status"] == "PASS" else "✗", i["id"], i["detail"]))
        lines.append("")
    common.write_text(os.path.join(run_root, "data", "selfcheck.md"), "\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description="阶段5 合规自检")
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    r = run(args.run)
    if not r["all_pass"]:
        sys.exit(1)
    common.ok("六项自检全部通过")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""textcheck.py — 阶段 3.3 硬性关卡：字数控制 + 中文 n-gram 重合检测。

口径（与 SKILL 一致）：
  · 字数 = 归一化后（去 emoji 标记/标点/空白）的字符数，含标题与正文
  · n-gram：n ∈ {5,6,7,8} 的连续字片段，取对单一源文的最大重合占比
  · 判定：max_overlap < 0.15 且字数在 spec 中位数 ±15% → PASS
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

EMOJI_TAG = re.compile(r"\[[^\[\]]{1,8}R\]")   # 素材中的表情标记，归一化时剔除
TOPIC_RE = re.compile(r"#([^#\s]{1,20})#")        # 公众号贴图话题：#话题名#
CTRL = re.compile(r"[\s\u3000]+")


def normalize(text):
    t = EMOJI_TAG.sub("", text or "")
    t = CTRL.sub("", t)
    return "".join(ch for ch in t if ch.isalnum())


def ngrams(text, n):
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def overlap_ratio(cand, source, n):
    cg = ngrams(cand, n)
    if not cg:
        return 0.0, set()
    sg = ngrams(source, n)
    hit = cg & sg
    return len(hit) / float(len(cg)), hit


# AI 味体检（软指标）：只提示，不阻断。
# 强信号＝几乎只在套话里出现；弱信号＝正常写作也会用（首先/最后/还是），给低权重。
AI_STRONG = [
    "不仅仅是", "在这个", "随着", "值得注意", "综上", "总而言之", "让我们",
    "赋能", "打造", "抓手", "闭环", "颗粒度", "底层逻辑", "不断提升", "持续优化",
    "核心在于", "关键在于", "不难发现", "众所周知", "显而易见", "都值得",
]
AI_WEAK = ["不仅", "首先", "其次", "最后", "接下来", "换句话说", "真正的",
           "无论是", "还是", "所谓", "维度", "深度"]
AI_PATTERNS = [
    (re.compile(r"不是.{1,12}而是"), "不是…而是（对偶句）", 1.0),
    (re.compile(r"既.{1,10}又"), "既…又（套话对偶）", 0.6),
    (re.compile(r"从.{1,8}到.{1,8}，"), "从…到…（排比铺陈）", 0.6),
]


def ai_smell(text):
    """加权 AI 味密度（每千字）。强信号 1 分，弱信号 0.35 分，句式 0.6–1 分。

    ≥8 基本说明没做去 AI 味；4–8 属于偏书面；<4 正常。
    """
    t = text or ""
    strong, weak = {}, {}
    for w in AI_STRONG:
        c = t.count(w)
        if c:
            strong[w] = c
    for w in AI_WEAK:
        c = t.count(w)
        if c:
            weak[w] = c
    pats, score = [], 0.0
    for rx, label, weight in AI_PATTERNS:
        n = len(rx.findall(t))
        if n:
            pats.append({"pattern": label, "count": n})
            score += n * weight
    score += sum(strong.values()) + sum(weak.values()) * 0.35
    # 短文本按 120 字归一，避免几十个字就把密度放大到不可比
    total_chars = max(120, len(normalize(t)))
    density = round(score * 1000.0 / total_chars, 1)
    return {"strong": strong, "weak": weak, "patterns": pats,
            "hits": dict(sorted(list(strong.items()) + list(weak.items()),
                                key=lambda kv: -kv[1])[:6]),
            "score": round(score, 2), "per_1000": density,
            "level": "高" if density >= 8 else ("中" if density >= 4 else "低"),
            "smelly": density >= 8}


def check_note(copy_obj, sources, spec, thresholds):
    title = copy_obj.get("title", "")
    body = copy_obj.get("body", "")
    topics = copy_obj.get("topics") or TOPIC_RE.findall(body)
    body_core = TOPIC_RE.sub("", body)
    cand = normalize(title + body_core + "".join(topics))
    # 正文字数只算正文（话题另计），标题另按标题上限判定
    char_count = len(normalize(body_core))
    title_chars = len(normalize(title))

    txt = spec["text"]
    lo = txt.get("char_limit_min")
    hi = txt.get("char_limit_max")
    if lo is None or hi is None:
        median = txt["char_median"] or 1
        tol = txt.get("char_tolerance", 0.15)
        lo, hi = int(median * (1 - tol)), int(median * (1 + tol))
        basis = "source_median"
    else:
        basis = txt.get("char_basis", "policy")
    char_ok = lo <= char_count <= hi
    title_max = txt.get("title_max", 32)
    title_target = txt.get("title_target_max", 20)
    title_ok = txt.get("title_min", 0) <= title_chars <= title_max
    title_warn = title_chars > title_target
    n_topics = len(topics)
    topics_ok = txt.get("topics_min", 0) <= n_topics <= txt.get("topics_max", 99)

    per_source = []
    for src in sources:
        s_norm = normalize(src["desc"])
        ratios = {}
        worst_hit = set()
        worst_n = None
        worst = 0.0
        for n in thresholds["ngram_ns"]:
            r, hit = overlap_ratio(cand, s_norm, n)
            ratios[str(n)] = round(r, 4)
            if r > worst:
                worst, worst_hit, worst_n = r, hit, n
        per_source.append({
            "source_id": src["id"],
            "source_title": src["title"],
            "overlap_by_n": ratios,
            "max_overlap": round(worst, 4),
            "worst_n": worst_n,
            "sample_hits": sorted(worst_hit)[:12],
        })
    max_overlap = max([p["max_overlap"] for p in per_source], default=0.0)
    dedupe_ok = max_overlap < thresholds["max_overlap"]

    page_over = []
    limit_per_page = txt.get("per_image_text_max")
    for i, pg in enumerate(copy_obj.get("pages") or [], start=2):
        n = len(normalize((pg.get("headline") or "") + (pg.get("body") or "")))
        if limit_per_page and n > limit_per_page:
            page_over.append({"page": i, "chars": n})
    return {
        "char_count": char_count,
        "char_target": {"min": int(lo), "max": int(hi), "basis": basis},
        "char_ok": char_ok,
        "title_chars": title_chars,
        "title_max": title_max,
        "title_target_max": title_target,
        "title_warn": title_warn,
        "title_ok": title_ok,
        "topics": topics,
        "topics_count": n_topics,
        "topics_ok": topics_ok,
        "page_text_over_limit": page_over,
        "max_overlap": max_overlap,
        "dedupe_ok": dedupe_ok,
        "sources": per_source,
        "ai_smell": ai_smell(body_core),
        "pass": bool(char_ok and dedupe_ok and title_ok and topics_ok),
    }


def run(run_root, only=None):
    meta = common.load_run(run_root)
    spec = common.jload(os.path.join(run_root, "data", "spec.json"))
    if spec is None:
        common.die("缺少 spec.json，请先执行 spec 阶段")
    cfg = common.load_config()
    thresholds = {"ngram_ns": cfg["defaults"]["ngram_ns"],
                  "max_overlap": cfg["defaults"]["max_overlap"]}

    spec_tol = spec["text"].get("char_tolerance", 0.15)
    summary = {"checked_at": common.now_str(), "thresholds": thresholds, "notes": []}
    all_pass = True
    for idx, note in enumerate(meta["notes"], start=1):
        nd = common.note_dir(run_root, idx)
        copy_path = os.path.join(nd, "copy.json")
        if not os.path.exists(copy_path):
            summary["notes"].append({"index": idx, "status": "missing_copy",
                                     "pass": False})
            all_pass = False
            continue
        copy_obj = common.jload(copy_path)
        res = check_note(copy_obj, meta["notes"], spec, thresholds)
        res.update({"index": idx, "note_id": note["id"], "title": copy_obj.get("title", "")})
        res["status"] = "pass" if res["pass"] else "fail"
        all_pass = all_pass and res["pass"]
        common.jdump(os.path.join(nd, "textcheck.json"), res)
        summary["notes"].append(res)
        common.log_event(run_root, "S3",
                         "第%d篇 正文 %d 字（%d–%d）标题 %d 字 话题 %d 个 重合 %.1f%% → %s"
                         % (idx, res["char_count"], res["char_target"]["min"],
                            res["char_target"]["max"], res["title_chars"],
                            res.get("topics_count", 0), res["max_overlap"] * 100,
                            "PASS" if res["pass"] else "FAIL"),
                         "info" if res["pass"] else "warn")
    summary["all_pass"] = all_pass
    common.jdump(os.path.join(run_root, "data", "textcheck.json"), summary)
    for r in summary["notes"]:
        if r.get("status") == "missing_copy":
            print("  #%s 缺少 copy.json（需先完成阶段3改写）" % r["index"])
        else:
            print("  #%d 正文 %d 字（%d–%d）｜标题 %d 字｜话题 %d 个｜重合 %.1f%%｜%s"
                  % (r["index"], r["char_count"], r["char_target"]["min"],
                     r["char_target"]["max"], r["title_chars"], r.get("topics_count", 0),
                     r["max_overlap"] * 100, "PASS" if r["pass"] else "FAIL"))
            ai = r.get("ai_smell") or {}
            if ai.get("level") == "高":
                top = "、".join("%s×%d" % (k, v) for k, v in
                               list(ai["hits"].items())[:4])
                print("       ⚠️ AI 味偏重（%s，%.1f/千字）%s → 先走阶段 3.4 humanizer-zh"
                      % (ai["level"], ai["per_1000"], top))
            else:
                print("       · AI 味体检：%s（%.1f/千字）" % (ai["level"], ai["per_1000"]))
    return summary


def main():
    ap = argparse.ArgumentParser(description="阶段3 去重与字数校验")
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    s = run(args.run)
    if not s["all_pass"]:
        sys.exit(1)
    common.ok("阶段3 校验通过")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""philosophy.py — 设计哲学库的加载与分配。

一套哲学 = 一套完整的设计语言：
  配色 / 栏网格 / 字号节奏 / 图像处理 / 版式原型集合 / 配图风格。

分配规则（可复现）：
  第 i 篇取 order[((i-1) * stride) % n]，stride 与 n 互质时，前 n 篇恰好
  每套各出现一次，相邻两篇必不同。默认 stride=2 就是按这个目的取的。

同一篇在 compose 与 prompts 两个阶段必须拿到同一套哲学，所以这里是唯一
的实现点，两边都 import 它，不各自写一份。
"""
import json
import math
import os

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHIL_DIR = os.path.join(SKILL_DIR, "assets", "design-philosophies")
LEGACY_TOKENS = os.path.join(SKILL_DIR, "assets", "design-tokens.json")

DEFAULT_KEYS = {
    "palette": {"paper": "#F7F4EE", "ink": "#1B3A5C", "accent": "#ED6C1D",
                "muted": "#8A8F98", "line": "#D8D2C6", "sub": "#3B4A5A", "body": "#2E3B4A"},
    "grid": {"columns": 12, "margin": 72, "gutter": 24},
    "type": {"title_min": 92, "title_max": 148, "title_line_height": 0.95, "headline": 62,
             "body": 33, "body_line_height": 1.72, "meta": 19, "meta_tracking": "0.18em",
             "numeral": 300},
    "rules": {"hairline": 1, "accent_bar": 8},
    "photo": {"filter": "saturate(.94) contrast(1.02)"},
    "skin": {"photo_border": "0", "show_hair": True, "focus": "left"},
    "layout": {"cover": ["cover-hero-bleed", "cover-photo-top"],
               "inner": ["inner-editorial", "inner-quote-band", "inner-photo-top"]},
}


def _jload(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize(ph):
    """补齐缺省字段，让老的 tokens 文件也能当作一套哲学用。"""
    out = dict(ph)
    out.setdefault("id", "legacy")
    out.setdefault("name", out.get("philosophy", "Legacy"))
    out.setdefault("philosophy", out["name"])      # 旧接口兼容：load_tokens()["philosophy"]
    out.setdefault("name_zh", out["name"])
    out.setdefault("claim", "")
    out.setdefault("signature", [])
    out.setdefault("canvas", {"width": 1080, "height": 1440})
    out.setdefault("grain", 0.05)
    out.setdefault("photo_style", "")
    for k, v in DEFAULT_KEYS.items():
        cur = out.get(k) or {}
        if isinstance(v, dict):
            merged = dict(v)
            merged.update(cur)
            out[k] = merged
        else:
            out[k] = cur or v
    return out


def dir_available():
    return os.path.isdir(PHIL_DIR) and os.path.exists(os.path.join(PHIL_DIR, "index.json"))


def load_all(cfg=None):
    """返回 (philosophies, index)。目录不存在时回落到单套 design-tokens.json。"""
    cfg = cfg or {}
    conf = (cfg.get("design") or {}).get("philosophies") or {}
    enabled = conf.get("enabled", True)

    if not (enabled and dir_available()):
        legacy = _normalize(_jload(LEGACY_TOKENS))
        return [legacy], {"order": [legacy["id"]], "stride": 1, "legacy": True}

    index = _jload(os.path.join(PHIL_DIR, "index.json"))
    order = list(index.get("order") or [])
    pool = conf.get("pool") or []
    if pool:
        order = [i for i in order if i in pool]
    phils = []
    for pid in order:
        p = os.path.join(PHIL_DIR, "%s.json" % pid)
        if os.path.exists(p):
            phils.append(_normalize(_jload(p)))
    if not phils:
        legacy = _normalize(_jload(LEGACY_TOKENS))
        return [legacy], {"order": [legacy["id"]], "stride": 1, "legacy": True}
    index["stride"] = int(conf.get("stride") or index.get("stride") or 1)
    return phils, index


def assign(note_idx, phils, index):
    """第 note_idx 篇（从 1 开始）用哪套哲学。同一输入永远同一输出。"""
    n = len(phils)
    stride = int(index.get("stride") or 1) % n
    if stride == 0:
        stride = 1
    while n > 1 and math.gcd(stride, n) != 1:   # 保证前 n 篇不重复
        stride += 1
    return phils[((note_idx - 1) * stride) % n]


def plan(notes_n, phils, index):
    return [assign(i, phils, index)["id"] for i in range(1, notes_n + 1)]


def varies(phils, index):
    """理论上一批里会出现几套不同的哲学。"""
    return min(len(phils), len(plan(max(1, len(phils)), phils, index)))


def summary(phils, index, notes_n=None):
    ids = plan(notes_n or len(phils), phils, index)
    uniq = []
    for i in ids:
        if i not in uniq:
            uniq.append(i)
    return "哲学库 %d 套，本批用到 %d 套：%s" % (len(phils), len(uniq), " → ".join(ids))

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字体字形可用性：找出「当前字体渲染不出来」的字符。

为什么需要
----------
PNG 长图与封面是 PIL 绘制，**只加载 Noto Sans SC 一个字体文件，没有字体回退**。
字体里没有的字符会被画成 .notdef——一个带叉的方框。实测：

    ✅ 🔥 📌 👉 🎯 → 五个一模一样的叉框
    ⚠ → ※ ① ·   → 正常（这些单色符号字体里确实有）
    藏文 བ / 梵文 क / 扩展汉字 𠮷 → 同样是叉框

而 `make_long_image.py` 照样输出「OK 长图已生成」，零警告。

为什么不按 Unicode 区间猜
------------------------
emoji 只是「渲染不出来」的一个子集。按区间（1F300–1FAFF、2600–27BF…）判定
会同时犯两种错：漏掉藏文/梵文/扩展汉字，误伤 ⚠ → ※ ① 这些字体里真有的符号。
所以这里直接问字体。

做法
----
拿一个几乎必然缺失的私用区码位渲染出 .notdef 位图当基准，逐字比对位图，
相同即「渲染不出来」。零依赖，不需要 fontTools。
"""
import re
from pathlib import Path

FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "NotoSansSC-VF.ttf"

# 私用区码位：正常字体不会有字形，必然落到 .notdef
_PROBE = "\ue000"
_font_cache = {}


def _font(size: int = 48):
    """按字号缓存字体对象（.notdef 的形状与字号无关，判定结果也一致）。"""
    if size not in _font_cache:
        from PIL import ImageFont

        _font_cache[size] = ImageFont.truetype(str(FONT_PATH), size)
    return _font_cache[size]


def _mask(font, ch: str):
    m = font.getmask(ch)
    return (tuple(m.size), bytes(m))


def missing_chars(text: str, size: int = 48) -> list:
    """返回 text 里当前字体渲染不出来的字符（去重，按首次出现顺序）。

    字体文件缺失或 Pillow 不可用时返回空列表——调用方不该因为「查不出来」
    就把整段文字剥掉。
    """
    try:
        font = _font(size)
        ref = _mask(font, _PROBE)
    except Exception:
        return []
    out, seen = [], set()
    for ch in text:
        if ch in seen or ch.isspace():
            continue
        seen.add(ch)
        try:
            if _mask(font, ch) == ref:
                out.append(ch)
        except Exception:
            continue
    return out


def _strip(text: str, bad: list) -> str:
    for ch in bad:
        text = text.replace(ch, "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    return text


def strip_missing(text: str, size: int = 48):
    """剥掉渲染不出来的字符，返回 (处理后的文本, 被剥的字符列表)。

    只清理由剥离产生的空白（行内连续空格、行尾空格），不动行首缩进——
    Markdown 的列表缩进是有语义的。
    """
    bad = missing_chars(text, size=size)
    return (_strip(text, bad) if bad else text), bad


def describe(chars: list) -> str:
    """把字符列表拼成给人看的一串，附带码位，方便对照替换。"""
    return " ".join(f"{c}(U+{ord(c):04X})" for c in chars)


def warn_dropped(bad: list, where: str, keep: bool):
    """统一口径的告警：剥离与保留都要说出来。"""
    import sys

    if keep:
        print(f"WARN: {where}保留了 {len(bad)} 个字体渲染不出的字符：{describe(bad)}\n"
              f"      它们会印成叉框（--keep-emoji 指定保留；去掉该参数即剥离）",
              file=sys.stderr)
    else:
        print(f"WARN: 已从{where}文字中剥离 {len(bad)} 个字体渲染不出的字符：{describe(bad)}\n"
              f"      PNG 用 Noto Sans SC，无彩色字形；HTML 版不受影响、原样保留。"
              f"要保留请加 --keep-emoji", file=sys.stderr)


def clean_for_png(text: str, where: str = "PNG", keep: bool = False):
    """PNG 渲染前置：剥离字体渲染不出的字符并打 WARN，返回 (文本, 被剥字符)。

    keep=True（--keep-emoji）时不动文字，只警告——留给以后自备彩色字体的使用者。
    两种情况下都要说出来：静默删字和静默印叉框一样是事故。
    """
    bad = missing_chars(text)
    if not bad:
        return text, []
    warn_dropped(bad, where, keep)
    return (text if keep else _strip(text, bad)), bad


def clean_many(texts: list, where: str = "PNG", keep: bool = False):
    """多段文字一起处理，告警合并成一条（封面有标题/副标题/关键词等六七个字段）。

    返回 (处理后的列表, 去重后的被剥字符)。
    """
    out, bad_all = [], []
    for t in texts:
        if keep:
            out.append(t)
            bad_all += missing_chars(t)
        else:
            cleaned, bad = strip_missing(t)
            out.append(cleaned)
            bad_all += bad
    bad_all = list(dict.fromkeys(bad_all))
    if bad_all:
        warn_dropped(bad_all, where, keep)
    return out, bad_all

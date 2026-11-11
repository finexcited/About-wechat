#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公众号 · 内容自动校验 v1

词库**实时解析** references/content-guidelines.md（单一数据源，不另维护副本）。

逐篇检查：
  - 标题：≤20 字、标题禁用词
  - 正文：谨慎词库（类别数按规范文件实际解析）、去 AI 味禁用句式
  - 结构：字数 800–2000、## 小标题、加粗重点、互动问题、收藏/转发引导
  - 条件归因：正文命中「归因触发词」→ 结尾（`> ` 行或最后 8 行）必须有「归因句式」，
              缺则 ✗ 必改；一条都没命中不要求（Q36）。
              句式匹配留一层宽松：首 3 字 + 末 2 字作锚、中间容许 ≤10 字插词，
              所以「以当年公告与岗位表为准」能命中「以当年公告为准」
  - 字体：正文含当前字体渲染不出的字符（emoji 等）时给 · 级提示，不阻断
批次检查：
  - 至少 1 篇含结构化块（Markdown 表格 / 清单）
  - 标题互不重复（2-gram Jaccard 相似度）

用法：
  python3 check_content.py 文章1.md 文章2.md ...
  python3 check_content.py --dir $WX_DAILY_OUT --date 2026-09-23
  python3 check_content.py 文章.md --warn-only    # 必改项放行：照旧逐条报错，只把退出码 1 改成 0
                                                 # （exit=2 的「根本没法质检」不受影响）

词库格式契约（五处锚点；改词库前看这里，写错就是「配了但没生效」）：
  ### 标题禁用词   下方**连续非空行**，「、」分隔（一行写完或分行写都认）
  ### 禁用句式     下方**连续非空行**，「/」或「／」分隔（句式自带斜杠请拆成两条）
  谨慎词库        章节标题（序号任意，正则匹配「…、谨慎词库」）+ `| 类别 | 词 |` 两列表格，
                  「、」分隔；**表格扫描到下一个同级标题即停**（末尾加附录表不会被误当词库）；
                  多出的列（如「说明」）只忽略、不参与校验
  #### 归因触发词   `| 类别 | 词 |` 表格，「、」分隔；命中任一条即要求结尾给来源（Q36）
  #### 归因句式     `| 类别 | 句式 |` 表格，「、」分隔；结尾出现任一条即通过
                  两张表缺任一 → 条件归因检查**不生效**（不阻断，但 ! 会写明）；
                  终止条件同上，按行首正则匹配标题，行内提及不会误命中
  --dump-lexicon 的 ✗ 才是真的失效（退出码 1）；! 是能解析但偏离契约（不阻断）

退出码：0 通过；1 存在 ERROR 级问题；2 没法质检（类目已改仍用示例规范文件、无稿件、目录不存在）
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brand import (GUIDELINES as _BRAND_GUIDELINES, VERTICAL,  # noqa: E402
                   article_plan, residue_is_consumed, sample_content_residue,
                   sample_guidelines_in_use, warn_sample_mismatch)

# 规范文件默认取 WX_GUIDELINES（换类目就换这份文件），可用 --guidelines 临时覆盖
GUIDELINES = _BRAND_GUIDELINES

# 每篇最少插图张数（Q22）。默认 1：没有插图的稿子在公众号里是纯文字墙，
# 完读率明显偏低，所以把它定成及格线而不是加分项。WX_MIN_ILLUS=0 可关掉。
try:
    MIN_ILLUS = max(0, int(os.environ.get("WX_MIN_ILLUS", "1")))
except ValueError:
    MIN_ILLUS = 1

CJK = r"\u4e00-\u9fff"


# ---------- 词库解析（从规范文件动态读取） ----------
def _heading_level(line: str) -> int:
    m = re.match(r"^(#{1,6})\s", line)
    return len(m.group(1)) if m else 0


# 谨慎词库的章节标题：**不写死序号**。换类目时重排章节号（六→五）曾让整张词库静默失效。
CAUTION_HEAD_RE = re.compile(r"^#{1,3}\s*[一二三四五六七八九十]+\s*[、.．]?\s*谨慎词库")

# 来源与归因（Q36）：两个小节标题同样不写死层级与序号
ATTRIB_TRIGGER_RE = re.compile(r"^#{2,6}\s*归因触发词")
ATTRIB_PHRASE_RE = re.compile(r"^#{2,6}\s*归因句式")


def _table_words_after(lines, i: int) -> list:
    """取锚点下方表格里第二列的词，按「、」拆开。

    终止条件与谨慎词库一致：遇到同级或更高级标题即停——否则文末再加一张表
    就会被当成这一节的词吃掉。
    """
    lvl = _heading_level(lines[i])
    out = []
    for row in lines[i + 1:]:
        if row.startswith("#") and _heading_level(row) <= lvl:
            break
        s = row.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2 or cells[0] == "类别":
            continue
        if set(cells[1]) <= set("-"):      # 分隔行
            continue
        out += [w.strip() for w in cells[1].split("、") if w.strip()]
    return out


def parse_attribution(lines) -> dict:
    """解析「归因触发词」与「归因句式」两张表。两者都缺＝该条件检查不启用。"""
    out = {"triggers": [], "phrases": []}
    for i, ln in enumerate(lines):
        if ATTRIB_TRIGGER_RE.match(ln):
            out["triggers"] = _table_words_after(lines, i)
        elif ATTRIB_PHRASE_RE.match(ln):
            out["phrases"] = _table_words_after(lines, i)
    return out


def phrase_hit(text: str, phrase: str) -> bool:
    """归因句是否出现：原句优先，再容忍句中插词。

    按原句做子串匹配会误杀最常见的自然写法——实测作者写
    「具体报考条件以当年公告与岗位表为准」，句式表里是「以当年公告为准」，
    意思完全一样却判「没写归因」。逼着人为了过检把话写成模板，与「像人说的」
    直接冲突。所以留一层宽松匹配：取句式首 3 字与末 2 字作锚，
    中间允许 ≤10 个非句末标点字符。

    锚点必须按顺序成对出现，正文里零散出现同一个词不会误命中；
    短句式（<6 字）仍走精确匹配，避免锚点退化成单个常用字。
    """
    if phrase in text:
        return True
    if len(phrase) < 6:
        return False
    pat = re.escape(phrase[:3]) + r"[^。；;！!？?\n]{0,10}" + re.escape(phrase[-2:])
    return re.search(pat, text) is not None


def find_caution_section(lines) -> int:
    for i, ln in enumerate(lines):
        if CAUTION_HEAD_RE.match(ln):
            return i
    return -1


def _block_after(lines, i: int) -> list:
    """取锚点下方连续的非空行（遇到空行或标题即停）。

    原实现只取「下一行」——使用者分行写成一行一个词时，第二行起全部静默丢弃。
    """
    out, j = [], i + 1
    while j < len(lines):
        s = lines[j].strip()
        if not s:
            if out:
                break
            j += 1
            continue
        if s.startswith("#"):
            break
        out.append(re.sub(r"^[-*+]\s*", "", s))
        j += 1
    return out


def parse_lexicon(path: Path) -> dict:
    lex = {"title_ban": [], "ai_style": [], "cautions": {},
           "attrib_triggers": [], "attrib_phrases": []}
    if not path.exists():
        return lex
    lines = path.read_text(encoding="utf-8").splitlines()

    for i, ln in enumerate(lines):
        if ln.startswith("### 标题禁用词"):
            lex["title_ban"] = [w.strip() for w in "、".join(_block_after(lines, i)).split("、") if w.strip()]
        elif ln.startswith("### 禁用句式"):
            raw = [w.strip() for w in re.split(r"[/／]", "、".join(_block_after(lines, i))) if w.strip()]
            for term in raw:
                base = term.split("（")[0].replace("…", "").replace("...", "").strip()
                if base:
                    lex["ai_style"].append(base)

    ci = find_caution_section(lines)
    if ci >= 0:
        lvl = _heading_level(lines[ci])
        for row in lines[ci + 1:]:
            if row.startswith("#"):
                if _heading_level(row) <= lvl:
                    break          # 到下一节了，别再往下扫（原来是扫到文件尾，末尾加张附录表就被当词库）
                continue
            s = row.strip()
            if not s.startswith("|"):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) < 2:
                continue
            cat, words = cells[0], cells[1]   # 多出来的列（如「说明」）不参与，也不影响解析
            if cat in ("类别", "") or set(words) <= set("-"):
                continue
            ws = [w.strip() for w in words.split("、") if w.strip()]
            if ws:
                lex["cautions"][cat] = ws

    attrib = parse_attribution(lines)
    lex["attrib_triggers"] = attrib["triggers"]
    lex["attrib_phrases"] = attrib["phrases"]
    return lex


# ---------- 工具 ----------
def cjk_count(text: str) -> int:
    """正文字数：中日韩汉字 + 字母数字串，忽略空白与 Markdown 标记。"""
    t = re.sub(r"[#>*`|\-_\[\]()（）]", " ", text)
    han = len(re.findall(f"[{CJK}]", t))
    words = len(re.findall(r"[A-Za-z0-9]+", t))
    return han + words


def count_hit(text: str, word: str) -> int:
    """命中计数；词库中的「XX」作占位符通配（如"再不XX就晚了"）。"""
    if not word:
        return 0
    if "XX" in word:
        pat = re.escape(word).replace("XX", r".{0,6}?")
        return len(re.findall(pat, text))
    return text.count(word)


def ngrams(s: str, n: int = 2) -> set:
    s = re.sub(f"[^{CJK}A-Za-z0-9]", "", s)
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))} or {s}


def jaccard(a: str, b: str, n: int = 2) -> float:
    sa, sb = ngrams(a, n), ngrams(b, n)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# 标题相似度告警阈值（批次内查重与台账查重共用这一个值）。
# 0.45 是实测值：10—15 字的中文标题改几个字换说法，2-gram Jaccard 通常落在 0.40—0.50。
# 原先取 0.5 会漏判——「国考报名人数创新高」vs「国考报名人数再创新高」相似度 0.47，
# 明明是同一个题，却被判"不重复"。
DUP_THRESHOLD = 0.45


def has_table(text: str) -> bool:
    lines = [l.strip() for l in text.splitlines()]
    for i, l in enumerate(lines):
        if l.startswith("|") and i + 1 < len(lines):
            sep = lines[i + 1].strip("|")
            if re.fullmatch(r"[\s:\-|]+", sep) and "-" in sep:
                return True
    return False


def has_list_block(text: str) -> bool:
    """清单类结构化块：连续 ≥3 行的 - / 数字. 列表。"""
    run = 0
    for l in text.splitlines():
        if re.match(r"^\s*([-*+]|\d+[.、])\s+\S", l):
            run += 1
            if run >= 3:
                return True
        else:
            run = 0
    return False


# ---------- 阈值解析（单一数据源：references/content-guidelines.md） ----------
DEFAULT_RULES = {"title_max": 20, "word_min": 800, "word_max": 2000}
RULES_SRC = {"found": False, "detail": "使用内置默认值"}


def parse_rules(path: Path) -> dict:
    """从规范文件解析标题字数上限与正文字数区间，避免脚本与文档双写漂移。

    识别写法：
      - 标题：`- 每个标题 ≤ 20 字`（兼容 `<=`/`不超过`）
      - 正文：`## 二、正文结构（每篇 800—2000 字）`
    """
    rules = dict(DEFAULT_RULES)
    if not path.exists():
        return rules
    text = path.read_text(encoding="utf-8")

    m = re.search(r"每个标题\s*(?:≤|<=|不超过)\s*(\d+)\s*字", text)
    if m:
        rules["title_max"] = int(m.group(1))

    m = re.search(r"每篇\s*(\d+)\s*[—\-–~到]\s*(\d+)\s*字", text)
    if m:
        rules["word_min"], rules["word_max"] = int(m.group(1)), int(m.group(2))

    RULES_SRC["found"] = bool(re.search(r"每篇\s*\d+\s*[—\-–~到]\s*\d+\s*字", text))
    RULES_SRC["detail"] = (
        f"来自 {path.name}" if RULES_SRC["found"] else "规范文件未写字数区间，使用内置默认值"
    )
    return rules


# ---------- 词库格式校验（防"写着但没生效"） ----------
LEX_ANCHORS = [
    ("### 标题禁用词", "、", "标题禁用词"),
    ("### 禁用句式", "/", "去 AI 味禁用句式"),
]


def parse_directions(path: Path) -> list:
    """从规范文件「方向清单」节取出方向名。认不出就返回空列表（不阻断）。

    方向是泛干货的唯一选题来源：条数少于每日篇数，轮换池一周见底，
    选题开始靠换措辞糊弄。所以这条要能在体检时看见。
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out, inside = [], False
    for ln in lines:
        if ln.startswith("###"):
            # 进入「方向」节；离开任何其他 ### 就结束
            inside = "方向" in ln
            continue
        if not inside:
            continue
        if ln.startswith("##"):
            break
        m = re.match(r"^\s*\d+[.、]\s*\*{0,2}([^*：:]+)", ln)
        if m:
            out.append(m.group(1).strip())
    return out


def lexicon_issues(path: Path):
    """检查词库锚点与分隔符。返回 (issues, notes)。

    issues：真的会失效，阻断（`--dump-lexicon` 退出码 1）。
    notes：能解析但偏离契约（比如多了一列「说明」），只提示不阻断——
           把它们算成错误的话，使用者会为了"过检"去删掉有用的备注。
    """
    issues, notes = [], []
    if not path.exists():
        return [f"规范文件不存在：{path}"], notes
    lines = path.read_text(encoding="utf-8").splitlines()

    for anchor, sep, label in LEX_ANCHORS:
        hits = [i for i, l in enumerate(lines) if l.startswith(anchor)]
        if not hits:
            issues.append(f"未找到锚点「{anchor}」——{label}将不会生效（标题行必须以该文字开头）")
            continue
        i = hits[0]
        block = _block_after(lines, i)
        if not block:
            issues.append(f"「{anchor}」下方没有内容——{label}解析为 0 条")
            continue
        joined = "、".join(block)
        if sep == "/":
            items = [w.strip() for w in re.split(r"[/／]", joined) if w.strip()]
        else:
            items = [w.strip() for w in joined.split(sep) if w.strip()]
        if not items:
            issues.append(f"「{anchor}」未使用「{sep}」分隔——{label}解析为 0 条")
            continue
        if sep == "、" and ("/" in joined or "," in joined):
            issues.append(f"「{anchor}」检测到「/」或逗号，本行分隔符应为「、」，否则会被当成一个词")
        if sep == "/":
            frag = [w for w in items if len(w) <= 1]
            if frag:
                notes.append(f"「{anchor}」里有 {len(frag)} 段长度 ≤1（{ '、'.join(frag) }）——"
                             "多半是句式本身带斜杠被劈开了，例如「和/或」。请拆成两条写")

    ci = find_caution_section(lines)
    if ci < 0:
        issues.append("未找到「谨慎词库」小节标题（形如 `## 六、谨慎词库`）——谨慎词库将不会被校验")
    else:
        lvl = _heading_level(lines[ci])
        rows, parsed_cats, wide = 0, 0, []
        for idx, row in enumerate(lines[ci + 1:], start=ci + 2):
            if row.startswith("#"):
                if _heading_level(row) <= lvl:
                    break
                continue
            s2 = row.strip()
            if not s2.startswith("|"):
                continue
            rows += 1
            cells = [c.strip() for c in s2.strip("|").split("|")]
            if set(cells[1] if len(cells) > 1 else "") <= set("-"):
                continue          # 分隔行
            if cells[0] == "类别":
                if len(cells) > 2:
                    notes.append(f"第 {idx} 行表头有 {len(cells)} 列（`| 类别 | 词 | 说明 |`？）"
                                 "——只取前两列，后面几列不会参与校验")
                continue
            if len(cells) < 2:
                issues.append(f"第 {idx} 行只有 {len(cells)} 列，解析不出「类别 | 词」")
                continue
            if len(cells) > 2:
                wide.append(idx)
            if [w for w in cells[1].split("、") if w.strip()]:
                parsed_cats += 1
        if rows < 3:
            issues.append("谨慎词库表格行数不足（需表头 + 分隔行 + 至少 1 类词）")
        elif parsed_cats == 0:
            issues.append("谨慎词库解析出 0 类词——检查表格是否为「| 类别 | 词 |」两列、词是否用「、」分隔")
        if wide:
            notes.append(f"第 {'、'.join(map(str, wide[:5]))} 行有 3 列及以上——只取前两列，"
                         "多出来的列（如「说明」）不会参与校验，但仍会被解析")

    # 来源与归因（Q36）：两张表缺任一 → 条件归因检查不生效。
    # 只提示不阻断：老规范文件没这两节是正常的，升级不该因此卡住出稿；
    # 但必须在 --dump-lexicon 里看得见，否则又是一处静默关闭。
    attrib = parse_attribution(lines)
    for key, anchor, label in (("triggers", "归因触发词", "归因触发词表"),
                               ("phrases", "归因句式", "归因句式表")):
        if not attrib[key]:
            notes.append(f"未解析到「{anchor}」——{label}为空，条件归因检查（Q36）不会触发。"
                         f"需要这条检查就补一个 `#### {anchor}` 小节 + `| 类别 | 词 |` 表格")

    return issues, notes


# ---------- 单篇检查 ----------
def check_file(md: Path, lex: dict, rules: dict = None) -> dict:
    rules = rules or DEFAULT_RULES
    text = md.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = ""
    body_lines = []
    for l in lines:
        if l.startswith("# ") and not title:
            title = l[2:].strip()
        else:
            body_lines.append(l)
    body = "\n".join(body_lines)

    errors, warns = [], []

    if not title:
        errors.append("缺少 # 标题")
    else:
        tlen = len(re.findall(f"[{CJK}]", title)) + len(re.findall(r"[A-Za-z0-9]+", title))
        if tlen > rules["title_max"]:
            errors.append(f"标题 {tlen} 字，超过 {rules['title_max']} 字上限")
        for w in lex["title_ban"]:
            if w and w in title:
                errors.append(f"标题命中禁用词「{w}」")

    wc = cjk_count(body)
    if wc < rules["word_min"]:
        errors.append(f"正文 {wc} 字，不足 {rules['word_min']} 字下限")
    elif wc > rules["word_max"]:
        errors.append(f"正文 {wc} 字，超过 {rules['word_max']} 字上限")

    for cat, words in lex["cautions"].items():
        for w in words:
            n = count_hit(body, w)
            if n:
                errors.append(f"正文命中【{cat}】「{w}」×{n}")

    for p in lex["ai_style"]:
        n = body.count(p)
        if n:
            errors.append(f"正文命中【去 AI 味·禁用句式】「{p}」×{n}")

    heads = [l for l in body_lines if l.startswith("## ")]
    if not heads:
        warns.append("无 ## 小标题（建议每 300–500 字一个）")
    elif wc / max(1, len(heads)) > 600:
        warns.append(f"小标题偏少（{len(heads)} 个 / {wc} 字），建议加密")

    if len(re.findall(r"\*\*.+?\*\*", body, re.S)) < 1:
        warns.append("无加粗重点句（建议每节至少 1 句）")

    if "？" not in body and "?" not in body:
        errors.append("缺少互动问题（正文/结尾应有提问）")

    if "收藏" not in body or ("转发" not in body and "转给" not in body):
        errors.append("缺少收藏/转发引导（两者都要：只写「收藏」不够，需同时出现「转发」或「转给」）")

    # 插图：每篇至少 N 张（默认 1，Q22）。判据是正文里的 Markdown 图片行
    # `![图注](路径)`——它不是装饰，而是**插图位置的声明**：
    # make_article_html.py 按这些行把图按原位置插进 HTML，位置由作者定，不由脚本猜。
    # 只查语法不查文件是否存在：质检发生在出图之前，此时图片还没生成。
    n_illus = len(re.findall(r"!\[[^\]]*\]\([^)]+\)", body))
    if n_illus < MIN_ILLUS:
        errors.append(
            f"缺少插图（{n_illus}/{MIN_ILLUS} 张）：正文需要至少 {MIN_ILLUS} 行 "
            f"`![图注](标题_日期_插图1.png)` 来声明插图位置"
            f"（`make_article_html.py` 按这些行把图插到原位置）"
        )

    # PNG 长图与封面是 PIL + 单一字体渲染，没有字体回退：字体里没有的字符
    # （emoji、藏文、扩展汉字…）会印成带叉的方框。这里只提示、不阻断——
    # HTML 版由浏览器用系统字体，不受影响，用不用由作者定（Q35）。
    try:
        from glyph import describe, missing_chars

        unsupported = missing_chars(title + "\n" + body)
    except Exception:
        unsupported = []
    if unsupported:
        warns.append(
            f"含 {len(unsupported)} 个当前字体渲染不出的字符（{describe(unsupported)}）"
            f"——走 PNG 长图/封面时会被剥掉（否则印成叉框），HTML 版不受影响"
        )

    # 条件归因（Q36）：提到政策时点或数据就必须给来源；一条都没提到就不要求——
    # 每篇都挂免责声明，读者两篇之后就自动跳过，等于没写。
    trig = lex.get("attrib_triggers") or []
    phrases = lex.get("attrib_phrases") or []
    if trig and phrases:
        hits = [w for w in trig if w in body]
        if hits:
            tail = "\n".join([l for l in body_lines if l.lstrip().startswith("> ")]
                             + body_lines[-8:])
            if not any(phrase_hit(tail, p) for p in phrases):
                errors.append(
                    f"正文提到「{hits[0]}」等政策/数据内容，结尾却没有来源归因——"
                    f"补一行 `> {phrases[0]}`（条件要求：没提到这类内容的稿子不用加）"
                )

    return {
        "file": md.name,
        "title": title,
        "words": wc,
        "errors": errors,
        "warns": warns,
        "structured": has_table(text) or has_list_block(text),
    }


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="Markdown 稿件路径")
    ap.add_argument("--dir", default="", help="目录；配合 --date 取当日稿件")
    ap.add_argument("--date", default="", help="YYYY-MM-DD，配合 --dir 筛选文件名含该日期的 .md")
    ap.add_argument("--warn-only", action="store_true",
                    help="必改项不阻断：检查逻辑与报告完全不变，只把「有必改项」的退出码 1 改成 0。"
                         "exit=2（示例规范文件未替换 / 无稿件 / 目录不存在）仍会硬退，那是「没法质检」不是「没通过」")
    ap.add_argument("--allow-sample", action="store_true",
                    help="类目已自定义、但仍故意使用仓库示例规范文件时放行（默认直接失败）")
    ap.add_argument("--guidelines", default="",
                    help="规范文件路径；默认取 WX_GUIDELINES，缺省 references/content-guidelines.md")
    ap.add_argument("--dump-lexicon", action="store_true",
                    help="只打印词库与阈值解析结果并做格式校验（不校验稿件），用于确认配置真的生效")
    ap.add_argument("--require-structured", choices=["any", "all", "none"], default="any",
                    help="结构化块要求（对应 Q25）：any=至少 1 篇（默认），all=每篇都要，"
                         "none=不强制。判据只有两类：Markdown 表格、连续 ≥3 行清单")
    ap.add_argument("--require-illus", type=int, default=None, metavar="N",
                    help="每篇最少插图张数（对应 Q22）；默认取 WX_MIN_ILLUS，再缺省 1。"
                         "判据是正文里的 `![图注](路径)` 行——它同时是 HTML 插图的插入位置")
    args = ap.parse_args()
    require_structured = args.require_structured

    global MIN_ILLUS
    if args.require_illus is not None:
        MIN_ILLUS = max(0, args.require_illus)

    global GUIDELINES
    if args.guidelines:
        GUIDELINES = Path(args.guidelines).expanduser()

    lex = parse_lexicon(GUIDELINES)
    rules = parse_rules(GUIDELINES)
    issues, notes = lexicon_issues(GUIDELINES)

    if args.dump_lexicon:
        # 诊断命令不受阻断影响，但要说明「你现在看到的词库不是你的类目的」
        warn_sample_mismatch()
        print("=" * 60)
        print(f"类目：{VERTICAL}（WX_VERTICAL，初始化时由使用者定义）")
        print(f"规范文件：{GUIDELINES}")
        print("-" * 60)
        dirs = parse_directions(GUIDELINES)
        total_arts, _, _ = article_plan()
        flag = ""
        if dirs and total_arts and len(dirs) < total_arts:
            flag = f"  ⚠️ 少于每日 {total_arts} 篇，轮换池会一周见底"
        print(f"标题方向：{len(dirs)} 条{flag}")
        print(f"标题字数上限：{rules['title_max']} 字")
        print(f"正文字数区间：{rules['word_min']}–{rules['word_max']} 字（{RULES_SRC['detail']}）")
        print("-" * 60)
        n_caution_words = sum(len(v) for v in lex["cautions"].values())
        print(f"标题禁用词：{len(lex['title_ban'])} 条")
        for w in lex["title_ban"]:
            print(f"    · {w}")
        print(f"去 AI 味禁用句式：{len(lex['ai_style'])} 条")
        for w in lex["ai_style"]:
            print(f"    · {w}")
        print(f"谨慎词库：{len(lex['cautions'])} 类 / {n_caution_words} 词")
        for cat, ws in lex["cautions"].items():
            print(f"    · {cat}（{len(ws)}）：{'、'.join(ws)}")
        tr, ph = lex.get("attrib_triggers") or [], lex.get("attrib_phrases") or []
        print(f"归因触发词：{len(tr)} 条" + (f"（{'、'.join(tr)}）" if tr else "——条件归因检查未启用"))
        print(f"归因句式：{len(ph)} 条" + (f"（{'、'.join(ph)}）" if ph else "——条件归因检查未启用"))
        print("-" * 60)
        if notes:
            print(f"格式提示：{len(notes)} 项（不影响解析，只是偏离契约）")
            for n in notes:
                print(f"  ! {n}")
        if issues:
            print(f"格式检查：{len(issues)} 项有问题")
            for i in issues:
                print(f"  ✗ {i}")
            print("提示：解析为 0 条＝该词库实际未生效，按上面提示修分隔符或锚点")
            sys.exit(1)

        # 示例预设残留（Q44）：上面每一行都在证明「词库解析成功了」，
        # 但解析成功 ≠ 是你要的词库。换了路径、只改三节的场景下，
        # 标题禁用词和归因表还是考公的，而上面全部显示正常。
        residue = sample_content_residue(GUIDELINES)
        hard = [(h, w) for h, w in residue if residue_is_consumed(h)]
        if hard:
            print(f"示例预设残留：{len(hard)} 张词表仍是示例类目的内容"
                  f"（能解析、能生效，但永远不会命中）")
            for head, hits in hard:
                print(f"  ! {head.split('（')[0]}：{'、'.join(hits)}")
            print("  修法：按 Q13c 的七个落点改成你自己行业的词，"
                  "然后重跑 --dump-lexicon 直到这一行消失")

        _attrib_on = bool(tr) and bool(ph)
        verdict = "格式检查：通过（词库已正确解析" + (
            "，归因表已生效）" if _attrib_on else "；归因表未配，条件归因检查未启用）")
        if hard:
            verdict += f"，但 {len(hard)} 张词表仍是示例内容"
        elif residue:
            verdict += f"，另有 {len(residue)} 处举例仍是示例"
        print(verdict)
        if residue and not hard:
            print("示例预设举例：正文示范段里还有示例类目的词（不影响校验，想改再改）——"
                  + "；".join(f"{h.split('（')[0]}={'、'.join(w)}" for h, w in residue))
        print("=" * 60)
        sys.exit(0)

    # 类目已改、规范文件还是仓库自带那份 → 直接失败。
    # 这条原来是 stderr 上的 WARN，但自动化跑的时候没人看 stderr，
    # 结果就是拿着考公的词库去产出「职场」稿件，一路静默。
    if sample_guidelines_in_use(GUIDELINES):
        if args.allow_sample:
            warn_sample_mismatch()
        else:
            print(
                f"错误：类目「{VERTICAL}」仍在用仓库自带的示例规范文件\n"
                f"      {GUIDELINES}\n"
                f"      里面的标题禁用词、去 AI 味句式、谨慎词库、字数区间全是示例类目的。\n"
                f"      现在产出的稿子，是在用别人的词库过检。\n"
                f"      修法：cp 一份改成你的类目，再 export WX_GUIDELINES=<你的文件>（见 Q13c）\n"
                f"      确实想先用示例跑通链路：加 --allow-sample",
                file=sys.stderr,
            )
            sys.exit(2)

    # 路径换过了、内容没换干净（Q44）：只提示硬残留——即残留在脚本直接消费的
    # 词表里。软残留（正文示范段的旧例子）不影响这次质检，不在这里出声，
    # 否则每篇稿子都挂一条与本次判定无关的 WARN，很快就被无视了。
    hard_residue = [(h, w) for h, w in sample_content_residue(GUIDELINES)
                    if residue_is_consumed(h)]
    if hard_residue:
        print(f"WARN: 规范文件换了，但 {len(hard_residue)} 张词表仍是示例类目的内容"
              f"（这一节的校验对象永远不命中，等于没查）：", file=sys.stderr)
        for head, hits in hard_residue:
            print(f"      - {head.split('（')[0]}：{'、'.join(hits)}", file=sys.stderr)
        print("      按 Q13c 的七个落点改成你自己行业的词；"
              "`--dump-lexicon` 可看完整残留清单", file=sys.stderr)

    if issues:
        print(f"WARN: 词库格式有问题（{len(issues)} 项），部分词库可能未生效：", file=sys.stderr)
        for i in issues:
            print(f"      - {i}", file=sys.stderr)
        print("      跑 `--dump-lexicon` 可查看解析详情", file=sys.stderr)
    dirs = parse_directions(GUIDELINES)
    total_arts, _, _ = article_plan()
    if dirs and total_arts and len(dirs) < total_arts:
        print(f"WARN: 规范文件只有 {len(dirs)} 个标题方向，但每天要出 {total_arts} 篇——"
              f"轮换池不够，第 {len(dirs) + 1} 天起必然重复角度。"
              f"建议补到 {max(total_arts, min(10, total_arts * 2))} 条（见 Q13b）", file=sys.stderr)

    # 每天总字数：篇数 × 字数上限。超了就提醒备稿压力——
    # 使用者选「长稿 2000—3500」时往往没算过这件事。
    if total_arts and rules["word_max"]:
        per_day = total_arts * rules["word_max"]
        if per_day > 12000:
            print(f"WARN: {total_arts} 篇 × 上限 {rules['word_max']} 字 = 约 {per_day} 字/天，"
                  f"备稿与审稿压力很大（审稿约 {total_arts * 5} 分钟起）。"
                  f"要么减篇数，要么把字数区间收窄（见 Q23）", file=sys.stderr)

    if not (lex["title_ban"] or lex["cautions"]):
        print("WARN: 未能从 content-guidelines.md 解析词库，校验将不完整", file=sys.stderr)

    files = [Path(f) for f in args.files]
    if args.dir:
        d = Path(args.dir).expanduser()
        pat = f"*{args.date}*.md" if args.date else "*.md"
        found = [p for p in sorted(d.glob(pat)) if not p.name.startswith("00_")]
        if not found and args.date:
            # 文件名未带日期时回退为目录内全部稿件，避免因命名差异漏检
            found = [p for p in sorted(d.glob("*.md")) if not p.name.startswith("00_")]
            if found:
                print(f"WARN: 未匹配到文件名含 {args.date} 的稿件，回退为校验目录内全部 {len(found)} 篇",
                      file=sys.stderr)
        files += found

    files = [f for f in files if f.exists()]
    if not files:
        print("ERROR: 未找到任何 Markdown 稿件", file=sys.stderr)
        sys.exit(2)

    results = [check_file(f, lex, rules) for f in files]

    total_err = 0
    for r in results:
        flag = "FAIL" if r["errors"] else ("WARN" if r["warns"] else " OK ")
        print(f"[{flag}] {r['file']}  「{r['title']}」 {r['words']}字"
              f"{' [结构化]' if r['structured'] else ''}")
        for e in r["errors"]:
            print(f"        ✗ {e}")
        for w in r["warns"]:
            print(f"        · {w}")
        total_err += len(r["errors"])

    # 批次检查：结构化块的要求由 Q25 决定（any / all / none），别写死成「至少一篇」。
    print("-" * 60)
    n_struct = sum(1 for r in results if r["structured"])
    if require_structured == "none":
        print(f"· 结构化块：不强制（Q25 选「不强制」）；本批次实际有 {n_struct}/{len(results)} 篇")
    elif require_structured == "all":
        missing = [r["file"] for r in results if not r["structured"]]
        if missing:
            print(f"✗ 要求每篇都有结构化块，但有 {len(missing)} 篇没有：")
            for f in missing:
                print(f"        - {f}")
            print("      判据：Markdown 表格（表头 + 分隔行），或连续 ≥3 行的清单")
            total_err += 1
        else:
            print(f"✓ 全部 {len(results)} 篇都含结构化块")
    else:  # any
        if n_struct == 0:
            print("✗ 批次内无任何结构化块（需 ≥1 篇含表格/清单）")
            total_err += 1
        else:
            print(f"✓ 批次含结构化块（{n_struct}/{len(results)} 篇）")

    dup = []
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            s = jaccard(results[i]["title"], results[j]["title"])
            if s >= DUP_THRESHOLD:
                dup.append((results[i]["title"], results[j]["title"], round(s, 2)))
    if dup:
        for a, b, s in dup:
            print(f"✗ 标题近似（相似度 {s}）：「{a}」≈「{b}」")
        total_err += len(dup)
    else:
        print("✓ 标题互不重复")

    print("-" * 60)
    if total_err:
        print(f"结论：{total_err} 项必改" + ("（warn-only 已放行）" if args.warn_only else ""))
        sys.exit(0 if args.warn_only else 1)
    print("结论：全部通过")
    sys.exit(0)


if __name__ == "__main__":
    main()

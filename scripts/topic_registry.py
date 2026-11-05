#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公众号 · 选题去重台账 v1

解决"同一主题反复出题"：维护 00_选题台账.md（日期｜标题｜主题），
新标题生成后先与历史做 2-gram Jaccard 相似度比对，近似即告警；
并统计近期主题分布，避免选题扎堆。

用法：
  # 生成标题后先查重（参数是标题文本，或 .md 文件路径→自动取 # 标题）
  python3 topic_registry.py check "标题一" "标题二" 文章.md
  python3 topic_registry.py check 文章1.md 文章2.md --threshold 0.45

  # 定稿后写入台账
  python3 topic_registry.py add --date 2026-09-23 文章1.md 文章2.md

  # 查看台账与主题分布（分布随 check 一起打印，也可单独看）
  python3 topic_registry.py list
  python3 topic_registry.py stats --days 7

  # 迁移历史（老号换工具时用一次）
  python3 topic_registry.py import --from 历史稿件目录
  python3 topic_registry.py import --from 标题清单.csv
  python3 topic_registry.py import --from 稿件.md --date-from fixed --date 2026-01-01

选项：
  --ledger <路径>   台账文件（默认 $WX_DAILY_OUT/00_选题台账.md）
  --threshold <f>   相似度告警阈值（默认 0.45，与批次内查重共用 DUP_THRESHOLD）
  --days <n>        主题分布统计天数（默认 7）
  --from <路径>     import 用：.md 文件/目录、.csv、.tsv、.txt
  --date-from       import 用：filename（默认，解析不到退 mtime）/ mtime / fixed

导入支持的格式：
  .md     取每个文件首个 "# " 标题；文件名里的 2026-10-05 会作为发布日期
  .csv    两列「日期,标题」或单列「标题」，自动跳过表头
  .txt    一行一条，支持「日期<TAB>标题」或「日期|标题」
  日期解析不出时退回文件修改时间，并单独计数提醒。
  台账自身（00_选题台账.md）始终被排除，重复跑同一目录不会灌入重复行。

退出码：check 发现近似选题时为 1；其余 0
"""
# 注解延迟求值：`skip: Path | None` 是 PEP 604，3.10 才支持运行期求值；
# 本技能声明 Python ≥ 3.9，缺这一行 3.9 上 import 就崩。**别删这一行。**
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_content import DUP_THRESHOLD, jaccard  # noqa: E402
from brand import OUT_DIR, THEME_FILE, VERTICAL  # noqa: E402

DEFAULT_LEDGER = OUT_DIR / "00_选题台账.md"

# 主题词表（用于归类与分布统计）
# 内置这份是「考公」类目示例预设；换类目请提供 $WX_DAILY_OUT/00_主题词表.json
BUILTIN_THEMES = {
    "国考": ["国考", "国家公务员"],
    "省考": ["省考", "省考联考"],
    "选调": ["选调", "选调生"],
    "事业单位": ["事业单位", "联考"],
    "报名": ["报名", "报考", "资格审查", "资格审核"],
    "行测": ["行测", "言语", "判断推理", "资料分析", "数量关系"],
    "申论": ["申论", "大作文", "小题"],
    "面试": ["面试", "结构化", "无领导", "考官", "答题"],
    "政审": ["政审", "考察", "档案"],
    "体检": ["体检", "标准"],
    "应届身份": ["应届", "择业期", "身份"],
    "选岗": ["选岗", "岗位表", "职位表", "专业"],
    "时间线": ["时间线", "时间表", "流程", "截止"],
    "心态": ["心态", "焦虑", "放弃", "坚持"],
}


# 归类优先级：「内容主题」压过「范围主题」。
# 一条标题同时命中「国考」和「面试」时，按内容角度归「面试」——扎堆检测要防的是
# 「同一个角度反复写」，而归到「国考」会让整个国考季全落在一个主题下，永远显示扎堆。
# 词表可用保留键 "_priority": ["面试", ...] 覆盖；未列到的主题按词表原顺序兜底。
BUILTIN_PRIORITY = ["报名", "行测", "申论", "面试", "政审", "体检", "选岗", "时间线", "应届身份", "心态"]


def load_themes(path: Path):
    """主题词表：优先读 JSON（{"主题": ["关键词", ...]}），否则退回内置示例预设。

    返回 (themes, 来源说明, priority)。
    """
    import json
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                # 跳过 "_说明" / "_priority" 之类的保留键，只收 值为数组 的主题
                themes = {
                    str(k): [str(x) for x in v]
                    for k, v in data.items()
                    if not str(k).startswith("_") and isinstance(v, list) and v
                }
                if themes:
                    raw_pri = data.get("_priority")
                    pri = [str(x) for x in raw_pri] if isinstance(raw_pri, list) else []
                    pri = [x for x in pri if x in themes]
                    if not pri:
                        pri = [x for x in BUILTIN_PRIORITY if x in themes]
                    return themes, str(path), pri
                print(f"WARN: 主题词表无有效条目（需 {{\"主题\": [\"关键词\"]}}）", file=sys.stderr)
        except Exception as e:
            print(f"WARN: 主题词表解析失败（{e}），退回内置示例词表", file=sys.stderr)
    return dict(BUILTIN_THEMES), "内置考公示例词表", [x for x in BUILTIN_PRIORITY if x in BUILTIN_THEMES]


THEMES, THEMES_SRC, PRIORITY = load_themes(THEME_FILE)


# ---------- 台账读写 ----------
def load_ledger(path: Path) -> list:
    """返回 [(日期, 标题, 主题)]"""
    rows = []
    if not path.exists():
        return rows
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("日期", "") or set(cells[1]) <= set("-"):
            continue
        date, title = cells[0], cells[1]
        theme = cells[2] if len(cells) > 2 else ""
        rows.append((date, title, theme))
    return rows


def write_row(path: Path, date: str, title: str, theme: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "# 选题台账（防重复出题）\n\n"
            "| 日期 | 标题 | 主题 |\n|---|---|---|\n",
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as f:
        f.write(f"| {date} | {title} | {theme} |\n")


def theme_hits(title: str) -> list:
    """标题命中的全部主题（按词表顺序）。用于诊断「一条标题归错主题」。"""
    return [t for t, kws in THEMES.items() if any(k in title for k in kws)]


def detect_theme(title: str) -> str:
    hits = theme_hits(title)
    if not hits:
        return "其他"
    for p in PRIORITY:          # 内容主题优先于范围主题
        if p in hits:
            return p
    return hits[0]


def resolve_titles(items: list) -> list:
    """参数是 .md 文件时取其 # 标题，否则按标题文本处理。"""
    out = []
    for it in items:
        p = Path(it)
        if p.exists() and p.suffix.lower() == ".md":
            for ln in p.read_text(encoding="utf-8").splitlines():
                if ln.startswith("# "):
                    out.append(ln[2:].strip())
                    break
        else:
            out.append(it.strip())
    return [t for t in out if t]


# ---------- 命令 ----------
def print_distribution(cnt: Counter, scope: list, dates: list):
    """打印主题分布。「其他」单独说明，不参与扎堆标记。"""
    print(f"\n近 {len(dates)} 天主题分布（历史 {len(scope)} 篇）：")
    others = cnt.pop("其他", 0)   # 「其他」不是一个主题：留在分布里会把互不相干的新题材合成一堆并误报扎堆
    for th, n in cnt.most_common():
        star = " ← 扎堆" if n >= 3 else ""
        print(f"  {th}: {n}{star}")
    total = (sum(cnt.values()) + others) or 1
    if others:
        pct = others / total
        print(f"  其他: {others}（{pct:.0%}｜未匹配任何主题关键词——不同内容全挤在这里，别当扎堆看）")
        if pct >= 0.3:
            print("  ⚠️ 「其他」占比 ≥30%：主题词表没覆盖这些选题，扎堆检测对它们失效。"
                  "按 Q33 把新主题补进 00_主题词表.json 后重跑本命令，历史归集会一起修正",
                  file=sys.stderr)
    if not others and not cnt:
        print("  （台账为空）")


def cmd_stats(ledger: Path, days: int) -> int:
    """只看台账的主题分布，不用先凑一批候选标题。"""
    hist = load_ledger(ledger)
    if not hist:
        print(f"台账为空：{ledger}")
        return 0
    dates = sorted({r[0] for r in hist}, reverse=True)[:days]
    scope = [r for r in hist if r[0] in dates]
    cnt = Counter(r[2] or detect_theme(r[1]) for r in scope)
    print(f"台账：{ledger}（共 {len(hist)} 条，分布取近 {days} 个有记录的日期）")
    print_distribution(cnt, scope, dates)
    return 0


def cmd_check(ledger: Path, titles: list, threshold: float, days: int) -> int:
    hist = load_ledger(ledger)
    print(f"台账条目：{len(hist)} 条" if hist else "台账为空（首次使用，无历史可比）")

    bad = 0
    for t in titles:
        best, best_row = 0.0, None
        for date, ht, _ in hist:
            s = jaccard(t, ht)
            if s > best:
                best, best_row = s, (date, ht)
        mark = "✗" if best >= threshold else "✓"
        if best >= threshold:
            bad += 1
            print(f"  {mark} 「{t}」与历史「{best_row[1]}」({best_row[0]}) 相似度 {best:.2f} ≥ {threshold} → 建议换角度")
        else:
            print(f"  {mark} 「{t}」最高相似度 {best:.2f}（主题：{detect_theme(t)}）")

    # 近期主题分布
    dates = sorted({r[0] for r in hist}, reverse=True)[:days]
    scope = [r for r in hist if r[0] in dates]
    cnt = Counter(r[2] or detect_theme(r[1]) for r in scope)
    cand = Counter(detect_theme(t) for t in titles)
    print_distribution(cnt, scope, dates)
    print("本次候选主题：", "、".join(f"{k}×{v}" for k, v in cand.most_common()))

    if bad:
        print(f"\n结论：{bad} 个标题与历史近似，请改写")
        return 1
    print("\n结论：选题无重复")
    return 0


def cmd_add(ledger: Path, date: str, titles: list) -> int:
    hist = {h[1] for h in load_ledger(ledger)}
    added = 0
    for t in titles:
        if t in hist:
            print(f"  · 已在台账，跳过：{t}")
            continue
        th = detect_theme(t)
        write_row(ledger, date, t, th)
        hist.add(t)
        added += 1
        flag = "" if th != "其他" else "  ⚠️ 未匹配任何主题（补主题词表后重跑 add 会修正；这条不影响去重，只影响分布统计）"
        print(f"  ✓ 已写入：{t}（主题：{th}）{flag}")
    print(f"\n新增 {added} 条 → {ledger}")
    return 0


# ---------- 历史台账导入 ----------
LEDGER_NAME = "00_选题台账.md"
# 文件名里的日期：2026-09-23-xxx.md / 20260923xxx.md / 2026.9.23 xxx.md 都认
_NAME_DATE = re.compile(r"(20\d{2})\s*[-_.年]?\s*(\d{1,2})\s*[-_.月]?\s*(\d{1,2})")


def date_from_name(p: Path) -> str:
    """从文件名解析日期，解析不出来返回空串。"""
    from datetime import date as _date

    m = _NAME_DATE.search(p.stem)
    if not m:
        return ""
    try:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return ""


def date_from_mtime(p: Path) -> str:
    from datetime import date as _date

    try:
        return _date.fromtimestamp(p.stat().st_mtime).isoformat()
    except OSError:
        return ""


def norm_date(s: str) -> str:
    """把 2026/10/5、2026.10.5、2026年10月5日、20261005 统一成 2026-10-05；认不出返回空串。"""
    from datetime import date as _date

    s = (s or "").strip()
    m = re.match(r"^(20\d{2})\s*[-/.年]?\s*(\d{1,2})\s*[-/.月]?\s*(\d{1,2})", s)
    if not m:
        return ""
    try:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return ""


def _md_title(p: Path) -> str:
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.startswith("# "):
            return ln[2:].strip()
    return ""


def _rows_from_table(p: Path) -> list:
    """csv/tsv：两列视为「日期,标题」，一列视为「标题」。自动跳过表头。"""
    import csv

    delim = "\t" if p.suffix.lower() == ".tsv" else ","
    out = []
    try:
        with p.open(encoding="utf-8-sig", errors="replace", newline="") as f:
            for i, cells in enumerate(csv.reader(f, delimiter=delim)):
                cells = [c.strip() for c in cells if c.strip()]
                if not cells:
                    continue
                if i == 0 and any(k in cells[0] for k in ("日期", "时间", "date")):
                    continue  # 表头
                d0 = norm_date(cells[0]) if len(cells) >= 2 else ""
                if d0:
                    out.append((d0, cells[1]))
                else:
                    out.append(("", cells[0]))
    except OSError:
        pass
    return out


def _rows_from_txt(p: Path) -> list:
    """txt：一行一条，支持「日期<TAB>标题」或「日期|标题」，否则整行当标题。"""
    out = []
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip().lstrip("-*· ").strip()
        if not ln:
            continue
        parts = re.split(r"[\t|｜]", ln, maxsplit=1)
        d0 = norm_date(parts[0]) if len(parts) == 2 else ""
        if d0:
            out.append((d0, parts[1].strip()))
        else:
            out.append(("", ln))
    return out


def collect_history(src: Path, skip: Path | None = None) -> list:
    """把各种历史素材摊平成 [(原始日期, 标题, 来源文件)]。

    skip 是台账自身：台账默认就住在产物目录里，若用户直接把产物目录当 --from，
    它会把台账的 H1「选题台账（防重复出题）」当成一篇历史稿吃进去，
    于是每重跑一次就多一行垃圾。
    """
    skip_res = skip.resolve() if skip else None
    items = []
    files = []
    if src.is_dir():
        files = sorted(p for p in src.rglob("*") if p.is_file())
    elif src.is_file():
        files = [src]
    for p in files:
        if p.name == LEDGER_NAME or (skip_res and p.resolve() == skip_res):
            continue
        suf = p.suffix.lower()
        if suf in (".md", ".markdown"):
            t = _md_title(p)
            if t:
                items.append((date_from_name(p), t, p))
        elif suf in (".csv", ".tsv"):
            items += [(d, t, p) for d, t in _rows_from_table(p)]
        elif suf == ".txt":
            items += [(d, t, p) for d, t in _rows_from_txt(p)]
    return items


def cmd_import(ledger: Path, src: Path, date_mode: str, fixed_date: str) -> int:
    if not src.exists():
        print(f"ERROR: 找不到 {src}", file=sys.stderr)
        return 2
    raw = collect_history(src, skip=ledger)
    if not raw:
        print(f"ERROR: {src} 里没有认出可导入的内容。"
              f"支持 .md（取首个 # 标题）、.csv/.tsv（日期,标题）、.txt（一行一条）", file=sys.stderr)
        return 2

    # 主题词表若是内置示例词表，导入结果会全归「其他」，必须当场告警
    sample_themes = THEMES_SRC.startswith("内置")
    if sample_themes:
        print("WARN: 主题词表仍是内置示例词表，导入的条目会全部归入「其他」，主题分布统计失真。"
              f"请先做 Q13c 生成 {THEME_FILE}", file=sys.stderr)

    hist = {h[1] for h in load_ledger(ledger)}
    # 先算出每条该记什么日期，再按日期升序落表——台账是给人翻的，倒序会很难读
    resolved, skipped = [], 0
    for d0, title, f in raw:
        if title in hist:
            skipped += 1
            continue
        if date_mode == "fixed":
            d, guessed = fixed_date, False
        elif date_mode == "mtime":
            d, guessed = date_from_mtime(f) or fixed_date, False
        else:  # filename：文件名/表格里的日期最可信，拿不到才退 mtime
            d, guessed = (d0 or date_from_mtime(f) or fixed_date), not d0
        resolved.append((d, title, guessed))
    resolved.sort(key=lambda r: (r[0], r[1]))

    added = guessed_n = 0
    for d, title, guessed in resolved:
        if title in hist:          # 同一批里重复出现的标题
            skipped += 1
            continue
        write_row(ledger, d, title, detect_theme(title))
        hist.add(title)
        added += 1
        guessed_n += 1 if guessed else 0

    counts = Counter(detect_theme(t) for t in hist)
    other_n = counts.get("其他", 0)
    print(f"\n新增 {added} 条 · 跳过 {skipped} 条重复 · 日期靠 mtime 推测 {guessed_n} 条")
    print(f"台账现有 {len(hist)} 条 → {ledger}")
    if guessed_n:
        print(f"提示：{guessed_n} 条没在文件名或表格里找到日期，用了文件修改时间。"
              f"若不准，把文件名改成 2026-10-05-标题.md 再导，或 --date-from fixed --date <YYYY-MM-DD>")
    if sample_themes and other_n:
        print(f"⚠️  {other_n} 条主题归为「其他」——补上主题词表后重跑本命令即可修正")
    return 0


def cmd_list(ledger: Path) -> int:
    rows = load_ledger(ledger)
    if not rows:
        print("台账为空")
        return 0
    for date, title, theme in rows:
        print(f"{date}  [{theme or detect_theme(title)}]  {title}")
    print(f"\n共 {len(rows)} 条")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "add", "list", "import", "stats"])
    ap.add_argument("items", nargs="*")
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    ap.add_argument("--themes", default="", help="主题词表 JSON 路径；默认 WX_THEMES 或 00_主题词表.json")
    ap.add_argument("--date", default="")
    ap.add_argument("--threshold", type=float, default=DUP_THRESHOLD)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--from", dest="src", default="",
                    help="import 用：历史素材路径（.md 目录 / .md / .csv / .tsv / .txt）")
    ap.add_argument("--date-from", dest="date_from", default="filename",
                    choices=["filename", "mtime", "fixed"],
                    help="import 用：日期来源，默认 filename（解析不到退 mtime）")
    args = ap.parse_args()

    global THEMES, THEMES_SRC, PRIORITY
    if args.themes:
        THEMES, THEMES_SRC, PRIORITY = load_themes(Path(args.themes).expanduser())

    # 类目与主题词表不匹配时提醒（主题归类只影响"分布统计"，不影响相似度去重）
    if THEMES_SRC == "内置考公示例词表" and VERTICAL not in ("考公", "公考", ""):
        print(f"WARN: 当前类目「{VERTICAL}」仍在用内置考公主题词表，主题分布统计会失真；"
              f"建议提供主题词表 JSON（{THEME_FILE}）", file=sys.stderr)

    ledger = Path(args.ledger).expanduser()
    titles = resolve_titles(args.items)

    if args.cmd == "import":
        if not args.src:
            print("ERROR: import 需要 --from <路径>", file=sys.stderr)
            sys.exit(2)
        from datetime import date as _d
        fixed = (args.date or _d.today().isoformat())[:10]
        sys.exit(cmd_import(ledger, Path(args.src).expanduser(), args.date_from, fixed))
    if args.cmd == "stats":
        return cmd_stats(ledger, args.days)
    if args.cmd == "check":
        if not titles:
            print("ERROR: check 需要提供标题或 .md 文件", file=sys.stderr)
            sys.exit(2)
        sys.exit(cmd_check(ledger, titles, args.threshold, args.days))
    if args.cmd == "add":
        if not titles:
            sys.exit(2)
        date = args.date or "未知日期"
        sys.exit(cmd_add(ledger, date, titles))
    print(f"类目：{VERTICAL}｜主题词表：{THEMES_SRC}（{len(THEMES)} 个主题）", file=sys.stderr)
    sys.exit(cmd_list(ledger))


if __name__ == "__main__":
    main()

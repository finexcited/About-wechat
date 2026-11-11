#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付前残留检查（onboarding Q42）

查两件事，范围是**所有文本文件**（不只 .py / .md——json / mjs / sh / html 一样会夹带）：

  ① 本机绝对路径：真实用户名那种，别人拿到仓库能看出「这是谁的机器导出的」
  ② 品牌词：仓库里不该出现既有号的名称（本技能不预置品牌）

为什么不用白名单：模板占位天然不命中——`<你的用户名>` 里是中文，不在
[A-Za-z0-9._-] 字符集内；`~/xxx` 用的是波浪号，也不是绝对路径。
**白名单是残留检查最容易失效的地方**：每加一条「这个是合法的」，
就等于给它开了个后门，而后面没人会复查那条白名单。

用法
----
  python3 scripts/check_residue.py                        # 扫本仓库
  python3 scripts/check_residue.py --brand 旧号名,旧品牌   # 加查具体品牌词
  python3 scripts/check_residue.py ~/code/另一个仓库       # 扫指定目录

退出码
------
  0  干净
  1  有残留（逐条列出 文件:行）
  2  没法检查（目录不存在 / 一个文件都没读到）

**只查工作树**：`git log` 里的历史它看不到。历史上出现过的品牌名要另行处理
（重写历史或重新开一个干净仓库），这不在这道检查的能力范围内。
"""
import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 目录与文件类型跳过表：二进制与生成物里搜字符串没有意义
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
             ".mypy_cache", ".pytest_cache", ".idea", ".workbuddy"}
SKIP_SUFFIX = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".ico", ".icns",
    ".ttf", ".otf", ".woff", ".woff2", ".pyc", ".zip", ".gz", ".pdf",
    ".mp3", ".mp4", ".mov", ".sketch", ".ardot",
}
MAX_BYTES = 2 * 1024 * 1024

# 正则在源码里刻意不出现可直接匹配的完整字样，免得脚本扫到自己
PATH_PATTERNS = (
    ("本机绝对路径", re.compile(r"/(?:Users|home|root)/[A-Za-z0-9._-]{2,}")),
    ("本机绝对路径", re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9._-]{2,}")),
)


def read_text(p: Path):
    """读文本；二进制与超大文件跳过。"""
    try:
        if p.stat().st_size > MAX_BYTES:
            return None
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def iter_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in SKIP_SUFFIX:
            continue
        yield p


def scan(root: Path, brands: list):
    hits, scanned = [], 0
    for p in iter_files(root):
        text = read_text(p)
        if text is None:
            continue
        scanned += 1
        rel = p.relative_to(root)
        # 文件名本身也可能是残留（例如「旧号名_模板.md」）
        for b in brands:
            if b.lower() in p.name.lower():
                hits.append(("品牌词（文件名）", rel, 0, p.name))
        for i, line in enumerate(text.splitlines(), 1):
            for label, pat in PATH_PATTERNS:
                m = pat.search(line)
                if m:
                    hits.append((label, rel, i, m.group(0)))
            low = line.lower()
            for b in brands:
                if b.lower() in low:
                    hits.append(("品牌词", rel, i, b))
    return hits, scanned


def main():
    ap = argparse.ArgumentParser(description="交付前残留检查（Q42）")
    ap.add_argument("path", nargs="?", default=str(REPO), help="要扫的目录（默认本仓库）")
    ap.add_argument("--brand", default="",
                    help="额外要查的品牌词，逗号分隔；会与 WX_LEGACY_BRANDS 合并")
    args = ap.parse_args()

    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"ERROR: 目录不存在：{root}", file=sys.stderr)
        return 2

    brands = [b.strip() for b in args.brand.split(",") if b.strip()]
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from brand import LEGACY_BRANDS
        brands += [b for b in LEGACY_BRANDS if b not in brands]
    except Exception:
        pass

    print(f"残留检查：{root}")
    hits, scanned = scan(root, brands)
    if scanned == 0:
        print("ERROR: 一个文本文件都没读到（路径写错了？）", file=sys.stderr)
        return 2
    print(f"扫描 {scanned} 个文本文件" + (f"；品牌词 {len(brands)} 个" if brands else ""))
    print("-" * 62)

    if not hits:
        print("✓ 未发现本机绝对路径")
        print("✓ 未发现品牌词" if brands else
              "· 品牌词检查未启用（没设 WX_LEGACY_BRANDS 也没传 --brand）——"
              "这一项是「跳过」，不是「干净」")
        print("-" * 62)
        print("结论：干净")
        return 0

    groups = {}
    for label, rel, line, found in hits:
        groups.setdefault(label, []).append((rel, line, found))
    for label, items in groups.items():
        print(f"✗ {label} {len(items)} 处")
        for rel, line, found in items:
            where = f"{rel}:{line}" if line else f"{rel}（文件名）"
            print(f"    {where}  {found}")
    print("-" * 62)
    print(f"结论：{len(hits)} 处残留，交付前必须清掉（或确认它是有意保留的示例并说明理由）")
    return 1


if __name__ == "__main__":
    sys.exit(main())

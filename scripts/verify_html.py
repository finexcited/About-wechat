#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公众号 · HTML 合规校验 v1（官方 CLI + 自动降级）

优先跑微信官方校验器 verify-article-structure-spec（退出码 0=通过 / 1=违规 / 2=异常）；
官方 CLI 不可用时，自动降级为 make_article_html.self_check 静态自查，并明确标注。

一次性安装官方 CLI：
  python3 verify_html.py --setup

校验：
  python3 verify_html.py 推文1.html 推文2.html
  python3 verify_html.py --dir $WX_DAILY_OUT --date 2026-09-23

退出码：0 全部通过；1 存在违规；2 环境异常
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_URL = "https://github.com/wechatjs/verify-article-structure-spec.git"
TOOLS_DIR = Path(
    os.environ.get(
        "WX_VERIFY_TOOLS_DIR",
        str(Path.home() / ".workbuddy" / "tools" / "verify-article-structure-spec"),
    )
).expanduser()
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def find_cli():
    """定位官方 CLI 目录（环境变量 WX_VERIFY_CLI 优先）；未安装返回 None。"""
    env = os.environ.get("WX_VERIFY_CLI", "").strip()
    if env:
        p = Path(env).expanduser()
        if (p / "package.json").exists():
            return p
    for cand in (TOOLS_DIR / "cli", Path.home() / "verify-article-structure-spec" / "cli"):
        if (cand / "package.json").exists():
            return cand
    return None


def find_chrome() -> str:
    env = os.environ.get("PUPPETEER_EXECUTABLE_PATH", "").strip()
    if env and Path(env).exists():
        return env
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    return ""


def setup() -> int:
    """克隆并安装官方 CLI（需 git + npm + 网络）。"""
    if not shutil.which("git"):
        print("ERROR: 未找到 git", file=sys.stderr)
        return 2
    TOOLS_DIR.parent.mkdir(parents=True, exist_ok=True)
    if TOOLS_DIR.exists():
        print(f"已存在：{TOOLS_DIR}")
    else:
        print(f"克隆 {REPO_URL} …")
        r = subprocess.run(["git", "clone", "--depth", "1", REPO_URL, str(TOOLS_DIR)])
        if r.returncode != 0:
            print("ERROR: 克隆失败", file=sys.stderr)
            return 2
    cli = TOOLS_DIR / "cli"
    if not (cli / "node_modules").exists():
        print("安装依赖（npm install）…")
        r = subprocess.run(["npm", "install"], cwd=str(cli))
        if r.returncode != 0:
            print("ERROR: npm install 失败", file=sys.stderr)
            return 2
    print(f"OK 官方 CLI 就绪：{cli}")
    return 0


def static_check(html_path: Path) -> list:
    """降级自查：复用 make_article_html.self_check（PIL 依赖，失败则最小检查）。"""
    try:
        sys.path.insert(0, str(HERE))
        from make_article_html import self_check  # noqa
        return self_check(html_path.read_text(encoding="utf-8"))
    except Exception:
        text = html_path.read_text(encoding="utf-8")
        issues = []
        if "<style" in text or "class=" in text:
            issues.append("存在 <style> 或 class")
        if "!important" in text:
            issues.append("使用了 !important")
        if "<table" in text:
            issues.append("出现裸 <table>")
        if "font-family" in text:
            issues.append("设置了 font-family")
        return issues


def run_official(cli: Path, html: Path) -> tuple:
    """返回 (通过?, 原始输出)。"""
    env = dict(os.environ)
    chrome = find_chrome()
    if chrome:
        env["PUPPETEER_EXECUTABLE_PATH"] = chrome
    try:
        r = subprocess.run(
            ["npm", "run", "check", "--", str(html.resolve())],
            cwd=str(cli), env=env, capture_output=True, text=True, timeout=180,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, f"执行异常：{e}"
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 0:
        return True, out
    if r.returncode == 1:
        return False, out
    return False, f"环境异常(exit={r.returncode})：{out}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--dir", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--setup", action="store_true", help="克隆并安装官方 CLI")
    args = ap.parse_args()

    if args.setup:
        sys.exit(setup())

    files = [Path(f) for f in args.files if Path(f).exists()]
    if args.dir:
        d = Path(args.dir).expanduser()
        pat = f"*{args.date}*.html" if args.date else "*.html"
        found = [p for p in sorted(d.glob(pat)) if not p.name.startswith("00_")]
        if not found and args.date:
            found = [p for p in sorted(d.glob("*.html")) if not p.name.startswith("00_")]
            if found:
                print(f"WARN: 未匹配到文件名含 {args.date} 的 HTML，回退为校验目录内全部 {len(found)} 个",
                      file=sys.stderr)
        files += found
    if not files:
        print("ERROR: 未找到 HTML 文件", file=sys.stderr)
        sys.exit(2)

    cli = find_cli()
    chrome = find_chrome()
    if cli:
        print(f"官方 CLI：{cli}（Chrome: {chrome or '未指定'}）")
    else:
        print("官方 CLI：未安装 → 降级为内置静态自查"
              "（需官方校验可执行：python3 verify_html.py --setup）")

    failed = 0
    for f in files:
        issues = static_check(f)
        if cli:
            ok, out = run_official(cli, f)
            bad = (not ok) or bool(issues)
            tag = " OK " if not bad else "FAIL"
            print(f"[{tag}] {f.name}  官方CLI:{'通过' if ok else '未通过'}"
                  f"  静态自查:{len(issues)} 项")
            if not ok:
                tail = "\n".join(out.strip().splitlines()[-12:])
                print("      官方输出：\n" + tail)
        else:
            bad = bool(issues)
            tag = " OK " if not bad else "FAIL"
            print(f"[{tag}] {f.name}  静态自查:{len(issues)} 项（降级模式）")
        for i in issues:
            print(f"        ✗ {i}")
        if bad:
            failed += 1

    print("-" * 60)
    if failed:
        print(f"结论：{failed} 个文件未通过")
        sys.exit(1)
    print(f"结论：{len(files)} 个文件全部通过")
    sys.exit(0)


if __name__ == "__main__":
    main()

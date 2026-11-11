# -*- coding: utf-8 -*-
"""push_ui.py — 无 API 凭证时，用已登录的浏览器把贴图写进公众号草稿箱。

为什么需要这条路：`draft/add` 要求 appid/secret，很多号主拿不到或不想配 IP 白名单，
于是只能走网页。网页这条路有五个坑（已在 push_draft_ui.js 里修掉），这里负责编排与核验：

  1. 逐篇：生成 payload → 喂给 ego-browser → 解析 SAVED id
  2. 全部推完只查一次后台列表（mode=list），和成稿标题比对
  3. 绝不「保存后打开草稿看效果」——贴图编辑器自动保存会把没加载完的空状态写回去

用法：
  python3 push_ui.py --run "." --space 2              # 推全部
  python3 push_ui.py --run "." --space 2 --only 3,5   # 只推指定篇
  python3 push_ui.py --run "." --space 2 --verify     # 只核验，不推送
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_JS = os.path.join(SKILL_DIR, "scripts", "push_draft_ui.js")
PAYLOAD = "/tmp/xh_push_payload.json"


def build_payload(note_idx, note_dir, copy_obj, mode="create", space=2):
    paras = [x.strip() for x in (copy_obj.get("body") or "").split("\n") if x.strip()]
    topics = copy_obj.get("topics") or []
    if topics:
        paras.append(" ".join("#%s#" % t for t in topics))
    files = []
    for p in range(1, 30):
        f = os.path.join(note_dir, "composed", "page-%02d.png" % p)
        if os.path.exists(f):
            files.append(f)
    return {"mode": mode, "space_id": space, "note": note_idx,
            "title": copy_obj.get("title", ""), "paras": paras, "files": files}


def run_js(payload, timeout=280):
    with open(PAYLOAD, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    with open(UI_JS, "r", encoding="utf-8") as f:
        js = f.read()
    proc = subprocess.run(["ego-browser", "nodejs"], input=js, text=True,
                          capture_output=True, timeout=timeout)
    return (proc.stdout or "") + (proc.stderr or "")


def parse_list(out):
    m = re.search(r"^LIST (\[.*\])$", out, re.M)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--space", type=int, default=2, help="已登录公众号的 ego 任务空间 id")
    ap.add_argument("--only", default="", help="只推这些篇，逗号分隔")
    ap.add_argument("--verify", action="store_true", help="只核验不推送")
    ap.add_argument("--gap", type=float, default=4.0, help="篇间停顿秒数")
    a = ap.parse_args()

    run_root = os.path.abspath(a.run)
    meta = common.load_run(run_root)
    notes = meta["notes"]
    only = {int(x) for x in a.only.split(",") if x.strip().isdigit()} or None

    ids_path = os.path.join(run_root, "data", "draft-ids.json")
    ids = common.jload(ids_path) or {}

    if not a.verify:
        if not os.path.exists(UI_JS):
            common.die("缺少 scripts/push_draft_ui.js")
        for idx, note in enumerate(notes, 1):
            if only and idx not in only:
                continue
            nd = common.note_dir(run_root, idx)
            copy_obj = common.jload(os.path.join(nd, "copy.json"))
            if copy_obj is None:
                print("  #%d 缺 copy.json，跳过" % idx)
                continue
            payload = build_payload(idx, nd, copy_obj, "create", a.space)
            if not payload["files"]:
                print("  #%d 没有合成图，跳过（先跑 compose）" % idx)
                continue
            out = run_js(payload)
            m = re.search(r"SAVED id=(\d+)", out)
            if m:
                ids[str(idx)] = {"appmsgid": int(m.group(1)), "title": payload["title"],
                                 "images": len(payload["files"])}
                print("  #%d 已写入草稿箱 id=%s（%d 图）" % (idx, m.group(1), len(payload["files"])))
            else:
                err = re.search(r"ERROR (.+)", out)
                print("  #%d 失败：%s" % (idx, err.group(1) if err else out.strip()[:160]))
            common.jdump(ids_path, ids)
            import time
            time.sleep(a.gap)

    # 统一核验：只读列表，不打开草稿
    out = run_js({"mode": "list", "space_id": a.space, "note": 0})
    rows = parse_list(out)
    if rows is None:
        err = re.search(r"ERROR (.+)", out)
        common.die("列表核验失败：%s" % (err.group(1) if err else out.strip()[:200]))
    by_id = {r["id"]: r for r in rows}
    ok = miss = empty = 0
    print("\n草稿箱核验（贴图共 %d 条）" % len(rows))
    for idx, note in enumerate(notes, 1):
        rec = ids.get(str(idx))
        if not rec:
            continue
        r = by_id.get(rec["appmsgid"])
        if r is None:
            print("  #%-2d ✗ 列表中没有（可能被后台清理）  %s" % (idx, rec["title"]))
            miss += 1
        elif not r["cover"] or r["digest_len"] < 50:
            print("  #%-2d ✗ 图片或正文缺失 cover=%s 正文%d字  %s"
                  % (idx, r["cover"], r["digest_len"], rec["title"]))
            empty += 1
        else:
            print("  #%-2d ✓ %s（封面+正文 %d 字）" % (idx, rec["title"], r["digest_len"]))
            ok += 1
    print("\n正常 %d ／ 缺失 %d ／ 残缺 %d" % (ok, miss, empty))
    if miss or empty:
        sys.exit(7)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""rss_import.py — 阶段 0-1（RSS 通道）：不依赖 REDFOX，用 RSS 抓选题素材。

为什么用 RSS 做替代：
  · 免费、无需 Key、结构稳定（RSS 2.0 / Atom 都是标准 XML）；
  · 只给标题 + 摘要 + 链接，天然符合「只取选题信号、正文自己写」的原则，不诱导抄袭；
  · 任意垂类都能找到 1–2 个可订阅源，比爬虫稳，比手抄快。

支持：
  · http(s) feed、本地文件路径、file://
  · RSS 2.0（<item>）与 Atom（<entry>）
  · 关键词过滤（标题/摘要命中任一即保留，命中越多排越前）
  · 去重：先按链接，再按归一化标题

用法（一般由 run.py init --source rss 调用）：
  python3 scripts/rss_import.py --check            # 逐个探测配置里的 feed 是否可用
  python3 scripts/rss_import.py --url <feed> --keyword 护肤 --n 3   # 单独试抓
"""
import argparse
import email.utils
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

UA = "Mozilla/5.0 (compatible; WECHAT-picture-design/2.2; +rss)"
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[\s\u3000]+")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _text(node, names):
    for n in names:
        el = node.find(n)
        if el is not None and (el.text or "").strip():
            return el.text.strip()
    return ""


def _clean(s, limit=600):
    s = TAG_RE.sub(" ", html.unescape(s or ""))
    s = WS_RE.sub(" ", s).strip()
    return s[:limit]


def _pub(ts):
    if not ts:
        return ""
    try:
        return email.utils.parsedate_to_datetime(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts[:19]


def read_source(url, timeout=20):
    """读 feed：支持 http(s)、file://、本地路径。"""
    if re.match(r"^https?://", url):
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    path = url[7:] if url.startswith("file://") else url
    with open(os.path.expanduser(path), "rb") as f:
        return f.read()


def parse_feed(blob, feed_url=""):
    """解析 RSS 2.0 / Atom，返回 item 列表（字段已清洗）。"""
    root = ET.fromstring(blob)
    tag = root.tag.split("}")[-1].lower()
    items = []
    nodes = root.iter()
    if tag == "feed":                      # Atom
        for e in nodes:
            if e.tag.split("}")[-1].lower() != "entry":
                continue
            link = ""
            for l in e.findall("{*}link"):
                if l.get("rel") in (None, "alternate"):
                    link = l.get("href") or ""
                    break
            summary = _text(e, ["{*}summary", "{*}content"])
            items.append({
                "title": _text(e, ["{*}title"]),
                "link": link,
                "desc": _clean(summary),
                "author": _text(e, ["{*}name"]),
                "pub": _pub(_text(e, ["{*}updated", "{*}published"])),
            })
    else:                                   # RSS 2.0 / RDF
        for e in nodes:
            if e.tag.split("}")[-1].lower() != "item":
                continue
            desc = _text(e, ["description", "{*}encoded", "{*}summary"])
            cover = ""
            for enc in e.findall("{*}enclosure"):
                if (enc.get("type") or "").startswith("image"):
                    cover = enc.get("url") or ""
                    break
            if not cover:
                for mc in e.findall("{*}content"):
                    if (mc.get("medium") or "") == "image" or (mc.get("type") or "").startswith("image"):
                        cover = mc.get("url") or ""
                        break
            items.append({
                "title": _text(e, ["title"]),
                "link": _text(e, ["link"]) or e.get("{*}about", ""),
                "desc": _clean(desc),
                "author": _text(e, ["{*}creator", "author"]),
                "pub": _pub(_text(e, ["pubDate", "{*}updated", "{*}published"])),
                "cover": cover,
            })
    for it in items:
        it["feed"] = feed_url
        it.setdefault("cover", "")
    return [it for it in items if it["title"]]


def _hits(text, keywords):
    t = text.lower()
    return sum(1 for k in keywords if k and k.lower() in t)


def collect(keywords, n, cfg=None, window_days=90, log=None, runs_root=None):
    """按配置里的 feed 列表抓取，返回 (items, fetch_report)。items 结构与 source_pool 对齐。"""
    cfg = cfg or common.load_config()
    feeds = (cfg.get("channels", {}).get("rss") or {}).get("feeds") or []
    limit = (cfg.get("channels", {}).get("rss") or {}).get("limit_per_feed", 20)
    if not feeds:
        common.die("channels.rss.feeds 为空：请先跑 setup_wizard.py 选 RSS 源，或手工在 config.json 里填 feed URL", 4)

    kws = [k for k in (keywords if isinstance(keywords, (list, tuple)) else str(keywords).replace("，", " ").replace(",", " ").split())
           if k.strip()]
    all_items, feed_stat = [], []
    for url in feeds:
        try:
            blob = read_source(url)
            items = parse_feed(blob, url)
            feed_stat.append({"feed": url, "items": len(items), "ok": True})
            if log and runs_root:
                common.log_event(runs_root, "S1", "RSS %s 取回 %d 条" % (url, len(items)))
        except Exception as e:
            feed_stat.append({"feed": url, "items": 0, "ok": False, "error": str(e)[:120]})
            if log and runs_root:
                common.log_event(runs_root, "S1", "RSS 抓取失败 %s：%s" % (url, e), "warn")
            continue
        # 关键词过滤 + 评分
        kept = []
        for it in items[:limit]:
            blob_txt = it["title"] + " " + it["desc"]
            h = _hits(blob_txt, kws)
            if kws and h == 0:
                continue
            it["_hits"] = h
            kept.append(it)
        all_items.extend(kept)

    # 去重：链接 → 归一化标题
    seen_link, seen_title, dedup = set(), set(), []
    ordered = sorted(all_items, key=lambda x: x["pub"], reverse=True)   # 新的在前
    ordered = sorted(ordered, key=lambda x: -x["_hits"])                # 命中多的在前（稳定）
    for it in ordered:
        link = (it.get("link") or "").split("?")[0]
        title = WS_RE.sub("", it["title"])[:40]
        if link and link in seen_link:
            continue
        if title in seen_title:
            continue
        seen_link.add(link)
        seen_title.add(title)
        dedup.append(it)

    items = []
    for i, it in enumerate(dedup[:n], 1):
        items.append({
            "id": "rss-%d" % i,
            "channel": "rss",
            "title": it["title"],
            "text": it["desc"],
            "author": it.get("author") or "RSS",
            "url": it.get("link") or "",
            "publish_time": it.get("pub") or "",
            "cover_url": it.get("cover") or "",
            "metrics": {"like": 0, "collect": 0, "share": 0, "comment": 0},
            "is_image_post": False,
            "score": it["_hits"],
        })
    report = {
        "source": "rss",
        "channels": {"rss": len(items)},
        "channel_mix": {"rss": len(items)},
        "feeds": feed_stat,
        "candidates": len(all_items),
        "after_dedupe": len(dedup),
        "selected": len(items),
        "keywords": kws,
        "note": "RSS 只提供标题与摘要；正文须自行改写，不得整段搬运",
    }
    return items, report


def check_feeds(cfg=None):
    cfg = cfg or common.load_config()
    feeds = (cfg.get("channels", {}).get("rss") or {}).get("feeds") or []
    if not feeds:
        print("配置里没有 RSS feed（channels.rss.feeds 为空）")
        return 1
    bad = 0
    for url in feeds:
        try:
            items = parse_feed(read_source(url), url)
            print("  ✅ %-60s %d 条" % (url[:60], len(items)))
        except Exception as e:
            bad += 1
            print("  ❌ %-60s %s" % (url[:60], str(e)[:60]))
    print("\n可用 %d / 共 %d" % (len(feeds) - bad, len(feeds)))
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="RSS 通道：探测与试抓")
    ap.add_argument("--check", action="store_true", help="逐个探测 config 里的 feed")
    ap.add_argument("--url", help="单个 feed URL 或本地 XML 路径")
    ap.add_argument("--keyword", default="", help="试抓时的关键词，空格分隔")
    ap.add_argument("--n", type=int, default=5)
    a = ap.parse_args()
    if a.check:
        sys.exit(check_feeds())
    if not a.url:
        ap.error("要么 --check，要么给 --url")
    items, rep = collect(a.keyword or "", a.n, cfg={"channels": {"rss": {"feeds": [a.url]}}})
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    for it in items:
        print("- [%s] %s" % (it["publish_time"][:10], it["title"]))
        print("  %s" % it["text"][:90])


if __name__ == "__main__":
    main()

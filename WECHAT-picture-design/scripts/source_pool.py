# -*- coding: utf-8 -*-
"""source_pool.py — 阶段 0/1：多渠道爆款素材采集（公众号 / 小红书 / 全网热点）。

渠道（可在 config.channels 开关）：
  gzh  公众号侧爆款：redfox 无「贴图」专用检索，用 hotArticleNew 取公众号高互动内容，作选题与结构参考
  xhs  小红书贴图（图文笔记）：xhs/search/search + xhs/search/noteDetail，作选题与版式参考
  hot  全网热点：hotKeyword/list，仅提供选题信号（无正文，不参与改写）

统一条目结构：
  {id, channel, title, text, url, publish_time, author, metrics{read,like,collect,share,comment},
   is_image_post, score, usable_as_source}

注意：渠道只影响「素材从哪来」；成稿规范一律按微信公众号贴图（newspic）执行，不沿用任何平台专属表述。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class RedfoxError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class Redfox:
    def __init__(self, config=None):
        cfg = config or common.load_config()
        r = cfg["redfox"]
        self.base = r["base"].rstrip("/")
        self.key = os.environ.get("REDFOX_API_KEY") or r.get("api_key", "")
        self.endpoints = r["endpoints"]
        self.timeout = r.get("timeout", 30)

    def post(self, endpoint_key, payload, retries=2):
        url = self.base + self.endpoints[endpoint_key]
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   "REDFOX_API_KEY": self.key, "X-API-KEY": self.key}
        last = None
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                if data.get("code") != 2000:
                    raise RedfoxError("接口返回异常 code=%s msg=%s"
                                      % (data.get("code"), data.get("msg") or data.get("message")),
                                      code=data.get("code"))
                return data
            except RedfoxError:
                raise
            except urllib.error.HTTPError as e:
                last = "HTTP %s %s" % (e.code, url)
                if e.code in (401, 403):
                    break
            except Exception as e:
                last = "%s (%s)" % (e, url)
            time.sleep(1.2 * (attempt + 1))
        raise RedfoxError("请求失败：%s" % last)

    # ---------- 渠道采集 ----------
    def probe(self, keyword):
        """连通性：取 1 条公众号内容，校验凭证与关键字段。"""
        today = datetime.date.today()
        start = today - datetime.timedelta(days=90)
        d = self.post("gzh_hot", {"keyword": keyword, "startDate": start.isoformat(),
                                  "endDate": today.isoformat(), "pageNum": 1, "pageSize": 1})
        arts = (d.get("data") or {}).get("articles") or []
        if not arts:
            return {"ok": False, "reason": "接口可达但无返回", "fields": []}
        need = ["id", "title", "summary", "clicksCount", "publicTime", "url"]
        missing = [k for k in need if arts[0].get(k) in (None, "")]
        return {"ok": not missing, "sample_id": arts[0].get("id"),
                "missing_fields": missing, "fields": sorted(arts[0].keys())}

    def gzh(self, keyword, start, end):
        d = self.post("gzh_hot", {"keyword": keyword, "startDate": start, "endDate": end,
                                  "pageNum": 1, "pageSize": 50})
        out = []
        for a in (d.get("data") or {}).get("articles") or []:
            out.append({
                "id": "gzh-" + str(a.get("id")),
                "channel": "gzh",
                "title": (a.get("title") or "").strip(),
                "text": (a.get("summary") or "").strip(),
                "author": a.get("author") or "",
                "url": a.get("url") or "",
                "publish_time": a.get("publicTime") or "",
                "metrics": {"read": a.get("clicksCount") or 0, "like": a.get("likeCount") or 0,
                            "collect": 0, "share": a.get("shareCount") or 0,
                            "comment": a.get("commentsCount") or 0},
                "cover_url": a.get("imageUrl") or "",
                "is_image_post": None,     # 公众号侧无贴图标识，按图文近似
            })
        return out

    def xhs(self, keyword, start, end, pages=(1, 2)):
        out = []
        for q in [keyword, keyword + " 图文", keyword + " 贴图"]:
            for p in pages:
                d = self.post("xhs_search", {"keyword": q, "pageNum": p, "pageSize": 50,
                                             "startDate": start, "endDate": end})
                arts = (d.get("data") or {}).get("articles") or []
                if not arts:
                    break
                for a in arts:
                    if not a.get("id"):
                        continue
                    out.append({
                        "id": "xhs-" + str(a["id"]),
                        "channel": "xhs",
                        "raw_id": str(a["id"]),
                        "title": (a.get("title") or "").strip(),
                        "text": (a.get("desc") or "").strip(),
                        "author": a.get("authorNickname") or "",
                        "url": a.get("shareInfoLink") or "",
                        "publish_time": a.get("createTime") or "",
                        "metrics": {"read": 0, "like": a.get("likedCount") or 0,
                                    "collect": a.get("collectedCount") or 0,
                                    "share": a.get("sharedCount") or 0,
                                    "comment": a.get("commentsCount") or 0},
                        "cover_url": a.get("cover") or "",
                        "is_image_post": None,
                    })
        return out

    def enrich_xhs(self, item):
        """补详情：判定图文/视频，取完整正文。"""
        d = self.post("xhs_detail", {"noteId": item.get("raw_id")})
        arr = (d.get("data") or [])
        if not arr:
            return item
        it = arr[0]
        item["is_image_post"] = (it.get("noteType") == "normal")
        item["text"] = (it.get("contentDesc") or item["text"]).strip()
        item["title"] = (it.get("noteTitle") or item["title"]).strip()
        item["metrics"].update({
            "like": it.get("thumbCount") or item["metrics"]["like"],
            "collect": it.get("favoriteCount") or item["metrics"]["collect"],
            "comment": it.get("replyCount") or item["metrics"]["comment"],
            "share": it.get("forwardCount") or item["metrics"]["share"],
        })
        item["hashtags"] = it.get("hashTags") or []
        return item

    def hot(self, start_dt, end_dt, keyword):
        d = self.post("hot_keyword", {"startDate": start_dt, "endDate": end_dt})
        out = []
        for group in d.get("data") or []:
            for h in group.get("hotSpotList") or []:
                title = (h.get("title") or "").strip()
                out.append({
                    "id": "hot-" + str(h.get("hotId")),
                    "channel": "hot",
                    "title": title,
                    "text": "",
                    "author": h.get("platName") or "",
                    "url": h.get("url") or "",
                    "publish_time": h.get("latestRankDate") or "",
                    "metrics": {"read": 0, "like": 0, "collect": 0, "share": 0,
                                "comment": 0, "hot_score": h.get("maxHotScore") or 0},
                    "is_image_post": False,
                })
        return out


# ---------------- 排序与筛选 ----------------

def _norm(values):
    lo, hi = min(values), max(values)
    if hi <= lo:
        return [0.5] * len(values)
    return [(v - lo) / float(hi - lo) for v in values]


def score_items(items, cfg):
    if not items:
        return items
    likes = _norm([i["metrics"].get("like", 0) for i in items])
    collects = _norm([i["metrics"].get("collect", 0) for i in items])
    shares = _norm([i["metrics"].get("share", 0) for i in items])
    comments = _norm([i["metrics"].get("comment", 0) for i in items])
    reads = _norm([i["metrics"].get("read", 0) for i in items])
    weights = {k: v.get("weight", 1.0) for k, v in cfg["channels"].items() if isinstance(v, dict)}
    for n, it in enumerate(items):
        base = 0.30 * likes[n] + 0.20 * collects[n] + 0.15 * shares[n] + 0.15 * comments[n] + 0.20 * reads[n]
        bonus = 0.15 if it.get("is_image_post") else 0.0
        it["score"] = round(base * weights.get(it["channel"], 1.0) + bonus, 4)
    items.sort(key=lambda x: x["score"], reverse=True)
    return items


def _dedupe_key(it):
    if it["channel"] == "xhs":
        return urllib.parse.urlsplit(it["url"]).path or it["id"]
    return "".join(ch for ch in it["title"].lower() if ch.isalnum())[:40]


def _bigrams(text):
    t = "".join(ch for ch in text if ch.isalnum())
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 2 else {t}


def _jac(a, b):
    return len(a & b) / float(len(a | b)) if a and b else 0.0


def dedupe(items):
    seen, kept, removed = set(), [], []
    for it in items:
        key = _dedupe_key(it)
        if key and key in seen:
            removed.append({"id": it["id"], "title": it["title"], "channel": it["channel"],
                            "reason": "键重复"})
            continue
        dup = None
        for k in kept:
            if k["channel"] != it["channel"]:
                continue
            if _jac(_bigrams(it["title"]), _bigrams(k["title"])) >= 0.8 or \
               _jac(_bigrams(it["text"][:120]), _bigrams(k["text"][:120])) >= 0.7:
                dup = k
                break
        if dup is not None:
            removed.append({"id": it["id"], "title": it["title"], "channel": it["channel"],
                            "reason": "标题近重复"})
            continue
        seen.add(key)
        kept.append(it)
    return kept, removed


def collect(keyword, n, cfg=None, window_days=90, max_xhs_detail=24, log=None, run_root=None):
    """三渠道并行采集 → 去重 → 打分 → 产出候选（含热点信号）。"""
    cfg = cfg or common.load_config()
    rf = Redfox(cfg)
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=window_days)).isoformat()
    end = today.isoformat()
    enabled = cfg["channels"]["enabled"]
    report = {"keyword": keyword, "window_days": window_days, "channels": {}, "errors": []}

    pool = []
    if "gzh" in enabled:
        try:
            g = rf.gzh(keyword, start, end)
            report["channels"]["gzh"] = {"count": len(g), "label": cfg["channels"]["gzh"]["label"]}
            pool.extend(g)
        except RedfoxError as e:
            report["errors"].append({"channel": "gzh", "error": str(e)})
            if log:
                log("S1", "公众号渠道失败：%s" % e, "warn")

    if "xhs" in enabled:
        try:
            x = rf.xhs(keyword, start, end)
            report["channels"]["xhs"] = {"count": len(x), "label": cfg["channels"]["xhs"]["label"]}
            pool.extend(x)
        except RedfoxError as e:
            report["errors"].append({"channel": "xhs", "error": str(e)})
            if log:
                log("S1", "小红书渠道失败：%s" % e, "warn")

    topic_signals = []
    if "hot" in enabled:
        try:
            h_start = (today - datetime.timedelta(days=7)).isoformat()
            h = rf.hot(h_start + " 00:00:00", end + " 23:59:59", keyword)
            tokens = [t for t in keyword.split() if t]
            hit = [x for x in h if any(t in x["title"] for t in tokens)] if tokens else []
            report["channels"]["hot"] = {"count": len(h), "matched": len(hit),
                                         "label": cfg["channels"]["hot"]["label"]}
            topic_signals = sorted(hit, key=lambda x: x["metrics"].get("hot_score", 0), reverse=True)[:10]
        except RedfoxError as e:
            report["errors"].append({"channel": "hot", "error": str(e)})
            if log:
                log("S1", "热点渠道失败：%s" % e, "warn")

    report["pool_raw"] = len(pool)
    pool, removed = dedupe(pool)
    report["dedupe_removed"] = len(removed)
    report["dedupe_detail"] = removed[:20]

    # 相关性分级：先要求命中主词（关键词第一个词），不足再放宽到任一词
    tokens = [t for t in keyword.split() if t]
    primary = tokens[0] if tokens else ""

    def rel(it, must):
        blob = it["title"] + " " + it["text"]
        return must in blob if must else True

    strict = [c for c in pool if rel(c, primary)]
    report["after_relevance_strict"] = len(strict)
    candidates = strict if len(strict) >= n * 3 else [c for c in pool if any(t in (c["title"] + c["text"]) for t in tokens)]
    report["relevance_mode"] = "primary" if strict else "any_token"
    candidates = [c for c in candidates if c["channel"] != "hot" and len(c["text"]) >= 80]

    # 业务相关性黑名单：保健品/带货/壁纸/涉法新闻一律剔除
    bl = cfg["channels"].get("blocklist", {})
    words, risk_topics = bl.get("words", []), bl.get("topics", [])
    blocked, kept = [], []
    for c in candidates:
        blob = c["title"] + " " + c["text"]
        hit = [w for w in words if w.lower() in blob.lower()]
        risk = [t for t in risk_topics if t in blob]
        if hit or risk:
            blocked.append({"id": c["id"], "title": c["title"][:24], "hit": (hit + risk)[:4]})
            continue
        kept.append(c)
    candidates = kept
    report["blocklist_removed"] = len(blocked)
    report["blocklist_detail"] = blocked[:12]
    if log:
        log("S1", "业务黑名单剔除 %d 条：%s" % (len(blocked), "、".join(b["title"] for b in blocked[:5])))
    candidates = score_items(candidates, cfg)

    # 先给高分 xhs 候选补详情（判定图文 + 取全文），再按「贴图形态优先」排序
    detail_calls = 0
    for c in candidates[:max_xhs_detail]:
        if c["channel"] == "xhs" and c.get("is_image_post") is None:
            try:
                rf.enrich_xhs(c)
                detail_calls += 1
            except RedfoxError as e:
                report["errors"].append({"channel": "xhs", "id": c["id"], "error": str(e)})
                continue
    report["xhs_detail_calls"] = detail_calls

    candidates.sort(key=lambda x: (x.get("is_image_post") is True, x["score"]), reverse=True)
    usable = [c for c in candidates if c.get("is_image_post") is not False]
    selected = usable[:n]
    report["pool_total"] = len(pool)
    report["usable"] = len(usable)
    report["selected"] = [{"id": s["id"], "channel": s["channel"], "title": s["title"]} for s in selected]
    report["topic_signals"] = [{"title": t["title"], "platform": t["author"],
                                "hot_score": t["metrics"].get("hot_score")} for t in topic_signals]
    report["channel_mix"] = {}
    for s in selected:
        report["channel_mix"][s["channel"]] = report["channel_mix"].get(s["channel"], 0) + 1
    return selected, report


def download_cover(url, dest, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        blob = resp.read()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(blob)
    return dest

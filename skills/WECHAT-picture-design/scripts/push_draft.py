# -*- coding: utf-8 -*-
"""push_draft.py — 阶段 6：写入微信公众号草稿箱（贴图 / 图片消息 newspic）。

官方依据：
  POST https://api.weixin.qq.com/cgi-bin/draft/add
  article_type = "newspic"（图片消息，即公众号「贴图」）
  字段：title ≤32 字；content 纯文本（≤20000 字符，话题用 #话题名# 写在正文内）；
        image_info.image_list[].image_media_id 必须为永久素材（material/add_material 返回）；
        首张图为封面；cover_info.crop_percent_list 支持 1_1 / 16_9 / 2.35_1。

凭证缺失时：不伪造调用，输出「贴图发布包」到 drafts/NN/（按发布顺序的图片 + title.txt + content.txt + meta.json），
状态 local_only，并在摘要注明未推送。
"""
import argparse
import hashlib
import json
import mimetypes
import os
import shutil
import sys
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

API = "https://api.weixin.qq.com"


def _multipart(url, file_field, file_path, timeout=90):
    boundary = "----XH" + uuid.uuid4().hex
    ctype = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    with open(file_path, "rb") as f:
        blob = f.read()
    head = ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
            "Content-Type: %s\r\n\r\n"
            % (boundary, file_field, os.path.basename(file_path), ctype)).encode("utf-8")
    tail = ("\r\n--%s--\r\n" % boundary).encode("utf-8")
    data = head + blob + tail
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "multipart/form-data; boundary=%s" % boundary,
        "Content-Length": str(len(data))})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url, payload, timeout=90):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class WeChatClient:
    def __init__(self, appid, secret):
        self.appid, self.secret = appid, secret
        self.token = None

    def access_token(self):
        if self.token:
            return self.token
        q = urllib.parse.urlencode({"grant_type": "client_credential",
                                    "appid": self.appid, "secret": self.secret})
        with urllib.request.urlopen(API + "/cgi-bin/token?" + q, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
        if "access_token" not in d:
            raise RuntimeError("获取 access_token 失败：%s（检查 appid/secret 与 IP 白名单）" % d)
        self.token = d["access_token"]
        return self.token

    def upload_image_material(self, path):
        """永久图片素材：贴图 image_media_id 必须用它，不能用 uploadimg 的 URL。"""
        url = "%s/cgi-bin/material/add_material?access_token=%s&type=image" % (API, self.access_token())
        d = _multipart(url, "media", path)
        if "media_id" not in d:
            raise RuntimeError("素材上传失败：%s" % d)
        return d["media_id"]

    def add_sticker_draft(self, title, content, media_ids, need_open_comment=0, ratio=None):
        article = {
            "article_type": "newspic",
            "title": title,
            "content": content,
            "need_open_comment": need_open_comment,
            "only_fans_can_comment": 0,
            "image_info": {"image_list": [{"image_media_id": m} for m in media_ids]},
        }
        if ratio:
            article["cover_info"] = {"crop_percent_list": [
                {"ratio": ratio, "x1": "0", "y1": "0", "x2": "1", "y2": "1"}]}
        d = _post_json(API + "/cgi-bin/draft/add?access_token=" + self.access_token(),
                       {"articles": [article]})
        if "media_id" not in d:
            raise RuntimeError("草稿写入失败：%s" % d)
        return d["media_id"]


def build_content(copy_obj):
    """正文 + 话题（#话题# 写在正文内，无独立字段）。"""
    body = (copy_obj.get("body") or "").strip()
    topics = copy_obj.get("topics") or []
    if topics:
        return body + "\n\n" + " ".join("#%s#" % t for t in topics)
    return body


def artifact_sig(run_root, nd, manifest):
    h = hashlib.sha1()
    for p in [os.path.join(nd, "copy.json")] + [common.resolve(run_root, pg["file"]) for pg in manifest["pages"]]:
        if os.path.exists(p):
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()[:16]


def validate_platform(title, content, pages, cfg):
    p = cfg["platform"]
    problems = []
    if not (1 <= len(title) <= p["title_max"]):
        problems.append("标题 %d 字，平台上限 %d 字" % (len(title), p["title_max"]))
    if len(content) > p["content_max_chars"]:
        problems.append("正文 %d 字符，平台上限 %d" % (len(content), p["content_max_chars"]))
    if not (1 <= len(pages) <= p["image_count_max"]):
        problems.append("图片 %d 张，平台上限 %d 张" % (len(pages), p["image_count_max"]))
    for pg in pages:
        mb = os.path.getsize(pg) / 1024.0 / 1024.0
        if mb > p["image_max_mb"]:
            problems.append("%s 体积 %.1fMB 超过 %dMB" % (os.path.basename(pg), mb, p["image_max_mb"]))
    return problems


def run(run_root, dry_run=False):
    meta = common.load_run(run_root)
    cfg = common.load_config()
    selfcheck = common.jload(os.path.join(run_root, "data", "selfcheck.json"))
    if selfcheck is None or not selfcheck.get("all_pass"):
        common.die("阶段5 自检未全部通过，拒绝写入草稿")

    for entry in selfcheck.get("notes", []):
        idx = entry["index"]
        nd = common.note_dir(run_root, idx)
        manifest = common.jload(os.path.join(nd, "compose-manifest.json"))
        if manifest is None:
            common.die("第%d篇缺少 compose-manifest.json" % idx)
        if artifact_sig(run_root, nd, manifest) != entry.get("artifact_sig"):
            common.die("第%d篇自检结果已过期（文案或配图在自检后被修改），请重新执行 check" % idx)

    wc = cfg.get("wechat", {})
    appid, secret = wc.get("appid", ""), wc.get("secret", "")
    client = None
    mode = "local_only"
    if appid and secret and not dry_run:
        client = WeChatClient(appid, secret)
        mode = "wechat_draft_newspic"
    elif appid and secret and dry_run:
        mode = "wechat_dryrun"

    drafts_root = os.path.join(run_root, "drafts")
    os.makedirs(drafts_root, exist_ok=True)
    result = {"pushed_at": common.now_str(), "mode": mode,
              "article_type": cfg["wechat"].get("article_type", "newspic"), "notes": []}

    for idx, note in enumerate(meta["notes"], start=1):
        nd = common.note_dir(run_root, idx)
        copy_obj = common.jload(os.path.join(nd, "copy.json"))
        manifest = common.jload(os.path.join(nd, "compose-manifest.json"))
        pages = [common.resolve(run_root, p["file"]) for p in manifest["pages"]]
        title = (copy_obj.get("title") or "").strip()
        content = build_content(copy_obj)
        problems = validate_platform(title, content, pages, cfg)

        out_dir = os.path.join(drafts_root, "%02d" % idx)
        os.makedirs(out_dir, exist_ok=True)
        rec = {"index": idx, "title": title, "source_id": note["id"],
               "source_channel": note.get("channel"), "mode": mode,
               "pages": len(pages), "title_chars": len(title), "content_chars": len(content)}

        if problems:
            rec.update({"status": "rejected", "reason": problems})
            common.log_event(run_root, "S6", "第%d篇不符合平台规范：%s" % (idx, "；".join(problems)), "error")
            print("  ✗ #%d 未通过平台校验：%s" % (idx, "；".join(problems)))
            result["notes"].append(rec)
            continue

        if mode == "wechat_draft_newspic":
            try:
                media_ids = [client.upload_image_material(p) for p in pages]
                media_id = client.add_sticker_draft(title, content, media_ids,
                                                    ratio=cfg["wechat"].get("cover_ratio"))
                rec.update({"status": "draft_created", "media_id": media_id,
                            "image_media_ids": media_ids})
                common.log_event(run_root, "S6", "第%d篇贴图草稿已创建：%s" % (idx, media_id))
                print("  #%d 草稿已创建 → %s" % (idx, media_id))
            except Exception as e:
                rec.update({"status": "failed", "error": str(e)})
                common.log_event(run_root, "S6", "第%d篇草稿创建失败：%s" % (idx, e), "error")
                print("  ✗ #%d 草稿创建失败：%s" % (idx, e))
        else:
            for i, p in enumerate(pages, 1):
                shutil.copy2(p, os.path.join(out_dir, "%02d%s"
                                             % (i, os.path.splitext(p)[1] or ".png")))
            common.write_text(os.path.join(out_dir, "title.txt"), title + "\n")
            common.write_text(os.path.join(out_dir, "content.txt"), content + "\n")
            common.jdump(os.path.join(out_dir, "meta.json"), {
                "article_type": "newspic", "title": title,
                "topics": copy_obj.get("topics") or [],
                "content_chars": len(content), "pages": len(pages),
                "source_id": note["id"], "source_channel": note.get("channel"),
                "cover": "01.png（首图即封面，后台可裁 1:1 / 16:9 / 2.35:1）",
            })
            rec["status"] = "local_only"
            rec["reason"] = ("未配置公众号 appid/secret，发布包已落盘未推送"
                             if mode == "local_only" else "dry-run 未实际推送")
            common.log_event(run_root, "S6", "第%d篇发布包已落盘（未推送）：%s" % (idx, out_dir), "warn")
            print("  #%d 发布包 → %s（%d 张图 + 标题 + 正文）" % (idx, out_dir, len(pages)))

        result["notes"].append(rec)

    common.jdump(os.path.join(run_root, "data", "draft-result.json"), result)
    return result


def main():
    ap = argparse.ArgumentParser(description="阶段6 写入公众号贴图草稿")
    ap.add_argument("--run", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    r = run(args.run, args.dry_run)
    ok = [n for n in r["notes"] if n["status"] in ("draft_created", "local_only")]
    print("模式：%s（article_type=%s）；成功 %d/%d"
          % (r["mode"], r["article_type"], len(ok), len(r["notes"])))
    if any(n["status"] in ("failed", "rejected") for n in r["notes"]):
        sys.exit(1)


if __name__ == "__main__":
    main()

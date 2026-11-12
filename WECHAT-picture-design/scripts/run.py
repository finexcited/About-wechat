# -*- coding: utf-8 -*-
"""run.py — WECHAT-picture-design 编排入口。

子命令（对应 SKILL 阶段）：
  init         阶段 0-1：参数校验 → Redfox 连通性测试 → 三渠道采集素材 → 落盘候选
  spec         阶段 2：平台规范基线 + 素材参考统计 → data/spec-extracted.md + spec.json
  brief        阶段 3 输入：为每篇生成改写素材包（源文 + 字数目标）
  deai         阶段 3.4：生成去 AI 味清单（交给人化技能处理）
  verify-text  阶段 3.3：字数与 n-gram 重合硬性关卡
  prompts      阶段 4.1：按骨架/色系/尺寸生成生图提示词
  compose      阶段 4.2-4.3：配图合成 + LOGO 嵌入 + 文字渲染
  check        阶段 5：六项合规自检
  draft        阶段 6：写入公众号草稿（newspic 贴图）
  report       运行摘要
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import source_pool
import rss_import
import spec_extract
import textcheck
import compose_images
import canvas_render
import philosophy
import check_compliance
import push_draft

ALLOWED_LOGO_EXT = (".png", ".webp", ".jpg", ".jpeg")


# ---------------- 阶段 0 ----------------

def validate_checklist(keyword, n, logo, relax):
    problems = []
    if not keyword or not keyword.strip():
        problems.append("关键词为空")
    if not (1 <= n <= 10):
        problems.append("篇数 N=%s 不在 1–10 区间（超出请分批）" % n)
    if not logo or not os.path.exists(logo):
        problems.append("LOGO 文件不存在：%s" % logo)
    else:
        ext = os.path.splitext(logo)[1].lower()
        if ext not in ALLOWED_LOGO_EXT:
            problems.append("LOGO 需为透明背景 PNG（当前 %s）；SVG 请先导出为 512×512 以上 PNG" % ext)
        else:
            try:
                from PIL import Image
                with Image.open(logo) as im:
                    w, h = im.size
                    has_alpha = im.mode in ("RGBA", "LA") or "transparency" in im.info
                    if w < 512 or h < 512:
                        problems.append("LOGO 分辨率 %dx%d 低于 512×512" % (w, h))
                    if not has_alpha:
                        problems.append("LOGO 缺少透明背景（需 RGBA/带 alpha 的 PNG）")
            except Exception as e:
                problems.append("LOGO 无法解析：%s" % e)
    if relax not in ("ask", "allow", "deny"):
        problems.append("--relax 取值非法：%s" % relax)
    return problems


def cmd_init(args):
    cfg = common.load_config()
    if not args.logo:
        args.logo = common.resolve(os.path.dirname(os.path.abspath(__file__)) + "/..",
                                   cfg.get("logo", {}).get("default", "assets/logo.png"))
    problems = validate_checklist(args.keyword, args.n, args.logo, args.relax)
    if problems:
        print("运行前检查未通过：")
        for p in problems:
            print("  ✗ " + p)
        common.die("请补全后重试", 3)

    src = getattr(args, "source", "auto")
    if src == "auto":
        has_key = bool((cfg.get("redfox") or {}).get("api_key") or os.environ.get("REDFOX_API_KEY"))
        has_feed = bool((cfg.get("channels", {}).get("rss") or {}).get("feeds"))
        src = "redfox" if has_key or not has_feed else "rss"

    if src == "rss":
        print("阶段 0：RSS 通道（不依赖 REDFOX）…")
        run_root = common.create_run(args.workdir, args.keyword)
        log = lambda s, m, lv="info", extra=None: common.log_event(run_root, s, m, lv, extra)
        print("阶段 1：按关键词过滤 RSS 素材 …")
        items, freport = rss_import.collect(args.keyword, args.n, cfg=cfg,
                                            window_days=args.window, log=log, runs_root=run_root)
        if not items:
            common.die("RSS 未取回任何相关素材：先跑 `rss_import.py --check` 确认 feed 可访问，"
                       "或把关键词放宽一层", 4)
        common.ok("RSS 采集完成：%d 篇（feed %d 个）"
                  % (len(items), len(freport.get("feeds", []))))
    else:
        print("阶段 0：Redfox 连通性测试 …")
        rf = source_pool.Redfox(cfg)
        try:
            probe = rf.probe(args.keyword)
        except source_pool.RedfoxError as e:
            common.die("Redfox 连通性失败：%s（按 spec，禁止在无数据状态生成内容）" % e, 4)
        if not probe.get("ok"):
            common.die("Redfox 返回字段不完整：缺失 %s" % probe.get("missing_fields"), 4)
        common.ok("连通性正常（sample=%s，字段齐全）" % probe.get("sample_id"))

        run_root = common.create_run(args.workdir, args.keyword)
        log = lambda s, m, lv="info", extra=None: common.log_event(run_root, s, m, lv, extra)

        print("阶段 1：三渠道采集素材（公众号 / 小红书 / 全网热点）…")
        items, freport = source_pool.collect(args.keyword, args.n, cfg=cfg, window_days=args.window,
                                             max_xhs_detail=args.max_detail_calls,
                                             log=log, run_root=run_root)
    notes = []
    for it in items:
        m = it["metrics"]
        notes.append({
            "id": it["id"], "channel": it["channel"], "title": it["title"],
            "desc": it["text"], "author": it["author"], "url": it["url"],
            "publish_time": it["publish_time"], "cover_url": it.get("cover_url", ""),
            "likes": m.get("like", 0), "collects": m.get("collect", 0),
            "shares": m.get("share", 0), "comments": m.get("comment", 0),
            "is_image_post": it.get("is_image_post"), "score": it.get("score"),
        })
    common.jdump(os.path.join(run_root, "data", "fetch-report.json"), freport)

    if len(notes) < args.n:
        msg = "三渠道仅采集到 %d/%d 篇可用素材" % (len(notes), args.n)
        if args.relax == "deny" or (args.relax == "ask"):
            print("⚠️ " + msg)
            print("   可选：接受缩量（--relax allow）、更换关键词，或放宽检索后重跑")
            common.jdump(common.run_meta_path(run_root), {
                "run_id": os.path.basename(run_root), "keyword": args.keyword, "n": args.n,
                "status": "insufficient", "found": len(notes),
            })
            print("   RUN_DIR=%s" % run_root)
            sys.exit(5)
        print("⚠️ " + msg + " → 按 --relax allow 接受缩量")
        log("S1", msg + "，接受缩量", "warn")

    # 下载封面（仅作色系/版式参考；尺寸规范以平台为准）
    print("下载封面样本（参考用）…")
    cover_ok = 0
    for note in notes:
        if not note.get("cover_url"):
            continue
        dest = os.path.join(run_root, "data", "covers", "%s.img" % note["id"])
        try:
            source_pool.download_cover(note["cover_url"], dest)
            note["cover_local"] = dest
            cover_ok += 1
        except Exception as e:
            log("S1", "封面下载失败 %s：%s" % (note["id"], e), "warn")
    refs = []
    for i, nt in enumerate(notes, 1):
        refs.append({"index": i, "channel": nt.get("channel"), "title": nt.get("title"),
                     "url": nt.get("url"), "image": nt.get("cover_local"),
                     "usable": bool(nt.get("cover_local")),
                     "note": "素材渠道仅提供封面，作为风格参考；不复制画面"})
    common.jdump(os.path.join(run_root, "data", "refs.json"), refs)
    common.jdump(os.path.join(run_root, "data", "notes.json"), notes)

    meta = {
        "run_id": os.path.basename(run_root),
        "keyword": args.keyword,
        "n": args.n,
        "found": len(notes),
        "images_per_note": args.images_per_note or cfg["defaults"]["images_per_note"],
        "window": args.window,
        "relax": args.relax,
        "logo": {"path": os.path.abspath(args.logo)},
        "created_at": common.now_str(),
        "status": "fetched",
        "notes": notes,
    }
    common.save_run(run_root, meta)

    common.ok("阶段 0-1 完成：%d 篇（封面 %d/%d）" % (len(notes), cover_ok, len(notes)))
    for i, nt in enumerate(notes, 1):
        print("  #%d [%s] %s | 赞%d 藏%d 评%d"
              % (i, nt["channel"], nt["title"][:26], nt["likes"], nt["collects"], nt["comments"]))
    print("  渠道分布：%s；热点信号 %d 条"
          % (freport.get("channel_mix"), len(freport.get("topic_signals") or [])))
    print("RUN_DIR=%s" % run_root)


# ---------------- 阶段 2 ----------------

def cmd_spec(args):
    run_root = os.path.abspath(args.run)
    meta = common.load_run(run_root)
    log = lambda s, m, lv="info": common.log_event(run_root, s, m, lv)
    spec = spec_extract.extract(run_root, args.layout_json, meta.get("images_per_note"), log)
    meta["status"] = "spec_extracted"
    common.save_run(run_root, meta)
    print("  色系：主色 %s（%s）｜强调 %s"
          % (spec["color"]["primary"], "切换" if spec["color"]["switch_reason"] else "默认稳重蓝",
             spec["color"]["accent"]))
    common.ok("阶段 2 完成 → data/spec-extracted.md")


# ---------------- 阶段 3 素材包 ----------------

BRIEF_TMPL = """# 第 {idx} 篇改写素材包（阶段 3）

## 源爆款
- 标题：{title}
- 作者：{author}｜点赞 {likes}｜收藏 {collects}｜评论 {comments}｜收藏/点赞 {ratio}
- 发布：{publish}｜链接：{url}

## 源正文（仅供理解与信息点提取，禁止逐句复用）
{desc}

## 改写硬性约束（公众号贴图）
- 正文字数目标：{char_target} 字（允许 {lo}–{hi} 字；依据：{basis}）
- 标题：≤{title_max} 字；单图文字：≤{page_limit} 字
- 必须保留：核心信息点、论点顺序、可验证的事实/数据
- 必须变换：句式结构、修辞方式、叙述视角、段落拆分与合并
- 禁止：逐句近义替换、调换语序复用原句骨架、搬运原文独特比喻或原创表述
- 去重关卡：与所有源文的连续 5–8 字重合率 < 15%，未过则退回复写
- 话题：{topics_min}–{topics_max} 个，写在正文内 `#话题名#`（平台无独立话题字段）

## 设计方向（人群驱动）
- 目标人群：{audience}（{age}）
- 语气：{style_keywords}
- 版式：顶部品牌色带压标题，眉标 + 大字标题 + 关键词撞色；内页带页序与要点短句
- 可填设计字段：`eyebrow`（眉标，≤10 字）、`highlight`（标题里要高亮成橙色的词，2–4 字）、`sticker`（封面贴纸，≤8 字）

## 交付格式（写入本目录 copy.json）
```json
{{
  "title": "封面标题（≤14 字，不含 emoji 堆砌）",
  "cover_line": "封面副标题一行（可选，≤18 字）",
  "body": "正文（段落用 \\n 分隔，需满足字数约束）",
  "digest": "摘要（≤60 字，可选）",
  "topics": ["话题1", "话题2", "话题3"],
  "pages": [
    {{"headline": "第2页小标题", "body": "第2页说明文字", "eyebrow": "可选眉标"}}
  ]
}}
```
> pages 数组长度 = 本次执行张数 - 1（共 {pages_count} 个元素）。
"""

COPY_TMPL = {
    "title": "",
    "cover_line": "",
    "body": "",
    "digest": "",
    "eyebrow": "",
    "highlight": "",
    "sticker": "",
    "topics": [],
    "pages": [],
}


def cmd_brief(args):
    run_root = os.path.abspath(args.run)
    cfg = common.load_config()
    meta = common.load_run(run_root)
    spec = common.jload(os.path.join(run_root, "data", "spec.json"))
    if spec is None:
        common.die("请先执行 spec 阶段")
    txt = spec["text"]
    char_target = txt.get("char_target") or txt.get("char_median") or 250
    lo = txt.get("char_limit_min") or int(char_target * 0.85)
    hi = txt.get("char_limit_max") or int(char_target * 1.15)
    basis = txt.get("char_basis_reason", "源正文中位数 ±15%")
    pages_count = max(0, (spec["image_count"].get("chosen") or spec["image_count"].get("fallback")) - 1)
    for idx, note in enumerate(meta["notes"], 1):
        nd = common.note_dir(run_root, idx)
        common.write_text(os.path.join(nd, "text-source.md"), BRIEF_TMPL.format(
            idx=idx, title=note["title"], author=note["author"], likes=note["likes"],
            collects=note["collects"], comments=note["comments"],
            ratio=note.get("collect_like_ratio"), publish=note["publish_time"],
            url=note["url"], desc=note["desc"], char_target=char_target, lo=lo, hi=hi,
            basis=basis, title_max=txt.get("title_max", 20),
            page_limit=txt.get("per_image_text_max", 100), pages_count=pages_count,
            topics_min=txt.get("topics_min", 3), topics_max=txt.get("topics_max", 5),
            audience=spec["design"]["audience"]["name"], age=spec["design"]["audience"]["age"],
            style_keywords=spec["design"]["style_keywords"]))
        tmpl = dict(COPY_TMPL)
        tmpl["pages"] = [{"headline": "", "body": "", "eyebrow": "", "highlight": ""}
                         for _ in range(pages_count)]
        common.jdump(os.path.join(nd, "copy-template.json"), tmpl)
    brief_path = os.path.join(run_root, "data", "audience-brief.md")
    if not os.path.exists(brief_path):
        ind = cfg.get("industry", {})
        aud = spec["design"]["audience"]
        common.write_text(brief_path, "\n".join([
            "# audience-brief.md — 行业与受众分析（阶段 2.5）",
            "",
            "> 由 Agent 依据关键词所在行业补充；下列为自动生成的初稿，可直接改写。",
            "",
            "## 行业", "- 行业：%s" % ind.get("name", ""),
            "- 关键词：%s" % "、".join(ind.get("keywords", [])),
            "- 行业调性：%s（不得夸大承诺、不得暗示效果保证）" % ind.get("sub_tone", ""), "",
            "## 目标人群", "- 人群：%s（%s 岁）" % (aud["name"], aud["age"]),
            "- 偏好：%s" % "、".join(aud["traits"]),
            "- 设计含义：%s" % aud["implication"], "",
            "## 本次结论（写 3 条，决定版式与配色）",
            "1. ",
            "2. ",
            "3. ",
            "",
        ]))
        common.ok("受众分析初稿：data/audience-brief.md（建议补充 3 条结论）")

    common.ok("素材包已生成：%d 篇（正文目标 %d 字，允许 %d–%d；标题 ≤%d 字）"
              % (len(meta["notes"]), char_target, lo, hi, txt.get("title_max", 20)))
    print("  每篇目录：notes/NN/text-source.md + copy-template.json → 改写后写 copy.json")


# ---------------- 阶段 3.4 去 AI 味 ----------------

DEAI_TMPL = """## 第 {idx} 篇（notes/{idx:02d}/copy.json）

- 标题：{title}
- AI 味体检：{smell}
- 字数：{chars} 字（阶段 3.3 会复核）

### 待处理文本

正文（只改表达，不改事实）：

```
{body}
```

内页短句（逐条顺一遍，别改信息）：

{pages}

### 处理要求

1. 调用 humanizer-zh 技能处理上面的文本；
2. 只改表达：删空话、拆长句、去套话对偶、把名词化改成动词；**不新增事实、数字、人名、出处**；
3. 保留原意与确定程度（可能仍是可能，计划仍是计划），保留第一人称与作者口吻；
4. 标题与话题不在本次范围（标题受字数与重合率约束，改了要重跑 3.3）；
5. 处理完写回 `copy.json` 的 `body` 与 `pages[].body`，然后跑 `verify-text` 复核字数与重合率。
"""


def cmd_deai(args):
    run_root = os.path.abspath(args.run)
    meta = common.load_run(run_root)
    cfg = common.load_config()
    out = ["# 阶段 3.4 去 AI 味清单", "",
           "> 由 `run.py deai` 生成。逐篇调用 **humanizer-zh** 处理正文与内页短句，写回 `copy.json` 后再跑 `verify-text`。",
           "> 硬约束：不新增事实/数字/出处，保留原意与确定程度，保留作者口吻；标题与话题不动。", ""]
    todo = 0
    for idx, note in enumerate(meta["notes"], 1):
        nd = common.note_dir(run_root, idx)
        copy_obj = common.jload(os.path.join(nd, "copy.json"))
        if copy_obj is None:
            out += ["## 第 %d 篇：缺 copy.json，跳过" % idx, ""]
            continue
        body = copy_obj.get("body", "")
        smell = textcheck.ai_smell(textcheck.TOPIC_RE.sub("", body))
        chars = len(textcheck.normalize(textcheck.TOPIC_RE.sub("", body)))
        pages = []
        for p, pg in enumerate(copy_obj.get("pages") or [], start=2):
            h = (pg.get("headline") or "").strip()
            b = (pg.get("body") or "").strip()
            if h or b:
                pages.append("- 第%d页：%s ／ %s" % (p, h, b))
        smell_txt = "%.1f/千字" % smell["per_1000"]
        if smell["hits"]:
            smell_txt += "（" + "、".join("%s×%d" % (k, v) for k, v in
                                        sorted(smell["hits"].items(), key=lambda kv: -kv[1])[:5]) + "）"
        if smell["smelly"]:
            todo += 1
        out.append(DEAI_TMPL.format(idx=idx, title=copy_obj.get("title", ""), smell=smell_txt,
                                    chars=chars, body=body, pages="\n".join(pages) or "-（无内页短句）"))
    path = os.path.join(run_root, "data", "deai-todo.md")
    common.write_text(path, "\n".join(out))
    print("  AI 味偏重 %d 篇 ／ 共 %d 篇" % (todo, len(meta["notes"])))
    common.ok("去 AI 味清单 → data/deai-todo.md（逐篇交 humanizer-zh 处理）")


def cmd_verify(args):
    run_root = os.path.abspath(args.run)
    print("阶段 3.3 去重与字数校验 …")
    s = textcheck.run(run_root)
    if not s["all_pass"]:
        common.die("存在未通过篇目：按 spec 退回重写（连续 3 次不通过则该篇放弃并记录）", 6)
    common.ok("阶段 3 校验通过")


# ---------------- 阶段 4.1 提示词 ----------------

PROMPT_TMPL = """【人群】{audience}（{age}）：{traits}。内容深度与信息密度贴合该人群；配色与光线以下面的设计哲学为准。
【设计哲学】{phil_zh}——{claim}
【版式骨架】本篇第 {page} 页用「{layout}」：{hint}
【视觉风格】{style}
【色彩方案】底色 {paper}，主色 {primary}，强调 {accent}；按上面的风格执行，不要套用固定的撞色公式；画面纸底尽量贴近底色，便于与文字区无缝衔接
【尺寸】成片 {width}×{height}px（{aspect} 竖版）；本页图窗是 {win_aspect} {win_kind}，请按 {win_aspect} 出图，{win_crop}
【留白区域】{logo_area} 留出干净、低细节的区域放 LOGO；其余留白按版式要求执行
【画面内容】第 {page}/{total} 页：{scene}
【禁用】画面内任何文字、字母、数字（文字由合成阶段渲染）、品牌 logo、水印、二维码、真实人物肖像
"""

LOGO_AREA = {
    "bottom-right": "右下角",
    "bottom-left": "左下角",
    "bottom-center": "底部居中",
}


def cmd_prompts(args):
    run_root = os.path.abspath(args.run)
    meta = common.load_run(run_root)
    spec = common.jload(os.path.join(run_root, "data", "spec.json"))
    if spec is None:
        common.die("请先执行 spec 阶段")
    cfg = common.load_config()
    phils, pindex = philosophy.load_all(cfg)
    plan_file = os.path.join(run_root, "data", "philosophy-plan.json")
    total = (spec["image_count"].get("chosen") or spec["image_count"].get("fallback"))
    for idx in range(1, len(meta["notes"]) + 1):
        nd = common.note_dir(run_root, idx)
        copy_obj = common.jload(os.path.join(nd, "copy.json"))
        if copy_obj is None:
            common.die("第%d篇缺少 copy.json" % idx)
        design = spec["design"]
        phil = philosophy.assign(idx, phils, pindex)
        variants = canvas_render.assign_variants(idx, total, phil)
        extra = (copy_obj.get("style_keywords") or "").strip()
        if phil.get("id") == "legacy":
            # 没有哲学库时沿用旧口径
            style = design["style_keywords"] + ("；" + design["image_style"] if design.get("image_style") else "")
            style += ("；" + extra if extra else "")
        else:
            # 哲学自带完整风格，不再叠加全局风格词（"橙蓝撞色"会抵消"高反差黑白"）
            style = "；".join(x for x in [phil.get("photo_style", ""), extra] if x)
        pal = phil["palette"]
        primary = pal.get("ink") or pal.get("primary")
        prompts = []
        for p in range(1, total + 1):
            if p == 1:
                scene = "封面主视觉：与标题「%s」呼应的抽象场景或物件特写" % copy_obj.get("title", "")
            else:
                ps = (copy_obj.get("pages") or [])[p - 2] if p - 2 < len(copy_obj.get("pages") or []) else {}
                scene = ps.get("scene") or ("第%d页插图：围绕「%s」的概念化画面，简洁、单一主体"
                                            % (p, ps.get("headline", "要点")))
            variant = variants[p - 1]
            text = PROMPT_TMPL.format(
                audience=design["audience"]["name"], age=design["audience"]["age"],
                traits="、".join(design["audience"]["traits"]),
                phil_zh=phil.get("name_zh") or phil.get("name"),
                claim=phil.get("claim", ""),
                layout=canvas_render.VARIANT_LABEL.get(variant, variant),
                hint=canvas_render.ARCH_HINT.get(variant, ""),
                win_aspect=canvas_render.ARCH_WINDOW.get(variant, ("3:2", "横向", ""))[0],
                win_kind=canvas_render.ARCH_WINDOW.get(variant, ("3:2", "横向", ""))[1],
                win_crop=canvas_render.ARCH_WINDOW.get(variant, ("3:2", "横向", ""))[2],
                style=style, paper=pal["paper"], primary=primary, accent=pal["accent"],
                width=spec["image"]["width"], height=spec["image"]["height"],
                aspect=spec["image"]["aspect"].replace(":", "："),
                logo_area=LOGO_AREA.get(spec["logo"]["position"], "右下角"),
                page=p, total=total, scene=scene)
            prompts.append({"page": p, "prompt": text, "variant": variant,
                            "philosophy": phil["id"]})
            common.write_text(os.path.join(nd, "prompt-%02d.txt" % p), text)
        common.jdump(os.path.join(nd, "prompts.json"),
                     {"pages": prompts, "style": style, "philosophy": phil["id"],
                      "philosophy_zh": phil.get("name_zh", "")})
        print("  #%d 哲学：%s" % (idx, phil.get("name_zh") or phil["id"]))
    common.jdump(plan_file, {"plan": [{"index": i + 1, "philosophy": philosophy.assign(i + 1, phils, pindex)["id"]}
                                      for i in range(len(meta["notes"]))],
                             "pool": [x["id"] for x in phils], "stride": pindex.get("stride")})
    common.ok("生图提示词已生成：%d 篇 × %d 张（%s）"
              % (len(meta["notes"]), total, philosophy.summary(phils, pindex, len(meta["notes"]))))


def cmd_compose(args):
    run_root = os.path.abspath(args.run)
    engine = args.engine
    if engine == "canvas" and not args.placeholder:
        print("阶段 4 配图合成（canvas-design 引擎：%s）…"
              % common.jload(os.path.join(run_root, "data", "design-tokens.json"), {}).get("title", "Margin Notes"))
        try:
            ms = canvas_render.run(
                run_root, log=lambda s2, m, lv="info": common.log_event(run_root, s2, m, lv))
            if ms:
                common.ok("合成完成（canvas）：%d 篇" % len(ms))
                return
        except Exception as e:
            common.log_event(run_root, "S4", "canvas 渲染失败，回退 Pillow：%s" % e, "warn")
            print("  ⚠️ canvas 渲染失败（%s），回退 Pillow" % str(e)[:120])
    print("阶段 4 配图合成（Pillow 引擎）…")
    ms = compose_images.run(run_root, args.placeholder)
    if not ms:
        common.die("合成失败：无产出")
    common.ok("合成完成：%d 篇" % len(ms))


def cmd_check(args):
    run_root = os.path.abspath(args.run)
    print("阶段 5 合规自检 …（按当前产物重算字数与重合率）")
    textcheck.run(run_root)
    r = check_compliance.run(run_root)
    if not r["all_pass"]:
        common.die("自检未通过 → 禁止进入草稿阶段（详见 data/selfcheck.md）", 7)
    common.ok("六项自检全部通过")


def cmd_draft(args):
    run_root = os.path.abspath(args.run)
    print("阶段 6 写入草稿 …")
    if getattr(args, "via", "api") == "ui":
        # 无凭证通道：走已登录浏览器。界面通道有五个坑，逻辑都在 push_ui.py / push_draft_ui.js
        import subprocess
        cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "push_ui.py"),
               "--run", run_root, "--space", str(args.space)]
        if args.only:
            cmd += ["--only", args.only]
        print("  通道：浏览器（ego-browser，任务空间 %d）" % args.space)
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            common.die("浏览器通道未全部核验通过（退出码 %d）" % proc.returncode, 7)
        common.ok("草稿阶段完成（浏览器通道）")
        return
    r = push_draft.run(run_root, args.dry_run)
    print("草稿模式：%s" % r["mode"])
    common.ok("草稿阶段完成（%d 篇）" % len(r["notes"]))


def cmd_report(args):
    run_root = os.path.abspath(args.run)
    meta = common.load_run(run_root)
    spec = common.jload(os.path.join(run_root, "data", "spec.json"), {})
    freport = common.jload(os.path.join(run_root, "data", "fetch-report.json"), {})
    selfcheck = common.jload(os.path.join(run_root, "data", "selfcheck.json"), {})
    draft = common.jload(os.path.join(run_root, "data", "draft-result.json"), {})
    exceptions = common.jload(os.path.join(run_root, "exceptions.json"), [])
    text_sum = common.jload(os.path.join(run_root, "data", "textcheck.json"), {})

    dup_rate = None
    if freport.get("pool_raw"):
        dup_rate = (freport.get("dedupe_removed", 0) / float(freport["pool_raw"]))

    lines = ["# 运行摘要 — %s（公众号贴图）" % meta["keyword"], "",
             "- 运行目录：%s" % run_root,
             "- 时间：%s" % common.now_str(),
             "- 目标篇数：%d；实际篇数：%d；检索时间窗：%s 天"
             % (meta["n"], len(meta["notes"]), freport.get("window_days")),
             "- 素材渠道：%s；热点信号 %s 条"
             % (freport.get("channel_mix") or freport.get("channels"), len(freport.get("topic_signals") or [])),
             "- 候选池：%s 条 → 去重剔除 %s 条（去重率 %s）→ 相关性过滤后 %s 条"
             % (freport.get("pool_raw"), freport.get("dedupe_removed"),
                "%.1f%%" % (dup_rate * 100) if dup_rate is not None else "-",
                freport.get("after_relevance_strict")),
             "- 小红书详情调用：%s 次（判定图文/视频并取全文）" % freport.get("xhs_detail_calls", 0),
             "- 相关性模式：%s" % freport.get("relevance_mode"),
             "", "## 抓取篇目", "",
             "| # | 渠道 | 标题 | 作者 | 赞 | 藏 | 评 |", "|---|---|---|---|---|---|---|"]
    for i, nt in enumerate(meta["notes"], 1):
        lines.append("| %d | %s | %s | %s | %d | %d | %d |"
                     % (i, nt.get("channel", "-"), (nt["title"] or "")[:24], nt["author"],
                        nt["likes"], nt["collects"], nt["comments"]))
    if spec:
        lines += ["", "## 规范提取结果", "",
                  "- 尺寸/比例：%s（%d×%d px）" % (spec["image"]["aspect"], spec["image"]["width"], spec["image"]["height"]),
                  "- 张数：%d 张/篇（平台上限 %d，首图为封面）" % (
                      spec["image_count"].get("chosen") or 6,
                      spec["image_count"].get("platform_max", 20)),
                  "- 字数口径：正文目标 %d 字（允许 %d–%d，%s）"
                  % (spec["text"].get("char_target", 0),
                     spec["text"].get("char_limit_min", 0),
                     spec["text"].get("char_limit_max", 0),
                     spec["text"].get("char_basis", "-")),
                  "- 骨架：%s%s" % (spec["layout"].get("skeleton_id"),
                                  "（降级：未做视觉归纳）" if spec["layout"].get("degraded") else ""),
                  "- 色系：主色 %s / 强调 %s%s" % (spec["color"]["primary"], spec["color"]["accent"],
                                              "；切换理由：" + spec["color"]["switch_reason"] if spec["color"].get("switch_reason") else "")]
    if text_sum.get("notes"):
        lines += ["", "## 去重率（改写稿 vs 源文）", "",
                  "| # | 正文字数 | 标题字数 | 最大 n-gram 重合 | 判定 |", "|---|---|---|---|---|"]
        for r in text_sum["notes"]:
            if r.get("char_count") is None:
                continue
            lines.append("| %s | %s | %s | %.1f%% | %s |" % (
                r["index"], r["char_count"], r.get("title_chars", "-"),
                r["max_overlap"] * 100, "PASS" if r["pass"] else "FAIL"))
    if selfcheck:
        lines += ["", "## 合规自检", "",
                  "- 结论：%s" % ("全部通过" if selfcheck.get("all_pass") else "存在未通过项")]
    if draft:
        lines += ["", "## 草稿（公众号贴图 newspic）", "",
                  "- 模式：%s｜article_type：%s" % (draft.get("mode"), draft.get("article_type"))]
        for n in draft.get("notes", []):
            lines.append("- #%d %s（%d 张 / 正文 %d 字）→ %s"
                         % (n["index"], n["title"], n.get("pages", 0),
                            n.get("content_chars", 0), n["status"]))
    if freport.get("topic_signals"):
        lines += ["", "## 热点选题信号", ""]
        for t in freport["topic_signals"][:8]:
            lines.append("- %s（%s，热度 %s）" % (t["title"], t["platform"], t["hot_score"]))
    lines += ["", "## 异常记录", ""]
    if exceptions:
        for e in exceptions:
            lines.append("- [%s] %s：%s" % (e["stage"], e["message"], e["level"]))
    else:
        lines.append("- 无")
    lines.append("")
    out = os.path.join(run_root, "run-summary.md")
    common.write_text(out, "\n".join(lines))
    common.ok("运行摘要：%s" % out)
    print("\n".join(lines[:14]))


def main():
    ap = argparse.ArgumentParser(prog="run.py", description="WECHAT-picture-design")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="阶段0-1")
    p.add_argument("--keyword", required=True)
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--logo", default=None,
                   help="LOGO 路径；省略时用 config.logo.default（出厂 assets/logo.png）")
    p.add_argument("--workdir", default="xh-picture-runs")
    p.add_argument("--window", type=int, default=90)
    p.add_argument("--images-per-note", type=int, default=None)
    p.add_argument("--max-detail-calls", type=int, default=40)
    p.add_argument("--relax", choices=["ask", "allow", "deny"], default="ask")
    p.add_argument("--source", choices=["auto", "redfox", "rss"], default="auto",
                   help="素材来源：auto=有 Key 走 REDFOX、否则走 RSS")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("spec", help="阶段2")
    p.add_argument("--run", required=True)
    p.add_argument("--layout-json", default=None)
    p.set_defaults(func=cmd_spec)

    p = sub.add_parser("brief", help="阶段3 素材包")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("deai", help="阶段3.4 去 AI 味清单")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_deai)

    p = sub.add_parser("verify-text", help="阶段3.3")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("prompts", help="阶段4.1")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_prompts)

    p = sub.add_parser("compose", help="阶段4.2-4.3")
    p.add_argument("--run", required=True)
    p.add_argument("--placeholder", action="store_true")
    p.add_argument("--engine", choices=["canvas", "pillow"], default="canvas",
                   help="canvas=canvas-design 哲学渲染（默认），pillow=旧版合成")
    p.set_defaults(func=cmd_compose)

    p = sub.add_parser("check", help="阶段5")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("draft", help="阶段6")
    p.add_argument("--run", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--via", choices=["api", "ui"], default="api",
                   help="api=官方接口（需 appid/secret）；ui=已登录浏览器（无凭证时）")
    p.add_argument("--space", type=int, default=2, help="--via ui 时已登录公众号的 ego 任务空间 id")
    p.add_argument("--only", default="", help="--via ui 时只推这些篇，逗号分隔")
    p.set_defaults(func=cmd_draft)

    p = sub.add_parser("report", help="运行摘要")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_report)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

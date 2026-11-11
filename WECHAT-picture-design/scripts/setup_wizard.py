# -*- coding: utf-8 -*-
"""setup_wizard.py — 首次安装的初始化问卷（逐题交互，答案直接写进 config.json）。

设计原则：
  1. 每题都有默认值，回车即默认；不想答的题可以直接跳过。
  2. 只改 config.json，不动任何脚本；改前自动备份 config.json.bak。
  3. 答完把答案另存一份 setup-answers.json，方便以后回溯「当初选了什么」。
  4. 选项与字段的对应关系写在 docs/setup-questionnaire.md，改问卷先改文档。

用法：
  python3 scripts/setup_wizard.py            # 逐题问答
  python3 scripts/setup_wizard.py --dry-run  # 只打印将要写入的差异，不落盘
  python3 scripts/setup_wizard.py --reset    # 从出厂默认开始答（忽略当前配置）
"""
import argparse
import copy
import datetime
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG = os.path.join(HERE, "config.json")
ANSWERS = os.path.join(ROOT, "setup-answers.json")

# ── 预设：风格 → 色板 / 排版语气 ────────────────────────────────────────────
STYLE_PRESETS = {
    "1": {"key": "bright", "label": "明亮活泼（欢快、节奏快）",
          "style_keywords": "明亮通透 / 撞色点缀 / 几何色块 / 大字排版 / 轻微质感颗粒",
          "image_style": "自然光、通透、日常场景静物，色彩明快，双色点缀；不要暗调、不要厚重滤镜",
          "palette": {"paper": "#F7F4EE", "primary": "#1B3A5C", "accent": "#ED6C1D", "muted": "#8A8F98"}},
    "2": {"key": "calm", "label": "克制理性（有内涵、信息密度高）",
          "style_keywords": "低饱和 / 大留白 / 细线分隔 / 等宽小标 / 纸感纹理",
          "image_style": "柔光、低饱和、单一主体的静物特写，背景干净；不要高对比撞色、不要装饰过度",
          "palette": {"paper": "#F5F3EE", "primary": "#243B4A", "accent": "#B5651D", "muted": "#8C8C86"}},
    "3": {"key": "warm", "label": "温暖叙事（故事感、可共情）",
          "style_keywords": "暖调 / 胶片颗粒 / 手写感 / 柔边 / 生活场景",
          "image_style": "暖阳、胶片颗粒、生活化场景（窗边、桌面、旧物），色调偏暖；不要冷硬、不要商务感",
          "palette": {"paper": "#FAF5EC", "primary": "#4A3A2E", "accent": "#C2703D", "muted": "#9A8B7A"}},
    "4": {"key": "sharp", "label": "钩子强（强对比、标题党但不违规）",
          "style_keywords": "高对比 / 粗黑大字 / 荧光强调色 / 色带切割 / 强节奏",
          "image_style": "硬光、高对比、强色彩块面，主体突出；不要灰调、不要柔焦",
          "palette": {"paper": "#FFFFFF", "primary": "#111418", "accent": "#FF4D2E", "muted": "#7A7F87"}},
}

AUDIENCES = {
    "1": {"key": "student", "label": "学生 / 应届（18–24）",
          "name": "学生 / 应届", "age": "18–24",
          "traits": ["刷图快", "预算敏感", "需要被鼓励", "偏好多巴胺配色"],
          "implication": "要亮、要快、要有情绪；避免深色压抑与长段落"},
    "2": {"key": "junior", "label": "职场新人（23–30）",
          "name": "职场新人", "age": "23–30",
          "traits": ["碎片时间阅读", "关心具体方法", "反感说教", "愿为效率付费"],
          "implication": "要具体、可执行；少讲道理，多给清单与步骤"},
    "3": {"key": "parent", "label": "家庭决策者（30–45）",
          "name": "家庭决策者", "age": "30–45",
          "traits": ["看重可信度", "关注长期收益", "对夸张标题警惕"],
          "implication": "要稳、要有据可依；标题克制，信息完整"},
    "4": {"key": "pro", "label": "行业从业者（25–45）",
          "name": "行业从业者", "age": "25–45",
          "traits": ["专业判断强", "关心趋势与数据", "反感常识科普"],
          "implication": "要有信息增量；少铺垫，直接给判断与依据"},
    "5": {"key": "general", "label": "泛大众（不限）",
          "name": "泛大众", "age": "18–45",
          "traits": ["被标题吸引", "看图多过看字", "注意力短"],
          "implication": "标题即信息，图即结论；文字只做补充"},
}

LENGTHS = {
    "1": {"label": "轻量：3 张图 + 150–200 字", "images": 3, "min": 150, "max": 200, "target": 180},
    "2": {"label": "标准：4 张图 + 200–300 字", "images": 4, "min": 200, "max": 300, "target": 250},
    "3": {"label": "加长：6 张图 + 300–400 字", "images": 6, "min": 300, "max": 400, "target": 350},
    "4": {"label": "自定义（分别填张数与字数区间）", "images": None, "min": None, "max": None, "target": None},
}

RSS_SOURCES = {
    "0": {"key": "redfox", "label": "我用 REDFOX（有 Key，最省事）"},
    "1": {"key": "google", "label": "Google 新闻 RSS（按类目词自动拼好 URL）"},
    "2": {"key": "bing", "label": "Bing 新闻 RSS（国内可达性通常更好）"},
    "3": {"key": "rsshub", "label": "RSSHub（自建实例，能订阅公众号/微博/知乎）"},
    "4": {"key": "custom", "label": "自定义 RSS（我已有 feed URL）"},
}


def rss_url(kind, keyword, extra=""):
    from urllib.parse import quote
    q = quote(keyword)
    if kind == "google":
        return "https://news.google.com/rss/search?q=%s&hl=zh-CN&gl=CN&ceid=CN:zh-Hans" % q
    if kind == "bing":
        return "https://www.bing.com/news/search?q=%s&format=RSS" % q
    return extra.strip()


def ask(prompt, default="", allow_empty=True):
    tip = "（回车＝%s）" % default if default not in ("", None) else ""
    while True:
        v = input("%s%s： " % (prompt, tip)).strip()
        if v:
            return v
        if default not in ("", None):
            return str(default)
        if allow_empty:
            return ""
        print("  这一题需要填一个值。")


def ask_choice(prompt, options, default="1"):
    print("\n" + prompt)
    for k in sorted(options):
        print("  %s) %s" % (k, options[k]["label"] if isinstance(options[k], dict) else options[k]))
    while True:
        v = ask("  选择", default)
        if v in options:
            return v
        print("  输入 1–%s 之间的序号。" % len(options))


def ask_multi(prompt, options, default_keys=""):
    print("\n" + prompt)
    for k in sorted(options):
        print("  %s) %s" % (k, options[k]["label"] if isinstance(options[k], dict) else options[k]))
    print("  可多选，用逗号分隔（例：1,3）；回车＝默认 %s" % (default_keys or "无"))
    while True:
        v = ask("  选择", default_keys, allow_empty=True)
        if not v:
            return []
        keys = [x.strip() for x in v.replace("，", ",").split(",") if x.strip()]
        if all(k in options for k in keys):
            return keys
        print("  有无效序号，请重选。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只显示差异，不写文件")
    ap.add_argument("--reset", action="store_true", help="忽略当前配置，从出厂默认开始")
    a = ap.parse_args()

    cfg = json.load(open(CONFIG, encoding="utf-8"))
    if a.reset:
        cfg = json.load(open(os.path.join(HERE, "config.default.json"), encoding="utf-8")) \
            if os.path.exists(os.path.join(HERE, "config.default.json")) else cfg
    before = copy.deepcopy(cfg)
    answers = {}

    print("=" * 62)
    print(" WECHAT-picture-design · 初始化问卷")
    print(" 共 12 题，约 3 分钟。每题回车＝默认值，随时 Ctrl+C 退出。")
    print("=" * 62)

    # Q1 类目关键词
    print("\n【Q1】你主要做哪个类目？（决定检索词，可多个，逗号分隔）")
    q1 = ask("  类目关键词（例：护肤,换季,敏感肌）", "护肤,换季")
    answers["Q1_category_keywords"] = [x.strip() for x in q1.replace("，", ",").split(",") if x.strip()]

    # Q2 行业关键词
    print("\n【Q2】所属行业用什么词描述？（写进受众简报，影响语气）")
    q2 = ask("  行业关键词（例：护肤,成分党,国货）", "护肤品,成分研究")
    answers["Q2_industry_keywords"] = [x.strip() for x in q2.replace("，", ",").split(",") if x.strip()]

    # Q3 内容风格
    q3 = ask_choice("【Q3】内容与图片的整体风格？（单选，决定配色与版式语气）", STYLE_PRESETS, "1")
    preset = STYLE_PRESETS[q3]
    answers["Q3_style"] = preset["key"]

    # Q4 情绪基调
    print("\n【Q4】情绪基调偏向？（单选，决定标题语气与配图光线）")
    tones = {"1": "欢快、有活力", "2": "克制、可信", "3": "温暖、可共情", "4": "沉重但给解法", "5": "悬念钩子、强吸引"}
    q4 = ask_choice("", {k: {"label": v} for k, v in tones.items()}, "2")
    answers["Q4_tone"] = tones[q4]

    # Q5 读者画像
    q5 = ask_choice("【Q5】主要面向谁？（单选，决定字号、密度与信息量）", AUDIENCES, "1")
    aud = AUDIENCES[q5]
    answers["Q5_audience"] = aud["key"]

    # Q6 读者状态（多选）
    print("\n【Q6】读者最常在什么状态下打开你的内容？（多选，最多 2 个）")
    states = {"1": "通勤路上、只看图", "2": "睡前刷手机、愿意读长一点", "3": "遇到问题、在找答案", "4": "被朋友转发、带着怀疑看"}
    q6 = ask_multi("", {k: {"label": v} for k, v in states.items()}, "1")
    answers["Q6_reading_states"] = [states[k] for k in q6]

    # Q7 篇幅
    q7 = ask_choice("【Q7】发布篇幅？（决定每篇张数与正文字数）", LENGTHS, "2")
    spec = LENGTHS[q7]
    if spec["images"] is None:
        n_img = int(ask("  每篇几张图（2–20）", "4"))
        lo = int(ask("  正文最少字", "200"))
        hi = int(ask("  正文最多字", "300"))
        custom = {"images": max(2, min(20, n_img)), "min": lo, "max": max(lo + 20, hi),
                  "target": (lo + max(lo + 20, hi)) // 2}
        answers["Q7_length"] = custom
    else:
        answers["Q7_length"] = {"images": spec["images"], "min": spec["min"],
                                "max": spec["max"], "target": spec["target"]}

    # Q8 品牌资产
    print("\n【Q8】品牌资产：LOGO 怎么处理？")
    logos = {"1": "我有透明底 PNG，现在就给路径", "2": "暂时没有，先用占位 LOGO", "3": "不要 LOGO（纯图输出）"}
    q8 = ask_choice("", {k: {"label": v} for k, v in logos.items()}, "2")
    logo_path = ""
    if q8 == "1":
        logo_path = ask("  LOGO 文件绝对路径", os.path.join(ROOT, "assets", "logo.png"))
    answers["Q8_logo"] = {"mode": {"1": "own", "2": "placeholder", "3": "none"}[q8], "path": logo_path}

    # Q9 图片库
    print("\n【Q9】配图从哪来？")
    imgs = {"1": "AI 生成（默认，按提示词出图）", "2": "用我的自有图片库（给目录路径）",
            "3": "混合：优先自有，缺图再 AI 生成"}
    q9 = ask_choice("", {k: {"label": v} for k, v in imgs.items()}, "1")
    lib = ""
    if q9 in ("2", "3"):
        lib = ask("  图片库目录（绝对路径）", "")
    answers["Q9_images"] = {"mode": {"1": "ai", "2": "own", "3": "hybrid"}[q9], "library": lib}

    # Q10 发布方式
    print("\n【Q10】成品最终怎么发？")
    pub = {"1": "官方接口（我有 appid/secret）", "2": "已登录的浏览器（无需 appid）",
           "3": "只导出图片和文案，我手动发"}
    q10 = ask_choice("", {k: {"label": v} for k, v in pub.items()}, "2")
    answers["Q10_publish"] = {"1": "api", "2": "ui", "3": "local"}[q10]

    # Q11 素材渠道（RSS 替代 REDFOX）
    print("\n【Q11】不用 REDFOX 时，用 RSS 抓素材（可多选；详见 docs/setup-questionnaire.md 第 11 题）")
    q11 = ask_multi("", RSS_SOURCES, "0")
    picks = [RSS_SOURCES[k]["key"] for k in q11]
    feeds = []
    seed_kw = answers["Q1_category_keywords"][0] if answers["Q1_category_keywords"] else "热点"
    for kind in picks:
        if kind in ("google", "bing"):
            feeds.append(rss_url(kind, seed_kw))
        elif kind in ("rsshub", "custom"):
            print("  贴 %s 的 feed URL（多个用逗号分隔）" % ("RSSHub" if kind == "rsshub" else "自定义"))
            urls = ask("  feed URL", "")
            feeds += [u.strip() for u in urls.replace("，", ",").split(",") if u.strip()]
    use_redfox = ("redfox" in picks) or not picks
    answers["Q11_use_redfox"] = use_redfox
    answers["Q11_rss_feeds"] = [] if use_redfox else feeds
    answers["Q11_use_rss"] = bool(feeds) and not use_redfox

    # Q12 合规黑名单
    print("\n【Q12】有没有必须避开的话题或词？（写进选题黑名单，逗号分隔）")
    q12 = ask("  黑名单（例：带货,团购,医疗宣称）", "带货,团购,优惠券")
    words = [x.strip() for x in q12.replace("，", ",").split(",") if x.strip()]
    dropped = [w for w in words if w.isdigit()]
    if dropped:
        print("  已忽略纯数字项 %s（看起来像误填的题号）" % "、".join(dropped))
    answers["Q12_blocklist"] = [w for w in words if not w.isdigit()]

    # ── 落配置 ───────────────────────────────────────────────────────────
    cfg.setdefault("brand", {})
    cfg["industry"]["name"] = "、".join(answers["Q2_industry_keywords"]) or cfg["industry"]["name"]
    cfg["industry"]["keywords"] = answers["Q2_industry_keywords"]

    cfg["design"]["style_keywords"] = preset["style_keywords"]
    cfg["design"]["image_style"] = preset["image_style"]
    cfg["design"].setdefault("palette", {}).update(preset["palette"])
    cfg["design"]["tone"] = answers["Q4_tone"]
    cfg["design"]["audience"] = {"name": aud["name"], "age": aud["age"],
                                 "traits": aud["traits"] + answers["Q6_reading_states"][:2],
                                 "implication": aud["implication"]}

    L = answers["Q7_length"]
    cfg["defaults"]["images_per_note"] = L["images"]
    cfg["text_policy"]["body_min"] = L["min"]
    cfg["text_policy"]["body_max"] = L["max"]
    cfg["text_policy"]["body_target"] = L["target"]

    if answers["Q8_logo"]["mode"] == "own" and answers["Q8_logo"]["path"]:
        dest = os.path.join(ROOT, "assets", "logo.png")
        src = os.path.abspath(answers["Q8_logo"]["path"])
        if os.path.exists(src) and os.path.abspath(src) != dest:
            shutil.copy2(src, dest)
            answers["Q8_logo"]["copied_to"] = "assets/logo.png"
        cfg["logo"]["default"] = "assets/logo.png" if os.path.exists(dest) else src
        cfg["brand"]["logo_source"] = "own"
    elif answers["Q8_logo"]["mode"] == "none":
        cfg["logo"]["enabled"] = False
        cfg["brand"]["logo_source"] = "none"
    else:
        cfg["brand"]["logo_source"] = "placeholder"

    cfg["images"] = cfg.get("images", {})
    cfg["images"].update({"source": answers["Q9_images"]["mode"],
                          "library_path": answers["Q9_images"]["library"]})
    cfg["wechat"]["publish_via"] = answers["Q10_publish"]

    cfg.setdefault("channels", {})
    cfg["channels"].setdefault("rss", {"feeds": []})
    cfg["channels"]["mode"] = "rss" if answers["Q11_use_rss"] else "redfox"
    cfg["channels"]["rss"]["feeds"] = answers["Q11_rss_feeds"]
    cfg["channels"]["primary_keyword"] = answers["Q1_category_keywords"]

    bl = cfg["channels"].get("blocklist", {"words": [], "topics": []})
    bl["words"] = sorted(set(bl.get("words", [])) | set(answers["Q12_blocklist"]))
    cfg["channels"]["blocklist"] = bl

    cfg["setup"] = {"answered_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "answers_file": "setup-answers.json"}

    diff = []
    for sec in ("design", "defaults", "text_policy", "channels", "brand", "logo", "wechat", "images"):
        if json.dumps(before.get(sec), ensure_ascii=False, sort_keys=True) != \
           json.dumps(cfg.get(sec), ensure_ascii=False, sort_keys=True):
            diff.append(sec)

    print("\n" + "=" * 62)
    print(" 配置摘要")
    print("  类目：%s" % "、".join(answers["Q1_category_keywords"]))
    print("  风格：%s ／ %s" % (preset["label"], answers["Q4_tone"]))
    print("  人群：%s（%s）" % (aud["name"], aud["age"]))
    print("  篇幅：%d 张图，正文 %d–%d 字" % (L["images"], L["min"], L["max"]))
    print("  LOGO：%s ｜ 配图：%s ｜ 发布：%s" % (answers["Q8_logo"]["mode"],
                                                answers["Q9_images"]["mode"], answers["Q10_publish"]))
    if answers["Q11_use_rss"]:
        print("  素材：RSS → %d 个 feed（首个：%s）" % (len(answers["Q11_rss_feeds"]),
                                              answers["Q11_rss_feeds"][0][:52]))
    else:
        print("  素材：REDFOX")
    print("  变更段落：%s" % ("、".join(diff) if diff else "无"))
    print("=" * 62)

    if a.dry_run:
        print("\n--dry-run：未写入任何文件。")
        return

    shutil.copy2(CONFIG, CONFIG + ".bak")
    json.dump(cfg, open(CONFIG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(answers, open(ANSWERS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n✅ 已写入 scripts/config.json（旧配置备份为 config.json.bak）")
    print("✅ 已保存问卷答案 setup-answers.json")
    if answers["Q11_use_rss"]:
        print("下一步：python3 scripts/rss_import.py --check 验证 feed 可达，再跑 run.py init --source rss")
    else:
        print("下一步：python3 scripts/setup_wizard.py --dry-run 可复核，或直接跑 run.py init")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n已取消，未写入任何配置。")
        sys.exit(130)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
品牌与路径配置（单一配置点）

所有可自定义项都集中在这里，脚本不再硬编码任何品牌名或用户路径。
可用环境变量覆盖（优先级高于默认值）：

  WX_VERTICAL    类目，如「职场」「母婴」「财经」。本技能不预设类目，初始化时必须填
  WX_AUDIENCE    读者画像一句话（身份 + 阶段 + 最在意的事），供写稿对齐语气
  WX_ACCENT      主色 #RRGGBB → HTML 主视觉 + 封面强调元素
  WX_ACCENT_ALT  辅色 #RRGGBB → 封面主视觉（标题/分隔线/关键词条）
  WX_GUIDELINES  类目规范文件路径（词库/字数区间/标题方向的唯一来源）
  WX_CALENDAR    选题日历路径（S 篇专栏的「当月热点」来源）
  WX_THEMES      主题词表 JSON 路径（选题归类与分布统计）
  WX_CTA         文末引导语，{vertical} 会被替换成 WX_VERTICAL
  WX_BRAND       公众号名称，出现在正文引导语、封面文字角标、草稿作者署名
  WX_DAILY_OUT   产物输出目录（Markdown / 长图 / 封面 / 台账）
  WX_PUBLISH_SPACE   发布用 TaskSpace 名（换名＝丢登录态）
  WX_LEGACY_BRANDS   旧品牌名清洗词表，逗号分隔
  WX_VERIFY_TOOLS_DIR  微信官方校验 CLI 所在目录
  WX_ARTICLES    每天总篇数（正整数，**无默认**，由使用者自定义填写）
  WX_SERIES      其中「专栏/强时效」的篇数；不填按总篇数 40% 自动分；填 0 表示不做专栏
  WX_SERIES_RATIO  专栏占比（0—1，也接受 25 / 40% 这种百分数写法），默认 0.4。
                 与 WX_SERIES 同时存在时，**WX_SERIES（绝对篇数）优先**

示例：
  WX_VERTICAL=职场 WX_ACCENT=#3B6EA5 WX_BRAND="某某职场号" \
  WX_GUIDELINES=~/wx/guidelines.md python3 scripts/make_cover.py --help
"""
# 注解延迟求值：`ratio: float | None` 是 PEP 604 语法，Python 3.10 才支持运行期求值。
# 本技能声明的是 Python ≥ 3.9，缺了这一行，3.9 上执行到 def 就抛 TypeError ——
# 而 brand 是所有脚本的单一配置入口，等于全线崩。**别删这一行。**
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# 仓库根目录（本文件位于 <repo>/scripts/）
def _env(name: str, fallback: str = "") -> str:
    """读环境变量，**空字符串视同未设置**。

    直接 os.environ.get 会把 `export WX_THEMES=` 读成 ""，
    而 Path("") 等于当前目录——主题词表/输出目录/LOGO 会静默指到错误位置，
    而且完全不报错。多号切换脚本最容易产生这种空值。
    """
    v = os.environ.get(name)
    return fallback if v is None or not v.strip() else v


REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "assets"
FONT_PATH = ASSETS / "fonts" / "NotoSansSC-VF.ttf"

# 品牌 LOGO：默认仓库内 assets/logo.png（占位图）。
# 管多个号时必须用 WX_LOGO 指到各自的文件——否则两个号会把同一个 LOGO 印到封面上。
#
# **「不显示 LOGO」是合法选择**（onboarding Q8b 选项 3）：把 WX_LOGO 设成
# none / off / no / 0 / - / 无 任一即可。这不是「没配置」也不是「用占位图」——
# 出图脚本会**整块跳过**角标（不会退化成文字角标），bootstrap 也判 OK。
# 三者的区别必须分清：
#   没设置 WX_LOGO     → 用 assets/logo.png（可能是占位图，bootstrap 会报）
#   WX_LOGO 指向坏路径 → 判「缺失」，是错误
#   WX_LOGO=none       → 有意不显示，正常状态
NO_LOGO_TOKENS = {"none", "off", "no", "0", "-", "无", "不显示", "false"}
_LOGO_RAW = _env("WX_LOGO", str(ASSETS / "logo.png")).strip()
LOGO_DISABLED = _LOGO_RAW.lower() in NO_LOGO_TOKENS
LOGO_PATH = Path(str(ASSETS / "logo.png") if LOGO_DISABLED else _LOGO_RAW).expanduser()

# 品牌名：正文引导语、封面角标、草稿作者署名统一走这里
BRAND_NAME = _env("WX_BRAND", "你的公众号")

# ---- 类目（vertical）：本技能不绑定任何行业，类目由使用者在初始化时定义 ----
# 考公只是内置的**示例预设**，换类目只需改这些环境变量 + 换规范文件，不用动代码
VERTICAL = _env("WX_VERTICAL", "考公")
AUDIENCE = _env("WX_AUDIENCE", "")  # 读者画像一句话，供 AI 写作时对齐

# ---- 色系：默认值沿用示例预设的品牌色，可换任意十六进制 ----
# 两个色槽分工不同，别只改一个：
#   ACCENT     主色 → HTML 主视觉（章节色条/导读徽章/引导语/表格卡表头）、封面圆点与强调标签
#   ACCENT_ALT 辅色 → 封面占面积最大的那个（标题混排基色/竖分隔线/底部关键词条底色）
ACCENT = _env("WX_ACCENT", "#EE7800")           # 主色
ACCENT_ALT = _env("WX_ACCENT_ALT", "#007E5C")  # 辅色

# 文末引导语（正文模板里 "关注 XX，……" 的后半句）；{vertical} 会被替换成类目名
CTA_TEXT = _env(
    "WX_CTA", "每天一篇{vertical}干货，只讲你用得上的。"
).replace("{vertical}", VERTICAL)

# 规范文件：换类目时指向你自己的那份，脚本不用改
GUIDELINES = Path(
    _env(
        "WX_GUIDELINES", str(REPO_ROOT / "references" / "content-guidelines.md")
    )
).expanduser()

# 选题日历：换类目的**第二个文件**。S 篇专栏从这里的「当月热点」出题，
# 所以它和规范文件必须一起换——只换一个，稿子的语气是新类目、题目还是旧的。
# 这个变量是后补的：在此之前该路径只写在 SKILL.md 正文里，没有任何脚本知道它在哪。
CALENDAR = Path(
    _env(
        "WX_CALENDAR", str(REPO_ROOT / "references" / "exam-calendar.md")
    )
).expanduser()

# 兼容旧品牌名的清洗词表（cmd=author 用），逗号分隔；留空则不启用清洗
LEGACY_BRANDS = [
    s.strip()
    for s in _env("WX_LEGACY_BRANDS", "").split(",")
    if s.strip()
]

# 产物输出目录
OUT_DIR = Path(
    _env("WX_DAILY_OUT", "~/Documents/公众号推文")
).expanduser()

# 账号的浏览器会话名（ego lite 的 TaskSpace）：同一个号别改，改了等于换空白会话；
# 多号必须逐号不同，否则登录态互相顶掉。pub_jobs.json 的 space 若写了，会优先于本变量。
PUBLISH_SPACE = _env("WX_PUBLISH_SPACE", "公众号发布")

# 主题词表（选题归类与分布统计）：JSON；缺省读输出目录下的 00_主题词表.json
THEME_FILE = Path(
    _env("WX_THEMES", str(OUT_DIR / "00_主题词表.json"))
).expanduser()


# ---- 每日篇数：由使用者自定义，技能不给预设 ----
# 篇数不是"感觉"问题：它决定积分消耗、审核时长、备稿压力。
# 任何脚本都不许替使用者猜一个数——未配置时一律返回 0，由调用方提示去问。
def _as_int(name: str, fallback: int) -> int:
    raw = _env(name, "").strip()
    if not raw:
        return fallback
    try:
        return int(raw)
    except ValueError:
        print(f"WARN: {name}={raw!r} 不是整数，已忽略", file=sys.stderr)
        return fallback


ARTICLES = _as_int("WX_ARTICLES", 0)          # 0 = 未配置
SERIES = _as_int("WX_SERIES", -1)             # -1 = 未指定，按比例算


def _as_ratio(name: str, fallback: float) -> float:
    """读 0<n≤1 的比例；也接受 `40` / `40%` 这种百分数写法并自动除以 100。

    为什么要容错：Q24 的题面按「25% / 40% / 60%」提问，使用者和 AI 都可能直接
    把 `40` 或 `40%` 写进环境变量。若按 40 直接乘，专栏会算出 40 篇然后被 clamp 成
    全部篇数——配置看着对、结果全错，还不会有任何报错。
    """
    raw = _env(name, "").strip().rstrip("%")
    if not raw:
        return fallback
    try:
        v = float(raw)
    except ValueError:
        print(f"WARN: {name}={raw!r} 不是数字，已忽略", file=sys.stderr)
        return fallback
    if v > 1:                     # 百分数写法
        v = v / 100.0
    if not (0 < v <= 1):
        print(f"WARN: {name}={raw!r} 超出 0—1（或 0—100%），已忽略", file=sys.stderr)
        return fallback
    return v

# 专栏占比：没有使用者偏好时的默认分工。0.4 是经验值——
# 全做专栏时效压力太大，一个不做又丢掉"强结构"带来的收藏率。
# Q24 的三档比例（25% / 40% / 60%）通过 WX_SERIES_RATIO 落到这里。
SERIES_RATIO = _as_ratio("WX_SERIES_RATIO", 0.4)


def series_count(total: int, ratio: float | None = None) -> int:
    """按比例算专栏篇数。三档比例共用一个取整规则，别在各处自己 round()。

    取整规则（这是 Q24 唯一的判定口径，改动要同步 onboarding 的题面）：
      1. 基础值 = total × ratio，**四舍五入到整数**。刻意不用 Python 内置 round()——
         它是 banker's rounding，round(0.5)=0、round(1.5)=2，同一份配置在不同 N 下
         会得到「有时进位有时不进位」的结果，使用者没法预期。
      2. total ≥ 2 且 ratio > 0 却算出 0 时，抬到 1。否则「选了 25%」在篇数少的号上
         等于没选，配置看着生效了实际一篇专栏都不排。
      3. 上限 total（ratio=1 时才可能取满）。
    """
    total = max(0, total)
    if total == 0:
        return 0
    r = SERIES_RATIO if ratio is None else ratio
    n = int(total * r + 0.5)          # 规则 1：half-up
    if n == 0 and r > 0 and total >= 2:
        n = 1                          # 规则 2：选了比例就至少给一篇
    return max(0, min(n, total))       # 规则 3：不越界


def article_plan() -> tuple:
    """返回 (总篇数, 专栏数, 泛干货数)。总篇数未配置时返回 (0, 0, 0)。"""
    total = max(0, ARTICLES)
    if total == 0:
        return 0, 0, 0
    series = SERIES if SERIES >= 0 else series_count(total)
    series = max(0, min(series, total))
    return total, series, total - series


def require_articles() -> tuple:
    """取篇数配置；未配置就报错，绝不回退成一个猜测值。"""
    total, series, evergreen = article_plan()
    if total == 0:
        raise SystemExit(
            "未配置每日篇数。\n"
            "  本技能不预设篇数——请先问使用者每天发几条，再 export WX_ARTICLES=<篇数>。\n"
            "  可选：export WX_SERIES=<专栏篇数>（不填按 40% 自动分，0 表示不做专栏）"
        )
    return total, series, evergreen


def require_font() -> Path:
    """返回字体路径；缺失时给出可执行的修复提示。

    字体（17MB 可变字体）随包提供，正常安装不会走到这里——能走到就说明
    文件被删了（清缓存 / 换机器只拷了部分目录 / 误 rm）。
    所以先给「恢复」，再给「下载」：能断网解决就别让人等网络。
    """
    if not FONT_PATH.exists():
        raise SystemExit(
            f"缺少字体：{FONT_PATH}\n"
            "字体随包提供（SIL OFL 1.1），缺失说明文件被删。\n"
            "  恢复：git checkout -- assets/fonts/   或从压缩包重新解压 assets/fonts/\n"
            "  联网重下：bash scripts/setup_fonts.sh"
        )
    return FONT_PATH


# ---- 示例预设自检：类目已改但规范文件还是仓库自带那份时提醒 ----
SAMPLE_GUIDELINES = (REPO_ROOT / "references" / "content-guidelines.md").resolve()
SAMPLE_CALENDAR = (REPO_ROOT / "references" / "exam-calendar.md").resolve()
SAMPLE_VERTICALS = ("考公", "公考", "")


def sample_guidelines_in_use(guidelines=None) -> bool:
    """类目已自定义、却仍指向仓库自带的示例规范文件？

    传 guidelines 时按传入路径判断（--guidelines 会改掉生效路径，
    此时只看模块级 GUIDELINES 会误判）。
    """
    if VERTICAL in SAMPLE_VERTICALS:
        return False
    try:
        return (guidelines or GUIDELINES).resolve() == SAMPLE_GUIDELINES
    except OSError:
        return False


def sample_calendar_in_use(calendar=None) -> bool:
    """类目已自定义、日历却还是仓库自带那份（一次都没换）。

    与规范文件不同，日历是**整份按类目写死的节点表**（几月是什么考期、
    本月读者关心什么、配什么结构化块）。换类目后它没有「部分可用」这回事，
    所以这里用路径判定：路径没变 = 完全没换，不存在改了一半的可能。

    反过来说，使用者把自带的日历 `cp` 出去只改了几行，路径就变了、这条判不出来了——
    那种「改了一半」由 sample_content_residue() 按内容兜。
    """
    if VERTICAL in SAMPLE_VERTICALS:
        return False
    try:
        return (calendar or CALENDAR).resolve() == SAMPLE_CALENDAR
    except OSError:
        return False


def warn_sample_mismatch() -> bool:
    """类目已自定义、却仍指向仓库示例规范文件时打印 WARN。返回是否命中。

    这是最容易踩的坑：改了 WX_VERTICAL，词库和标题方向还是考公的，
    产出的稿子会带着别人的禁用词表在跑，而且完全静默。
    （check_content.py 已把它升级为阻断，见 --allow-sample）
    """
    if not sample_guidelines_in_use():
        return False
    print(
        f"WARN: 类目「{VERTICAL}」仍在用仓库自带的考公示例规范文件。\n"
        f"      词库、标题方向、字数区间都不是你类目的。\n"
        f"      修法：cp references/content-guidelines.md <你的目录>/guidelines.md 改成你的类目，"
        f"再 export WX_GUIDELINES=<你的目录>/guidelines.md",
        file=sys.stderr,
    )
    return True


# ---- 示例预设「内容指纹」：路径换了，内容还是旧的 ----
# 上面两个判定看的是**路径**（你换没换文件）。可最常见的真实情况是
# `cp` 一份、只改了「读者画像 / 方向清单 / 谨慎词库」三节，
# 标题禁用词、归因触发词、归因句式原样留着——路径已经变了，
# 于是所有路径判定全部放行，而这三张表在你的类目里永远不命中，等于废表。
#
# 所以再补一层按**内容**判定：扫生效文件，看还剩多少示例专属词。
#
# 词表只收「考公圈专有、别的行业不会自然写出」的词。刻意剔掉了公告、
# 简章、笔试、面试、分数线这类泛用词——职场号写「招聘公告」是正当的，
# 把它算成残留会造成误报。
SAMPLE_MARKERS = (
    "国考", "省考", "选调", "行测", "申论", "报录比", "进面", "政审",
    "上岸", "岗位表", "招录", "命题人", "押题", "事业单位",
    "包过", "保过", "必上岸", "考公", "公考", "公务员",
)

# 一个章节命中几个专属词才算「这一节还是示例内容」。
# 取 2 而不是 1：单独一个「公务员」很可能是有意保留的（职场号讲体制内选题），
# 而一张词表里出现两个以上考公专属词，基本就是照抄没改——
# 这类表的作用是「一网打尽本行业的高危表达」，跨行业混装没有意义。
SAMPLE_MARKER_MIN = 2

# 会被脚本真正消费的章节。残留出现在这些章节里 = 校验逻辑失效（硬）；
# 出现在别处（「内容具体度」「互动设计」这类写给人看的示范段）= 只是例子不对味（软）。
#
# 这个区分决定了要不要阻断：使用者按 Q13c 的七个落点改完，正文里的考公举例
# 往往还留着——那些不影响校验，把它们也判成失败会逼人做无用功。
#
# 只对**规范文件**有意义。选题日历没有「示范段」这个概念，整份都是 AI 直接读的
# 当月数据，所以调用方（bootstrap.check_calendar）不做这个过滤。
CONSUMED_HEADINGS = ("标题禁用词", "禁用句式", "谨慎词库", "归因触发词", "归因句式", "方向清单")


def residue_is_consumed(head: str) -> bool:
    """这一节的残留会不会真的让校验失效。"""
    return any(k in head for k in CONSUMED_HEADINGS)


def _split_blocks(text: str) -> list:
    """按 `##` 及更深的标题切块，返回 [(标题, 正文), ...]。

    文件头（第一个 `##` 之前）整块丢弃：那里写着「本文件是考公示例预设」，
    每个照模板拷贝的用户都会保留这段说明，扫进去就是人人误报。
    """
    blocks, head, buf, seen = [], "", [], False
    for ln in text.splitlines():
        m = re.match(r"^(#{2,6})\s+(.*)$", ln)
        if m:
            if seen:
                blocks.append((head, "\n".join(buf)))
            head, buf, seen = m.group(2).strip(), [], True
            continue
        if seen:
            buf.append(ln)
    if seen:
        blocks.append((head, "\n".join(buf)))
    return blocks


def sample_content_residue(path=None, vertical=None) -> list:
    """生效文件里还留着多少示例预设的行业专属词。

    返回 `[(节标题, [命中词...]), ...]`，只回命中 ≥ SAMPLE_MARKER_MIN 的节。
    类目就是考公（或未配置）时一律返回空——那时示例内容本来就是对的。
    """
    v = VERTICAL if vertical is None else vertical
    if v in SAMPLE_VERTICALS:
        return []
    try:
        text = Path(path or GUIDELINES).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    for head, body in _split_blocks(text):
        hits = [w for w in SAMPLE_MARKERS if w in body]
        if len(hits) >= SAMPLE_MARKER_MIN:
            out.append((head, hits))
    return out


def warn_sample_content(path=None, label: str = "规范文件") -> list:
    """残留打印成 WARN 并返回残留列表（空列表 = 干净）。不阻断。"""
    residue = sample_content_residue(path)
    if not residue:
        return []
    hard = [h for h, _ in residue if residue_is_consumed(h)]
    print(f"WARN: {label}换了，但下面 {len(residue)} 节还是示例预设的内容：",
          file=sys.stderr)
    for head, hits in residue:
        flag = "（这一节的校验会失效）" if residue_is_consumed(head) else ""
        print(f"      · {head}：{'、'.join(hits)}{flag}", file=sys.stderr)
    print("      这些词在你的类目里永远不会命中。改成你自己行业的词"
          "（见 onboarding Q13c 的七个落点）。", file=sys.stderr)
    if hard:
        print(f"      其中 {len(hard)} 节是脚本直接消费的词表，必须改。", file=sys.stderr)
    return residue


def warn_text_fit(label: str, text: str, font, max_w: float) -> bool:
    """文案超出可用宽度时打印 WARN（不阻断出图），返回是否溢出。

    封面有固定画布，标题/副标题过长会被右侧裁切，而脚本原本不报错——
    这里把"看不见的裁切"变成一条可执行的提示。
    """
    if not text:
        return False
    try:
        w = float(font.getlength(text))
    except AttributeError:
        return False
    if w <= max_w:
        return False
    per_char = max(1.0, w / max(1, len(text)))
    suggest = max(1, int(max_w / per_char))
    print(
        f"WARN: {label}「{text}」宽 {w:.0f}px 超出可用 {max_w:.0f}px，可能被裁切；"
        f"建议 ≤{suggest} 字（或换行）",
        file=sys.stderr,
    )
    return True


def hex_rgb(value: str) -> tuple:
    """'#EE7800' -> (238, 120, 0)；非法值回退主色。"""
    v = (value or "").strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6:
        v = ACCENT.lstrip("#")
    try:
        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return hex_rgb(ACCENT)


def resolve_accent(value: str, as_rgb: bool = False):
    """把 --accent 的取值归一化。

    支持三种写法：
      orange / primary  -> WX_ACCENT
      green  / alt      -> WX_ACCENT_ALT
      #RRGGBB           -> 任意十六进制（换品牌色、换类目主色都走这条）
    """
    v = (value or "orange").strip().lower()
    if v in ("orange", "primary", "main", ""):
        hexv = ACCENT
    elif v in ("green", "alt", "secondary"):
        hexv = ACCENT_ALT
    else:
        hexv = value.strip()
        if not hexv.startswith("#"):
            hexv = "#" + hexv
    return hex_rgb(hexv) if as_rgb else hexv.upper()


def accent_pair(value: str):
    """返回 (主色, 辅色)。传入的是主色，辅色自动取另一支，保证两色交替。"""
    main = resolve_accent(value)
    alt_hex = ACCENT_ALT.upper()
    if main.upper() == alt_hex:
        alt_hex = ACCENT.upper()
    return main, alt_hex

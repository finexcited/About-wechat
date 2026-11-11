#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
环境自举：首次运行时自动把依赖补齐，成功不打扰用户。

设计原则
--------
1. **静默成功**：全部就绪时默认只打一行 OK（`--quiet` 连这行都不打）。
   Agent 在首次执行时装完就往下走，不向用户汇报环境细节。
2. **失败才说话**：只有「无法自动修复且会阻断出稿」时才打印可执行的手工修法。
3. **可查**：用户主动问「环境装了什么」时跑 `--report`，给完整清单。
4. **零依赖**：只用标准库，保证在 Pillow 还没装的时候就能跑。

用法
----
  python3 scripts/bootstrap.py              # 检查 + 自动修复（默认）
  python3 scripts/bootstrap.py --quiet      # 同上，成功时完全静默
  python3 scripts/bootstrap.py --report     # 只报状态，不修复（用户问起时用）
  python3 scripts/bootstrap.py --report --strict             # 交付验收（Q37）
  python3 scripts/bootstrap.py --report --strict --publish   # Q4=2 时连第七步一起卡
  python3 scripts/bootstrap.py --no-net     # 跳过需要联网的项（校验 CLI 克隆）
  python3 scripts/bootstrap.py --json       # 机器可读输出

退出码
------
  0  出稿链路（第 1—6 步）可用
  1  有必装项缺失且自动修复失败——会阻断出稿，必须告知用户
     --strict 时为「待处理项没清空」（产物目录 / 品牌 LOGO / 00_配置.md）；
     再加 --publish 时连 Node.js / ego-browser 一起算

附带产物：`publish_ready`（Node + ego-browser 是否都就绪）决定 onboarding
Q4「要不要自动存草稿」的默认值——已装好的不该再让人点一次「不用」。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

FONT = REPO / "assets" / "fonts" / "NotoSansSC-VF.ttf"
_LOGO_RAW = os.environ.get("WX_LOGO", str(REPO / "assets" / "logo.png")).strip()
# 「不显示 LOGO」是合法选择（onboarding Q8b 选项 3）。与「没配置」「路径写错」区分开：
#   没配置 → assets/logo.png（可能是占位图，要报）
#   坏路径 → 判「缺失」，是错误
#   none   → 有意不显示，正常状态，--strict 不该拦
NO_LOGO_TOKENS = {"none", "off", "no", "0", "-", "无", "不显示", "false"}
LOGO_DISABLED = _LOGO_RAW.lower() in NO_LOGO_TOKENS
LOGO = Path(str(REPO / "assets" / "logo.png") if LOGO_DISABLED else _LOGO_RAW).expanduser()
# 多号场景下每个号有自己的 LOGO，校验必须看实际生效的那份，不能写死 assets/logo.png

# 占位图的两种指纹。
# 字节哈希是快路径（毫秒级、精确命中），但对「另存为」无效——实测把占位图
# 用同像素重编码一次（optimize=True），字节变了，这题就从 SKIP 变成 OK，
# 而它唯一要拦的就是「占位图上封面」，失效方式还是静默通过。
# 所以再加一层感知哈希（dHash）：比的是像素结构，编码、缩放、1—2px 裁切都扛得住。
PLACEHOLDER_SHA = REPO / "assets" / "logo.placeholder.sha256"
PLACEHOLDER_DHASH = REPO / "assets" / "logo.placeholder.dhash"
DHASH_MAX_DISTANCE = 8   # 64bit 里允许差 8 位；实测占位图变体 ≤4、真实 LOGO ≥17

# 只影响第七步（自动存草稿）的项。Q4 答「不用发布」时它们缺了也不算没配好，
# 所以严格验收默认不卡——否则只出稿的用户会被两条与自己无关的红灯挡在交付外。
PUBLISH_ONLY = ("node", "ego")

# 00_配置.md 里与脚本实际取值一一对应的四项（Q40）。
# 这个文件没有任何脚本消费，它和 WX_* 是双源：md 改成「母婴」而环境变量还是
# 「考公」，脚本照直按考公跑，两边都不报错。所以要比一次。
CONFIG_MD_FIELDS = (
    ("类目", "VERTICAL", "WX_VERTICAL"),
    ("读者画像", "AUDIENCE", "WX_AUDIENCE"),
    ("主色", "ACCENT", "WX_ACCENT"),
    ("辅色", "ACCENT_ALT", "WX_ACCENT_ALT"),
)


def _norm_val(v: str) -> str:
    """比较用的归一：去空白与包裹符号，颜色统一大写并去掉 #。"""
    return re.sub(r"[\s`'\"「」#]", "", v or "").upper()


def _dhash(path: Path, size: int = 8) -> int:
    """感知哈希（差分）：缩到 9×8 灰度，逐行比较相邻像素亮度，输出 64bit。

    只描述「明暗走势」，不记具体颜色——所以重编码、缩放、轻微裁切都不影响。
    """
    from PIL import Image

    with Image.open(path) as im:
        gray = im.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = gray.tobytes()
    bits = 0
    for r in range(size):
        row = r * (size + 1)
        for c in range(size):
            bits = (bits << 1) | (1 if px[row + c] > px[row + c + 1] else 0)
    return bits


def is_placeholder_logo(path: Path) -> bool:
    """判定 LOGO 是否仍是仓库自带的那张占位图。两层：字节哈希 → 感知哈希。"""
    import hashlib

    if PLACEHOLDER_SHA.exists():
        cur = hashlib.sha256(path.read_bytes()).hexdigest()
        if cur == PLACEHOLDER_SHA.read_text(encoding="utf-8").strip():
            return True
    try:
        ref = PLACEHOLDER_DHASH.read_text(encoding="utf-8").strip()
        if not ref:
            return False
        dist = bin(int(ref, 16) ^ _dhash(path)).count("1")
        return dist <= DHASH_MAX_DISTANCE
    except (OSError, ValueError, ImportError):
        return False


# 必装项：缺一个就跑不出图
REQUIRED = ("python", "pillow", "font", "outdir")
# 可选/降级项：缺了不阻断，只是少一层保护
OPTIONAL = ("verify_cli", "node", "ego", "guidelines", "calendar", "logo")


def _run(cmd, timeout=300, cwd=None):
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _ensure_dir(path: Path):
    """建目录，容忍 macOS 上中文目录名的 Unicode 规范化差异。

    APFS 对中文名做了规范化，`Path.mkdir(exist_ok=True)` 会先 `is_dir()`
    判定为真而跳过；但若传入的名字与磁盘上的规范化形式不同，底层 mkdir
    仍返回 EEXIST 并抛 FileExistsError——此时目录其实已经存在。
    所以不能只看 exist_ok，必须复核 is_dir()。
    """
    if path.is_dir():
        return True
    try:
        path.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        if not path.is_dir():
            raise
    return path.is_dir()


PUB_POINTER = Path.home() / ".wx-ego-dir"


def _write_pub_pointer(out_dir: Path) -> bool:
    """把产物目录写进 `~/.wx-ego-dir`，供发布模块定位 `pub_jobs.json`。

    为什么非要有这个东西：ego-browser **既不转发命令行参数，也不继承调用方的
    环境变量**（实测 process.env.WX_* 全 undefined、cwd 变 "/"）。于是第七步
    拿不到 WX_DAILY_OUT，就无法找到配置目录——而 `dir` 又写在配置里，成了
    「想读配置得先知道去哪读」的鸡生蛋。这个指针就是那条通路。

    只在内容变化时写，避免每次 bootstrap 都去碰 $HOME。
    返回 True 表示这次真的写了（用于「本次自动补齐」清单）。
    """
    try:
        want = str(out_dir)
        if PUB_POINTER.exists() and PUB_POINTER.read_text(encoding="utf-8").strip() == want:
            return False
        PUB_POINTER.write_text(want + "\n", encoding="utf-8")
        return True
    except OSError:
        # 写不了不是阻断项：ego_pub.mjs 还有 env / 默认目录两条退路，
        # 只是自定义目录的用户下次得自己写指针。
        return False


def _has_variation_axis(path: Path) -> bool:

    """字体是不是可变字体（有 Weight 轴）。

    全部绘图脚本都靠 `set_variation_by_axes([weight])` 取不同粗细，
    而静态字体没有轴——调用抛 OSError，被 except 吞掉后**任何提示都没有**，
    只表现为「封面标题不粗了」。宁可在这里判死，也不要让人对着
    一张层次全平的长图找原因。
    """
    try:
        from PIL import ImageFont
        f = ImageFont.truetype(str(path), 12)
        return bool(f.get_variation_axes())
    except Exception:
        return False


class Env:
    def __init__(self, fix: bool, net: bool):
        self.fix = fix
        self.net = net
        self.items = {}
        self.fixed = []
        self.blocked = []
        self.publish_ready = False  # Node + ego-browser 都就绪 → Q4 默认值取 2

    def add(self, key, name, ok, detail="", required=False, hint="", cause=""):
        self.items[key] = {
            "name": name,
            "ok": ok,
            "detail": detail,
            "required": required,
            "hint": hint,
            # cause 给「未通过」定个性（unset / missing / unwritable），
            # 供汇总段落说人话用——别去 detail 里做字符串嗅探。
            "cause": cause,
        }
        if not ok and required:
            self.blocked.append(key)
        return ok

    # ---------- 各项检查 ----------

    def check_python(self):
        v = sys.version_info
        ok = v >= (3, 9)
        return self.add(
            "python", "Python ≥ 3.9", ok, f"{v.major}.{v.minor}.{v.micro}",
            required=True, hint="macOS: brew install python",
        )

    def check_pillow(self):
        try:
            import PIL
            return self.add("pillow", "Pillow", True, getattr(PIL, "__version__", "?"),
                            required=True)
        except ImportError:
            pass
        if self.fix:
            for extra in ([], ["--break-system-packages"]):
                r = _run([sys.executable, "-m", "pip", "install", "--quiet",
                          "--user", "pillow"] + extra, timeout=600)
                if r and r.returncode == 0:
                    try:
                        import PIL  # noqa: F401
                        self.fixed.append("Pillow")
                        return self.add("pillow", "Pillow", True,
                                        getattr(PIL, "__version__", "?"), required=True)
                    except ImportError:
                        pass
        return self.add(
            "pillow", "Pillow", False, "未安装",
            required=True,
            hint=f"{sys.executable} -m pip install --user pillow",
        )

    def check_font(self):
        """字体随包提供，所以「缺失」= 装置被破坏，不是正常安装态。

        除了存在性，还查**有没有 Weight 轴**：绘图脚本一律走
        `set_variation_by_axes([weight])`，静态字体（如思源黑体分字重的
        SourceHanSansCN-*.otf）没有轴，调用会抛 OSError 并被 except 吞掉——
        所有字重静默退化成同一个粗细，一个错都不报。这条检查就是为了
        让那种替换在体检阶段就露出来。
        """
        if FONT.exists():
            mb = FONT.stat().st_size / 1024 / 1024
            if not _has_variation_axis(FONT):
                return self.add(
                    "font", "Noto Sans SC 字体", False,
                    f"{mb:.1f} MB 但**没有字重轴**（不是可变字体）",
                    required=True,
                    hint="换成了分字重的静态字体（如 SourceHanSansCN-Bold.otf）。"
                         "静态字体没有 Weight 轴，set_variation_by_axes 会静默失败，"
                         "封面各级字号全变成同一个粗细。恢复随包的可变字体："
                         "git checkout -- assets/fonts/",
                )
            return self.add("font", "Noto Sans SC 字体", True,
                            f"{mb:.1f} MB（随包提供，含字重轴）", required=True)

        # 缺失：先试本地恢复（快、不用网），再试下载（慢、可能被墙）。
        if self.fix:
            _run(["git", "-C", str(REPO), "checkout", "--", "assets/fonts"], timeout=120)
            if FONT.exists():
                self.fixed.append("字体（git 恢复）")
                mb = FONT.stat().st_size / 1024 / 1024
                return self.add("font", "Noto Sans SC 字体", True,
                                f"{mb:.1f} MB（已从 git 恢复）", required=True)
            script = REPO / "scripts" / "setup_fonts.sh"
            if self.net and script.exists():
                r = _run(["bash", str(script)], timeout=1200)
                if r and r.returncode == 0 and FONT.exists():
                    self.fixed.append("字体（下载）")
                    mb = FONT.stat().st_size / 1024 / 1024
                    return self.add("font", "Noto Sans SC 字体", True,
                                    f"{mb:.1f} MB（已下载）", required=True)
        return self.add(
            "font", "Noto Sans SC 字体", False, "缺失（本应随包提供）",
            required=True,
            hint="文件被删了。恢复：git checkout -- assets/fonts/ "
                 "（或从压缩包重新解压 assets/fonts/）；"
                 "实在拿不到再联网：bash scripts/setup_fonts.sh",
        )

    def check_outdir(self):
        # 产物目录由使用者指定（onboarding Q7），不代填。
        # 未指定时只报「未指定」，不建兜底目录——偷偷建一个会让人以为已经配好了。
        if not os.environ.get("WX_DAILY_OUT", "").strip():
            try:
                from brand import OUT_DIR as _fallback
            except Exception:
                _fallback = "~/Documents/公众号推文"
            return self.add(
                "outdir", "产物目录", False,
                f"未指定（脚本兜底会用 {_fallback}，但那不是你的选择）",
                hint="首次使用先按 onboarding Q7 指定：export WX_DAILY_OUT=<你的绝对路径>",
                cause="unset",
            )
        try:
            from brand import OUT_DIR
        except Exception as e:  # brand 导入失败说明仓库结构坏了
            return self.add("outdir", "产物目录", False, f"读不到配置：{e}",
                            required=True, hint="检查 scripts/brand.py 是否存在",
                            cause="broken")
        try:
            if self.fix:
                _ensure_dir(OUT_DIR)
                _ensure_dir(OUT_DIR / "模板")
                # 同步发布模块的配置指针：ego-browser 不继承环境变量，
                # pub_jobs.json 全靠 ~/.wx-ego-dir 定位（详见 ego_pub.mjs 文件头）。
                if _write_pub_pointer(OUT_DIR):
                    self.fixed.append("发布配置指针")
            probe = OUT_DIR / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return self.add("outdir", "产物目录", True, str(OUT_DIR), required=True)
        except FileNotFoundError:
            # 「目录不存在」和「不可写」是两件事。--report 不建目录，写探针必然 ENOENT，
            # 若笼统报成「不可写」，人会去查权限、查同步盘，白折腾一圈。
            return self.add(
                "outdir", "产物目录", False,
                f"{OUT_DIR} 还不存在（目录没建，不是权限问题）",
                required=True,
                hint="跑一次 python3 scripts/bootstrap.py 会自动创建（连同「模板」子目录）",
                cause="missing",
            )
        except PermissionError as e:
            return self.add("outdir", "产物目录", False, f"{OUT_DIR} 不可写（{e}）",
                            required=True,
                            hint="换一个可写目录（避开 iCloud / OneDrive 同步盘）",
                            cause="unwritable")
        except OSError as e:
            return self.add("outdir", "产物目录", False, f"{OUT_DIR} 写入失败（{e}）",
                            required=True,
                            hint="检查磁盘空间与路径是否合法（避开 iCloud / OneDrive 同步盘）",
                            cause="unwritable")

    def check_guidelines(self):
        try:
            from brand import (AUDIENCE, GUIDELINES, VERTICAL,
                               residue_is_consumed, sample_content_residue)
        except Exception:
            return self.add("guidelines", "类目规范文件", False, "读不到配置")
        if not GUIDELINES.exists():
            return self.add("guidelines", "类目规范文件", False, str(GUIDELINES),
                            hint="export WX_GUIDELINES=<你的规范文件路径>")

        # 读者画像是一句话，脚本不消费它，但它是 AI 写语气与案例的唯一锚点——
        # 空着不报就等于没问过 Q14，所以在体检里显出来。
        note = "" if AUDIENCE.strip() else "；⚠️ 读者画像未填（Q14）"

        # 路径换了 ≠ 内容换了。`cp` 一份只改三节是最常见的真实情况，
        # 而路径判定（sample_guidelines_in_use）届时全部放行。
        # 所以这里按内容再看一眼，分两档：
        #   硬 —— 残留落在脚本直接消费的词表里，该节校验彻底失效
        #   软 —— 只是正文举例还是旧的，不影响校验
        residue = sample_content_residue(GUIDELINES)
        hard = [(h, w) for h, w in residue if residue_is_consumed(h)]
        if hard:
            detail = (f"{GUIDELINES.name}（类目：{VERTICAL}{note}）——"
                      f"换了文件，但 {len(hard)} 张词表还是示例内容："
                      + "；".join(f"{h.split('（')[0]}={'、'.join(w[:4])}"
                                  for h, w in hard))
            return self.add(
                "guidelines", "类目规范文件", False, detail,
                hint="这些词在你的类目里永远不会命中，那一节等于没写。"
                     "按 Q13c 的七个落点改成你自己行业的词")
        if residue:
            note += f"；{len(residue)} 处正文举例仍是示例（不影响校验）"
        return self.add("guidelines", "类目规范文件", True,
                        f"{GUIDELINES.name}（类目：{VERTICAL}{note}）")

    def check_calendar(self):
        """选题日历：换类目的第二个文件，也是原来唯一一个「没有任何脚本知道它在哪」的文件。

        在这项检查出现之前，`WX_VERTICAL=母婴` 配上全新的规范文件，体检全绿，
        而 S 篇专栏仍按考公日历出题（国考报名 / 省考公告）——SKILL.md 正文里
        硬编码着 references/exam-calendar.md 这一条路径，没有任何东西校验它。
        """
        try:
            from brand import (CALENDAR, VERTICAL, sample_calendar_in_use,
                               sample_content_residue)
        except Exception:
            return self.add("calendar", "选题日历", False, "读不到配置")
        if not CALENDAR.exists():
            return self.add("calendar", "选题日历", False, str(CALENDAR),
                            hint="export WX_CALENDAR=<你的日历文件路径>"
                                 "（没有就照 references/exam-calendar.md 的格式写一份本行业节点表）")
        if sample_calendar_in_use():
            return self.add(
                "calendar", "选题日历", False,
                f"仍是仓库自带的考公日历（类目：{VERTICAL}）",
                hint="这整份是考公的时间轴，专栏会照它出「国考报名」「省考公告」这类题。"
                     "cp 一份改成你行业的节点表，再 export WX_CALENDAR=<新路径>")
        residue = sample_content_residue(CALENDAR)
        # 日历不区分硬软：它整份都是 AI 直接读的当月数据（几月是什么节点、
        # 该配什么结构化块），没有「只是示范段」的部分。表名字也对不上
        # CONSUMED_HEADINGS——那是规范文件的章节名。
        if residue:
            return self.add(
                "calendar", "选题日历", False,
                f"{CALENDAR.name} 里 {len(residue)} 节仍是示例内容："
                + "；".join(f"{h.split('（')[0]}={'、'.join(w[:4])}" for h, w in residue),
                hint="日历换了路径但内容没换，本月专栏仍会取到考公节点（报名月/笔试月）")
        return self.add("calendar", "选题日历", True, CALENDAR.name)

    def check_logo(self):
        """LOGO 是必换项：占位图会印着「你的 LOGO」上封面，属于出片事故。

        四条判定，都是「会静默印坏、但脚本原来不吭声」的：
          ① 仍是占位图（字节哈希 + 感知哈希）——直接判不通过
          ② 高度 <128px——角标固定按 56/64px 高重采样，源图不够会被拉糊
          ③ 无透明通道——深色封面上是一块白方块，加 pill 衬底后更明显
          ④ 宽高比越界（>6:1 或 <1:1）——压到角标变成横条/竖线，
             实测 600×60 会拉成 560px 宽的白条横跨右上半屏
        """
        if LOGO_DISABLED:
            # 有意不显示角标：不是「没配」，也不是「用占位图」，判 OK。
            # 但要说清代价——没有 LOGO，封面就只剩标题和色带，同名号之间更难区分。
            return self.add(
                "logo", "品牌 LOGO", True,
                "按要求不显示（WX_LOGO=none）——封面不印角标",
            )

        if not LOGO.exists():
            return self.add("logo", "品牌 LOGO", False, "缺失",
                            hint="放一张透明底 PNG 到 assets/logo.png（或多号时用 WX_LOGO 指到你自己的文件），高度 ≥128px；确实不要 LOGO 就设 WX_LOGO=none")

        if is_placeholder_logo(LOGO):
            return self.add(
                "logo", "品牌 LOGO", False, "仍是仓库自带的占位图（会印着「你的 LOGO」上封面）",
                hint="换成你自己的 LOGO：透明底 PNG、高度 ≥128px、宽高比 1:1—6:1（420×140 ≈ 3:1 最贴现有版式）",
            )

        problems, detail = [], LOGO.name
        try:
            from PIL import Image

            with Image.open(LOGO) as im:
                w, h = im.size
                # 「有 alpha 通道」≠「背景真是透明的」：PNG 存成 RGBA 但像素全不透明
                # 是最常见的坑（截图、白底图另存），必须看 alpha 的实际取值范围。
                alpha = im.getchannel("A").getextrema() if "A" in im.getbands() else None
                has_alpha = (alpha[0] < 250) if alpha else "transparency" in im.info
                empty = bool(alpha) and alpha[1] == 0
            detail = f"{w}×{h}"
            if h < 128:
                problems.append(f"高度 {h}px <128px（角标会被拉大，边缘发糊）")
            if not has_alpha:
                problems.append("背景不透明（封面上会是一块白方块）")
            elif empty:
                problems.append("整张图全透明（角标位置会是一片空白）")
            if h:
                ratio = w / h
                if ratio > 6:
                    problems.append(f"宽高比 {ratio:.0f}:1 过宽（压到角标是一条横线，还会盖住标题区）")
                elif ratio < 1:
                    problems.append(f"宽高比约 1:{1 / ratio:.0f} 过窄（压到角标是一条竖线）")
        except Exception:
            pass

        if problems:
            return self.add(
                "logo", "品牌 LOGO", False, f"{detail}——" + "；".join(problems),
                hint="重导一张透明底 PNG（高度 ≥128px、宽高比 1:1—6:1，420×140 ≈ 3:1 最贴现有版式），覆盖 $WX_LOGO",
            )
        return self.add("logo", "品牌 LOGO", True, detail)

    def check_config_md(self):
        """00_配置.md 与当前环境变量是否一致（Q40）。

        这个文件**没有任何脚本消费**（`grep 00_配置 scripts/` 为空），它和 `WX_*`
        是双源：md 里改成「母婴」、环境变量还是「考公」，脚本照直按考公跑，
        而两边都不报错。所以在这里比一次，不一致就指出来——不猜哪个对。
        """
        label = "00_配置.md（Q40）"
        if not os.environ.get("WX_DAILY_OUT", "").strip():
            return self.add("config", label, False, "产物目录未指定，无从查找",
                            hint="先按 Q7 指定 WX_DAILY_OUT")
        try:
            from brand import ACCENT, ACCENT_ALT, AUDIENCE, OUT_DIR, VERTICAL
        except Exception as e:
            return self.add("config", label, False, f"读不到配置：{e}")
        md = OUT_DIR / "00_配置.md"
        if not md.exists():
            return self.add(
                "config", label, False, "未生成",
                hint="onboarding Q40：按模板写一份到 $WX_DAILY_OUT/00_配置.md"
                     "（文件名必须带下划线，否则 check_content.py 会把它当稿件）")
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return self.add("config", label, False, f"读不出来（{e}）")

        # 只认「- 字段：值」这种行；`  # 注释` 用两个以上空格分隔，避免切掉颜色值的 #
        parsed = {}
        for ln in text.splitlines():
            m = re.match(r"^\s*[-*]\s*([^：:]+)[：:]\s*(.+)$", ln)
            if not m:
                continue
            key = re.sub(r"[（(].*?[）)]", "", m.group(1)).strip()
            parsed.setdefault(key, re.split(r"\s{2,}#", m.group(2))[0].strip())

        cur = {"VERTICAL": VERTICAL, "AUDIENCE": AUDIENCE,
               "ACCENT": ACCENT, "ACCENT_ALT": ACCENT_ALT}
        blanks, diffs = [], []
        for name, attr, envname in CONFIG_MD_FIELDS:
            raw = parsed.get(name)
            if not raw or raw.startswith("<"):   # 缺字段，或模板占位没填
                blanks.append(name)
                continue
            if _norm_val(raw) != _norm_val(str(cur[attr])):
                diffs.append(f"{name} 写着「{raw}」，脚本实际用「{cur[attr] or '（未设置）'}」")

        if blanks:
            return self.add(
                "config", label, False, f"有 {len(blanks)} 项没填：{'、'.join(blanks)}",
                hint="这四项（类目/读者画像/主色/辅色）是根配置，留空或沿用模板占位等于没配")
        if diffs:
            return self.add(
                "config", label, False, "与当前环境不一致：" + "；".join(diffs),
                hint="脚本只认环境变量。要么按 md 的值 export，要么把 md 改成实际值——别让两处各说各话")
        return self.add("config", label, True, "四项与环境一致")

    def check_verify_cli(self):
        # 官方 HTML 校验 CLI：缺了会退化为静态自查，不阻断
        try:
            from verify_html import find_cli
            cli = find_cli()
        except Exception:
            cli = None
        if cli:
            return self.add("verify_cli", "官方 HTML 校验 CLI", True, str(cli))
        node = shutil.which("node")
        if self.fix and self.net and node:
            r = _run([sys.executable, str(REPO / "scripts" / "verify_html.py"),
                      "--setup"], timeout=900)
            if r and r.returncode == 0:
                self.fixed.append("官方校验 CLI")
                return self.add("verify_cli", "官方 HTML 校验 CLI", True, "已安装")
        return self.add("verify_cli", "官方 HTML 校验 CLI", False,
                        "未安装（降级为静态自查）",
                        hint="python3 scripts/verify_html.py --setup")

    def check_node(self):
        node = shutil.which("node")
        if node:
            r = _run(["node", "--version"], timeout=30)
            ver = (r.stdout or "").strip() if r else "?"
            return self.add("node", "Node.js（第七步需要）", True, ver)
        return self.add("node", "Node.js（第七步需要）", False, "未安装",
                        hint="brew install node（只有自动存草稿才需要）")

    def check_ego(self):
        ego = shutil.which("ego-browser")
        if ego:
            return self.add("ego", "ego-browser（第七步需要）", True, ego)
        return self.add("ego", "ego-browser（第七步需要）", False, "未安装",
                        hint="装 ego lite 桌面端并确保 ego-browser 在 PATH 上")

    def pending(self, include_publish: bool = False) -> list:
        """可选但没就绪的项。

        「可选」不等于「可以不管」：产物目录没指定、LOGO 还是占位图，这两件
        都能让出稿跑完却印错或存错地方。它们不阻断日常出稿，但交付验收要卡。

        `include_publish=True` 才把第七步的 Node.js / ego-browser 算进来：
        这两项只在「要自动存草稿」（Q4=2）时才该卡验收。
        """
        return [it["name"] for k, it in self.items.items()
                if not it["ok"] and not it["required"]
                and (include_publish or k not in PUBLISH_ONLY)]

    def run(self):
        self.check_python()
        self.check_pillow()
        self.check_font()
        self.check_outdir()
        self.check_config_md()
        self.check_guidelines()
        self.check_calendar()
        self.check_logo()
        self.check_verify_cli()
        self.check_node()
        self.check_ego()
        # Q4「要不要自动存草稿」的默认值跟着实际环境走：
        # 已装的没理由让人再点一次「不用」，没装的也不该默认成「要用」再失败
        self.publish_ready = bool(
            self.items.get("node", {}).get("ok") and self.items.get("ego", {}).get("ok")
        )
        return 0 if not self.blocked else 1


def print_report(env: Env, strict: bool = False, publish: bool = False):
    print("=" * 62)
    print("环境自检")
    print("=" * 62)
    for key, it in env.items.items():
        mark = "OK  " if it["ok"] else ("FAIL" if it["required"] else "SKIP")
        tag = "必装" if it["required"] else "可选"
        print(f"[{mark}] {it['name']:<26} {tag}  {it['detail']}")
        if not it["ok"] and it.get("hint"):
            print(f"       修法：{it['hint']}")
    print("-" * 62)
    print(f"出稿链路（第 1—6 步）：{'可用' if not env.blocked else '不可用'}")
    if not env.items["outdir"]["ok"]:
        _cause = env.items["outdir"].get("cause")
        if _cause == "missing":
            print("  └ 产物目录已指定但还没建，跑一次 bootstrap（不带 --report）就会创建")
        elif _cause == "unwritable":
            print("  └ 产物目录存在但写不进去，按上面的修法换目录")
        else:
            print("  └ 但产物目录还没指定，首次使用前先答 onboarding Q7")
    print(f"自动存草稿（第七步）："
          f"{'可用' if env.publish_ready else '不可用（不影响出稿）'}")
    print(f"→ Q4「要不要自动存草稿」建议默认值："
          f"{'2（要用）' if env.publish_ready else '1（不用，只出稿）'}")
    if env.fixed:
        print(f"本次自动补齐：{'、'.join(env.fixed)}")
    pending = env.pending(include_publish=True)   # 展示给全量，别把问题藏起来
    strict_pending = env.pending(include_publish=publish)
    if pending:
        print(f"待处理（不阻断）：{'、'.join(pending)}")
        only_publish = [n for n in pending if n not in strict_pending]
        if only_publish and strict:
            print(f"  └ 其中 {'、'.join(only_publish)} 只影响第七步自动存草稿；"
                  f"Q4 答「要用」时加 --publish 一并卡")
    if strict:
        # --strict 是交付验收口径：必装全绿还不够，待处理也要清空。
        # 「产物目录没指定」照样打印「出稿链路可用」，所以不能只看那一行。
        ok = not env.blocked and not strict_pending
        print(f"严格验收（--strict{' --publish' if publish else ''}）："
              f"{'通过' if ok else '不通过——待处理项未清空'}")
    print("=" * 62)


def main():
    ap = argparse.ArgumentParser(
        description="环境自举：自动补齐出图依赖。成功静默，失败才提示。")
    ap.add_argument("--report", action="store_true",
                    help="只报状态不修复，并打印完整清单（用户问起环境时用）")
    ap.add_argument("--quiet", action="store_true", help="成功时完全静默")
    ap.add_argument("--no-net", action="store_true", help="跳过需要联网的项")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="输出 JSON（供 Agent 判断）")
    ap.add_argument("--strict", action="store_true",
                    help="交付验收口径：连「待处理（不阻断）」一起要求清空，"
                         "有任何可选项未就绪即 exit=1（onboarding Q37 用这个判定）")
    ap.add_argument("--publish", action="store_true",
                    help="配合 --strict：把第七步的 Node.js / ego-browser 也算进"
                         "验收（Q4 答「要自动存草稿」时加）")
    args = ap.parse_args()

    env = Env(fix=not args.report, net=not args.no_net)
    code = env.run()
    pending = env.pending(include_publish=args.publish)
    # 只有显式 --strict 才把「可选待办」提升为失败；日常与既有调用者行为不变
    strict_fail = args.strict and (code != 0 or bool(pending))

    if args.as_json:
        print(json.dumps({
            "ok": code == 0,
            "items": env.items,
            "fixed": env.fixed,
            "blocked": env.blocked,
            "pending": env.pending(include_publish=True),
            "strict_pending": pending,
            "strict_ok": not strict_fail,
            "publish_ready": env.publish_ready,
            "q4_default": 2 if env.publish_ready else 1,
        }, ensure_ascii=False, indent=2))
        return 1 if strict_fail else code

    if args.report:
        print_report(env, strict=args.strict, publish=args.publish)
        return 1 if strict_fail else code

    if code != 0:
        # 唯一必须打扰用户的情形：缺了且修不了，出稿会失败
        print("环境自举没能全部补齐，以下项会阻断出稿：", file=sys.stderr)
        for key in env.blocked:
            it = env.items[key]
            print(f"  ✗ {it['name']}：{it['detail']}", file=sys.stderr)
            if it.get("hint"):
                print(f"    修法：{it['hint']}", file=sys.stderr)
        print("修好后重跑：python3 scripts/bootstrap.py", file=sys.stderr)
        return 1

    if not args.quiet:
        note = f"（自动补齐：{'、'.join(env.fixed)}）" if env.fixed else ""
        print(f"环境就绪{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

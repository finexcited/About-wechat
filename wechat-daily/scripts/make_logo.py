#!/usr/bin/env python3
"""按文字名称生成 LOGO（字标），透明底 PNG，零成本、零错字。

为什么用「字标」而不是 AI 生图：
  1. 文字必须**一字不差**——AI 生图的中文错字率在 LOGO 这种少字场景下格外显眼，
     而字标是真实字体渲染，没有错字这回事；
  2. 与封面同字体（Noto Sans SC）+ 同主色，视觉天然一致；
  3. 零积分、可复现：改个色号重跑一次就行，不需要抽卡；
  4. 无版权风险——字体是 OFL，渲染出的字标是自己生成的图形，不涉及他人商标。

规格（与 onboarding Q8b 的验收一致）：
  透明底 PNG、高度 ≥ 128px、宽高比 1:1—6:1。脚本按 2 倍尺寸渲染（默认高 280），
  等比缩放后仍清晰；宽高比超 6:1 时自动缩字号，不会产出不合规文件。

用法：
  python3 make_logo.py --name "小鲸儿童饮料" --out-dir ./logo-candidates
  python3 make_logo.py --name "小鲸" --style mark --out assets/logo.png
  python3 make_logo.py --name "小鲸儿童饮料" --accent '#2B38B1'

产出（--out-dir 模式）会让使用者三选一：
  1-wordmark.png  纯文字，最稳，适合文字型品牌
  2-mark.png      左侧图形标 + 右侧文字，辨识度高
  3-badge.png     胶囊描边，适合做角标
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brand import ACCENT, BRAND_NAME, FONT_PATH, hex_rgb, resolve_accent  # noqa: E402

H = 280          # 渲染高度（2 倍），显示高 140
MIN_RATIO = 1.0
MAX_RATIO = 6.0
INK = (35, 24, 21)   # 深字色，与 design-spec 的 #231815 一致


def load_font(size: int, weight: int = 800):
    if not FONT_PATH.exists():
        raise SystemExit(f"缺少字体：{FONT_PATH}\n请确认 assets/fonts/ 未被删除（字体随包提供）")
    f = ImageFont.truetype(str(FONT_PATH), size)
    try:
        f.set_variation_by_axes([weight])
    except Exception as e:      # 静态字体没有字重轴——这里必须报出来，不能静默降级
        raise SystemExit(
            f"字体没有字重轴（{type(e).__name__}）：{FONT_PATH}\n"
            "字标靠字重区分主次，静态字体渲染出来会整体一个粗细。"
            "请恢复随包的 NotoSansSC-VF.ttf。"
        )
    return f


def fit_size(text: str, cap_ratio: float, weight: int, start: int):
    """在「宽高比 ≤ cap_ratio」的约束下取最大字号。

    ⚠️ 注意：缩放是**等比**的，缩字号不会改变宽高比。所以这个函数只用于
    给「加在文字旁边的图形元素」留出预算，不能解决「字太多导致太扁」——
    那个只能靠缩短名称或换版式（见 STYLE_HINT）。
    """
    size = start
    while size > 20:
        f = load_font(size, weight)
        w = f.getlength(text)
        if w / H <= cap_ratio:
            return f, int(w)
        size -= 2
    f = load_font(size, weight)
    return f, int(f.getlength(text))


def canvas(w: int):
    return Image.new("RGBA", (max(w, 40), H), (0, 0, 0, 0))


def trim(img: Image.Image) -> Image.Image:
    box = img.split()[3].getbbox()
    if not box:
        raise SystemExit("生成结果全透明，请检查品牌名是否为空")
    return img.crop(box)


def style_wordmark(name: str, accent: tuple):
    pad = 12
    f, tw = fit_size(name, MAX_RATIO - 0.2, 800, int(H * 0.62))
    img = canvas(tw + pad * 2)
    d = ImageDraw.Draw(img)
    bbox = d.textbbox((0, 0), name, font=f)
    d.text((pad - bbox[0], (H - (bbox[3] - bbox[1])) / 2 - bbox[1]), name, font=f, fill=accent + (255,))
    return trim(img)


def style_mark(name: str, accent: tuple):
    """左侧圆角方（主色底 + 白色首字），右侧字标。"""
    pad = 12
    badge = int(H * 0.86)
    radius = int(badge * 0.28)
    head = name[0]
    rest = name[1:] or name
    f_badge, _ = fit_size(head, 1.0, 800, int(badge * 0.58))
    f_text, tw = fit_size(rest, MAX_RATIO - 1.4, 800, int(H * 0.52))
    gap = int(H * 0.14)
    total_w = badge + gap + tw
    img = canvas(total_w + pad * 2)
    d = ImageDraw.Draw(img)
    top = (H - badge) // 2
    d.rounded_rectangle([pad, top, pad + badge, top + badge], radius=radius, fill=accent + (255,))
    bb = d.textbbox((0, 0), head, font=f_badge)
    d.text((pad + (badge - (bb[2] - bb[0])) / 2 - bb[0],
            top + (badge - (bb[3] - bb[1])) / 2 - bb[1]), head, font=f_badge, fill=(255, 255, 255, 255))
    bx = pad + badge + gap
    bb2 = d.textbbox((0, 0), rest, font=f_text)
    d.text((bx - bb2[0], (H - (bb2[3] - bb2[1])) / 2 - bb2[1]), rest, font=f_text, fill=INK + (255,))
    return trim(img)


def style_badge(name: str, accent: tuple):
    """胶囊描边 + 主色文字，左右对称留白。"""
    f, tw = fit_size(name, MAX_RATIO - 0.8, 700, int(H * 0.52))
    pad_x = int(H * 0.30)
    w = tw + pad_x * 2
    img = canvas(w)
    d = ImageDraw.Draw(img)
    lw = max(4, int(H * 0.028))
    d.rounded_rectangle([lw // 2, lw // 2, w - lw // 2, H - lw // 2],
                        radius=int(H * 0.30), outline=accent + (255,), width=lw)
    bb = d.textbbox((0, 0), name, font=f)
    d.text(((w - (bb[2] - bb[0])) / 2 - bb[0], (H - (bb[3] - bb[1])) / 2 - bb[1]),
           name, font=f, fill=accent + (255,))
    return trim(img)


STYLES = {"wordmark": style_wordmark, "mark": style_mark, "badge": style_badge}


STYLE_HINT = {
    "wordmark": "纯字标是单行的，字越多越扁：6:1 的比例上限只容得下约 5 个汉字。"
                "名称为 6 字及以上时，请改用短名（如取前 2—3 字），或换 2-mark / 3-badge 版式。",
    "mark": "左侧图形标会占掉一部分宽度；名称过长时改用 3-badge，或缩短名称。",
    "badge": "胶囊描边会随文字变宽；名称过长时缩短名称。",
}


def report(path: Path, im: Image.Image, style: str = "") -> bool:
    ratio = im.width / im.height
    ok_h = im.height >= 128
    ok_r = MIN_RATIO <= ratio <= MAX_RATIO
    flag = "OK  " if (ok_h and ok_r) else "WARN"
    why = []
    if not ok_h:
        why.append("高度不足 128px")
    if not ok_r:
        why.append(f"宽高比 {ratio:.2f} 超出 1:1—6:1")
    print(f"  [{flag}] {path.name:18} {im.width}×{im.height}  比例 {ratio:.2f}"
          + (f"  ← {'；'.join(why)}" if why else ""))
    if not (ok_h and ok_r) and style in STYLE_HINT:
        print(f"         {STYLE_HINT[style]}")
    return ok_h and ok_r


def main() -> int:
    ap = argparse.ArgumentParser(description="按文字名称生成透明底 LOGO（字标）")
    ap.add_argument("--name", default=BRAND_NAME, help="品牌名称（默认取 WX_BRAND）")
    ap.add_argument("--accent", default=ACCENT, help="主色，默认取 WX_ACCENT")
    ap.add_argument("--style", default="", choices=[""] + list(STYLES),
                    help="只出一个版式；不给则三种都出")
    ap.add_argument("--out", default="", help="单文件输出路径（配合 --style 使用）")
    ap.add_argument("--out-dir", default="", help="输出目录，三种版式各一份")
    args = ap.parse_args()

    name = (args.name or "").strip()
    if not name:
        print("ERROR: 品牌名为空，无法生成 LOGO", file=sys.stderr)
        return 2
    if len(name) > 12:
        print(f"WARN: 品牌名 {len(name)} 字，字标会很长；建议 ≤12 字（封面角标也放不下）",
              file=sys.stderr)

    accent = resolve_accent(args.accent, as_rgb=True)
    if not isinstance(accent, tuple):
        accent = hex_rgb(args.accent)

    todo = [args.style] if args.style else list(STYLES)
    print(f"字标生成：名称「{name}」 主色 {args.accent}")
    print(f"  输出尺寸：渲染高 {H}px（显示高 {H // 2}px），透明底")

    targets = []
    if args.out:
        if len(todo) != 1:
            print("ERROR: --out 只能配合单个 --style 使用；多版式请用 --out-dir", file=sys.stderr)
            return 2
        targets.append((Path(args.out), todo[0]))
    else:
        out_dir = Path(args.out_dir or "logo-candidates")
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, s in enumerate(todo, 1):
            targets.append((out_dir / f"{i}-{s}.png", s))

    all_ok = True
    for path, style in targets:
        im = STYLES[style](name, accent)
        path.parent.mkdir(parents=True, exist_ok=True)
        im.save(path)
        all_ok &= report(path, im, style)

    print()
    if all_ok:
        print("完成。挑一张满意的，覆盖到 assets/logo.png 即可：")
        print("  cp <你选的那张> assets/logo.png")
        print("  然后跑 python3 scripts/bootstrap.py --report 确认「品牌 LOGO」行为 [OK]")
    else:
        print("有文件不满足规格（透明底 / 高 ≥128 / 比例 1:1—6:1）。缩短品牌名或换版式重跑。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

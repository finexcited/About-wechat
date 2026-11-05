#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pick_palette.py — 从 LOGO 或参考图里取主色/辅色（Q19 选项 1、2 的落地）

背景：Q19 给了三条取色路径——「从 LOGO 拆解」「上传一张色系参考图让 AI 调取」
「直接填 #RRGGBB」。前两条如果只靠 AI 看一眼图报个色号，问题有三个：
① 每次报的色号都不一样，同一张 LOGO 今天 `#3B6EA5` 明天 `#3A6DA3`，
   重出全套图时色带和封面角标就对不上；
② AI 容易被画面主体带偏——LOGO 里一个很小的红色点缀，在视觉上很显眼，
   但占比只有 2%，拿它当主色做出来的长图会整体偏色；
③ 说不出「为什么是它」，使用者没法复核。

所以取色这一步交给脚本：量化 → 按画面占比排序 → 剔除近白/近黑/低饱和，
输出可直接粘进 `WX_ACCENT` 的色号。带透明通道的 LOGO 先在白底上合成，
透明区域自然变成白色并被过滤掉。

用法：
  python3 scripts/pick_palette.py assets/logo.png
  python3 scripts/pick_palette.py 参考图.jpg --top 6
  python3 scripts/pick_palette.py assets/logo.png --json

  # 底色/字色对比度校验（Q20 用；不带图片也能跑）
  python3 scripts/pick_palette.py --check "#F8F5F0" "#231815"
  python3 scripts/pick_palette.py --check "#EE7800" "#FFFFFF"

判读：
  主色 = 占比最大的**有彩色**（饱和度 ≥ 0.12）。占比而非观感排序是刻意的——
        主色要能撑起大片色带和标题底色，2% 的点缀色撑不起来。
  辅色 = 与主色色相差 ≥ 60° 的下一个候选。色差太近等于没有辅色，
        封面会因为「两个相近的色」显得脏。
  退出码 3 = 整张图没有可用色相（纯黑白灰 LOGO），需退回 Q19 选项 3 或上传参考图。
  退出码 4 = 对比度不足（`--check` 专用，见下）。

关于对比度：Q20 允许使用者把底色/字色/条底色一起换掉，而这是**唯一会同时影响可读性**
的一组值。填深蓝底 + 深灰字时脚本会照样渲染，封面标题糊在背景里，肉眼在缩略图上
根本看不出来。所以这里按 WCAG 2.1 算相对亮度对比度：
  ≥ 4.5:1  通过（AAA 大字号 / AA 正文）
  3.0—4.5  仅够大字号（封面标题 ≥24px 粗体可以，正文别用）
  < 3.0    拒绝，要求重选（exit 4）
封面标题属于「大字号」一档，所以 3.0 是硬底线而不是 4.5——按 4.5 卡会把
很多正常的浅底深字方案误杀。
"""
import argparse
import colorsys
import json
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("需要 Pillow：python3 scripts/bootstrap.py")

# 量化到多少个色。24 足够覆盖一张 LOGO 或一张参考图的主要色相，
# 再高会把抗锯齿产生的过渡色也当成候选，输出一堆肉眼分不出的近邻色。
QUANT_COLORS = 24
# 缩到多小再做量化。取色只看占比，不需要细节；240px 够稳且很快。
SAMPLE_EDGE = 240

S_MIN = 0.12      # 饱和度低于此视为「中性色」（灰/米/白/黑），不当主色
V_MIN = 0.08      # 明度低于此视为黑
V_MAX_WHITE = 0.96  # 明度高于此且饱和度低 → 白
HUE_GAP = 60.0    # 辅色与主色的最小色相差（度）


def _load(path: Path) -> Image.Image:
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    im.thumbnail((SAMPLE_EDGE, SAMPLE_EDGE), Image.LANCZOS)
    return im


def _hex(rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb[:3])


def parse_hex(s: str):
    """接受 #RGB / #RRGGBB / RRGGBB，返回 (r,g,b)；认不出抛 ValueError。"""
    t = s.strip().lstrip("#")
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) != 6 or any(c not in "0123456789abcdefABCDEF" for c in t):
        raise ValueError(s)
    return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))


def _rel_luminance(rgb) -> float:
    """WCAG 2.1 相对亮度：先做 sRGB 反伽马，再加权。"""
    def chan(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b) -> float:
    la, lb = _rel_luminance(a), _rel_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def check_pair(bg_hex: str, fg_hex: str) -> int:
    """打印一对底/字色的对比度判定，返回退出码（0 通过或仅够大字，4 拒绝）。"""
    try:
        bg, fg = parse_hex(bg_hex), parse_hex(fg_hex)
    except ValueError as e:
        print(f"✗ 色号格式不对：{e}（要 #RRGGBB 或 #RGB）")
        return 2

    ratio = contrast_ratio(bg, fg)
    bg_h = _hex(bg)
    fg_h = _hex(fg)

    if ratio >= 4.5:
        verdict, code = "✓ 通过（正文与标题都清晰）", 0
    elif ratio >= 3.0:
        verdict, code = "△ 仅够大字号（封面标题可以，正文别用）", 0
    else:
        verdict, code = "✗ 拒绝：字会糊在底色里，请重选", 4

    print(f"底色 {bg_h}  字色 {fg_h}  对比度 {ratio:.2f}:1")
    print(f"  {verdict}")
    if code == 4:
        print("  参考：去掉底色改纯白底，或把字色换成反极性的深/浅色；")
        print("        实在要这个底色，就把它用在小面积色条上而不是整块底。")
    return code


def _hsv(rgb):
    r, g, b = [c / 255.0 for c in rgb[:3]]
    return colorsys.rgb_to_hsv(r, g, b)


def _hue_gap(a: float, b: float) -> float:
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d) * 360.0


def candidates(path: Path, top: int = 5) -> dict:
    """返回 {'kept': [...], 'dropped': n, 'size': (w,h), 'alpha': bool}"""
    raw = Image.open(path)
    alpha = raw.mode in ("RGBA", "LA", "P") and (
        raw.mode != "P" or "transparency" in raw.info
    )
    size = raw.size
    im = _load(path)

    q = im.quantize(colors=QUANT_COLORS, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    total = im.width * im.height
    kept, dropped = [], 0

    for count, idx in sorted(q.getcolors() or [], reverse=True):
        rgb = tuple(pal[idx * 3: idx * 3 + 3])
        if len(rgb) < 3:
            continue
        h, s, v = _hsv(rgb)
        neutral = s < S_MIN
        black = v < V_MIN
        white = v > V_MAX_WHITE and s < 0.25
        if neutral or black or white:
            dropped += 1
            continue
        kept.append({
            "hex": _hex(rgb),
            "rgb": list(rgb),
            "share": round(count / total, 4),
            "h": round(h * 360, 1),
            "s": round(s, 3),
            "v": round(v, 3),
        })

    kept.sort(key=lambda c: c["share"], reverse=True)
    kept = kept[:top]

    primary = kept[0] if kept else None
    alt = None
    if primary:
        for c in kept[1:]:
            if _hue_gap(primary["h"] / 360.0, c["h"] / 360.0) >= HUE_GAP:
                alt = c
                break
        if alt is None and len(kept) > 1:
            # 没有足够色差的第二色：说明整张图是单色系。
            # 辅色退回主色的深色变体，而不是硬拿一个色相相近的色当辅色。
            h, s, v = primary["h"] / 360.0, primary["s"], primary["v"]
            v2 = max(0.18, v * 0.62)
            r, g, b = colorsys.hsv_to_rgb(h, min(1.0, s * 1.05), v2)
            alt = {
                "hex": _hex((round(r * 255), round(g * 255), round(b * 255))),
                "rgb": [round(r * 255), round(g * 255), round(b * 255)],
                "share": None, "h": primary["h"],
                "s": round(min(1.0, s * 1.05), 3), "v": round(v2, 3),
                "derived": "primary-darker",
            }

    return {"kept": kept, "primary": primary, "alt": alt,
            "dropped": dropped, "size": size, "alpha": alpha,
            "src": str(path)}


def main():
    ap = argparse.ArgumentParser(description="从 LOGO / 参考图取主色与辅色；或校验底色/字色对比度")
    ap.add_argument("image", nargs="?", help="LOGO 或参考图路径（PNG/JPG/WEBP）；用 --check 时可省略")
    ap.add_argument("--top", type=int, default=5, help="候选色条数（默认 5）")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    ap.add_argument("--check", nargs=2, metavar=("底色", "字色"),
                    help="校验一对底/字色的 WCAG 对比度，不读图片")
    args = ap.parse_args()

    if args.check:
        return check_pair(*args.check)

    if not args.image:
        ap.error("要么给图片路径取色，要么用 --check <底色> <字色> 校验对比度")

    p = Path(args.image).expanduser()
    if not p.is_file():
        sys.exit(f"找不到图片：{p}")

    try:
        r = candidates(p, args.top)
    except Exception as e:  # 图片损坏 / 格式不支持
        sys.exit(f"读取失败：{p}（{e}）")

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["primary"] else 3

    w, h = r["size"]
    print(f"取色来源：{r['src']}（{w}×{h}{'，含透明通道已合成白底' if r['alpha'] else ''}）")

    if not r["primary"]:
        print(f"  ✗ 没有可用的有彩色相（已剔除 {r['dropped']} 个近白/近黑/低饱和色）")
        print("  这张图是纯黑白灰，拆不出品牌色。两条路：")
        print("    · 换一张有颜色的图（Q19 选项 2）")
        print("    · 直接指定色号（Q19 选项 3）")
        return 3

    print("候选色（按画面占比排序，已剔除近白/近黑/低饱和）：")
    for i, c in enumerate(r["kept"]):
        role = ""
        if i == 0:
            role = "  ← 建议作主色（占画面最多）"
        elif c is r["alt"]:
            role = "  ← 建议作辅色"
        print(f"  {c['hex']}  占比 {c['share'] * 100:5.1f}%  "
              f"饱和度 {c['s']:.2f}  明度 {c['v']:.2f}{role}")

    if r["alt"] and r["alt"].get("derived"):
        print(f"\n  辅色说明：全图只有一个色相，辅色按主色压深得出 → {r['alt']['hex']}")

    print(f"\n主色（WX_ACCENT）    ：{r['primary']['hex']}")
    print(f"辅色（WX_ACCENT_ALT）：{r['alt']['hex'] if r['alt'] else '（未取到，建议手工指定）'}")
    print("\n把这两个色号填进 Q19 / Q19b 即可；取色只看占比，最终仍要人眼确认一次。")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)

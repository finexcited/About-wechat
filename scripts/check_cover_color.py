#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_cover_color.py — 判定封面图是否「带品牌彩色」（防空封面 / 被正文表格图顶替）

背景：草稿存完后，封面可能压根没提交（微信自动拿正文首图、纯灰白块顶上），
或提交成了一张白底表格截图，草稿箱里就出现「不是彩色封面」。

⚠️ 判定不能用「平均饱和度」：本号封面有多种版式，米白/纸白底 + 高饱和主色标题的
浅色版式平均饱和度只有 0.17，会被误判成「偏灰」。改用**彩色像素占比**。

判据（两条分开看，别混）：
  1. **什么算一个「彩色像素」**：饱和度 ≥0.30 且明度 ≥0.15 的像素。
  2. **多少占比算合格**：见下面判档，默认 0.05 / 0.02。

参考值（实测，不是阈值）：浅色版式 0.15—0.23、深底版式 0.80+、
白底文字图 / 表格截图 / 空封面 <0.02。合格线（0.05）比浅色版式的实测值低一大截，
是故意留的余量——别把 0.15 当成合格线去卡，那是版式的长相，不是判据。

用法：
  python3 check_cover_color.py --dir $WX_DAILY_OUT/_ego/verify
  python3 check_cover_color.py 图1.png 图2.png
  python3 check_cover_color.py --dir … --json           # JSON（含生效阈值与汇总）
  python3 check_cover_color.py --dir … --colorful 0.08  # 自定义合格线

判档（彩色像素占比，默认阈值）：
  >= 0.05   彩色（正常设计稿，浅色版式也过）
  0.02—0.05 弱彩（可疑：多为白底截图 / 近乎单色）
  < 0.02    无彩色（空封面、纯灰白块、黑白表格）
退出码：0 全部合格 / 1 存在弱彩或无彩色 / 2 无法检查（含参数自相矛盾）
"""
import argparse
import colorsys
import glob
import json
import os
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("需要 Pillow：pip install -r requirements.txt")

COLORFUL = 0.05
WEAK = 0.02
SAT_MIN = 0.30
VAL_MIN = 0.15


def analyse(path, sat_min=SAT_MIN, val_min=VAL_MIN):
    with Image.open(path) as im:
        im = im.convert("RGB").resize((240, 120))
        raw = im.tobytes()  # RGB 连续字节；不用 getdata（Pillow 14 起删除）
    n = max(1, len(raw) // 3)
    colored = 0
    sat_sum = 0.0
    for i in range(0, len(raw), 3):
        _, s, v = colorsys.rgb_to_hsv(raw[i] / 255.0, raw[i + 1] / 255.0, raw[i + 2] / 255.0)
        sat_sum += s
        if s >= sat_min and v >= val_min:
            colored += 1
    return colored / n, sat_sum / n


def verdict(ratio, colorful=COLORFUL, weak=WEAK):
    if ratio >= colorful:
        return "彩色"
    if ratio >= weak:
        return "弱彩"
    return "无彩色"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--dir")
    ap.add_argument("--json", action="store_true", help="输出 JSON（含当前生效的阈值与汇总）")
    ap.add_argument("--colorful", type=float, default=COLORFUL,
                    help=f"彩色像素占比达到多少判「彩色」＝合格（默认 {COLORFUL}）")
    ap.add_argument("--weak", type=float, default=WEAK,
                    help=f"弱彩下限，低于它判「无彩色」（默认 {WEAK}）")
    ap.add_argument("--sat-min", type=float, default=SAT_MIN,
                    help=f"单个像素算「彩色」的饱和度门槛（默认 {SAT_MIN}）")
    ap.add_argument("--val-min", type=float, default=VAL_MIN,
                    help=f"单个像素算「彩色」的明度门槛（默认 {VAL_MIN}）")
    args = ap.parse_args()

    # 参数自检：这几个数之间有关系，改错一个就会变成「永远合格」或「永远不合格」
    for name in ("colorful", "weak", "sat_min", "val_min"):
        v = getattr(args, name)
        if not 0.0 <= v <= 1.0:
            print(f"参数 --{name.replace('_', '-')} 必须在 0—1 之间，收到 {v}", file=sys.stderr)
            sys.exit(2)
    if args.weak > args.colorful:
        print(f"参数矛盾：--weak({args.weak}) 大于 --colorful({args.colorful})，"
              "「弱彩」这一档将永远取不到，等于把判据悄悄改成两档", file=sys.stderr)
        sys.exit(2)

    files = list(args.files)
    if args.dir:
        files += sorted(glob.glob(os.path.join(args.dir, "*.png")))
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        print("没有可检查的图片", file=sys.stderr)
        sys.exit(2)

    rows = []
    for f in files:
        try:
            ratio, mean = analyse(f, args.sat_min, args.val_min)
            rows.append({
                "file": os.path.basename(f),
                "colorRatio": round(ratio, 3),
                "meanSaturation": round(mean, 3),
                "verdict": verdict(ratio, args.colorful, args.weak),
                "kb": round(os.path.getsize(f) / 1024),
            })
        except Exception as e:
            rows.append({"file": os.path.basename(f), "error": str(e)[:120]})

    bad = sum(1 for r in rows if "error" in r or r["verdict"] != "彩色")

    if args.json:
        print(json.dumps({
            "thresholds": {
                "colorful": args.colorful, "weak": args.weak,
                "satMin": args.sat_min, "valMin": args.val_min,
            },
            "summary": {"total": len(rows), "bad": bad},
            "files": rows,
        }, ensure_ascii=False, indent=1))
        if bad:
            print(f"→ {bad} 张不合格（看 files[].verdict）；重设封面用 cmd=cover，"
                  "重设后仍不合格说明该篇封面图本身不是设计稿", file=sys.stderr)
    else:
        for r in rows:
            if "error" in r:
                print(f"✗ {r['file']}  读取失败：{r['error']}")
                continue
            ok = r["verdict"] == "彩色"
            print(f"{'✓' if ok else '✗'} {r['file']}  彩色占比={r['colorRatio']:.3f}  "
                  f"平均饱和={r['meanSaturation']:.3f}  {r['verdict']}  {r['kb']}KB")
        print(f"\n合计 {len(rows)} 张，不合格 {bad} 张"
              f"（判据：彩色像素占比 ≥{args.colorful}；单像素 饱和度≥{args.sat_min} 且 明度≥{args.val_min}）")
        if bad:
            print("→ 不合格项用 cmd=cover 重设封面后重新核验；若重设后仍不合格，说明该篇封面图本身不是设计稿。")

    # 两种模式的退出码必须一致：不合格就是 1，不许 --json 静默放行
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
成本与人工工时估算（跑之前先算清账）

为什么需要这个脚本：AI 生图是**按张计积分**的，篇数 × (封面 + 插画) 看起来不多，
一个月下来是四位数积分级别。配置问答里选了"用 AI 背景"的人，应该先看到账单再决定。
篇数本身**不预设**：优先读 WX_ARTICLES，其次 --articles，都没有就报错退出。

积分单价来自 SKILL.md 的实测区间：
  - AI 封面背景：约 5—10 积分/张
  - 正文插画：约 5—10 积分/张

用法：
  WX_ARTICLES=3 python3 scripts/cost_estimate.py            # 读配置的篇数
  python3 scripts/cost_estimate.py --articles 3             # 临时指定篇数
  python3 scripts/cost_estimate.py --articles 3 --cover ai --illust 3 --price 0.1
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brand import ARTICLES, article_plan  # noqa: E402

LOW, HIGH = 5, 10          # 单张 AI 图积分区间
REVIEW_MIN_PER_ARTICLE = (3, 5)   # 人工过目一篇的分钟区间（读一遍 + 改标题）


def main():
    ap = argparse.ArgumentParser(description="估算每月积分消耗与人工工时")
    ap.add_argument("--articles", type=int, default=0,
                    help="每天篇数；不给则读 WX_ARTICLES，都没有则报错（不预设）")
    ap.add_argument("--days", type=int, default=30, help="统计天数（默认 30）")
    ap.add_argument("--cover", choices=["ai", "prog", "none"], default="prog",
                    help="封面方案：ai=AI背景+程序排版，prog=纯程序版（零积分），none=不做封面")
    ap.add_argument("--cover-ai-count", type=int, default=None,
                    help="ai 方案里只用几张 AI 封面（混合方案，Q21 选项 3）。"
                         "不给 = 全部 N 张都用 AI")
    ap.add_argument("--illust", type=int, choices=[0, 1, 2, 3], default=1,
                    help="每篇配图张数：1=每篇1张（默认，Q22 硬下限）、2=头部+中段1、3=头部+中段2、"
                         "0=不配（仅用于「如果一张都不要能省多少」的反向测算；真这么跑会被 "
                         "check_content.py 判必改项，除非显式 WX_MIN_ILLUS=0）")
    ap.add_argument("--illust-count", type=int, default=None,
                    help="只给其中几张稿配插画（混合方案，Q22 选项 4）。"
                         "不给 = 全部 N 篇都配")
    ap.add_argument("--review-min", type=float, default=None,
                    help="人工过目一篇的分钟数（默认取 3—5 分钟区间）")
    ap.add_argument("--price", type=float, default=None,
                    help="每积分单价（元）。给了才折算金额；不给只报积分")
    args = ap.parse_args()

    n, days = args.articles or ARTICLES, args.days
    if n <= 0:
        sys.exit("ERROR: 未给出每天篇数。本技能不预设篇数——"
                 "请用 WX_ARTICLES=<篇数> 或 --articles <篇数> 指定，先问使用者每天发几条。")
    total_plan = article_plan() if not args.articles else (0, 0, 0)
    # 混合方案：只给前 K 篇配 AI 背景，其余走程序版。
    # 这是真实的主流做法——读者主要看头条封面，全 N 张都上 AI 成本翻 N 倍而边际收益很小。
    ai_k = args.cover_ai_count if args.cover_ai_count is not None else n
    if args.cover != "ai" and args.cover_ai_count:
        sys.exit("ERROR: --cover-ai-count 只在 --cover ai 时有效")
    if ai_k < 0 or ai_k > n:
        sys.exit(f"ERROR: --cover-ai-count 必须落在 0—{n} 之间（每天共 {n} 篇）")
    cover_imgs = ai_k if args.cover == "ai" else 0
    # 混合方案：只给部分篇配插画（典型是只给专栏篇）。
    # 短稿配 3 张等于每 300 字一张图，读者会以为在看画册——所以「配几张稿」和「每篇配几张」
    # 是两个独立的事，不能只用一个 N 篇全配的假设。
    il_k = args.illust_count if args.illust_count is not None else n
    if il_k < 0 or il_k > n:
        sys.exit(f"ERROR: --illust-count 必须落在 0—{n} 之间（每天共 {n} 篇）")
    illust_imgs = il_k * args.illust
    total_imgs_day = cover_imgs + illust_imgs

    low_day = total_imgs_day * LOW
    high_day = total_imgs_day * HIGH
    low_month, high_month = low_day * days, high_day * days

    rmin = args.review_min if args.review_min is not None else REVIEW_MIN_PER_ARTICLE[0]
    rmax = args.review_min if args.review_min is not None else REVIEW_MIN_PER_ARTICLE[1]
    review_day = (n * rmin, n * rmax)

    print("=" * 62)
    print("成本估算")
    print("=" * 62)
    if total_plan[0]:
        print(f"篇数结构：{total_plan[1]} 篇专栏 + {total_plan[2]} 篇泛干货")
    if args.cover == "ai":
        if cover_imgs == n:
            cover_desc = f"AI 背景+程序排版（全部 {n} 张）"
        elif cover_imgs == 0:
            cover_desc = "纯程序版（AI 张数给了 0）"
        else:
            cover_desc = f"混合：{cover_imgs} 张 AI + {n - cover_imgs} 张纯程序"
    else:
        cover_desc = "纯程序版" if args.cover == "prog" else "不做"
    if args.illust and il_k < n:
        illust_desc = f"{il_k} 篇各配 {args.illust} 张（其余 {n - il_k} 篇按 0 张算——注意 Q22 要求每篇 ≥1 张，这个结果只用于测算）"
    elif args.illust:
        illust_desc = f"每篇 {args.illust} 张"
    else:
        illust_desc = "不配图"
    print(f"配置：每天 {n} 篇 / 封面 {cover_desc}"
          f" / 插画 {illust_desc} / 统计 {days} 天")
    print("-" * 62)
    print(f"AI 图片数量：封面 {cover_imgs} 张/天 + 插画 {illust_imgs} 张/天"
          f" = {total_imgs_day} 张/天")
    if total_imgs_day == 0:
        print("积分消耗：0（当前方案全部为程序绘制，不消耗积分）")
    else:
        print(f"积分消耗：{low_day}–{high_day} 积分/天")
        print(f"          {low_month}–{high_month} 积分/{days} 天")
    print("-" * 62)
    print(f"人工审核：{review_day[0]:.0f}–{review_day[1]:.0f} 分钟/天"
          f"（{review_day[0] * days / 60:.1f}–{review_day[1] * days / 60:.1f} 小时/{days} 天）")

    if args.price and total_imgs_day:
        print(f"折算金额：{low_month * args.price:.0f}–{high_month * args.price:.0f} 元"
              f"（按 {args.price} 元/积分）")

    # 降本建议：只列能立刻省下来的
    tips = []
    if args.cover == "ai" and cover_imgs:
        save = cover_imgs * LOW * days, cover_imgs * HIGH * days
        tips.append(f"封面全改纯程序版：省 {save[0]}–{save[1]} 积分（4 套版式，零成本）")
        if cover_imgs > 1:
            tips.append(f"只留 1 张 AI 封面（头条）：再省 {(cover_imgs - 1) * LOW * days}–"
                        f"{(cover_imgs - 1) * HIGH * days} 积分，视觉收益基本还在")
    if args.illust == 3:
        save = il_k * 2 * LOW * days, il_k * 2 * HIGH * days
        tips.append(f"插画从 3 张减到 1 张：省 {save[0]}–{save[1]} 积分")
    if args.illust >= 2:
        save = il_k * (args.illust - 1) * LOW * days, il_k * (args.illust - 1) * HIGH * days
        tips.append(f"每篇张数降到 1 张（{args.illust} → 1）：省 {save[0]}–{save[1]} 积分"
                    "（1 张是 Q22 的硬下限，再往下会被质检拦）")
    if args.illust >= 1:
        save = illust_imgs * LOW * days, illust_imgs * HIGH * days
        tips.append(f"参考：若一张都不配，账面可省 {save[0]}–{save[1]} 积分——"
                    "但这会触发 check_content.py 的「缺少插图」必改项（需 WX_MIN_ILLUS=0 才放行）")

    if tips:
        print("-" * 62)
        print("降本选项：")
        for t in tips:
            print(f"  · {t}")
    print("=" * 62)
    print("提示：积分单价随平台计费变动，本表只算张数×区间，不含重试与废图。")
    print("      实际消耗通常比下限高，建议按上限做预算。")


if __name__ == "__main__":
    main()

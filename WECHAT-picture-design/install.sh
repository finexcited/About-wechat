#!/usr/bin/env bash
# WECHAT-picture-design 安装脚本（macOS / Linux）
# 用法：
#   bash install.sh            # 安装到 ~/.workbuddy/skills/
#   bash install.sh --verify   # 只做环境与脚本自检，不复制
#   bash install.sh --force    # 已存在时覆盖（会先备份旧目录）
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_ROOT="${WORKBUDDY_HOME:-$HOME/.workbuddy}/skills"
DEST_DIR="$DEST_ROOT/WECHAT-picture-design"
MODE="install"

for arg in "$@"; do
  case "$arg" in
    --verify) MODE="verify" ;;
    --force)  MODE="force" ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "未知参数：$arg"; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
ok()  { printf '  ✅ %s\n' "$*"; }
warn(){ printf '  ⚠️  %s\n' "$*"; }
bad() { printf '  ❌ %s\n' "$*"; }

check_env() {
  say "检查运行环境 …"
  if ! command -v python3 >/dev/null 2>&1; then
    bad "未找到 python3（需 3.9+）"; exit 1
  fi
  local pyv
  pyv="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
  ok "python3 $pyv"

  if python3 -c 'import PIL' >/dev/null 2>&1; then
    ok "Pillow $(python3 -c 'import PIL;print(PIL.__version__)')"
  else
    bad "缺少 Pillow，请执行：python3 -m pip install --user pillow"
    exit 1
  fi

  if command -v ego-browser >/dev/null 2>&1; then
    ok "ego-browser 可用（canvas-design 渲染）"
  else
    warn "未检测到 ego-browser：将回退 Pillow 版式（compose --engine canvas 会失败后自动回退）"
  fi

  # 字体：canvas 渲染与折行测量都依赖中文黑体
  if [ -f "/System/Library/Fonts/Hiragino Sans GB.ttc" ] || [ -f "/System/Library/Fonts/PingFang.ttc" ]; then
    ok "中文字体可用"
  else
    warn "未找到 Hiragino/PingFang，中文折行测量可能不准"
  fi

  # 凭证
  local appid
  appid="$(python3 -c 'import json,os;print(json.load(open(os.path.join("'"$SRC_DIR"'","scripts","config.json")))["wechat"].get("appid",""))' 2>/dev/null || true)"
  if [ -n "$appid" ]; then ok "公众号凭证已配置"; else warn "公众号 appid/secret 未配置：draft 阶段只输出发布包"; fi
}

verify_scripts() {
  say "校验脚本 …"
  python3 -m py_compile "$SRC_DIR"/scripts/*.py
  ok "全部脚本编译通过"
  python3 "$SRC_DIR/scripts/run.py" --help >/dev/null
  ok "编排入口可执行"
  python3 - <<PY
import json, os, sys
sys.path.insert(0, os.path.join("$SRC_DIR", "scripts"))
import common, source_pool, spec_extract, textcheck, canvas_render, compose_images, check_compliance, push_draft
cfg = common.load_config()
need = ["redfox", "wechat", "platform", "text_policy", "industry", "defaults", "design"]
miss = [k for k in need if k not in cfg]
print("  ✅ 模块导入正常，配置完整" if not miss else "  ❌ 配置缺字段: %s" % miss)
_c, phils, _idx = canvas_render.resolve_philosophies()
print("  ✅ 设计哲学库：%d 套（%s）" % (len(phils), "、".join(x.get("name_zh") or x["id"] for x in phils)))
PY
}

case "$MODE" in
  verify)
    check_env
    verify_scripts
    say "自检完成。"
    ;;
  install|force)
    check_env
    mkdir -p "$DEST_ROOT"
    if [ -d "$DEST_DIR" ] && [ "$SRC_DIR" != "$DEST_DIR" ]; then
      if [ "$MODE" = "force" ]; then
        backup="$DEST_DIR.bak.$(date +%Y%m%d-%H%M%S)"
        mv "$DEST_DIR" "$backup"
        say "  · 已备份旧版本到 $backup"
      else
        bad "目标已存在：$DEST_DIR（如需覆盖请加 --force）"; exit 1
      fi
    fi
    if [ "$SRC_DIR" != "$DEST_DIR" ]; then
      mkdir -p "$DEST_DIR"
      rsync -a --exclude '__pycache__' --exclude '*.pyc' "$SRC_DIR"/ "$DEST_DIR"/
      ok "已安装到 $DEST_DIR"
    else
      ok "已在安装位置：$DEST_DIR"
    fi
    verify_scripts
    say ""
    say "安装完成。入口：python3 $DEST_DIR/scripts/run.py --help"
    say "在 WorkBuddy 中直接说「用 WECHAT-picture-design 做 N 篇贴图」即可调用。"
    ;;
esac

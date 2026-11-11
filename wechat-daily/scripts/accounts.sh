#!/usr/bin/env bash
# 多账号切换与串号体检
#
# 为什么需要这个脚本：
#   1. 切一个号要重设十几个环境变量，手工 export 错一个，就是把 A 号的品牌名
#      打进 B 号的封面。
#   2. 台账路径是 $WX_DAILY_OUT/00_选题台账.md —— 两个号共用目录，选题历史就
#      混成一份，A 号发过的题 B 号再也不敢发，扎堆检测也会把两号的量加一起。
#      这件事**完全静默**，所以需要 check 把它变成一条报错。
#
# 用法：
#   ./scripts/accounts.sh add <简称>              # 交互式录入
#   ./scripts/accounts.sh add <简称> --brand "xx" --out ~/wx/xx --vertical 职场 \
#        --space 发布-xx --author 笔名 --logo none ...   # --logo none = 封面上不印角标
#   eval "$(./scripts/accounts.sh use <简称>)"     # 切到该号（务必用 eval 包裹）
#   ./scripts/accounts.sh list                    # 列出所有号
#   ./scripts/accounts.sh check                   # 体检：查共用目录
#   ./scripts/accounts.sh show <简称>             # 看某个号的配置
#   ./scripts/accounts.sh rm <简称>               # 删掉（只删配置，不删产物）
#
# ⚠️ 第七步（ego-browser）**读不到任何 WX_***：它是另一个进程，既不继承环境变量
#    也不转发参数。所以 `use` 除了 export，还会顺带把本号产物目录写进
#    ~/.wx-ego-dir（发布模块靠它找配置）。但 space / author 必须由 Agent
#    **抄进 pub_jobs.json**——光 export 没用。见 references/publish-spec.md。
#
# 配置存在 ~/.wx-accounts/<简称>.env，一行一个 KEY=VALUE。
set -uo pipefail

ACC_DIR="${WX_ACCOUNTS_DIR:-$HOME/.wx-accounts}"

# 与 scripts/brand.py 的 PUBLISH_SPACE 兜底值保持一致。
# 留空不是「不占用」——空值会落回这个默认会话，两号都留空同样撞车。
DEFAULT_SPACE="公众号发布"

# 按号的变量。USE 会先把这些全部 unset 再 export，
# 否则从 A 切到 B 时，A 有而 B 没设的项会残留，造成跨号污染。
KEYS=(
  WX_BRAND WX_DAILY_OUT WX_VERTICAL WX_AUDIENCE
  WX_ACCENT WX_ACCENT_ALT WX_LOGO
  WX_GUIDELINES WX_THEMES WX_CTA
  WX_ARTICLES WX_SERIES WX_SERIES_RATIO WX_LEGACY_BRANDS
  WX_PUBLISH_SPACE WX_AUTHOR
)

err() { printf '%s\n' "错误：$*" >&2; exit 1; }

usage() {
  # 只打印文件头的注释块：跳过 shebang，遇到第一行非注释就停。
  # 原来写死 sed -n '2,30p'，头部注释一增减就会把代码也当帮助打出来。
  awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
  exit 0
}

valid_slug() {
  case "$1" in
    ""|*/*|*.*|*" "*) return 1 ;;
  esac
  return 0
}

env_file() { printf '%s/%s.env' "$ACC_DIR" "$1"; }

# 从 env 文件取某个 key 的值（没有就输出空）
# WX_LOGO 的「不显示 LOGO」取值（与 brand.py / bootstrap.py 的 NO_LOGO_TOKENS 保持一致）
is_no_logo() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    none|off|no|0|-|无|不显示|false) return 0 ;;
    *) return 1 ;;
  esac
}

get_val() {
  local f="$1" k="$2"
  [ -f "$f" ] || { printf ''; return; }
  sed -n "s/^${k}=//p" "$f" | head -1 | sed 's/^"//; s/"$//'
}

# 写一行 KEY="VALUE"（值里的双引号做转义）
write_kv() {
  local f="$1" k="$2" v="$3"
  v="${v//\"/\\\"}"
  printf '%s="%s"\n' "$k" "$v" >> "$f"
}

cmd_add() {
  local slug="${1:-}"
  shift || true
  valid_slug "$slug" || err "简称不合法：'${slug}'（不能含空格、斜杠、点）"
  [ -f "$(env_file "$slug")" ] && err "已存在：$(env_file "$slug")。要改就直接编辑该文件，或先 rm"

  local brand="" out="" vertical="" audience="" accent="#EE7800" alt="" logo=""
  local guidelines="" themes="" cta="" articles="" series="" ratio="" legacy=""
  local space="" author="" author_set=0

  while [ $# -gt 0 ]; do
    case "$1" in
      --brand) brand="${2:-}"; shift 2 ;;
      --out) out="${2:-}"; shift 2 ;;
      --vertical) vertical="${2:-}"; shift 2 ;;
      --audience) audience="${2:-}"; shift 2 ;;
      --accent) accent="${2:-}"; shift 2 ;;
      --accent-alt) alt="${2:-}"; shift 2 ;;
      --logo) logo="${2:-}"; shift 2 ;;
      --guidelines) guidelines="${2:-}"; shift 2 ;;
      --themes) themes="${2:-}"; shift 2 ;;
      --cta) cta="${2:-}"; shift 2 ;;
      --articles) articles="${2:-}"; shift 2 ;;
      --series) series="${2:-}"; shift 2 ;;
      --series-ratio) ratio="${2:-}"; shift 2 ;;
      --legacy) legacy="${2:-}"; shift 2 ;;
      --space) space="${2:-}"; shift 2 ;;
      --author) author="${2:-}"; author_set=1; shift 2 ;;
      *) err "未知参数：$1" ;;
    esac
  done

  # 缺必填项时才转交互。
  # 非终端输入（脚本调用 / 管道 / CI）绝不能 read —— 那会永久阻塞，
  # 所以这里先判断是不是真终端，不是就一次性报出缺哪些参数。
  # 读者画像不在这一问——Q14 会单独问，这里给空值不拦人。
  if [ -t 0 ] && [ "${WX_ACCOUNTS_NO_INPUT:-0}" != "1" ]; then
    if [ -z "$brand" ]; then printf '%s' "公众号名称（短名，≤12 字）："; read -r brand; fi
    if [ -z "$out" ]; then printf '%s' "产物目录（绝对路径，各号必须不同）："; read -r out; fi
    if [ -z "$vertical" ]; then printf '%s' "类目（如 职场/母婴/财经）："; read -r vertical; fi
    if [ -z "$articles" ]; then printf '%s' "每天发几条（正整数，必填）："; read -r articles; fi
  else
    local missing=""
    [ -n "$brand" ] || missing="$missing --brand"
    [ -n "$out" ] || missing="$missing --out"
    [ -n "$vertical" ] || missing="$missing --vertical"
    [ -n "$articles" ] || missing="$missing --articles"
    if [ -n "$missing" ]; then
      err "非交互模式缺少必填参数：${missing}
  示例：./scripts/accounts.sh add ${slug} --brand \"我的号\" --out ~/wx/mine --vertical 职场 --articles 3"
    fi
  fi

  [ -n "$brand" ] || err "公众号名称不能为空"
  [ -n "$out" ] || err "产物目录不能为空"
  [ -n "$vertical" ] || err "类目不能为空"
  case "$articles" in
    ''|*[!0-9]*) err "每天篇数必须是正整数，收到：'${articles}'" ;;
  esac
  [ "$articles" -ge 1 ] || err "每天篇数至少是 1"

  # 展开 ~ 并转绝对路径
  case "$out" in
    "~"*) out="$HOME${out#\~}" ;;
  esac
  case "$out" in
    /*) : ;;
    *) err "产物目录必须是绝对路径（或以 ~ 开头），收到：$out" ;;
  esac

  mkdir -p "$ACC_DIR" || err "建不了配置目录：$ACC_DIR"
  chmod 700 "$ACC_DIR" 2>/dev/null

  local f; f="$(env_file "$slug")"
  : > "$f"
  write_kv "$f" WX_BRAND "$brand"
  write_kv "$f" WX_DAILY_OUT "$out"
  write_kv "$f" WX_VERTICAL "$vertical"
  write_kv "$f" WX_AUDIENCE "$audience"
  write_kv "$f" WX_ACCENT "$accent"
  write_kv "$f" WX_ACCENT_ALT "$alt"
  write_kv "$f" WX_LOGO "$logo"
  write_kv "$f" WX_GUIDELINES "$guidelines"
  write_kv "$f" WX_THEMES "$themes"
  write_kv "$f" WX_CTA "$cta"
  write_kv "$f" WX_ARTICLES "$articles"
  write_kv "$f" WX_SERIES "$series"
  write_kv "$f" WX_SERIES_RATIO "$ratio"
  write_kv "$f" WX_LEGACY_BRANDS "$legacy"
  write_kv "$f" WX_PUBLISH_SPACE "$space"
  # 只在**给过** --author 时才写这一行：这个变量的空值有语义（有意不填作者），
  # 无条件写空串会让每个号都变成「不填作者」。
  if [ "$author_set" = 1 ]; then write_kv "$f" WX_AUTHOR "$author"; fi
  chmod 600 "$f" 2>/dev/null

  mkdir -p "$out" && printf '%s\n' "已建产物目录：$out"

  printf '\n%s\n' "已保存：$f"
  # 串号是当场就能查出来的，别等到攒了两个月才发现
  cmd_check_quiet "$slug" "$out" || true
}

# 单号写入时的即时查重：只和已存在的其他号比
cmd_check_quiet() {
  local slug="$1" out="$2" other o_out
  for other in $(list_slugs); do
    [ "$other" = "$slug" ] && continue
    o_out="$(get_val "$(env_file "$other")" WX_DAILY_OUT)"
    if [ -n "$o_out" ] && [ "$o_out" = "$out" ]; then
      printf '\n%s\n' "✗ 串号：'$slug' 与 '$other' 共用 $out"
      printf '%s\n' "  两个号的选题台账会混成一份，去重与扎堆检测都会失真，且不会报错。"
      printf '%s\n' "  修法：给 '$slug' 换一个目录，例如 ${out}-${slug}"
      return 1
    fi
  done
}

list_slugs() {
  [ -d "$ACC_DIR" ] || return 0
  local f
  for f in "$ACC_DIR"/*.env; do
    [ -e "$f" ] || continue
    basename "$f" .env
  done
}

cmd_use() {
  local slug="${1:-}"
  valid_slug "$slug" || err "用法：accounts.sh use <简称>"
  local f; f="$(env_file "$slug")"
  [ -f "$f" ] || err "没有这个号：$slug（先 add）"

  # 先全部清空，再按需赋值——否则会残留上一个号的值
  local k
  for k in "${KEYS[@]}"; do printf 'unset %s\n' "$k"; done

  # 只导出有值的项。空值一旦 export 出去，下游 Path("") 会变成当前目录，
  # 主题词表、输出目录就会静默指到错误位置。
  # WX_AUTHOR 是唯一「空值也要导出」的变量：它留空＝有意不填作者（Q28 选项 3）。
  # 其余变量的空值一律跳过，否则下游 Path("") 会变成当前目录。
  local line val
  while IFS= read -r line; do
    case "$line" in
      ''|'#'*) continue ;;
    esac
    val="${line#*=}"
    val="${val#\"}"; val="${val%\"}"
    if [ -z "$val" ]; then
      # 只有 WX_AUTHOR 的空值有语义，其余照旧跳过
      case "$line" in WX_AUTHOR=*) printf 'export WX_AUTHOR=""\n' ;; esac
      continue
    fi
    printf 'export %s\n' "$line"
  done < "$f"

  printf 'export WX_ACCOUNT="%s"\n' "$slug"

  # 同步发布指针：第七步（ego-browser）读不到任何 WX_*，只能靠 ~/.wx-ego-dir
  # 找到本号的配置目录。不同步的后果是「切了号，稿子却存进上一个号」，且不报错。
  local _out
  _out="$(get_val "$f" WX_DAILY_OUT)"
  if [ -n "$_out" ]; then
    printf "echo '%s' > \"\$HOME/.wx-ego-dir\"\n" "$_out"
  fi
}

cmd_list() {
  local any=0 slug f
  printf '%-12s %-14s %-10s %s\n' "简称" "类目" "篇数/专栏" "产物目录"
  printf '%s\n' "------------------------------------------------------------------------"
  for slug in $(list_slugs); do
    any=1; f="$(env_file "$slug")"
    local v a s
    v="$(get_val "$f" WX_VERTICAL)"; a="$(get_val "$f" WX_ARTICLES)"; s="$(get_val "$f" WX_SERIES)"
    [ -n "$s" ] || s="自动"
    printf '%-12s %-14s %-10s %s\n' "$slug" "${v:-—}" "${a:-未设}/${s}" "$(get_val "$f" WX_DAILY_OUT)"
  done
  [ "$any" = 1 ] || printf '%s\n' "（还没有配置任何号）"
}

cmd_show() {
  local slug="${1:-}"
  valid_slug "$slug" || err "用法：accounts.sh show <简称>"
  local f; f="$(env_file "$slug")"
  [ -f "$f" ] || err "没有这个号：$slug"
  printf '%s\n' "== $slug =="
  cat "$f"
}

cmd_check() {
  local fail=0 warn=0 slug other f o_out
  local -a slugs outs
  for slug in $(list_slugs); do
    f="$(env_file "$slug")"
    o_out="$(get_val "$f" WX_DAILY_OUT)"
    slugs+=("$slug"); outs+=("$o_out")

    # 单个号的自身完整性
    [ -n "$o_out" ] || { printf '%s\n' "✗ '$slug' 没设产物目录"; fail=1; }
    [ -n "$(get_val "$f" WX_ARTICLES)" ] || { printf '%s\n' "✗ '$slug' 没填每日篇数（WX_ARTICLES）"; fail=1; }
    local logo; logo="$(get_val "$f" WX_LOGO)"
    # WX_LOGO=none 表示「有意不显示角标」（onboarding Q8b 选项 3），
    # 不是路径写错——不能按「文件不存在」判红。
    if [ -n "$logo" ] && ! is_no_logo "$logo" && [ ! -f "$logo" ]; then
      printf '%s\n' "✗ '$slug' 的 LOGO 不存在：$logo"; fail=1
    fi
  done

  # 两两比产物目录：这是本脚本存在的理由
  local i j
  for ((i = 0; i < ${#slugs[@]}; i++)); do
    for ((j = i + 1; j < ${#slugs[@]}; j++)); do
      if [ -n "${outs[$i]}" ] && [ "${outs[$i]}" = "${outs[$j]}" ]; then
        printf '%s\n' "✗ 串号：'${slugs[$i]}' 与 '${slugs[$j]}' 共用 ${outs[$i]}"
        printf '%s\n' "  两个号的选题台账会混成一份，去重与扎堆检测都会失真，且不会报错。"
        printf '%s\n' "  修法：给其中一个换目录，例如 ${outs[$i]}-${slugs[$j]}"
        fail=1
      fi
    done
  done

  # LOGO 复用（同一份 LOGO 出现在两个号上，通常是把别人的素材沿用过来了）
  local li lj
  for ((i = 0; i < ${#slugs[@]}; i++)); do
    li="$(get_val "$(env_file "${slugs[$i]}")" WX_LOGO)"
    [ -n "$li" ] || continue
    for ((j = i + 1; j < ${#slugs[@]}; j++)); do
      lj="$(get_val "$(env_file "${slugs[$j]}")" WX_LOGO)"
      [ -n "$lj" ] || continue
      # 两个号都选「不显示」不算复用同一份素材
      if is_no_logo "$li" || is_no_logo "$lj"; then continue; fi
      if [ "$li" = "$lj" ]; then
        printf '%s\n' "⚠️  '${slugs[$i]}' 与 '${slugs[$j]}' 用的是同一份 LOGO：$li"
        printf '%s\n' "   如果这是两个不同的号，封面角标会一模一样。"
      fi
    done
  done

  # 浏览器会话撞车：两个号共用一个会话，后登录的会把前一个的 cookie 顶掉，
  # 下次跑发布表现为「莫名其妙未登录」，而且不会有任何报错。
  # 注意留空也算共用——空值落回 DEFAULT_SPACE，两号都留空就都挤在默认会话里。
  local sp_i sp_j
  for ((i = 0; i < ${#slugs[@]}; i++)); do
    sp_i="$(get_val "$(env_file "${slugs[$i]}")" WX_PUBLISH_SPACE)"
    [ -n "$sp_i" ] || sp_i="$DEFAULT_SPACE"
    for ((j = i + 1; j < ${#slugs[@]}; j++)); do
      sp_j="$(get_val "$(env_file "${slugs[$j]}")" WX_PUBLISH_SPACE)"
      [ -n "$sp_j" ] || sp_j="$DEFAULT_SPACE"
      if [ "$sp_i" = "$sp_j" ]; then
        printf '%s\n' "⚠️  '${slugs[$i]}' 与 '${slugs[$j]}' 共用同一个浏览器会话：$sp_i"
        printf '%s\n' "   后登录的号会把前一个的登录态顶掉，表现是「莫名未登录」，不会报错。"
        printf '%s\n' "   修法：各自设不同的会话名，例如 发布-${slugs[$i]} / 发布-${slugs[$j]}"
        warn=1
      fi
    done
  done

  if [ "$fail" = 0 ]; then
    if [ "$warn" = 1 ]; then
      printf '%s\n' "✓ 没有串号、必填项齐全（但有上面的警告要处理，否则多号会互相顶号）"
    else
      printf '%s\n' "✓ 体检通过：没有串号、会话不撞车、必填项齐全"
    fi
  fi
  return "$fail"
}

cmd_rm() {
  local slug="${1:-}"
  valid_slug "$slug" || err "用法：accounts.sh rm <简称>"
  local f; f="$(env_file "$slug")"
  [ -f "$f" ] || err "没有这个号：$slug"
  printf '%s\n' "将删除配置：$f"
  printf '%s\n' "（产物目录不会动：$(get_val "$f" WX_DAILY_OUT)）"
  printf '%s' "确认？输入 yes："
  local ans; read -r ans
  [ "$ans" = "yes" ] || { printf '%s\n' "已取消"; exit 0; }
  rm -f "$f"
  printf '%s\n' "已删除"
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    add) cmd_add "$@" ;;
    use) cmd_use "$@" ;;
    list|ls) cmd_list ;;
    show) cmd_show "$@" ;;
    check) cmd_check ;;
    rm|delete) cmd_rm "$@" ;;
    -h|--help|help|"") usage ;;
    *) err "未知子命令：$sub（可用：add / use / list / show / check / rm）" ;;
  esac
}

main "$@"

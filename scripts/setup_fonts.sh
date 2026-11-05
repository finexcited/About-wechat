#!/usr/bin/env bash
# 恢复 Noto Sans SC 可变字体到 assets/fonts/
#
# **字体随包提供，正常安装不需要跑这个脚本。**
# 17MB 的 NotoSansSC-VF.ttf 已入库（SIL OFL 1.1，许可原文见 assets/fonts/OFL.txt），
# 解压/克隆即有。这个脚本只在两种情况下用得上：
#
#   ① 字体被误删（清理缓存、换机器只拷了部分目录、误执行了 rm）
#   ② 想换成另一款**可变**字体
#
# 关于 ②：必须保留 Weight 轴。全部绘图脚本都走
#   ImageFont.truetype(path, size).set_variation_by_axes([weight])
# 静态 OTF（如思源黑体的 SourceHanSansCN-*.otf 分字重版本）没有轴，
# 调用会抛 OSError 而被 except 吞掉——**所有字重静默退化成同一个**，
# 封面 54/36/31/29/22 的字号分级看起来还在，粗细层次全没了。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$DIR/assets/fonts/NotoSansSC-VF.ttf"
mkdir -p "$(dirname "$OUT")"

if [ -f "$OUT" ]; then
  echo "字体已存在：$OUT"
  echo "（随包提供，无需下载。若怀疑文件损坏，先删除它再重跑本脚本）"
  exit 0
fi

URLS=(
  "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf"
  "https://cdn.jsdelivr.net/gh/notofonts/noto-cjk@main/Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf"
  "https://gitee.com/mirrors/noto-cjk/raw/main/Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf"
)

# 注意：变量后面紧跟中文标点时必须写成 ${VAR}。
# 部分 bash 会把这个全角字符吃进变量名（$OUT（ → 变量名 "OUT（"），
# 配合 set -u 就直接报 unbound variable，而且发生在文件已下载成功之后。
for u in "${URLS[@]}"; do
  echo "尝试下载：${u}"
  if curl -fL --retry 2 --connect-timeout 15 --max-time 900 -o "${OUT}.tmp" "${u}"; then
    SIZE=$(wc -c < "${OUT}.tmp" | tr -d ' ')
    if [ "$SIZE" -gt 5000000 ]; then
      mv "${OUT}.tmp" "${OUT}"
      echo "完成：${OUT}（$((SIZE / 1024 / 1024)) MB）"
      exit 0
    fi
    echo "文件过小（${SIZE} 字节），换下一个源"
  fi
  rm -f "${OUT}.tmp"
done

cat <<'EOF'
下载失败。字体本应随包提供，先试这两条恢复路径（都不需要联网）：

  1. 仓库/压缩包里应该有 assets/fonts/NotoSansSC-VF.ttf
     git 仓库：  git checkout -- assets/fonts/NotoSansSC-VF.ttf
     压缩包：    重新解压，把 assets/fonts/ 整个拷回来

  2. 都拿不到再手工下载（Noto Sans SC 可变字体，OFL 协议，免费商用）：
     https://github.com/notofonts/noto-cjk/tree/main/Sans/Variable/TTF/Subset
     下载后重命名为：assets/fonts/NotoSansSC-VF.ttf
     ⚠ 必须是**可变字体（Variable / VF）**，分字重的 static OTF 不能用：
       静态字体没有 Weight 轴，set_variation_by_axes 会失败并被静默吞掉，
       结果是所有字重变成同一个粗细，而且一点错都不报。
EOF
exit 1

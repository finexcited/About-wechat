# 微信公众平台编辑器 HTML 排版规范（官方开发规范摘要）

> 来源：《微信公众平台编辑器插件开发规范》（用户提供，2026-09-21）。
> 公众号 HTML 排版（make_article_html.py 路线 C）必须**逐条遵循**本规范。
> 官方校验工具：https://github.com/wechatjs/verify-article-structure-spec（CLI 基于 puppeteer，`npm run check ./article.html`，退出码 0=通过/1=违规/2=异常）。

## 一、CSS 属性禁令（硬性）

| 属性 | 禁止用法 | 原因 |
|---|---|---|
| `opacity` | img 设 opacity:0 再叠带背景图的 SVG | 发布后无法在后台修改图片 |
| `caret-color` | 透明（如 rgba(0,0,0,0)） | 光标不可见，无法编辑 |
| `line-height` | 小于字号且含多行文字 | 文字重叠（图片无缝拼接、单行文字豁免） |
| `width` 固定值 | 如 `width: 586px` / `width: 500px` | 破坏响应式：宽屏留白左对齐、窄屏溢出或比例不一致 |
| `height: 0` | 含文字的容器 | 编辑器有最小高度兜底，移动端内容完全不可见 |
| `height` 固定小值 + overflow | 内容超出容器被裁剪 | 超出部分不可见（可滚动容器豁免） |
| `text-align: start/end` | 任何场景 | 各终端兼容性不一致，文字对齐混乱 |
| SVG animate `begin` | 仅 `touchstart` | PC 端鼠标点击无法触发动画；须同时设 touchstart+click |
| `<pre>` 包裹正文 | 普通段落文本 | white-space:pre 不换行，窄屏水平截断；用 section/p 替代 |

**width 例外**：有意固定宽度（横向滚动等）加 `data-ignore-width` 属性豁免（仅豁免 width 检测，勿滥用）。

## 二、文章结构规则

1. **嵌套层级 ≤10 层**：同标签名、同内联样式、仅单子节点的连续嵌套链不超 10 层，超出会被编辑器自动删除冗余层级
2. **`<span leaf>` 只装行内元素**：内部严禁出现 section/div/p 等块级元素
3. **`<section nodeleaf>` 只装指定组件或 img**：不能随意塞块级元素

## 三、字体规范

- **不建议设置任何 font-family**。平台默认字体栈已针对创作端与 iOS/安卓阅读端优化：
  `font-family: "mp-quote", PingFang SC, system-ui, -apple-system, BlinkMacSystemFont, Helvetica Neue, Hiragino Sans GB, Microsoft YaHei UI, Microsoft YaHei, Arial, sans-serif;`
- 自定义字体在不同端显示不一致

## 四、Dark Mode 规则

1. **对比度**：文本与背景对比度过低或过高会被算法强制调整；用对比度适中的配色
2. **文字背景禁渐变**（除非加 `data-ignore-dm="text-bg-gradient"` 豁免）：渐变背景会被转成纯色，格子/纹理背景会消失；**纯装饰渐变（无文字）不受影响**
3. **背景容器 + 多文本节点**：公共背景写在外层容器，不要逐个文本节点重复写背景样式
4. **禁止绝对定位破坏视觉顺序**：Dark Mode 算法深度优先遍历，绝对定位/变形导致文本脱离背景嵌套关系会看不清
5. **不用图片承载纯文本**：算法不识别图片内文字；透明底图片含黑色系颜色需与 Dark Mode 底色 #191919 保证对比度
6. **SVG**：算法不处理 SVG；公式类 SVG 指定 `stroke="currentColor" fill="currentColor"` 或加底色
7. **`data-no-dark`**：仅当前节点跳过 Dark Mode 转换（后代有内联样式仍会转换）
8. **禁用 `!important`**：任何场景都不用，会使平台公共样式失效
9. **`data-ignore-dm`**：值填要忽略的规则（low-contrast / text-bg-gradient，空格分隔）

## 五、本技能 HTML 排版的合规映射（生成时必须遵守）

| 本技能现有做法 | 规范要求 | 执行 |
|---|---|---|
| `<style>` 标签集中样式 + class | 公众号编辑器粘贴时**内联样式才可靠** | 输出改用**全部内联 style**，不用 class/`<style>` |
| `font-family: "Noto Sans SC", ...` | 不建议设置 font-family | **删除 font-family**，用平台默认字体栈 |
| `.page max-width: 677px` 固定容器 | 固定宽度违规 | 改 `width: 100%` / 不设 width，内边距自适应 |
| 图片 `width: 100%` + base64 | 图片加 `data-w` 属性（原始像素宽） | 每个 `<img>` 加 `data-w="原始宽"` |
| `mark.hl` 荧光底 | 常规背景色可用，避免渐变文字背景 | 保持纯色 rgba，不用渐变 |
| SVG 线性图标 stroke 硬编码色 | SVG 不会被 Dark Mode 处理 | 图标用品牌橙绿即可；或 currentColor |
| 序号徽章/卡片圆角 | 无限制 | 保持 |
| 嵌套层级 | ≤10 层 | 扁平结构，section ≤3 层嵌套 |
| `text-align` | 只用 left/center/right，禁 start/end | 遵守 |
| `!important` | 禁用 | 不使用 |

**生成流程**：HTML 产出后可运行官方 CLI 校验（需 node + puppeteer）：
```bash
git clone https://github.com/wechatjs/verify-article-structure-spec.git
cd verify-article-structure-spec/cli && npm install
npm run check ./推文.html
```
无环境时人工按本清单逐条自查。

## 六、HTML 排版合规自查清单（每次产出必查）

- [ ] 无 `<style>` 标签/class 选择器，全部内联 style
- [ ] 无 font-family 设置
- [ ] 无固定 width/height（图片 width:100% 或按比例除外）
- [ ] 所有 `<img>` 带 `data-w`（原始像素宽）与 alt
- [ ] line-height 均 ≥ 字号（建议 1.75em 以上）
- [ ] text-align 只用 left/center/right
- [ ] 无 `!important`、无 `position: absolute` 文本、无 `<pre>`、无 opacity:0、无透明 caret-color
- [ ] 文字背景无渐变（纯装饰无文字渐变可保留）
- [ ] 嵌套 ≤10 层，span 内无块级元素
- [ ] 正文使用 `<section>`/`<p>` 段落结构

## 七、line-height 实测校验陷阱（必读，血泪经验）

官方 CLI 的 line-height 判定**不是读 CSS 值**，而是用 `Range.getClientRects()` 实测：

```
avgLineHeight = range.getBoundingClientRect().height / getClientRects().length
Rule B 违规 = lineCount≥2 且 avgLineHeight < 0.95 × fontSize
```

**陷阱**：当段落内含**行内高亮元素**（`<strong>` / 带 `background-color` 的 span）时，
Chrome 会把一行拆成**多个碎片矩形**，`getClientRects().length` 被放大 → `avgLineHeight` 虚假降低 →
明明 line-height 充裕（如 30px / 16px ≈ 1.9 倍），却被误报"行高小于字体大小，文字重叠"。

典型误报（font 14/16/15，lh 26/30/30，真实行数 1–2，但被拆成 4 个碎片矩形）：
`avg = contentHeight/4` ≈ 5–13 < 阈值 13–15 → 误报。

**规避手法（已写入 make_article_html.py）**：所有文本块的内容整体包进一个 `<span>`，
块级 `<p>`/`<h1>` **不直接包含文本节点**。校验器 `collectLineHeightFallback` 有
`hasDirectText` 判定——块级元素无直接文本子节点即跳过测量，彻底规避碎片误报。
视觉渲染与直接写在 `<p>` 上**完全一致**（span 继承/声明同款样式）。

> ⚠️ 代价：此举会让校验器对 span 包装后的段落**完全不做行高测量**，
> 因此模板自身必须保证 line-height ≥ 1.75em（本技能已统一用 26–36px），
> 切勿借机把行高压到危险值。如未来需要校验器仍能保护行高，
> 可改用在 `<p>` 上直接声明样式、但避免段落内出现跨行的行内高亮元素。

**生成后必须经官方 CLI 验证**：`npm run check ./推文.html` 须返回 `isValid：true`。

## 八、微信粘贴注入非标准 text-align（必读，实战踩坑）

官方 CLI 即使 `isValid：true`，把 HTML 粘贴进公众号编辑器后仍可能报**「文字对齐异常：文本对齐属性使用了非标准值（参考 #2.6 text-align）」**。

**原因**：本模板源文件只声明 `text-align:center`（标准），但**没有显式对齐的块**（尤其「导读」这类带边框的卡片容器）在微信粘贴归一化时，会被编辑器**自动注入非标准对齐值**（如 `start` / `justify`），从而触发告警。实测告警定位在「导读」卡片。

**规避（已写入 make_article_html.py）**：所有文本块**显式声明标准对齐值**——正文/标题/卡片/来源用 `text-align:left`，结尾关注块用 `text-align:center`；`P()/H1()` 辅助函数新增 `align` 参数默认 `left`。容器与内层 span 双重声明，微信不再注入。

**自检兜底**：`self_check()` 现在拦截任何非 `left/center/right` 的 text-align 值，防止回归。

> 注：PNG 长图（路线 B）设计可比 HTML 更丰富，不在此对齐约束内；HTML 版以「整齐美观」为首要，丰富度通过卡片样式/插画/CTA 文案体现，不与对齐规范冲突。


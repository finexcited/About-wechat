---
name: WECHAT-picture-design
description: 面向微信公众号「贴图」（图片消息 newspic）的内容生产技能：多渠道采集爆款素材 → 按公众号贴图规范改写短文案 → 重绘配图并嵌入 LOGO → 六项自检 → 写入公众号草稿箱。触发词：用 WECHAT-picture-design 做 N 篇贴图、按爆款做公众号贴图草稿、抓爆款素材改成公众号贴图。
version: 2.3.0
date: 2026-11-09
display_name: "公众号贴图生产（WECHAT-picture-design）"
description_zh: "按关键词采集爆款素材，用 canvas-design 设计哲学生成公众号贴图草稿"
visibility: "private"
---

# SKILL：WECHAT-picture-design（公众号贴图版）

## 一、技能描述（五要素）

| 要素 | 内容 |
|---|---|
| 技能名称 | WECHAT-picture-design |
| 用途 | 按关键词与篇数采集爆款素材，改写为公众号贴图短文案，重绘配图并嵌入用户 LOGO，通过合规自检后写入微信公众号草稿箱（`article_type=newspic`） |
| 输入 | ① 关键词；② 篇数 N（1–10）；③ 用户 LOGO（透明背景 PNG，≥512×512）；④ Redfox 凭证；⑤ 公众号 appid / secret（可选，缺失则只落盘发布包） |
| 输出 | N 篇公众号贴图草稿：标题（≤32 字）+ 正文（200–300 字）+ 3–5 个话题 + 按序配图（已嵌 LOGO，3:4） |
| 要求 | 不抄袭源文；配图 AI 重绘、不裁切源图；每张图带 LOGO；严格遵守公众号贴图规范；成稿不得出现任何其他平台专属表述 |

## 一点五、硬性要求（不可协商）

1. **严禁抄袭**：抓到的参考图只用于风格借鉴（版面结构、色彩关系、图文比例），不得复制画面内容、不得裁切挪用。生成后自动比对：文案走 n-gram（<15%），图像走 dHash（汉明距离 ≥12），任一不过即标警并要求重绘。
2. **每页版式必须不同**：封面两套、内页三套，按篇轮换；`compose-manifest.json` 记录每页 `variant`，`design-report.md` 列出变化点。禁止整组图套同一模板。
3. **内容必须贴人群与行业**：先出行业/受众分析（`data/audience-brief.md`），再据此定字号、信息密度、配色与配图语气；不脱离目标人群的阅读场景。
4. **成稿必须过 humanizer-zh**：改写稿要经人化处理才能进 `verify-text`，否则空话与套话会原样发出去。节奏是 `改写 → deai → humanizer-zh → verify-text`，顺序不可颠倒。

## 一点八、首次安装必做：初始化问卷

第一次用这个技能，先跑 12 题问卷，把类目、风格、人群、篇幅、素材来源定下来：

```bash
python3 scripts/setup_wizard.py --dry-run   # 预览会改哪些段落
python3 scripts/setup_wizard.py             # 逐题作答，写入 config.json（备份 config.json.bak）
```

题库、选项含义、默认值与「答案→字段」对照见 `docs/setup-questionnaire.md`；
没有 REDFOX 也能用，第 11 题给了 RSS / 热榜 / 手工 CSV / 浏览器剪藏四条替代路径。

## 二、运行前检查清单

`run.py init` 自动校验，任一不通过即退出（码 3）：

- [ ] Redfox 凭证有效，公众号渠道可返回字段完整的样本
- [ ] LOGO 就位、≥512×512、带透明通道（仅 PNG/WebP/JPG；SVG 需先导出）
- [ ] 关键词非空，N 为 1–10 整数
- [ ] 素材不足 N 篇时的策略已明确：`--relax ask`（默认暂停）/ `allow`（接受缩量）/ `deny`（终止）
- [ ] 需要真正入草稿箱时，`config.json` 的 `wechat.appid/secret` 已配置，且出口 IP 在公众号白名单内

## 三、平台规范（硬规则，来自官方文档）

来源：[微信 draft/add 文档](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html)，`article_type = newspic`。

| 项 | 规则 | 本技能执行值 |
|---|---|---|
| 图片张数 | 1–20 张，首张即封面 | 默认 6 张（可 `--images-per-note` 调，4–9） |
| 图片尺寸 | 单图 ≤10MB；JPG/PNG | 1080×1440（3:4 竖版） |
| 标题 | ≤32 字 | 目标 ≤20 字 |
| 正文 | 纯文本，≤20000 字符 | 目标 200–300 字 |
| 话题 | 无独立字段，正文内 `#话题名#` | 3–5 个 |
| 封面裁剪 | `1_1` / `16_9` / `2.35_1` | 默认 `1_1` |
| 图片素材 | 必须为永久素材 `image_media_id` | `material/add_material` 逐张上传 |

> 贴图不能用 `media/uploadimg` 返回的 URL 当图片素材（那是图文消息正文图用的），用错会报 `invalid media_id`。

## 四、工作流程

### 阶段 0：参数确认与连通性测试 — `init` 前半段
校验三项必填输入；向 Redfox 发 1 条公众号检索，确认凭证、可达性、字段完整（正文/互动/时间/链接）。失败即停（码 4），不在无数据状态生成内容。

### 阶段 1：多渠道素材采集 — `init` 后半段

两条通道，`--source auto` 自动判定（有 REDFOX Key 走 Redfox，否则走 RSS）：

| 通道 | 命令 | 说明 |
|---|---|---|
| REDFOX | `init --source redfox` | 三渠道（公众号/小红书/热点）+ 互动数据 + 封面 |
| RSS | `init --source rss` | 读 `channels.rss.feeds`，关键词过滤 + 去重；无 Key 也能跑，见 `docs/setup-questionnaire.md` Q11 |
三渠道并行（`config.channels` 可开关）：

| 渠道 | 用途 | 说明 |
|---|---|---|
| `gzh` 微信公众号 | 选题与结构参考 | Redfox 无贴图专用检索，用 `gzh/search/hotArticleNew` 取高互动图文近似 |
| `xhs` 小红书贴图 | 图文形态与版式参考 | `xhs/search/search` + `noteDetail` 判定图文/视频并取全文 |
| `hot` 全网热点 | 选题信号 | `hotKeyword/list`（近 7 天），只有标题与热度，无正文 |

处理链：合并 → 四层去重（ID／URL／标题近重复／正文前缀近重复）→ 相关性门槛（先要求命中关键词主词，不足再放宽）→ 打分（阅读/点赞/收藏/分享/评论归一加权 × 渠道权重，图文形态加分）→ **贴图形态优先**排序 → 取 N 篇。

正文过短（<80 字）或判定为视频的条目剔除；热点信号只进摘要，不参与改写。

### 阶段 1.5：参考图登记 — `init` 收尾
把每条素材的封面存为参考图（`data/covers/`），并在 `data/refs.json` 登记：渠道、标题、链接、本地路径、可用性。
素材渠道只提供封面，因此参考的是「封面级」构图与色调，不是完整贴图序列；无封面则记为「自主设计」。

### 阶段 2：规范基线 — `spec`
- **硬规范取平台规则**（见第三节），不从素材反推：素材来自三种形态，不能拿来定公众号规则；
- 素材只作参考：封面色彩倾向、常见比例、正文字数中位数，写入 `spec-extracted.md` 第 3 节；
- 色系：默认品牌稳重蓝 + LOGO 主色；仅当暖色样本 ≥4 个且占比 ≥60% 才切换，并记录理由（样本不足不切，避免小样本误判）。

### 阶段 2.5：行业与受众分析 — `brief` 附带生成
`brief` 会写出 `data/audience-brief.md` 初稿（行业调性、人群特征、使用场景），由 Agent 补三条结论（决定版式与配色的判断）。该文件会进入 `design-report.md` 第 1 节。

### 阶段 3：文案改写 — `brief` →（Agent 改写）→ `verify-text`
- `brief` 生成素材包：源文、字数目标、话题数、改写禁区、JSON 交付结构；
- 改写原则：保留信息点与可验证事实，变换句式、视角、段落组织；禁止逐句近义替换与搬运原句骨架；
- 硬性关卡：正文 200–300 字、标题 8–32 字（建议 ≤20）、话题 3–5 个、与所有源文连续 5–8 字重合 **<15%**；未过退回重写。

#### 3.4 去 AI 味 — `deai` →（**humanizer-zh**）→ `verify-text`

改写完成不等于能发。模型写的短文案有三种典型痕迹：空泛铺垫（「在这个…的时代」）、套话对偶（「不是…而是」）、名词化堆叠（「赋能/抓手/闭环」）。读者一眼能认出来。

**流程（强制，不可跳过）**：

1. `run.py deai --run <RUN_DIR>` → 生成 `data/deai-todo.md`，逐篇列出正文、内页短句与该篇 AI 味命中；
2. 逐篇调用 **humanizer-zh** 技能处理（`Skill(skill="humanizer-zh")`，把待处理文本交给它）；
3. 结果写回 `copy.json` 的 `body` 与 `pages[].body`；
4. 再跑 `verify-text` 复核字数与重合率（改了字，这两项都可能变）。

**四条不可越界**（既是 humanizer-zh 的约束，也是本技能的约束）：

| 允许 | 禁止 |
|---|---|
| 删空话、拆长句、去套话对偶、名词化改动词 | 新增事实、数字、人名、日期、出处 |
| 调整语序与段落切分 | 把「可能」写成「一定」、把「计划」写成「已完成」 |
| 保留第一人称与作者口吻 | 删掉真实的判断、限定、归因 |
| 顺一遍内页短句 | 改标题与话题（会触发字数与重合率复检） |

**体检口径**（`verify-text` 自动给出）：加权 AI 味密度（每千字）。强信号词 1 分、弱信号 0.35 分、句式 0.6–1 分。`<4` 正常，`4–8` 偏书面，`≥8` 判「高」并提示回炉。词表是线索不是黑名单，命中不等于要删。

### 阶段 4：配图重绘与合成 — `prompts` →（生图）→ `compose`

#### 4.0 设计引擎：设计哲学库（每篇换一整套视觉语言）

不是「一个模板换颜色」，而是**每篇抽一套完整的设计语言**：配色、栏网格、字号节奏、图像处理、版式原型全部一起换。

| 文件 | 作用 |
|---|---|
| `assets/design-philosophies/index.json` | 哲学清单与轮抽步长（`order` / `stride`） |
| `assets/design-philosophies/*.json` | 每套哲学一个文件：`palette / grid / type / rules / photo / layout / photo_style / claim` |
| `scripts/philosophy.py` | 加载与分配（`compose` 与 `prompts` 共用，保证同一篇两阶段拿到同一套） |
| `scripts/canvas_render.py` | 版式原型实现：拼 HTML/CSS → ego-browser 1080×1440 截图 → 叠 LOGO |
| `assets/design-tokens.json` | 旧单套令牌，仅在哲学库缺失或 `enabled=false` 时兜底 |

**分配规则**：第 i 篇取 `order[((i-1) * stride) % n]`。`stride` 与哲学数互质时，前 n 篇恰好每套出现一次，且**相邻两篇必不同**；同一篇的封面与内页原型还会随篇号整体偏移，所以第 6 篇不会和第 1 篇撞脸。分配结果写入 `data/philosophy-plan.json`，可复现。

**出厂五套**：

| id | 名称 | 一句话主张 | 视觉特征 |
|---|---|---|---|
| `margin-notes` | 页边批注 | 把每页当作深夜批注过的笔记 | 纸白＋墨蓝＋橙，发丝线、描边巨型页码 |
| `swiss-grid` | 瑞士网格 | 删掉一切不承担功能的元素 | 纯白＋黑＋信号红，巨量负空间，无纹理 |
| `risograph` | 丝网套印 | 像一张套色没对准的丝网印 | 牛皮纸＋荧光粉，双色套印、粗网点、图窗错位 |
| `kinfolk` | 留白静物 | 一页只说一件事 | 米灰＋柔褐，超大字距、细体、近乎空的版面 |
| `brutalist` | 粗野排版 | 字足够大，颜色足够脏 | 酸性黄压黑，黑底黄字标题块、高反差黑白图 |

**十一个版式原型**（每套哲学从中挑 2 封面 + 3 内页，组合互不重复）：

| 原型 | 用于 | 版面逻辑 |
|---|---|---|
| `cover-hero-bleed` | 封面 | 巨型标题压左栏，图片自底部全出血，色条切分 |
| `cover-photo-top` | 封面 | 图片占上半幅，标题落到纸面下半 |
| `cover-split-diagonal` | 封面 | 图片贴右满高、左缘斜切，标题独占左半 |
| `cover-mosaic` | 封面 | 一大一小两扇错位图窗＋色块，层次最多 |
| `cover-stacked-strip` | 封面 | 细长图带置顶，标题漂浮在大留白中 |
| `inner-editorial` | 内页 | 描边巨型页码＋色条＋正文压栏，密度最高 |
| `inner-photo-top` | 内页 | 上图上文，先视觉后信息 |
| `inner-quote-band` | 内页 | 大字观点居中，图片收成底部窄带 |
| `inner-side-band` | 内页 | 右侧全高窄图＋竖排标签，文字占左侧 |
| `inner-mosaic` | 内页 | 两扇错位图窗＋色块，版面最碎 |
| `inner-stacked-strip` | 内页 | 顶部细图带、中部大留白，克制到极简 |

**三条渲染细节**（否则画面会「看起来像模板出了 bug」）：

1. **裁切跟着主体走**：生成图常把主体压在画面偏下，`object-fit:cover` 居中裁会切掉主体。渲染前按行方向细节能量的重心反算 `object-position` 纵向百分比。
2. **元素位置与标题行高同源**：色块底标题用更松的行高（≥1.08）并计入上下内边距，副标题与后续元素的位置都从同一口径推导，否则字会顶出块边或与副标重叠。
3. **底边统一裁 4.5%**：模型会在图片右下烙「AI生成」角标，合成前裁掉底边；发布时按平台要求另行声明 AI 生成。

**视觉指纹自检**：`design-report.md` 第 5 节给相邻两篇封面的平均色距，`< 12` 判「过近⚠️」。这是把「不模式化」变成可验证指标的唯一办法——否则改完一两批又会退化回同一张脸。

`--engine pillow` 可切回旧版合成；canvas 渲染失败会自动回退并在摘要中记录。

- `prompts` 输出九段式提示词：人群 / **设计哲学** / 版式骨架（含该版式的构图要求）/ 视觉风格（来自哲学的 `photo_style`）/ 色彩方案（哲学的色板）/ 尺寸 / 留白区域 / 画面内容 / 禁用；哲学生效时不再叠加全局风格词，避免「橙蓝撞色」抵消「高反差黑白」；
- 设计方向由 `config.design` 决定，见第五节；
- `compose`：1080×1440 cover-crop → 顶部品牌色带压标题（眉标 + 大字标题 + 关键词撞色 + 副标/要点）→ 封面可挂倾斜贴纸 → 右下角 LOGO；
- LOGO：宽 12–18% 图宽（横版字标取 18%），边距短边 5–8%；对比不足或背景偏亮/高饱和 → 加白色圆角衬底；三处候选均偏杂时原位+衬底并标记降级。

### 阶段 5：合规自检 — `check`
写 `data/selfcheck.md`，六项全 PASS 才允许进草稿（否则退出码 7，附产物签名防过期）：

1. 文案：正文 200–300 字、标题 8–32 字、话题 3–5 个
2. 去重：与所有源文 n-gram 重合 <15%
3. 尺寸：每张 1080×1440
4. LOGO：每张在位，位置/尺寸/边距合规
5. 张数：与本次设定一致（±1），且不超平台 20 张
6. 色系：启用设计哲学后按「该篇哲学色板的纸底/正文对比度 ≥ 4.5:1」判定（旧单套模式下仍按品牌蓝色族 + 切换理由判定）；自定义哲学写出低对比配色会在这里被拦住

### 阶段 6：写入草稿 — `draft`

两条通道，按有无凭证选：

**A. 接口通道（默认，需 appid/secret）** `draft --via api`
- 逐张 `material/add_material` 上传为永久素材 → `draft/add`，`article_type=newspic`，`image_info.image_list` 按发布顺序、首图为封面、`cover_info` 指定 1:1 裁剪；
- 正文 = 改写正文 + 空行 + `#话题1# #话题2#`；标题用成稿标题（≤32 字，网页编辑器上限 20 字）；
- 凭证缺失 → 输出「贴图发布包」到 `drafts/NN/`（按序图片 + `title.txt` + `content.txt` + `meta.json`），状态 `local_only`。

**B. 浏览器通道（无凭证）** `draft --via ui --space <id>`
走已登录的公众号后台，`scripts/push_ui.py` 编排 + `scripts/push_draft_ui.js` 执行，逐篇 70–90 秒。
首次需先接管已登录窗口（`claimTaskSpace(id)`，须经用户同意）；跑完只读一次后台列表核验，不打开草稿。

#### 6.1 浏览器通道的五个坑（全部已硬编码修掉，改脚本时别退回去）

| # | 坑 | 现象 | 正确做法 |
|---|---|---|---|
| 1 | 误读计数器 | 标题旁 `8/20` 被当成图片张数 | 那是**标题字数/20 字上限**；图片数只看缩略图条 |
| 2 | 保存早于上传 | 草稿有文案、无图 | 必须等缩略图变成 `mmbiz` 服务端地址（`background-image` 含 mmbiz、宽 ≤70px）达到 N 张再点保存 |
| 3 | 保存后回读校验 | 草稿「消失」（320003）或标题正文被清空 | 贴图编辑器有**自动保存**，打开未加载完就写回空状态。保存后**绝不再打开**，只查后台列表的 `title/cover/digest` |
| 4 | 缩略图选择器 | 图片明明在，计数恒为 0 | 缩略图是 `background-image` 不是 `<img>`，用 `img` 选择器永远数不到 |
| 5 | 上传入口坐标写死 | 有图后再传报「文件选择器超时」 | 空态是「选择或拖拽图片」拖拽框，有图时是缩略图条末尾的 `+`，每次动态取 `getBoundingClientRect()` |

核验口径：后台列表里 `item_show_type=8`（贴图）且 `cover` 非空、`digest` 长度 >50 字，才算真正入库。

## 五、设计与人群

`config.design` 声明目标人群与视觉含义，版式与生图都从这里取值（出厂为通用读者示例：18–35，明亮通透、双色撞色、大字排版）。换行业只改这段，无需动代码。

版式令牌在 `design.tokens`：色带占比（封面 0.32 / 内页 0.28）、标题字号、眉标字号、正文行距、贴纸角度等，改完 `compose` 立即生效。

## 五点六、输出契约：设计执行说明

每次 `compose` 后自动生成 `data/design-report.md`，必须含四节：

1. **行业与受众分析**：行业调性、人群特征、设计含义、视觉语气（含 `audience-brief.md` 摘要）；
2. **参考来源**：每篇逐条写明「抓取参考（文件名）」或「自主设计（无参考图）」，并注明仅取构图与色调；
3. **版式变化**：逐页列出 `variant` 与变化点，证明没有套模板；
4. **反抄袭核验**：文案 n-gram 表＋图像 dHash 距离表（阈值标红）。

## 六、异常处理

| 场景 | 处理 |
|---|---|
| 素材不足 N 篇 | 按 `--relax` 暂停询问／接受缩量／终止（码 5） |
| Redfox 凭证失效或不可达 | 立即停止，报告具体 code/msg（码 4） |
| 单一渠道失败 | 记录错误、继续其他渠道，摘要标注缺失渠道 |
| 某页生图失败 | 跳过该页并标注「配图缺失，需人工补图」，张数按 ±1 判定 |
| LOGO 遮挡主体 | 右下→左下→底部居中→原位+衬底并标记降级 |
| 平台校验不过（标题/正文/体积超限） | 拒绝该篇入草稿并说明超限项，不静默截断 |
| 自检后文案或配图被改动 | 产物签名不一致，拒绝入草稿，要求重跑 `check` |
| 生成图与参考图 dHash < 12 | 记录 warn「过于相似，建议重绘」，阻断不了流程但会写进报告 |
| 素材无封面（无参考图） | 按 config.design 自主设计，报告标注「自主设计」 |
| 浏览器通道：上传未完成就保存 | 草稿会「有文案无图」，必须等缩略图落成 mmbiz 地址再保存（见 6.1-2） |
| 浏览器通道：保存后打开草稿「看效果」 | 严禁。自动保存会把未加载完的空状态写回，标题正文会被清空（见 6.1-3） |
| 浏览器通道：草稿打开报 320003 | 多为上一次写入被空状态覆盖所致；不要反复重开，按列表核验，缺失的整篇重建 |

## 七、使用方式

```bash
S=~/.workbuddy/skills/WECHAT-picture-design/scripts

# 首次：初始化问卷（12 题，写入 config.json）
python3 $S/setup_wizard.py

# 阶段 0-1：三渠道采集
python3 $S/run.py init --keyword "秋季护肤" --n 2 --source rss \
  --logo ~/.workbuddy/skills/WECHAT-picture-design/assets/logo.png \
  --workdir ./runs --images-per-note 4
# → 打印 RUN_DIR

python3 $S/run.py spec --run <RUN_DIR>
python3 $S/run.py brief --run <RUN_DIR>        # 生成素材包
# 改写 → 写 notes/NN/copy.json（title/body/topics/pages/eyebrow/highlight/sticker）
python3 $S/run.py deai --run <RUN_DIR>          # 生成去 AI 味清单
# 逐篇交 humanizer-zh 处理 → 写回 copy.json
python3 $S/run.py verify-text --run <RUN_DIR>   # 字数/重合率 + AI 味体检
python3 $S/run.py prompts --run <RUN_DIR>      # 生图提示词
# 生图落盘 notes/NN/images/page-XX.png
python3 $S/run.py compose --run <RUN_DIR>            # canvas-design 引擎（默认）
python3 $S/run.py compose --run <RUN_DIR> --engine pillow   # 旧版 Pillow 合成
python3 $S/run.py check   --run <RUN_DIR>
python3 $S/run.py draft   --run <RUN_DIR>      # 有凭证→草稿箱；无凭证→发布包
python3 $S/run.py draft   --run <RUN_DIR> --via ui --space 2   # 无凭证：走已登录浏览器
python3 $S/push_ui.py     --run <RUN_DIR> --space 2 --verify   # 只核验草稿箱，不推送
python3 $S/run.py report  --run <RUN_DIR>
```

链路自测（不生图也能验证合成/自检/发布包）：`compose --placeholder`。

## 八、数据可得性说明

- **可得**：公众号图文标题/摘要/阅读/点赞/分享/评论；小红书贴图正文/互动/封面；全网热点标题与热度。
- **不可得**：公众号「贴图」的独立检索接口（Redfox 未提供）→ 用公众号图文近似，摘要长度有限，改写时信息点以摘要为准，不自行补充未经验证的事实。
- **图片素材**：素材渠道只提供封面，张数不可知；本技能按设定值出图，并在 `spec-extracted.md` 标注「素材侧不可得，按平台规范设定」。

## 九、关键设计说明

- **为什么规范不反向提取**：平台规则是硬约束（`newspic` 字段限制），素材是参考样本；把素材众数当规则，会在换行业或换渠道时产出不合规内容。
- **为什么素材要三渠道**：公众号侧贴近最终形态但缺贴图检索、小红书侧图文形态最全、热点头部提供选题时效性；三者分工不同，不用单一渠道替代判断。
- **为什么阈值 15%**：中文短文本字面重合难以避免，15% 是可读性与原创性的折中；商业投放可下调至 10%（改 `config.defaults.max_overlap`）。
- **为什么每张图都要 LOGO**：贴图在信息流中逐张滑动，中途图片可能被单独截取传播。
- **为什么引入 canvas-design**：Pillow 手写坐标只能做「色带 + 文字」这类安全版式，容易僵。canvas-design 先把品牌提炼成设计哲学，再由哲学推导网格、字号阶与用色规则，同一套规则能长出不同的版面；渲染层用 HTML/CSS，版式表达力（描边字、混合、出血、细线）远高于 Pillow。代价是多一个浏览器依赖，因此保留 Pillow 兜底。

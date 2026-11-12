# WECHAT-picture-design · 公众号贴图设计技能

按关键词抓爆款素材 → 改写成合规短文案 → 用设计哲学生成 3:4 贴图（含品牌 LOGO）→ 六项自检 → 写入微信公众号草稿箱。
这是从「某行业定制版」抽离出来的**通用副本**：行业、人群、品牌名、LOGO、检索词全部外置到配置，换行业不用改代码。

---

## 一、用途

### 1.1 它解决什么问题

公众号的「贴图」（图片消息，`article_type = newspic`）需要成套的竖版图 + 极短文案，手工做三件事最费时间：

1. **选题**：什么内容在同类账号里已经验证过；
2. **文案**：200–300 字、不能抄、要有信息点、要带话题；
3. **配图**：一张封面 + 若干内页，风格统一又不能每页一个模子。

本技能把这三件事串成流水线：确定性环节（采集、去重、规范校验、合成、自检、写草稿）由脚本完成，创造性环节（改写、生图）交给 Agent，每一步都有产物和闸门，出错能定位到阶段。

### 1.2 适合 / 不适合

| 适合 | 不适合 |
|---|---|
| 行业内容号、知识号批量做图片消息 | 长图文（`article_type=news`）排版 |
| 需要统一品牌视觉的多篇成套产出 | 必须使用真实摄影素材且有肖像/版权授权要求的内容 |
| 有明确关键词与目标人群的垂类 | 完全没有素材可参考、纯原创长故事 |

### 1.3 一次运行产出什么

```
N 篇（1–10）成品，每篇：
  标题（8–20 字）＋ 正文（200–300 字）＋ 3–5 个话题
  4–9 张 1080×1440 竖版图（首图为封面，每张含 LOGO）
  一条公众号草稿（或本地发布包）
```

---

## 二、目录结构

```
WECHAT-picture-design/
├── SKILL.md                     # 技能主文档：五要素、硬性要求、阶段 0–6、异常处理、设计说明
├── README.md                    # 本文件：用途、结构、依赖、使用方式
├── install.sh                   # 安装脚本（--verify 只自检 / --force 覆盖安装）
├── requirements.txt             # Python 依赖（Pillow）
├── assets/
│   ├── logo.png                 # 品牌 LOGO 占位图，替换成你自己的透明底 PNG
│   ├── manual-import-template.csv  # 无 REDFOX 时的手工素材导入模板（渠道/标题/作者/链接/正文）
│   ├── design-philosophies/     # 设计哲学库：一套 json = 一套完整设计语言
│   │   ├── index.json           #   清单与轮抽步长（order / stride）
│   │   ├── margin-notes.json    #   页边批注：纸白墨蓝橙 + 发丝线 + 描边页码
│   │   ├── swiss-grid.json      #   瑞士网格：纯白黑红 + 巨量负空间
│   │   ├── risograph.json       #   丝网套印：牛皮纸荧光粉 + 套印错位
│   │   ├── kinfolk.json         #   留白静物：米灰柔褐 + 超大字距
│   │   └── brutalist.json       #   粗野排版：酸性黄压黑 + 高反差黑白图
│   ├── design-philosophy.md     # 《Margin Notes》完整哲学文本（写法范例）
│   └── design-tokens.json       # 旧单套令牌，仅作兜底（哲学库缺失时生效）
├── docs/
│   └── setup-questionnaire.md   # 首次初始化问卷（12 题）：选项、默认值、写到哪个字段
├── references/
│   └── api.md                   # Redfox 三接口 + 微信 newspic 字段 + 常见错误码 + 浏览器操作要点
└── scripts/
    ├── philosophy.py            # 设计哲学的加载与分配（compose / prompts 共用，保证同篇同源）
    ├── setup_wizard.py          # 首次初始化问卷（12 题，答案直接写进 config.json）
    ├── run.py                   # 编排入口：init / spec / brief / verify-text / prompts / compose / check / draft / report
    ├── common.py                # 配置加载、运行目录、日志、JSON 读写
    ├── config.json              # 全部可调项：采集、平台规则、文案口径、行业/人群、设计令牌
    ├── source_pool.py           # 三渠道采集 + 四层去重 + 相关性分级 + 业务黑名单
    ├── spec_extract.py          # 平台规范基线 + 素材参考统计 → spec.json
    ├── textcheck.py             # 正文/标题/话题校验 + n-gram 与源文重合率
    ├── compose_images.py        # Pillow 兜底版式 + LOGO 叠加（place_logo/wrap_cjk）
    ├── canvas_render.py         # canvas-design 引擎：五套版式 → HTML/CSS → 截图 → 叠 LOGO → dHash 反抄袭
    ├── check_compliance.py      # 六项自检 + 产物签名（防过期放行）
    ├── push_draft.py            # 接口通道：material/add_material → draft/add（newspic）
    ├── push_draft_ui.js         # 浏览器通道：单篇写入（ego-browser 执行）
    └── push_ui.py               # 浏览器通道编排 + 只读列表核验
```

运行时目录（由 `init` 生成，可放在任意位置）：

```
runs/<时间戳>-<关键词>/
├── run.json                     # 本次运行的元信息与篇目
├── data/
│   ├── refs.json                # 参考图登记（渠道/标题/链接/本地路径）
│   ├── covers/                  # 抓到的参考封面
│   ├── spec.json                # 尺寸/张数/字数口径/LOGO 参数
│   ├── spec-extracted.md        # 规范来源说明（哪些是平台硬规则，哪些是素材参考）
│   ├── audience-brief.md        # 受众分析简报（Agent 补 3 条结论）
│   ├── design-report.md         # 设计执行说明：受众分析/参考来源/逐页版式/反抄袭核验
│   ├── selfcheck.json/md        # 六项自检结果
│   ├── draft-ids.json           # 已推送草稿的 appmsgid
│   └── textcheck.json           # 文案校验明细
└── notes/NN/
    ├── text-source.md           # 源素材（标题/作者/互动/正文）
    ├── copy-template.json       # 待填文案模板
    ├── copy.json                # 定稿文案（Agent 写）
    ├── prompt-0X.txt            # 生图提示词（脚本生成）
    ├── images_raw/              # 生图原始输出
    ├── images/                  # 规范命名 page-01..NN.png（3:4）
    ├── canvas/                  # 渲染用 HTML（可单独打开调试）
    └── composed/                # 成品图 1080×1440（已叠 LOGO）
```

---

## 三、依赖

### 3.1 必需

| 依赖 | 版本 | 用途 | 缺失后果 |
|---|---|---|---|
| Python | 3.9+ | 全部脚本 | 无法运行 |
| Pillow | 8.0+ | 图像合成、LOGO 叠加、dHash | `compose` 失败 |
| 中文字体 | macOS：Hiragino Sans GB / PingFang；Linux：Noto Sans CJK | 折行测量与渲染 | 中文排版错位 |
| **humanizer-zh 技能** | 本地 Agent 技能（`~/.workbuddy/skills/humanizer-zh`） | 阶段 3.4 去 AI 味 | 文案会保留空话与套话，读起来像模型写的 |

安装：`python3 -m pip install --user pillow`（或 `pip install -r requirements.txt`）。

### 3.2 可选（缺了会降级，不会崩）

| 依赖 | 用于 | 缺失时的行为 |
|---|---|---|
| `ego-browser`（ego lite） | canvas 引擎渲染截图、浏览器通道推草稿 | `compose` 自动回退 Pillow 版式；`draft --via ui` 不可用 |
| Redfox API Key | 三渠道素材采集 | `init` 直接失败（退出码 4），需手工准备素材 |
| 微信公众号 appid/secret | 接口通道写草稿 | 只输出本地发布包（`drafts/NN/`），状态 `local_only` |

### 3.3 图像生成

包内**不包含**图像生成模型，只产出提示词（`notes/NN/prompt-0X.txt`）。生图由 Agent 侧的 ImageGen 完成，落盘到 `notes/NN/images/page-XX.png`。
如果你用自己的绘图流程，只要保证：**1024×1536 或 1080×1440、无文字无水印、主体偏下、上方约 1/3 留白**，后续合成会自适应裁切。

---

## 四、安装

```bash
unzip WECHAT-picture-design.zip -d /tmp/wpd
bash /tmp/wpd/WECHAT-picture-design/install.sh          # 装到 ~/.workbuddy/skills/WECHAT-picture-design
bash /tmp/wpd/WECHAT-picture-design/install.sh --verify # 只做环境与脚本自检
bash /tmp/wpd/WECHAT-picture-design/install.sh --force  # 已存在时覆盖（先备份）
```

`install.sh` 会：检查 Python/Pillow/ego-browser/字体 → 幂等复制 → 编译校验全部脚本 → 打印依赖状态。
不想安装也可以直接用：`python3 <包目录>/scripts/run.py ...`。

---

## 五、使用方式

### 5.0 首次初始化：12 题问卷（推荐）

```bash
python3 scripts/setup_wizard.py --dry-run   # 先看会改哪些段落，不落盘
python3 scripts/setup_wizard.py             # 逐题作答，写入 config.json（自动备份 config.json.bak）
```

12 题覆盖：类目词、行业词、视觉风格、情绪基调、读者画像、阅读场景、篇幅（张数+字数）、LOGO、配图来源、发布方式、素材渠道（含无 REDFOX 的替代方案）、合规黑名单。
题库与字段对照见 `docs/setup-questionnaire.md`，答完答案另存 `setup-answers.json`。

不想交互，也可以照 `docs/setup-questionnaire.md` 末尾的三套预设直接手填 `config.json`。

### 5.1 先改三处配置（首次必做）

| 位置 | 改成什么 |
|---|---|
| `scripts/config.json` → `redfox.api_key` | 你的 Redfox Key；也可用环境变量 `REDFOX_API_KEY`（优先级更高）。**出厂为空时接口返回厂商样例数据，只能用于跑通链路** |
| `scripts/config.json` → `brand` | `name / meta_left / caption_prefix`，即页眉小字与图注前缀 |
| `assets/logo.png` | 换成你的透明底 PNG（≥512×512，横版字标最佳） |

行业与人群在 `industry`、`design.audience`、`design.image_style` 三处，属于「文案基调 + 配图语气」，可按客户改，不改也能跑。

### 5.2 素材通道：REDFOX 或 RSS

| 通道 | 前提 | 命令 | 拿到什么 |
|---|---|---|---|
| REDFOX | `redfox.api_key` 或环境变量 `REDFOX_API_KEY` | `init --source redfox` | 三渠道 + 互动数 + 封面 |
| RSS | `channels.rss.feeds` 有值 | `init --source rss` | 标题 + 摘要 + 链接（无互动数，封面可能缺） |

`--source auto`（默认）会自己判断：有 Key 用 REDFOX，没有就用 RSS。
RSS 源的可达性先自检：`python3 scripts/rss_import.py --check`。

### 5.3 主流程（一条命令一个阶段）

```bash
S=~/.workbuddy/skills/WECHAT-picture-design/scripts

# 0-1 采集：关键词 + 篇数（1–10）+ LOGO；--source auto 有 Key 走 REDFOX、否则走 RSS
python3 $S/run.py init --keyword "秋季护肤" --n 4 --source rss \
  --logo ~/.workbuddy/skills/WECHAT-picture-design/assets/logo.png \
  --workdir ./runs --images-per-note 4
# → 打印 RUN_DIR

# 2 规范：平台硬规则 + 素材参考统计
python3 $S/run.py spec --run <RUN_DIR>

# 3 素材包：每篇 text-source.md + copy-template.json + 受众简报
python3 $S/run.py brief --run <RUN_DIR>

# （Agent 环节）写 notes/NN/copy.json，字段见 5.4

# 3.4 去 AI 味：先出清单，再逐篇交 humanizer-zh 处理，写回 copy.json
python3 $S/run.py deai --run <RUN_DIR>

# 3.3 文案闸门：字数、标题、话题、与源文重合率 + AI 味体检
python3 $S/run.py verify-text --run <RUN_DIR>

# 4.1 生图提示词（每篇 N 条）
python3 $S/run.py prompts --run <RUN_DIR>

# （Agent 环节）生图 → notes/NN/images/page-01..NN.png

# 4.2 合成：五套版式轮换 + LOGO + dHash 反抄袭
python3 $S/run.py compose --run <RUN_DIR>                   # canvas 引擎（默认，需 ego-browser）
python3 $S/run.py compose --run <RUN_DIR> --engine pillow    # 无浏览器时的兜底
python3 $S/run.py compose --run <RUN_DIR> --placeholder      # 不依赖真图，验证链路

# 5 六项自检（文案/去重/尺寸/LOGO/张数/色系）
python3 $S/run.py check --run <RUN_DIR>

# 6 写草稿：有 appid/secret 走接口，没有就走浏览器或只落发布包
python3 $S/run.py draft --run <RUN_DIR>
python3 $S/run.py draft --run <RUN_DIR> --via ui --space 2

# 摘要
python3 $S/run.py report --run <RUN_DIR>
```

### 5.4 加一套自己的设计哲学

复制任意一个 `assets/design-philosophies/*.json` 改成你的，再把 id 登记进 `index.json` 的 `order`，就生效了——不用改代码。

```jsonc
{
  "id": "editorial-bauhaus",          // 文件名与 id 必须一致
  "name": "Bauhaus Editorial",
  "name_zh": "包豪斯编辑",
  "claim": "形式服从功能，几何即装饰。",  // 会写进生图提示词，一句话就够
  "signature": ["圆形与三角", "原色块面"],   // 会出现在 design-report 里
  "palette": { "paper": "#F5F2EA", "ink": "#1A1A1A", "accent": "#D62828",
               "muted": "#8C8C8C", "line": "#DCD6C8", "sub": "#3A3A3A", "body": "#2A2A2A" },
  "grid": { "columns": 12, "margin": 80, "gutter": 24 },
  "type": { "title_min": 90, "title_max": 140, "title_line_height": 0.98,
            "headline": 58, "body": 32, "body_line_height": 1.75,
            "meta": 18, "meta_tracking": "0.22em", "numeral": 280 },
  "rules": { "hairline": 1, "accent_bar": 10 },
  "photo": { "filter": "saturate(1.05) contrast(1.05)" },   // CSS filter，决定出图观感
  "grain": 0.04,                                            // 颗粒强度 0–0.2
  "skin": { "photo_border": "0", "show_hair": true,           // 可加 "title_bg"/"duotone"
            "focus": "center" },
  "photo_style": "摄影棚硬光、几何投影、原色块面",              // 直接进 prompts 的风格段
  "layout": { "cover": ["cover-hero-bleed", "cover-split-diagonal"],
              "inner": ["inner-editorial", "inner-mosaic", "inner-side-band"] }
}
```

三条经验：**版式原型从上面 11 个里挑**（写错 id 会自动回落到默认原型，不会崩）；**`photo_style` 要和 `palette` 一致**，否则「冷白硬光 + 牛皮纸底」这种组合会互相打架；**别把 `grain` 开太大**，超过 0.15 在微信压缩后会糊成噪点。

稿子已经发过一批想换风格？把 `design.philosophies.stride` 改一个数，或在 `pool` 里只留没试过的几套，重跑 `compose` 即可——文案不用重写。

### 5.4 `copy.json` 字段（Agent 唯一要写的文件）

```json
{
  "title": "八到二十字，不要用源文标题",
  "cover_line": "封面副标，一句话说清这篇给谁看",
  "eyebrow": "页眉小标，如「护肤 · 换季」",
  "highlight": "标题里要标橙的词（2–4 字）",
  "sticker": "左下角刊头字，如「先看成分」",
  "topics": ["话题1", "话题2", "话题3"],
  "body": "正文 200–300 字，4–6 段，用 \n 分段",
  "pages": [
    {"headline": "内页小标题", "body": "内页一两句", "eyebrow": "小标", "highlight": "标橙词", "quote": ""}
  ]
}
```

- `title` 8–32 字（网页编辑器实际上限 20 字，建议 8–20）；
- `body` 目标 250 字，允许 200–300；
- 与源文的 5–8 字连续重合率 **< 15%**（`config.defaults.max_overlap` 可调）；
- `pages` 条数 = 总页数 − 1（封面自动取 `title`）。

### 5.5 两条写草稿的通道

| 通道 | 前提 | 单篇耗时 | 命令 |
|---|---|---|---|
| 接口 `--via api` | `wechat.appid/secret` + 出口 IP 在公众号白名单 | 秒级 | `draft --run .` |
| 浏览器 `--via ui` | 本机已登录公众号后台（ego-browser 任务空间） | 70–90 秒 | `draft --run . --via ui --space 2` |

浏览器通道已把五个坑写进代码（见 `SKILL.md` 6.1），要点：**等图片真正上传完再保存、保存后绝不打开草稿「看效果」**——贴图编辑器有自动保存，打开未加载完的草稿会把空状态写回去。

核验口径（自动执行）：后台草稿列表中 `item_show_type=8`、`cover` 非空、`digest` > 50 字，才算真正入库。

---

## 六、可调项速查（`scripts/config.json`）

| 字段 | 作用 | 出厂值 |
|---|---|---|
| `redfox.api_key` | 采集凭证 | 空（需填） |
| `wechat.appid/secret` | 接口通道凭证 | 空（可留空走浏览器） |
| `brand.*` | 页眉小字、图注前缀 | `YOUR BRAND` |
| `industry.name/sub_tone/keywords` | 行业调性与简报文案 | 通用占位 |
| `design.audience` | 人群、年龄、特征、设计含义 | 通用读者 18–35 |
| `design.image_style` | 生图提示词的风格段 | 自然光/通透/静物 |
| `design.philosophies.enabled` | 是否启用哲学库轮换 | `true` |
| `design.philosophies.pool` | 只允许用哪几套（留空=全用） | `[]` |
| `design.philosophies.stride` | 轮抽步长，与哲学数互质时前 N 篇不重复 | `2` |
| `design.palette` | 旧色板，仅 Pillow 引擎与兜底使用 | `#F7F4EE / #1B3A5C / #ED6C1D / #8A8F98` |
| `design.variants` | 旧版式表，仅 Pillow 引擎使用 | 2 封面 + 3 内页 |
| `design.anti_copy.dhash_similarity_max` | 图像相似阈值（越小越严） | 12 |
| `text_policy.body_min/max` | 正文字数区间 | 200 / 300 |
| `defaults.images_per_note` | 每篇张数 | 6（4–9 可调） |
| `defaults.max_overlap` | 文案重合率上限 | 0.15 |
| `channels.blocklist` | 选题黑名单（词/话题） | 带货、诈骗等通用项 |
| `channels.mode` | 素材通道：`redfox` / `rss` | `redfox` |
| `channels.rss.feeds` | RSS 源列表（Q11 选完自动写入） | `[]` |
| `channels.rss.limit_per_feed` | 每个 feed 最多取几条 | 20 |
| `design.tone` | 情绪基调（问卷 Q4） | 克制可信 |
| `images.source` | 配图来源：`ai` / `own` / `hybrid` | `ai` |
| `wechat.publish_via` | 发布方式：`api` / `ui` / `local` | `ui` |

---

## 七、常见问题

**Q1 没有 Redfox Key 能跑吗？**
链路能跑通，但拿到的是厂商样例数据（`基线测试开始。` 这类），不能当真实选题用。要么填 Key / 设 `REDFOX_API_KEY`，要么手工建 `run.json` + `notes/NN/text-source.md`，从 `brief` 阶段接着跑。

**Q2 `compose` 报浏览器相关错误？**
装 ego-browser，或直接 `--engine pillow`（版式表达力弱一些，但完全不依赖浏览器）。

**Q3 生成的图右下角有「AI生成」角标？**
合成时会裁掉底边 4.5% 去掉角标碎片。正式发布时按平台要求另行勾选 AI 生成声明。

**Q4 草稿里有文案没图／标题被清空？**
这是浏览器通道保存时机不对造成的，新版脚本已修：必须等缩略图落成 `mmbiz` 地址再保存，且保存后不要打开草稿核对（会触发自动保存覆盖）。

**Q5 换行业要改哪些？**
`industry`、`design.audience`、`design.image_style`、`design.palette`，以及 `channels.blocklist` 的业务无关词。代码不用动。

**Q6 想要不同版式怎么办？**
`scripts/canvas_render.py` 里每个 `variant` 是一段 HTML 拼装函数，加一个分支并在 `config.design.variants` 注册即可；`design-tokens.json` 控制字号、边距、出血比例。

**Q7 标题能不能到 32 字？**
接口允许 32，网页编辑器上限 20。技能里按 8–20 收口，避免接口能过、后台编辑被截。

**Q8 一次能做多少篇？**
`init` 的 N 上限是 10（防单批过大）。要做 20 篇，分两批并换关键词，避免选题重复。

---

## 八、已知限制

- Redfox 不提供公众号「贴图」的独立检索，用公众号图文近似；摘要长度有限，改写时只依据摘要与正文，不补未经验证的事实。
- 素材渠道只给封面，原始张数不可知；张数按设定值出图，并在 `spec-extracted.md` 标注来源。
- 浏览器通道依赖登录态，token 会过期；过期需重新登录公众号后台。
- 生图质量取决于所使用的图像模型，包内只负责提示词与合成规范。

---

## 九、版本

`v2.2.0`（通用副本）— 在公众号贴图生产链上抽离行业内容，补齐浏览器通道与五坑防护。
变更记录见 `SKILL.md` 与各脚本头部注释。

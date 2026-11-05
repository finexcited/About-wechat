# 环境安装与依赖说明

本技能分三层依赖：**必装**（不出图就没法用）、**发布可选**（只有第七步需要）、**润色可选**。

## 零、通常你什么都不用做

首次运行时 Agent 会自动执行环境自举：

```bash
python3 scripts/bootstrap.py --quiet
```

它负责：检测 Python/Pillow（缺则自动 `pip install --user`）→ 校验字体（**随包提供**，只查存在性与字重轴）→ 建产物目录并验可写 → 检测官方 HTML 校验 CLI。

**成功时它不输出任何内容，Agent 也不会向你汇报。**只有自动修复失败、且会阻断出稿时，才会打印手工修法并非零退出。

想自己看状态（比如好奇装了什么、或怀疑环境有问题）：

```bash
python3 scripts/bootstrap.py --report    # 完整清单：每项 OK/FAIL、路径、版本、修法
python3 scripts/bootstrap.py --json      # 机器可读，供脚本判断
python3 scripts/bootstrap.py --no-net    # 跳过需要联网的项

# 交付前自检：不看输出看退出码
python3 scripts/bootstrap.py --report --strict             # 待处理清单清空才 exit=0
python3 scripts/bootstrap.py --report --strict --publish   # 连第七步 Node/ego 一起卡
```

> `--report` 的退出码**永远是 0**，哪怕产物目录没指定、LOGO 还是占位图、`00_配置.md` 还没写——它只负责显示，不负责判定。要一个能进脚本的结论，用 `--strict`（对应 onboarding Q37）。`--publish` 只在「要自动存草稿」（Q4=2）时加；不加时 `Node.js` / `ego-browser` 缺了不算没配好，报告里仍会列出来并注明只影响第七步。
>
> 其中「`00_配置.md`（Q40）」这一行比的是**四项根配置**（类目 / 读者画像 / 主色 / 辅色）与 `WX_*` 环境变量是否一致——这个 md 没有任何脚本消费，两边不一致时以前谁都不报，现在会在报告里逐项列出。

下面几节是**手工安装**的说明，只在自举失败、或你想自己掌控版本时才需要用。

---

## 一、必装依赖

| 依赖 | 版本 | 用途 | 安装 |
|---|---|---|---|
| Python | ≥ 3.9 | 跑全部出图 / 校验脚本 | macOS 自带或 `brew install python` |
| Pillow | ≥ 10.0 | 长图、封面合成 | `pip install -r requirements.txt` |
| Noto Sans SC 可变字体 | — | 长图 / 封面中文渲染 | **随包提供**（`assets/fonts/`，17MB），解压即有，不需要任何操作 |

> 字体是 SIL OFL 1.1，允许打包再分发，许可原文随包放在 `assets/fonts/OFL.txt`。**所以它入库了**——忽略它的代价是每次 clone 后都得联网下载，而下载失败正是「装好了却跑不出图」的主要来源。
>
> **只能用可变字体（VF）**：全部绘图脚本走 `set_variation_by_axes([weight])` 取字重。分字重的静态 OTF（思源黑体的 `SourceHanSansCN-*.otf` 那种）没有 Weight 轴，调用抛错后被 `except` 吞掉，**封面各级字号静默退化成同一个粗细**。`bootstrap.py --report` 会判「没有字重轴」并失败，别绕过它。
>
> `scripts/setup_fonts.sh` 现在是**修复命令**，不是安装步骤：只在文件被误删、或想换字体时用。

自检：

```bash
python3 -c "import PIL; print('Pillow', PIL.__version__)"
ls -lh assets/fonts/NotoSansSC-VF.ttf
python3 scripts/make_cover.py --help
```

四条命令都正常，说明生成链路（第三~五步）可用。

---

## 二、发布可选依赖（仅第七步「自动存草稿」需要）

| 依赖 | 说明 |
|---|---|
| Node.js | ≥ 18，`ego_pub.mjs` 运行环境 |
| ego lite 桌面端 | 浏览器自动化宿主，需自行安装并保持运行 |
| `ego-browser` CLI | 需在 `PATH` 上；首次使用先跑一次 `ego-browser skill` 读当前版本用法（其输出优先于本文档） |

装完后验证：

```bash
node --version
ego-browser --version
```

> `ego-browser` **不转发命令行参数**（`process.argv` 只有 Node 自身路径），
> 所有输入必须写进 `$WX_DAILY_OUT/_ego/pub_jobs.json`。这是最容易踩的坑。
>
> **它也不继承调用方的环境变量**（实测：`WX_TEST_PROBE=hello ego-browser nodejs -e '…'` 读到 `undefined`，`process.cwd() === "/"`）。
> 所以 `WX_DAILY_OUT` / `WX_LOGO` / `WX_BRAND` 这些 export 对第七步**统统无效**，
> 必须在 `pub_jobs.json` 里写 `"dir": "/你的/绝对/产物目录"`，并确保 `space` / `author` 等仍由环境变量或号配置提供。
> 症状：报 `ENOENT: …/Documents/公众号推文/_ego/pub_jobs.json`——不是目录没建，是脚本退回默认目录找配置了。
>
> **登录态会被强制重置**：`cmd=login` 默认先清掉 `mp.weixin.qq.com` 的所有浏览器存储再出二维码，
> 所以「我电脑上已经登录了，不用扫」这条路在本技能里是**不通的**（这正是防止草稿存进别人账号的设计）。
> 想复用只能显式 `"freshLogin": false`，代价是 `cmd=article` 的前置闸门仍会拦（`need_login`）。
> 详见 `publish-spec.md` §2.0。

**不装这套依赖也能用**：跳过第七步，手动把产出的 HTML 粘贴进公众号后台即可。

---

## 三、润色可选依赖（第二步 2.2 去 AI 味）

| 依赖 | 说明 |
|---|---|
| `humanizer-zh` 技能 | 中文去 AI 味润色器，通常位于 `~/.workbuddy/skills/humanizer-zh/`。未安装时该环节退化为人工润色，其余流程不受影响。 |

---

## 四、合规校验可选依赖（第六步）

| 依赖 | 说明 |
|---|---|
| `verify-article-structure-spec` | 微信官方 HTML 结构校验 CLI。`python3 scripts/verify_html.py --setup` 一键安装（需 git + npm，约 10 分钟）。未安装时自动降级为内置静态自查，并在输出中标注。 |

---

## 五、配置项

集中在 `scripts/brand.py`，用环境变量覆盖：

| 变量 | 默认值 | 作用 |
|---|---|---|
| `WX_BRAND` | `你的公众号` | 正文引导语、封面文字角标；也是草稿署名的兜底值（署名归 `WX_AUTHOR`） |
| `WX_DAILY_OUT` | `~/Documents/公众号推文`（仅兜底） | **由使用者在 Q7 自行指定**；不设时才落到兜底值 |
| `WX_ARTICLES` | **无默认**（0 = 未配置） | **每天总篇数，由使用者自定义填写**。未配置时 `cost_estimate.py` 直接报错退出，不会替你猜一个数 |
| `WX_SERIES` | 总篇数的 40% | 其中「专栏/强时效」的篇数；填 `0` 表示不做专栏。泛干货数 = 总数 − 专栏数，由 `brand.article_plan()` 算。**与 `WX_SERIES_RATIO` 并存时本项优先** |
| `WX_SERIES_RATIO` | `0.4` | 专栏占比（0—1，也接受 `25` / `25%` 写法）。Q24 选「三档比例」时用。取整走 `brand.series_count()`：N×比例四舍五入、有余量但算出 0 时抬到 1、上限 N |
| `WX_PUBLISH_SPACE` | `公众号发布` | 这个号的**浏览器会话名**。同一个号别改（改了＝换空白会话，登录态丢失）；**多号必须逐号不同**，否则后登录的会把前一个顶掉。可交给 `accounts.sh add --space` 统一管 |
| `WX_AUTHOR` | 空（= 取 `WX_BRAND`） | 草稿作者署名（onboarding Q28）。设笔名就用笔名；**设成空串＝有意不填作者**，不设才退品牌名 |
| `WX_LEGACY_BRANDS` | 空 | 逗号分隔的历史品牌名，`cmd=author` 时从正文里清洗掉 |
| `WX_LOGO` | `assets/logo.png` | 封面 LOGO 路径。**管多个号时必须逐号指定**，否则所有号共用同一个角标。设为 `none`（也认 `off` / `0` / `-` / `无`）表示**封面不印角标**——和「路径写错」不同，这是有意状态，`--report` 判 OK |
| `WX_ACCOUNT` | 空 | 当前号简称，由 `accounts.sh use` 写入，仅用于排查时确认"我现在在哪个号上" |
| `WX_VERTICAL` | `考公` | **类目名**，决定选题边界、语气与文末引导语（如 职场/母婴/财经/教培） |
| `WX_AUDIENCE` | 空 | 读者画像一句话，供 AI 对齐案例与代入感 |
| `WX_ACCENT` | `#EE7800` | **主色**，任意 `#RRGGBB`；HTML 主视觉（章节色条/导读徽章/引导语/表格卡表头）+ 封面圆点。**别手填**——先用 `scripts/pick_palette.py <你的LOGO或参考图>` 取色（Q19），脚本给的是「占比最大的有彩色相」，比目测更稳 |
| `WX_ACCENT_ALT` | `#007E5C` | **辅色**，任意 `#RRGGBB`；封面主视觉（标题混排基色/竖分隔线/底部关键词条），与主色交替用于多篇轮换。`pick_palette.py` 会一并给出建议 |
| `WX_CTA` | `每天一篇{vertical}干货，只讲你用得上的。` | 文末引导语；`{vertical}` 自动替换成类目名 |
| `WX_GUIDELINES` | `references/content-guidelines.md` | **类目规范文件**，换类目就指向你自己的那份（有 7 处类目专属内容） |
| `WX_CALENDAR` | `references/exam-calendar.md` | **选题日历**，换类目必须一起换。整份都是类目专属的节点表，只换规范文件不换它 = 语气是你的、题目还是考公的。`--report` 的「选题日历」一行专门查这个 |
| `WX_THEMES` | `$WX_DAILY_OUT/00_主题词表.json` | 选题主题词表，缺席则用内置考公示例 |
| `WX_VERIFY_TOOLS_DIR` | `~/.workbuddy/tools/verify-article-structure-spec` | 官方 HTML 校验 CLI 的安装位置 |

建议写进 shell 配置，避免每次重设——**写 `~/.zshenv`，不是 `~/.zshrc`**：

```bash
cat >> ~/.zshenv <<'EOF'

# >>> wechat-daily >>>
export WX_BRAND="你的公众号"
export WX_VERTICAL="你的类目"
export WX_AUDIENCE="一句话读者画像"
export WX_ACCENT="#RRGGBB"
export WX_ACCENT_ALT="#RRGGBB"
export WX_GUIDELINES="$HOME/wx/content-guidelines.md"
export WX_CALENDAR="$HOME/wx/calendar.md"
export WX_DAILY_OUT="$HOME/wx/out"
export WX_LOGO="$HOME/wx/logo.png"
# <<< wechat-daily <<<
EOF
```

原因：**非交互式 zsh 只读 `~/.zshenv`**，`~/.zshrc` 与 `~/.zprofile` 都不读。而自动化任务（定时触发）正是非交互式——变量写在 `.zshrc` 里，手动跑一切正常，定时任务却会静默退回示例值（产物写进兜底目录、封面上印着占位 LOGO）。重跑这段前先把旧的 `# >>> wechat-daily >>>` 块整块删掉，别累加两份 export。

验证不是 `echo $WX_BRAND`（那只能证明一个变量），而是让一个**非交互式**新 shell 自己报一遍：

```bash
zsh -c 'python3 <仓库路径>/scripts/bootstrap.py --report' | grep '00_配置'
# 期望：[OK  ] 00_配置.md（Q40）  可选  四项与环境一致
```

---

## 六、品牌素材替换

仓库内 `assets/logo.png` 是**占位图**。使用前处理掉，三条路（onboarding Q8b，按「手上已有素材」的先后来排——有图就直接传，不逼你读规格）：

**路线 1：自己上传透明底 PNG**

- 格式：透明底 PNG（**不是「存成 RGBA」就算**——白底图另存成 PNG 通道在、像素全不透明，印出来是一块白方块。脚本看 alpha 的实际取值范围）
  - **截图一定要先抠底**：截图抠出来的「透明」往往是四角米色 + alpha 全 255，压到主色上会露一圈白边和噪点。判据：`bootstrap.py --report` 会报「背景不透明」
- 高度：≥ 128px（角标按 56/64px 高重采样，两倍余量；太小的图会糊）
- 宽高比：1:1—6:1（420×140 ≈ 3:1 最贴现有版式）。超宽会被压成一条横线、超窄会压成一条竖线，宽度上限为画布宽 28%（252px），越界脚本压边并打 WARN
- 位置：右上角，脚本自动留 24px 安全边距

**路线 2：只给文字名，让脚本生成字标（手上没图时用，零积分）**

```bash
# 先出三个候选挑一个（推荐：看得见再决定）
python3 scripts/make_logo.py --name "你的品牌名" --out-dir /tmp/logo-candidates
# 选定版式后落到正式位置
python3 scripts/make_logo.py --name "你的品牌名" --style mark --out assets/logo.png
```

- 参数是 `--name`（不给则取 `WX_BRAND`）；`--accent` 可指定主色（默认 `WX_ACCENT`）；不给 `--style` 时三种版式都出，文件名带版式后缀
- 三种版式：`wordmark`（纯字标，≤4 字最好看）/ `mark`（字标 + 左侧色块，5—6 字用）/ `badge`（圆角色块卡片，品牌名带「的」「说」这类虚词时更稳）
- **为什么不用 AI 生图**：AI 画中文字必错字，而字标是纯排版，一个错都没有，还能随品牌色改
- **几何是硬的**：角标宽度上限为画布宽 28%（252px）、宽高比上限 6:1，等比缩放改变不了宽高比——所以**纯字标只容得下约 5 个汉字**。超了脚本报 `WARN` 并直接给建议（改短名 / 换 mark / 换 badge），不会硬压成一条细线
- 生成的图**墨色系会隐身**：深蓝字标压在主色块上看不出边界，封面 LOGO 区必须留浅底（现有版式默认米白底，没问题）

**路线 3：不体现任何 LOGO（素封面）**

```bash
export WX_LOGO=none      # 也认 off / no / 0 / - / 无
```

- 两张封面脚本（`make_cover.py` / `compose_cover.py`）都会**整块跳过角标**，不打印 WARN
- **不会退化成文字角标**：那个兜底只用于「图丢了」，跟「我要素封面」是两件事——否则你选了不显示，封面上反而多出一行品牌名
- `bootstrap.py --report` 判 `[OK] 按要求不显示（WX_LOGO=none）`，`--strict` 不拦
- **代价**：封面只剩标题＋色带，同名的多个号之间更难区分，读者少了「这是同一个号」的视觉锚点。是取舍，不是错
- 别用「全透明空白 PNG」代替：`--report` 会判「整图全透明」不通过，每次自检都得手动忽略一条红灯

替换后跑 `python3 scripts/bootstrap.py --report`，看「品牌 LOGO」这一行：
`[OK  ]` 才算合格；`[SKIP]` 会写明是占位图（含另存/裁切过的占位图）、高度不足、
背景不透明、整图全透明，还是宽高比越界。再出一张图确认角标清晰：

`python3 scripts/make_cover.py --title "测试\n标题" --variant 1 --out /tmp/t.png`

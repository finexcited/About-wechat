# 公众号草稿自动化发布：实战复盘与可复用手册

> 来源：2026-10-19 首次批量（6 篇）、2026-10-23 封面返工（5 篇）、2026-11-02 十篇批次与 ego lite 通道改版的连续实战。
> 定位：`publish-spec.md` 讲"规范怎么定"，本文讲"为什么这么定、踩过什么、怎么不再踩"。
> 读者：后续维护本技能的人 / AI。**遇到发布失败先读第七节排错表，再读第四节根因。**

---

## 一、适用场景

**该用本手册的时候**
- 已有成品三件套：`标题_YYYY-MM-DD_推文.html`（正文）+ `_封面.png`（900×383）+ `.md`（摘要来源），需要**批量存草稿**。
- 需要在无人值守下把 1—10 篇稳定塞进草稿箱，且**绝不群发**。
- 微信编辑器改版导致旧选择器失效，需要快速重定位。

**不该用的时候**
- 需要点「发表 / 群发」——永远留给用户手动。
- 需要 AI 代替用户扫码登录 / 选择多账号——违反铁律。
- 完全没有 GUI 的服务器环境——ego lite 要拉起真实浏览器，必须非沙箱运行。

**前置条件（缺一不可）**

| 条件 | 检查方式 | 不满足的表现 |
|---|---|---|
| 已装 ego lite 且 `ego-browser` 在 PATH | `ego-browser skill` 能打印用法指南 | `command not found` |
| 命令**非沙箱**执行 | 命令带 `dangerouslyDisableSandbox` | 浏览器拉不起来 / 页面空白 |
| 手机可扫码（首次登录） | 用户在场 | `login_timeout` |
| `$WX_DAILY_OUT/_ego/pub_jobs.json` 存在且可解析 | `cat` 一眼看 | 脚本启动即抛 JSON 解析错 |

---

## 二、端到端流程（6 步，实测耗时）

| # | 步骤 | 配置 / 命令 | 成功断言 | 实测耗时 |
|---|---|---|---|---|
| 1 | 登录 | `{"cmd":"login"}` + `ego-browser nodejs < ego_pub.mjs` | 输出 `login_ok` + `_wx_token.json` 有 token | 手动扫码 10—40s |
| 2 | 逐篇填充 | `{"cmd":"article","jobs":[…]}` | 每篇输出 `step=article` 且 `save.appmsgid` 非空 | 25—70s/篇（长图篇 4.5min） |
| 3 | 冷加载核验 | `{"cmd":"verify"}` | 每篇 `coverOk:true`，`_ego/verify/*.png` 落盘 | 40s / 10 篇 |
| 4 | 封面判色 | `check_cover_color.py --dir _ego/verify` | 全部 `彩色`，退出码 0 | 1s |
| 5 | 写台账 | `00_发布台账_YYYY-MM-DD.md` | 列齐 appmsgid / 封面 / 核验 | 即时 |
| 6 | 收尾 | `{"cmd":"close"}` | 输出 `step=close`，页面保留 | 1s |

**单篇四道断言（缺一不可，全部用 DOM/URL，不靠肉眼）**

1. 标题：`[data-placeholder='请在这里输入标题']`.innerText 含标题前 6 字 → `title.ok`。
2. 正文：`bodyLen > 800`，且 `mmbiz 图片数 == HTML 中 <img> 数` → `images{expect,bodyImgs,mmbiz}`。
3. 封面：`.js_cover_preview_new` 的 `background-image` 含 `mmbiz` → `cover.ok`。
4. 保存：URL 含 `appmsgid=`（新稿）或 toast「成功/已保存」（改稿）→ `save.appmsgid`。

> 第 3 条的判据是**改过一次**的：2026-10-23 之前用的是封面卡文案「修改 / 换一张」，结果隐藏模板里这段文案恒在，5 篇全部误报成功、实际全空。

---

## 三、关键步骤详解

### 3.1 登录：先判断"要不要切换扫码"，再等二维码渲染

登录页默认可能是**账号密码**形态，必须点「扫码登录」才出二维码。正确顺序：

1. `page.goto("https://mp.weixin.qq.com/")` → 等 3s。
2. 读 `a.login__type__container__link_text` 的文案：
   - 含「扫码登录」→ 页内 `click()` 切换，等 1.8s。
   - 是 `none`（找不到该链接）→ 多半**已经登录**，直接继续轮询。
3. 等 `.login__type__container__scan__qrcode` 出现。
4. 导出二维码：在页面内把 `<img>` 画到 canvas（4 倍、`imageSmoothingEnabled=false`）再 `toDataURL`。
   - **为什么不用整页截图**：整页截图里二维码只有 122px，二次压缩后手机上识别率明显下降；canvas 放大后是纯像素块，扫得更快。同源图片不会污染 canvas。
5. 轮询 `page.url()` 是否含 `token=`，命中即写 `_wx_token.json`。

### 3.2 打开编辑器：带 token 直开 URL，不要点导航

- 新稿：`...&type=10&isMul=0&isNew=1&token=<token>`
- 改稿：`...&type=10&isMul=0&token=<token>&appmsgid=<id>`
- 等 `[contenteditable]` ≥ 3 才算就绪（编辑器是异步挂载的，`domcontentloaded` 时还没有）。
- 随后 `dismissModals`：摘掉「支持添加话题卡片」引导弹窗与 `.weui-desktop-mask`，否则它会抢焦点，标题输不进去。

### 3.3 标题 / 作者 / 摘要：三种输入方式，各管一段

| 字段 | 方式 | 为什么 |
|---|---|---|
| 标题（contenteditable DIV） | **真实键盘输入** `page.click` + `keyboard.type` | JS 写 `textContent` 微信编辑器不采纳（会被内部 model 覆盖，`innerText` 恒为 `"\n"`）；失败依次退 `keyboard.paste` → `keyboard.insertText` |
| 作者 `#author`（原生 input） | `page.fill` | 原生 input 走 value + input 事件即可；失败退「点击 + 全选 + 输入」 |
| 摘要 `#js_description` | `page.fill`，文本由脚本清洗 | 旧实现直接截 Markdown 第 2 段，**会把 `**` 带进摘要**（2026-11-02 实测到），现在统一剥 `**`／反引号／`#`／链接语法 |

### 3.4 正文：合成 paste + 等图片转存

- HTML 读进来 → base64 → **按 400KB 分块**累加进 `window.__b64`（一次性塞会把 evaluate 的参数撑爆）。
- 页面内：`atob` → `Uint8Array` → `TextDecoder('utf-8')` → `DataTransfer` 装载 `text/html` + `text/plain` → **`new Event('paste')` 并把 `clipboardData` 挂在事件对象上**（不是构造器传参，也不是 `navigator.clipboard.write`）。
- 粘贴后等图片转存：轮询 `img[src*=mmbiz]` 直到 `mmbiz >= bodyImgs`。**5MB 级长图实测 60s+**，超时后保存必失败。

### 3.5 封面：唯一可用路径（4 次点击 + 1 次上传）

见第九节（单独成章，因为它是全流程最容易静默失败的一步）。

### 3.6 保存与收尾

- 滚到底 → 找「保存为草稿」按钮 → 真实鼠标点（不在视口则页内 `click()`）。
- 新稿：URL 从 `isNew=1` 变为带 `appmsgid=` → 成功，同时把 appmsgid 写回 `_ego/pub_results.json`。
- 改稿：URL 本来就有 appmsgid，**不能用 URL 判断**，看 toast「成功/已保存」。
- 收尾：`{"cmd":"close"}`，`task.finish({keep:true})` 保留页面，下次直接沿用登录态。

---

## 四、六个关键修复点（问题 → 根因 → 修复 → 验证）

### R1 脚本起了但什么都没发生：`ego-browser` 不转发命令行参数

- **现象**：按 `ego-browser nodejs script.mjs --date 2026-11-02` 传参，脚本里 `process.argv` 只有 Node 自身路径。
- **根因**：ego lite 的 nodejs 子命令只接收脚本文本（stdin / `-e`），不转发 argv。
- **修复**：所有输入改走 `$WX_DAILY_OUT/_ego/pub_jobs.json`（`cmd` / `jobs` / `author` / `timeout` 等）。
- **验证**：`ego-browser nodejs < /tmp/argvtest.mjs` 打印的 `process.argv` 长度为 1。

### R2 二维码不出现

- **根因**：登录页停在「账号密码」形态；或二维码 `<img>` 还没渲染就去读。
- **修复**：先读 `link_text` 决定是否切换，再 `waitForFunction` 等 `.login__type__container__scan__qrcode`。
- **验证**：`{"step":"qr","how":"canvas"}` 且 `login_qr_ego.png` 边长 ≥ 400px。

### R3 标题写不进去（`innerText` 恒为 `"\n"`）

- **根因**：用 JS 写 `textContent`，微信编辑器的内部 model 不认；或引导弹窗抢了焦点。
- **修复**：`dismissModals` + 真实点击 + `keyboard.type`，再断言前 6 字。
- **验证**：`{"title":{"ok":true,"now":"…"}}`。

### R4（**最核心**）按钮点了没反应 / 弹窗没关

- **根因**：微信编辑器里同名元素有多份隐藏模板（`.js_cover_btn_area` ×3、`.weui-desktop-dialog__wrp` ×4，含 w=0 的「未实名 / 未设头像 / 切换账号」），`querySelector` 取第一个必错；另外元素常在内层滚动容器里，坐标落在视口外。
- **修复**：① 一律按 `getBoundingClientRect().width` 过滤可见实例；② 点击前 `scrollIntoView({block:'center'})` 再取中心；③ 不在视口内才退回页内 `click()`。
- **验证**：每步都回读状态（弹窗宽度、`.selected` 数量、背景图是否含 mmbiz），不靠"点了应该就好了"。

### R5 封面设不上 / 误判为设上了

- **现象 A**：草稿箱 5 个封面全是灰白空块，但脚本每篇都报成功。
- **根因**：判据用了 `.setting-group__cover_primary` 的文案「修改 / 换一张」，而这段文案在隐藏模板里恒在；`cover_primary img` 也可能恒为 `null`。
- **修复**：判据改为 `.js_cover_preview_new` 的 `background-image` 含 `mmbiz`。
- **现象 B**：判据改了以后还是空 —— 因为「确认」按钮在 y≈935，窗口只有 718 高，坐标点击落在视口外，**静默落空、没有任何报错**。
- **修复**：`Browser.getWindowForTarget` + `Browser.setWindowBounds` 把真实窗口撑到 1460×1260；`Emulation.setDeviceMetricsOverride` 无效（只改视觉视口，不改布局）。
- **验证**：`cmd=verify` 逐篇冷加载，读服务端封面 URL 并落盘。

### R6 封面"有，但不是彩色设计稿"

- **现象**：草稿能存上，封面却不是本地那张 `_封面.png`，而是正文里的表格卡片 / 纯白块。
- **根因**：封面压根没提交成功时，微信保存会用**正文首图**顶替（表格 PNG 卡片接近灰白）。
- **修复**：① 封面失败必须重设，不能"能存上就行"；② 存完跑 `cmd=verify` + `check_cover_color.py`。
- **验证**：彩色像素占比 ≥ 0.05。实测本号白底浅色版式 0.15—0.23、深底版式 0.80+，而白底表格图 / 灰块 / 空封面都是 0.000 —— 这个指标能把三类彻底分开（平均饱和度不行：浅色版式只有 0.17，会被误杀）。

---

## 五、可复用经验（抽象成规则，跨项目通用）

### E1 先证明"能不能点"，再写业务逻辑

每个新页面先用 5 行脚本验证：目标元素可见吗？点下去有反应吗？状态怎么读？证明通了再写流程。本技能在封面上返工两次，都是因为跳过了这一步。

### E2 自定义组件页面，隐藏模板是常态

`querySelector` 取第一个、`querySelectorAll()[0]`、按文案判断状态，这三件事在微信后台全是坑。**一律加尺寸/可见性过滤，一律用"有没有真实内容"当判据。**

### E3 断言只用 DOM/URL，截图只用于"看不懂界面"

截图有三个问题：慢、长页面易超时、灰度/缩放导致误读。能用 `getBoundingClientRect` 和 `backgroundImage` 说清的事，不要截图。

### E4 会话生命周期决定架构

旧通道一个浏览器实例只绑一个会话，于是被迫"登录+批量同进程"，一旦进程挂了就得重新扫码。ego 的浏览器常驻、TaskSpace 跨进程复用，**架构上的这一条约束直接消失**——这也解释了为什么改版后代码里不再有 session 文件。

### E5 探测脚本要能自救

探测时每步都打印"我现在看到什么"，而不是只打印"成功/失败"。`{"step":"verify", …}` 这种结构化输出让排错不需要重跑。

### E6 文案匹配要归一化

`textContent.replace(/\s+/g,'')` 之后再比较；按钮文案可能是「保存为草稿」也可能是「保存 为草稿」。匹配不到时按 `sel` 换一层标签（`button` → `a,span`）再试。

### E7 修正已存草稿靠"再存一次"

带 `appmsgid` 打开 → 改 → 再点保存，是**更新同一条**，不会新建。补封面、补摘要、删多余图都走这条路。

### E8 把"失败"设计成可诊断的

失败时至少留下：当前 URL、可见弹窗文案、封面背景图、`.selected` 数量、`save.how`（mouse/js）。有这五项，90% 的问题不用复现就能定位。

---

## 六、优化建议（按收益排序）

| # | 建议 | 收益 |
|---|---|---|
| 1 | 1000px 分块累加 `window.__b64` 改小到 400KB | 大 HTML 更稳（已实施） |
| 2 | `resume` 断点续跑（`_ego/pub_done.json`） | 中断重跑不重复存草稿（已实施） |
| 3 | 封面失败自动重试 2 次再判失败 | 少一次人工返工 |
| 4 | 登陆态探测优先（cookie 还在则免扫码） | 已天然具备：ego profile 存 cookie，多数情况直接 `login_ok` |
| 5 | 台账自动生成（脚本直接写 md） | 省一步手工 |

---

## 七、排错速查表

| 症状 | 最可能原因 | 动作 |
|---|---|---|
| `command not found: ego-browser` | 未安装 / 不在 PATH | 读 ego-browser 技能的 `references/install.md` |
| 脚本无输出就退出 | `pub_jobs.json` 路径不对或 JSON 语法错 | `cat` 该文件；确认在 `$WX_DAILY_OUT/_ego/` |
| 传了参数但脚本没反应 | ego 不转发 argv | 改配置文件的 `jobs` |
| 二维码白屏 | 未切到扫码模式 / 未等渲染 | 重跑 `cmd=login`；看 `linkText` 输出 |
| `login_timeout` | 用户没扫 / 二维码过期 | 重跑 `cmd=login` 出新的码；有 `multi_account` 先让用户选账号 |
| 标题空白 | 引导弹窗抢焦点 / 用了 JS 写值 | 确认 `dismissModals` 生效；改用真实键盘输入 |
| 点按钮没反应 | 点到隐藏模板 / 按钮在视口外 | 加尺寸过滤 + `scrollIntoView`；回读状态确认 |
| 封面卡提示「图片不能为空」 | 封面未提交 | 跑 `cmd=cover`，再看 `cmd=verify` 的 `coverOk` |
| 保存失败、`mmbiz=0` | 图片未转存完 | 加大 `imageTimeout` 重跑该篇 |
| 草稿箱封面是灰白块 | 被微信自动首图顶替（R6） | `cmd=verify` + `check_cover_color.py` 定位后重设 |
| 草稿箱条目比成功数多 | 失败批次编辑器周期性自动保存留残留 | 人工核对后删除 |
| 「下一步」一直是灰的 | 没真正选中缩略图 | 点缩略图本体，断言 class 含 `selected` |
| 点了「确认」弹窗还在 | 窗口太矮，按钮在视口外 | 确认 `ensureWindow` 生效（`innerHeight` 应 >1100） |

---

## 八、验收清单

- [ ] 每篇都有 `appmsgid`，且写进 `_ego/pub_results.json`
- [ ] 每篇 `cmd=verify` 的 `coverOk` 为 true
- [ ] `check_cover_color.py` 全部「彩色」，退出码 0
- [ ] 每篇 `mmbiz 数 == HTML 中 <img> 数`
- [ ] 摘要不含 `**` 等 Markdown 记号，长度 ≤120
- [ ] 台账 `00_发布台账_YYYY-MM-DD.md` 已写，含 appmsgid 与核验结论
- [ ] 全程未点「发表 / 群发」

### 2026-11-02 十篇批次的实际验收记录

- 10 篇全部 `coverOk:true`（服务端封面图均带 mmbiz URL）
- 彩色像素占比：0.151 / 0.152 / 0.186 / 0.198 / 0.210 / 0.210 / 0.215 / 0.216 / 0.821 / 0.822 → **10/10 彩色**
- 结论：该批没有"封面缺失"问题；观感上偏白的是**米白底浅色版式**（占比 0.15 那两张），属设计选择，不是故障

---

## 九、封面专项：全流程最容易静默失败的一步

> 起因：2026-10-23 存了 5 篇草稿，标题/正文/摘要/配图全对，但草稿箱 5 个封面全是灰白空块。
> 结论：**封面从未被提交**，而不是图片没上传。上传一直成功，卡在「选中 → 下一步 → 确认」这一段。

### 9.1 三条根因（缺一条就得到空白封面）

| # | 现象 | 真正原因 |
|---|---|---|
| 1 | 点「下一步」无反应 | 未选中图片时按钮带 `weui-desktop-btn_disabled`。缩略图是 `<li class="weui-desktop-img-picker__item">`，必须**点中缩略图本体**，class 变成 `…item selected` 才算选中；点空白处/标题无效 |
| 2 | 「确认」点了但封面还是空 | 「编辑封面」弹窗里的 `确认` 按钮 y≈935。默认窗口 `innerHeight≈718`，坐标点击落在视口外 → **静默落空**，弹窗留在原地，没有任何报错 |
| 3 | 以为改视口就能解决 | `Emulation.setDeviceMetricsOverride` 只改视觉视口，**不改布局**，按钮仍在 935。要 `Browser.getWindowForTarget` + `Browser.setWindowBounds({width:1460,height:1260})` 改真实窗口；但**窗口高度会被屏幕钳制**（1440×900 屏实测 `innerHeight` 只到 ~715），所以还必须逐级滚动祖先容器把按钮推进视口 |

### 9.2 正确流程（`ego_pub.mjs` 的 `setCover` 已实现）

1. `Browser.setWindowBounds` 尽量撑到 1460×1260，等 800ms。**注意窗口高度会被屏幕高度钳制**（1440×900 屏实测只能到 `innerHeight≈715`），所以真正把「确认」送进视口的是下一步的逐级滚动。
2. 打开编辑器（新稿 `isNew=1`，改稿带 `appmsgid`），等 `[contenteditable]` ≥3。
3. 页内 `document.querySelector("a.js_imagedialog").click()` 直接开图片库 —— **不要** hover `.js_cover_btn_area` 再点 `.pop-opr__item`，那个悬浮菜单是 `visibility:hidden;opacity:0`，`elementFromPoint` 会命中背后的摘要 textarea，几乎必然失败。
4. 按文件名在 `.weui-desktop-img-picker__item` 里找 `{base}_封面.png`；找不到就上传：优先 `page.setInputFiles` 到弹窗内隐藏 `input[type=file]`，兜底点「上传文件」+ `waitForFileChooser` + `chooser.setFiles()`。上传成功后新图排在**第 0 位**。
5. 清掉其它项的选中（**但绝不动目标项**：新上传的图会自动选中，再点一次就是反选）。
6. 点中该缩略图，断言 `…item.selected` 数量 ≥1 且目标项在列。
7. 在可见弹窗里找「下一步」（断言未被禁用），点它，等 4.5s。
8. 在可见弹窗里找「确认」/「完成」，点它，等 4.5s。
9. **断言**：`.js_cover_preview_new` 的 `background-image` 含 `mmbiz`。
10. 滚到底 → 点「保存为草稿」。改稿的 URL 本来就带 appmsgid，**不能用 URL 判断成功**。

### 9.3 判据陷阱

- `.setting-group__cover_primary` 里的「拖拽或选择封面」遮罩（`.js_share_type_none_image`）**永远在 DOM 里**，即使封面已设置，用它的文案判断会误报「未设置」。
- 图片库里可能出现多份同名封面（之前反复重试上传的残留），按文件名取第一条即可，不必清理。

### 9.4 验收方式（不用截图）

`cmd=verify` 打开每篇编辑页，取 `.js_cover_preview_new` 背景图里的 mmbiz URL，`page.fetch(url,{saveAs})` 存到 `_ego/verify/`，再用 `check_cover_color.py` 判色。

- 空封面 → 背景图里没有 mmbiz
- 已设封面 → `url("https://mmbiz.qpic.cn/mmbiz_jpg/<hash>/0?wx_fmt=jpeg")`
- 是不是设计稿 → 彩色像素占比 ≥0.05（见 R6）

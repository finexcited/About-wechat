# 发布为草稿 · 浏览器自动化规范（第七步 · ego lite 通道）

> 目标：把已生成的公众号 HTML + 封面，通过 **ego lite（ego-browser）** 自动存成**草稿**。
> 🔴 **只存草稿，绝不点「发表 / 群发」**——群发永远由用户手动完成。
> 本规范为 2026-11-02 改版：**全部浏览器动作由 ego lite（ego-browser）执行**，旧的浏览器驱动通道已整体下线删除。

## 0. 前提与铁律

- **唯一工具**：`scripts/ego_pub.mjs`（ego lite 的 Node API 脚本）。不再有第二个浏览器通道。
- **前置**：
  1. 本机已装 ego lite，`ego-browser` 在 PATH 上；**首次使用先跑 `ego-browser skill`** 读当前版本用法。
  2. 命令**非沙箱**执行（要拉起 GUI 浏览器）。
- **不需要**：独立浏览器驱动进程、手动杀浏览器、系统级「允许远程自动化」开关、会话 JSON 文件。这些随旧通道一并废弃。
- **ego-browser 不转发命令行参数**（实测 `process.argv` 只有 Node 自身路径），所以**所有输入走配置文件** `$WX_DAILY_OUT/_ego/pub_jobs.json`，输出走 stdout 的 JSON 行 + `_ego/pub_log.jsonl`。
- **ego-browser 也不继承调用方的环境变量（实测）**：`WX_TEST_PROBE=hello ego-browser nodejs -e 'console.log(process.env.WX_TEST_PROBE)'` 打出 `undefined`，同时 `process.cwd() === "/"`。所以 `WX_DAILY_OUT` / `WX_BRAND` / `WX_AUTHOR` / `WX_PUBLISH_SPACE` 在第七步**全部读不到**，这四个值只能落进 `pub_jobs.json`（`dir` / `author` / `space`）。
- **配置文件位置三级解析（命中即停，不往下兜底）**：
  1. `env WX_DAILY_OUT/_ego/pub_jobs.json`（只有直接用 `node` 跑时才有效，走 ego-browser 时必然落空）；
  2. **指针** `~/.wx-ego-dir` 的第一行 + `/_ego/pub_jobs.json`；
  3. 默认 `~/Documents/公众号推文/_ego/pub_jobs.json`。

  指针存在的唯一理由：`dir` 写在配置里，但要读配置得先知道去哪读——鸡生蛋。它记录的是「**含 `_ego` 的那个目录**」，不是产物目录；`dir` 只负责把**产物**指到别处。`python3 scripts/bootstrap.py` 会按 `WX_DAILY_OUT` 自动维护指针（`--report` 只读不写），所以自定义目录的正常流程不需要手建。
  为什么不能「找不到就退回默认目录」：一兜底就会**静默读到默认目录里的旧配置**，表现为「明明配了自定义目录，任务却跑了别的号」。所以三条都落空时脚本直接 `{"step":"abort","why":"no_config",…}` + `exit=3`，同时列出解析链、尝试过的路径与两种修法。**别再把它读成「目录不存在」**——那是旧版裸 `ENOENT` 造成的误读。
- **登录必须「先清号再扫码」（强制）**：ego 浏览器由守护进程持有，**cookie 跨任务、跨目录共享**。不清就直接跑，会**静默复用**上一次的登录态——用户以为在测新号，草稿却存进了旧账号，全程零报错。因此 `cmd=login` 默认先清 `https://mp.weixin.qq.com` 的 cookies / localStorage / sessionStorage / IndexedDB / cacheStorage / serviceWorkers，再出二维码；`cmd=article` 有前置闸门（见 §2.0）。
- **登录半自动**：二维码必须用户手机扫（AI 不能代扫）；微信常为「扫码 + 手机端点确认」两步。
- **多账号必须交用户选（强制）**：脚本检测到 ≥2 个账号即输出 `{"step":"multi_account","accounts":[…]}` 并退出，**AI 必须暂停、原样列出账号交用户选定**，绝不代选。
- 一次登录连做当天多篇，减少重复扫码。不加延时、连续发布（用户已接受风控风险）。

### 0.1 ego lite 解决了旧通道的四个硬伤

| 旧通道（v1，已下线）痛点 | ego lite 的做法 |
|---|---|
| 一个浏览器实例只绑一个会话，进程退出即 `no such window` → **登录与批量必须同进程**，断了就得重扫码 | 浏览器由守护进程持有，**TaskSpace 跨进程复用**；登录一次，任意多次脚本调用都沿用同一页面与登录态 |
| 坐标点击**必须窗口在前台**，否则事件静默丢失（要用 `osascript activate` 把窗口提到前台） | `page.mouse.click` 走 CDP Input，**与窗口前后台无关** |
| 窗口高度超过屏幕（本机 1440×900）时点击被裁掉 → 「确认」按钮落空 | 布局高度用 `Browser.setWindowBounds` 撑到 1260，点击坐标由 CDP 派发不受屏幕裁切影响 |
| 驱动进程长批次易断，重启即丢登录态 | 断点续跑：`_ego/pub_done.json` 记录已成功篇目，重跑自动跳过 |

> 仍然成立的三条老经验（与浏览器无关，勿删）：隐藏模板要按尺寸过滤、封面判据只看 `.js_cover_preview_new` 背景图、修正已存草稿＝再存一次。

## 1. 执行闸门

向用户提示："即将登录公众号后台并自动保存为草稿（不会群发），是否继续？"
→ 用户确认后才启动。

## 2. 登录

```bash
# 0) 首次使用先读 ego lite 用法
ego-browser skill

# 1) 写任务配置
#    ⚠️ `space` **必须写**（多号逐号写不同的名字）。ego-browser 读不到 WX_PUBLISH_SPACE，
#    不写就全落进「公众号发布」同一个会话——两个号互相顶掉登录态，而且不报错（串号）。
#    `dir` 只把产物指到别处，不改变配置文件位置。
#    文件位置：脚本按 env → 指针 ~/.wx-ego-dir → 默认目录 三级解析，命中即停。
cat > $WX_DAILY_OUT/_ego/pub_jobs.json <<'EOF'
{ "cmd": "login", "dir": "/你的/绝对/产物目录", "space": "发布-号A", "loginTimeout": 300 }
EOF

# 2) 执行（后台跑，因为要等扫码）
ego-browser nodejs < "$SKILL_DIR"/scripts/ego_pub.mjs
```

- 清号先于出码：脚本第一行输出 `{"step":"fresh_login","cleared":"cdp|network|browser","space":"…"}`，表示已把该浏览器里 `mp.weixin.qq.com` 的旧登录态清空（`cleared` 是实际用上的清法，`cdp` 最彻底）。**看到这行才说明这次是真扫码，不是复用。**
- 脚本输出 `{"step":"qr","file":"…/login_qr_ego.png","how":"canvas"}` → 用 `present_files` 出示，提示"请手机微信扫码（含手机端点『确认登录』）"。
  - `how=canvas`：二维码是**在页面内用 canvas 放大 4 倍导出的 PNG**，扫码识别率最高；`how=screenshot` 是兜底整页截图。
- 成功：`{"step":"login_ok","token":"1234567890","via":"qr"}`，token 写入 `$WX_DAILY_OUT/_wx_token.json`（含 `at` 时间戳与 `via` 来源），后续命令自动读取，**同一批次内无需再扫**。
- 二维码约 2 分钟过期：脚本会输出 `{"step":"qr_expired"}`，重跑一次 `login` 即刷新（不用特殊命令）。
- **不再有「已有登录态就直接 login_ok」这条捷径**（v1.0.45 移除）：那正是把草稿存进别人账号的路径。要复用只能显式 `"freshLogin": false`，并且接受 §2.0 的闸门会拦住 `article`。

### 2.0 三个登录开关与 `need_login` 闸门

| 开关（写在 job JSON 里） | 默认 | 作用 | 关掉的后果 |
|---|---|---|---|
| `freshLogin` | `true` | `cmd=login` 执行前清空 `mp.weixin.qq.com` 的全部存储与 token 文件 | 复用上一次登录态，**可能存进别人的号** |
| `requireFreshLogin` | `true` | `cmd=article` 前校验 token 新鲜度 | 闸门失效，见下 |
| `freshMinutes` | `10` | 闸门允许的最大 token 年龄（分钟） | 放得太宽＝扫码后很久才跑，中途掉线也不知道 |

闸门逻辑（`cmd=article` 开头）：读 `_wx_token.json` → ① 文件不存在 → `need_login`；② `via !== "qr"`（复用来的一律不算）→ `need_login`；③ `ageMin > freshMinutes` → `need_login`。命中任一即输出

```json
{"step":"need_login","why":"token 是复用来的（via=reuse），不是本次扫码","hint":"重跑 {\"cmd\":\"login\"} 重新扫码"}
```

并 `exit=2`。**正确处理是回去扫码**；把 `requireFreshLogin` 改成 `false` 只是把保护关掉，问题没解决。`cmd=status` 会返回 `login:{via,at,ageMin,fresh}`，跑任何发布前先看这一眼最省事。

### 2.1 多账号：必须暂停并交用户亲自选择（与 SKILL 全局铁律 #6 一致）

- 脚本输出 `{"step":"multi_account","accounts":["…","…"]}`：
  - **立即暂停**，用文字**明确列出全部可选账号**（分类、昵称、状态如冻结）。
  - **交用户亲自选择**；AI **在任何环节都不得自行判断或替用户决定**。
  - 用户选定后，用 ego lite 点该账号，再跑一次 `cmd=login` 收 token（已登录过通常直接进后台）。
- 脚本输出 `{"step":"login_timeout"}` 且**没有** `multi_account`：先问用户是否看到了账号选择页，不要机械重试。

### 2.2 token 复用与登录态核验

- token 落盘在 `_wx_token.json`：`{token, at, via, space}`。`article` / `cover` / `verify` 都从文件读。
- **`via` 是关键的诚实标记**：`"qr"` ＝本机本次真的扫码了；`"reuse"` ＝从已有 cookie 里抠出来的。闸门（§2.0）只认 `qr`——这不是形式主义，「复用」正是那个会静默存错账号的来源。
- `cmd=status` 返回 `login:{via, at, ageMin, fresh}`，`fresh` 为 `false` 说明这批 `article` 会被闸门拦。**发之前先跑一次 status，比事后翻草稿箱省事。**
- 被踢线 → 重跑 `cmd=login` 重新扫码。ego 浏览器不需要 kill、不需要清 session 文件。

## 3. 逐篇循环

### 3.1 一条命令跑完整个批次

```bash
# 写批次配置（base 即 标题_YYYY-MM-DD，与 $WX_DAILY_OUT 下的文件名对齐）
# 注意：**author 必须写**——ego-browser 读不到 WX_AUTHOR / WX_BRAND，
#       不写署名就退化成占位值「你的公众号」（脚本会打 warn: author_placeholder）。
#       要「有意不填作者」写 "author": ""（空串 ≠ 没写，空串是有意的）。
#       space 同样必写，多号逐号不同，否则串号。
cat > $WX_DAILY_OUT/_ego/pub_jobs.json <<'EOF'
{ "cmd": "article", "dir": "/你的/绝对/产物目录", "author": "你的笔名", "space": "发布-号A", "resume": true,
  "jobs": [ {"base":"标题A_2026-11-02"}, {"base":"标题B_2026-11-02"} ] }
EOF

ego-browser nodejs < "$SKILL_DIR"/scripts/ego_pub.mjs
```

- **整批放在同一次调用里跑**：ego 的页面常驻，一批跑完再结束最省时间，也不会出现半截状态。
- `resume: true`（默认）：`_ego/pub_done.json` 里已成功的 base 直接跳过，断点续跑不重复存草稿。
- 每篇输出一行 `{"step":"article", …}`，字段含义：
  `title.ok` / `author.ok` / `paste.ok` / `images{expect,bodyImgs,mmbiz}` / `summary.now` / `cover{ok,why}` / `save{appmsgid,url,how}` / `status`。

**配置字段一览（`pub_jobs.json`）**

| 字段 | 适用命令 | 默认 | 说明 |
|---|---|---|---|
| `cmd` | 全部 | `status` | `login` / `article` / `cover` / `verify` / `status` / `close`（另有 `author`） |
| `dir` | 全部 | `WX_DAILY_OUT` → `~/Documents/公众号推文` | **产物目录**，建议写绝对路径。⚠️ 它只决定产物落哪儿，**不决定配置文件在哪读**（那是下文三级解析管的事）。env 在 ego-browser 通道下读不到，所以不写它就等于用默认产物目录 |
| `freshLogin` | `login` | `true` | 出码前**清空 `mp.weixin.qq.com` 的全部浏览器存储 + 删 token 文件**。设为 `false` 会复用上次登录态（可能存进别人的号），仅在明确要复用同一号时用 |
| `requireFreshLogin` | `article` | `true` | 前置闸门：token `via≠qr` 或超龄即 `need_login` + `exit=2` |
| `freshMinutes` | `article` | `10` | 闸门允许的 token 最大年龄（分钟） |
| `space` | 全部 | `公众号发布`（env 通常读不到） | **这个号的浏览器会话身份**，不是标签名。取值：**这里写了就用这里 → 否则取 `WX_PUBLISH_SPACE` → 再否则「公众号发布」**。⚠️ ego-browser **不继承调用方环境变量**，所以 `WX_PUBLISH_SPACE` 在第七步实际读不到——**这一项必须写**，不写就所有号共用「公众号发布」一个会话，登录态互相踢掉且**不报错**（串号）。**多号逐号不同**（建议 `发布-<号简称>`）；`accounts.sh add --space` 会写进号配置，`accounts.sh check` 会点名报出「两号共用同一会话」 |
| `jobs` | `article`/`cover`/`verify` | `[]` | `[{base, appmsgid}]`；`appmsgid` 缺省时从 `_ego/pub_results.json` 补 |
| `token` | 全部 | 读 `_wx_token.json` | 显式覆盖登录 token |
| `author` | `article`/`author` | 占位值「你的公众号」 | 草稿作者署名（onboarding Q28）。**三种取值语义不同**：不写＝env 兜底，而 env 在第七步读不到，于是落到占位值（脚本会打 `warn: author_placeholder`）；`""`＝**有意不填作者**；写了具体值＝就用它。⚠️ 关键词是「写了 vs 没写」，不是「空 vs 非空」——代码用 `typeof cfg.author === "string"` 判，所以 `""` 不会被当成「没配」。**多号逐号不同**时用 `accounts.sh add --author` 写进号配置 |
| `resume` | `article` | `true` | 跳过已成功篇目 |
| `haltAfter` | `article` | `2` | **连续**失败几篇就停机（Q30）。`0` ＝不停机，全批次跑完再统一处理。⚠️ 判的是「连续」：中间成功一篇就归零——用累计计数会把两处孤立故障误判成环境坏了，也解释不了「为什么第 4 篇才停」 |
| `cover` | `article` | `true` | 存草稿时是否顺带设封面 |
| `forceCover` | `article`/`cover` | `cover` 命令为 `true`，`article` 为 `false` | **已有封面也重设**。封面"存在但不是设计稿"（被微信首图顶替）时 `coverOk` 为 true，不加这个开关永远修不好 |
| `loginTimeout` | `login` | `300` | 等扫码的秒数 |
| `imageTimeout` | `article` | `120` | 等图片转存 mmbiz 的秒数 |

### 3.2 单篇内部流程（`cmdArticle`）

1. `openEditor`：带 token 的编辑器 URL 直开（新稿用 `isNew=1`，改稿带 `appmsgid`），等 `[contenteditable]` ≥3，再 `dismissModals` 摘掉「话题卡片」引导弹窗。
2. `fillTitle`：标记可见的 `[data-placeholder='请在这里输入标题']` → 真实点击 → `keyboard.type`（**JS 写 textContent 微信不采纳**）→ 断言前 6 字；失败依次退 `keyboard.paste` → `keyboard.insertText`。
3. `fillAuthor`：`#author` 用 `page.fill`；失败退「点击 + 全选 + 输入」。回读后**全等**比较（`now.trim() === author.trim()`）——后台若对超长署名做截断、或把全角空格规范化，就会稳定返回 `authorOk:false`，**这不是没填上**，先看 `author` 里回读到的值再判断。署名尽量短。
4. `pasteHtml`：HTML 读成 base64 → 按 400KB 分块累加进 `window.__b64` → 页面内 `atob` + `TextDecoder` + **合成 paste 事件（clipboardData 属性挂载，不是构造器传参）** 注入正文。**禁止** `atob→Blob`、**禁止** `navigator.clipboard.write`。
5. `waitImages`：正文含图时轮询 `img[src*=mmbiz]` 直到全部从 data-URI 转存为 CDN。**5MB 级长图实测要 60s 以上**（`imageTimeout` 默认 120s），超时后保存会失败。
6. `fillSummary`：取 Markdown 正文第 2 段 → **剥掉 `**`、反引号、`#`、链接语法** → ≤120 字 → 填 `#js_description`。（旧实现不剥 Markdown 记号，摘要里会带出 `**`，已修。）
7. `setCover`：见 §3.4。**必须在保存前完成**。
8. `saveDraft`：滚到底 → 点「保存为草稿」→ 轮询 URL 出现 `appmsgid=`（新稿判据）或 toast 出现「成功/已保存」（改稿判据），最长 25s。

> **点击策略**：优先真实鼠标（`page.mouse.click`，先 `scrollIntoView` 再取按钮中心）；按钮不在视口内时才退回页内 `click()`。微信新版编辑器对「页内派发事件」和「真实鼠标」都能响应，ego 下不需要一律强行派发事件。

### 3.3 元素定位（关键：不靠快照）

微信编辑器大量自定义组件，无障碍树里看不到封面卡、候选缩略图。**一律用 DOM 查询**：

- 可编辑元素：`document.querySelectorAll('[contenteditable]')`
  - 正文：按 `data-placeholder` **含「正文」**定位（不用下标猜）；标题：`[data-placeholder='请在这里输入标题']`。
- 作者 `#author`；摘要 `#js_description`。
- 封面卡 `.js_cover_btn_area`（页面共 3 个，取 `width>50` 的可见实例）；封面预览 `.js_cover_preview_new`。
- 图片库弹窗 `.weui-desktop-dialog__wrp.weui-desktop-dialog_img-picker`；缩略图 `.weui-desktop-img-picker__item`。
- **页面上同时存在「未实名」「未设头像」「切换账号」等 w=0 的隐藏模板弹窗**：`querySelector` 取第一个必错，一律 `getBoundingClientRect().width` 过滤。

### 3.4 封面（⚠️ 必须在保存前完成，且必须逐篇断言）

**结论：走「图片库 → 上传本地 PNG → 选中缩略图 → 下一步 → 确认」，不要往正文里粘封面图。**

| 步 | 动作 | 要点 |
|---|---|---|
| 0 | `Browser.setWindowBounds` 撑到 1460×1260，并用 `markBtn` 逐级滚动祖先容器 | 窗口高度会被屏幕高度钳制（本机 1440×900 实测只到 ~715），所以**不能只靠撑窗口**：必须同时 `scrollIntoView` + 逐级 `scrollTop` 把「确认」推进视口（`Emulation.setDeviceMetricsOverride` 只改视觉视口不改布局，无效） |
| 1 | 页内 `a.js_imagedialog.click()` | **不要** hover `.js_cover_btn_area` 再点 `.pop-opr__item`：那个悬浮菜单是 `visibility:hidden;opacity:0`，`elementFromPoint` 会命中背后的摘要框 |
| 2 | 等 `.weui-desktop-img-picker__item` 出现 | 弹窗宽度 >300 才算打开；4 个 tab：最近使用 / 我的图片 / 未分组 / AI配图 |
| 3 | 按文件名找 `{base}_封面.png`；没有就 `page.setInputFiles` 上传 | 上传兜底：点「上传文件」+ `waitForFileChooser` → `chooser.setFiles()`；上传后新图排在第 0 位 |
| 4 | **点中缩略图本体**（真实鼠标），断言 `class` 变 `…item selected` | 未选中时「下一步」带 `weui-desktop-btn_disabled`，点了没反应 |
| 5 | 点「下一步」（不是「确定」，「确定」只在隐藏模板里） | 先清掉其它项的选中，但**绝不动目标项**（新图会自动选中，再点一次是反选） |
| 6 | 裁剪弹窗点「确认」/「完成」 | 弹窗标题「编辑封面 2.35:1 / 1:1」 |
| 7 | 断言 `.js_cover_preview_new` 的 `background-image` 含 `mmbiz` | **唯一可信判据** |

判据陷阱：
- `.setting-group__cover_primary` 里的「拖拽或选择封面」遮罩（`.js_share_type_none_image`）**永远在 DOM 里**，用它判断会误报「未设置」；`cover_primary img` 也可能恒为 `null`。
- 旧版「把封面贴进正文再选默认首图」已废弃：会在正文留下 900×383 多余图片，且 `.js_share_type_image` 是 `display:none` 点不到。
- 微信若发现封面缺失，保存时**可能自动拿正文首图当封面**（表格 PNG 卡片 → 看起来像"灰白封面"）。这类"有封面但不是设计稿"的情况 `coverOk` 会是 true，**必须用 `cmd=cover`（默认强制重设）**，不能因为判据通过就放过。

### 3.5 原创 / 留言（未自动化，保持原状）

- 原创声明、留言精选、合集、原文链接：脚本**不处理**，留默认。需要时由用户在后台手动勾选。
- 未开通原创或额度用尽：直接跳过，台账标记。

### 3.6 保存与断言

- 新稿：URL 由 `isNew=1` 变成带 `appmsgid=` → 成功；`appmsgid` 写回 `_ego/pub_results.json`。
- 改稿（已带 appmsgid）：URL 不变，用 toast「成功/已保存」+ 重开核验判断。
- 脚本同时打印 `state`（title/author/desc/bodyLen/bodyImgs/mmbiz/coverBg），台账直接引用。

## 4. 存完必须核验（不要只看保存成功）

保存成功 ≠ 封面正确。**跑两条只读核验**：

```bash
# 1) 逐篇冷加载编辑页，取服务端封面图落盘（_ego/verify/*_cover_server.png）
cat > $WX_DAILY_OUT/_ego/pub_jobs.json <<'EOF'
{ "cmd": "verify", "jobs": [ {"base":"标题_2026-11-02","appmsgid":"100002766"} ] }
EOF
ego-browser nodejs < "$SKILL_DIR"/scripts/ego_pub.mjs

# 2) 判定是不是「彩色封面」（彩色像素占比，不靠肉眼逐张比）
python3 \
  "$SKILL_DIR"/scripts/check_cover_color.py --dir $WX_DAILY_OUT/_ego/verify
```

- `check_cover_color.py` 判据分两层，别混：① **什么算一个「彩色像素」**——饱和度 ≥0.30 且明度 ≥0.15；② **多少占比算合格**——≥0.05 彩色 / 0.02—0.05 弱彩（多为白底截图）/ <0.02 无彩色（空封面）。退出码 0 全部合格、1 有不合格、2 无法检查（目录空、参数自相矛盾）。
- **参考值（实测，不是阈值）**：浅色版式 0.15—0.23、深底版式 0.80+、白底表格图与空封面 <0.02。合格线刻意压得比实测低，留了余量——**别把 0.15 当门槛**去卡。
- **要改阈值**：`--colorful` / `--weak` / `--sat-min` / `--val-min`（默认即上面四个数）。改前先拿自己现有封面跑一次基线，否则很容易调到「永远通过」。`--json` 会在 `thresholds` 里回显生效值，**退出码与文本模式一致**（原来恒 0，用它做自动化等于没检）。
- 偏灰或非彩色 → 用 `cmd=cover` 对该篇重设封面（该命令**默认强制重设**，不会因为"已有封面"就跳过），再核验一次。
- 只想看某一篇：`--dir` 换成单文件路径即可。

## 5. 失败策略

- **单篇失败**：跳过 + 台账记原因，继续下一篇。
- **连续 N 篇失败**（`haltAfter`，默认 2）：脚本输出 `{"step":"halt", "why":"连续 N 篇失败…", "hint":…}` 并**立即停止**，交用户确认。已成功的篇目记在 `_ego/pub_done.json`，重跑 `resume=true` 会跳过，不会重复存草稿。
- **`0` ＝不停机**：整批跑完，用 `{"step":"done", "fails":N, "streak":M, "halted":0}` 统一汇报。
- **什么算「一篇失败」**：`no_editor`（编辑器打不开）· 保存后 URL 没有 `appmsgid` · 标题或正文断言不过（`status:"check"`）· 抛异常。四类都计入 `streak`。
- **停机只作用于 `cmd=article`（批量存稿）**：`cover` / `author` 是单点补救命令，失败就记一笔继续，不会中断——补救到一半停下来反而更难收拾。
- 判定标准（全部 DOM/URL，不靠肉眼）：保存成功＝URL 含 `appmsgid`；图片上传成功＝`mmbiz` 数 == HTML 中 `<img>` 数；封面成功＝`.js_cover_preview_new` 背景含 `mmbiz` 且核验图判定为彩色。

## 6. 台账

生成 `$WX_DAILY_OUT/00_发布台账_YYYY-MM-DD.md`：

| 序号 | 标题 | 草稿链接 | 保存时间 | 封面 | 核验 | 备注 |
|---|---|---|---|---|---|---|
| 1 | … | …appmsgid=… | … | ✅/⬜ | 彩色/偏灰 | … |

## 7. 收尾

- `{"cmd":"close"}` → 脚本归档当前 URL/token 并调用 `task.finish({keep:true})`，**页面保留**（下次少一次冷启动；但登录态仍会被下次 `login` 的 `freshLogin` 清掉，这是有意的）。
- ego 由守护进程管理浏览器，**不需要**手动杀进程、**不需要**删会话文件（这两条是旧通道时代防僵尸进程的做法，已废弃）。
- 汇报台账与失败清单；**不群发**。

## 8. 已知风险 / 待实机确认

- 微信改版会让选择器失效（本规范已尽量用 DOM 查询而非快照/ref，降低脆弱性）。
- 批量时编辑器会周期性自动保存，失败重跑可能在草稿箱留残留条目；收尾时核对草稿数与成功数。
- 原创声明、留言、合集不在自动化范围内。
- **`Storage.clearDataForOrigin` 的覆盖面**：已实测能清掉 `mp.weixin.qq.com` 的 cookie 让页面回到未登录态；若某个版本的 ego 不支持该 CDP 域名，脚本会依次降级为 `Network.getCookies` + 逐条 `deleteCookies`、再降级为 `clearBrowserCookies`，并在 `fresh_login` 的 `cleared` 字段里写明用的哪一种。**看到 `cleared:"browser"` 时最好人工确认一次页面确实在要扫码**。
- 基线：2026-11-02 批次 10 篇（含表格 PNG 卡片）在旧通道跑通；ego 通道的 `login / verify` 已于同日实测通过，`article / cover` 待下一次真实批次验证。**2026-11-04 端到端首跑（库外真实账号）已跑通 `login → article → 存草稿`**：单篇 848 字、封面 900×383 无裁切，草稿 `appmsgid 100002996`，`status: success`；该次跑出的 4 个缺陷已在本版全部修掉（env 不继承 → 写 `dir`；0 插图 → `MIN_ILLUS`；静默复用登录态 → `freshLogin`；`收藏/转发` 文案与逻辑不符 → 已订正）。

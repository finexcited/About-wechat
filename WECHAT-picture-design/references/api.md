# 接口要点

## 1. Redfox（素材采集）

鉴权：请求头 `REDFOX_API_KEY` 或 `X-API-KEY`；成功码 `code=2000`；`3210/3201` 为积分不足。

| 用途 | 方法 | 路径 | 关键参数 |
|---|---|---|---|
| 公众号爆款 | POST | `/story/api/gzh/search/hotArticleNew` | `keyword`、`startDate`、`endDate` |
| 小红书检索 | POST | `/story/api/xhs/search/search` | `keyword`、`pageNum`、`pageSize`、日期 |
| 小红书详情 | POST | `/story/api/xhs/search/noteDetail` | `noteId`（返回 `noteType`：normal=图文 / video） |
| 全网热点 | POST | `/story/api/hotKeyword/list` | `startDate`、`endDate`（仅近 7 天有效） |

字段差异：
- 公众号：`title/summary/clicksCount/likeCount/shareCount/commentsCount/imageUrl`
- 小红书：`title/desc/likedCount/collectedCount/commentsCount/cover`
- 热点：`title/hotId/maxHotScore/platName`（无正文，仅选题信号）

## 2. 微信公众号草稿（贴图）

`POST /cgi-bin/draft/add`，`article_type = "newspic"`。

| 字段 | 说明 |
|---|---|
| `title` | ≤32 字（网页编辑器上限 20 字，以 20 为准） |
| `content` | 纯文本 ≤20000 字符；话题用 `#话题#` 写在正文 |
| `image_info.image_list[].image_media_id` | 永久素材 ID，**必须**来自 `cgi-bin/material/add_material?type=image` |
| `cover_info.crop_percent_list` | 裁剪比例：`1_1` / `16_9` / `2.35_1`；首图即封面 |

配套接口：
- `GET /cgi-bin/token?grant_type=client_credential&appid=&secret=` → `access_token`（需 IP 白名单）
- `POST /cgi-bin/material/add_material?type=image`（multipart，字段名 `media`）→ `media_id`

常见错误：
- `40007 invalid media_id`：用了 `media/uploadimg` 的 URL 或未上传永久素材
- `45003`：标题超限
- `40164 / 61004`：调用方 IP 不在白名单

## 3. 网页端操作要点（ego-browser）

- 贴图编辑器地址：`/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1&type=77&createType=8&token=<token>`
- 上传：先点「选择或拖拽图片」开菜单，再按坐标点「本地上传」（元素被 label 遮挡，直接 click 会失败）
- 编辑器是 ProseMirror：先 `focus()` 再 `keyboard.insertText`；换行需逐段 `press("Enter")`
- 草稿删除：悬停卡片 → 点「删除」→ 弹窗内再点**「删除」**（不是「确定」）

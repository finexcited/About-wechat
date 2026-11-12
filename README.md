# wechat · 公众号内容生产技能合集

一个仓库放三个**互相独立**的 Agent Skill（技能包）：
两个负责公众号内容生产，一个负责抖音 / 小红书视频素材采集与语音本地化。可以单装，也可以按需组合使用。

| 目录 | 技能 | 做什么 | 状态 |
|---|---|---|---|
| [`wechat-daily/`](wechat-daily/) | 公众号日更自动化 | 选题 → 创作 → 润色 → 长图/HTML → 封面 → 质检 → 存草稿，一条流水线跑完当天 N 篇推文 | V1.0，macOS 完整验证 |
| [`WECHAT-picture-design/`](WECHAT-picture-design/) | 公众号贴图设计 | 采集素材 → 改写短文案 → 按设计哲学批量出 3:4 贴图（含 LOGO）→ 六项自检 → 写草稿箱 | v2.2.2 |
| [`douyin-xhs-video-harvest/`](douyin-xhs-video-harvest/) | 抖音 / 小红书视频采集 | 风格检索 → 竖屏 1080P+ 筛选 → 无水印下载 → 人声删除或目标语言 AI 配音 → 元数据清理 | V1.0 |

---

## 快速开始

三个技能都是「一个目录 = 一个技能包」，安装方式相同——把子目录整个拷到 WorkBuddy / Codex 的技能目录即可：

```bash
git clone https://github.com/finexcited/About-wechat.git
cd About-wechat

# 装日更技能
cp -R wechat-daily ~/.workbuddy/skills/wechat-daily

# 装贴图技能（也可以直接用子目录里的 install.sh）
cp -R WECHAT-picture-design ~/.workbuddy/skills/WECHAT-picture-design
bash WECHAT-picture-design/install.sh --verify    # 环境与脚本自检

# 装视频采集技能
cp -R douyin-xhs-video-harvest ~/.workbuddy/skills/douyin-xhs-video-harvest
```

装好后在对话里直接说需求即可，例如「用 WECHAT-picture-design 做 6 篇贴图」「用 wechat-daily 出今天的 3 篇」。

---

## 目录约定

```
.
├── LICENSE
├── README.md                 ← 本文件
├── wechat-daily/             ← 技能 1：公众号日更
│   ├── SKILL.md              ← 技能主文档（Agent 读它执行）
│   ├── README.md             ← 使用说明
│   ├── CHANGELOG.md
│   ├── VERSION
│   ├── assets/ docs/ references/ scripts/
│   └── requirements.txt
├── WECHAT-picture-design/    ← 技能 2：公众号贴图
│   ├── SKILL.md
│   ├── README.md             ← 用途/结构/依赖/使用方式
│   ├── docs/setup-questionnaire.md   ← 12 题初始化问卷
│   ├── assets/ references/ scripts/
│   ├── install.sh
│   └── requirements.txt
└── douyin-xhs-video-harvest/ ← 技能 3：抖音 / 小红书视频采集
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── references/
    └── scripts/
```

两条约定：

1. **一技能一子目录**，子目录内部路径一律相对，整体搬迁不会断链；
2. **运行产物与凭据不入库**（见 `.gitignore`）：`__pycache__`、`*.zip`、`_wx_token.json`、`_ego/`、日志等。

---

## 技能的差别（选哪个）

| 场景 | 用哪个 |
|---|---|
| 每天要发**图文长文**，需要长图、封面、排版 | `wechat-daily` |
| 要发**图片消息（贴图）**，一次 3–9 张竖版图 + 极短文案 | `WECHAT-picture-design` |
| 要采集抖音 / 小红书竖屏素材，并按需删除人声或生成目标语言配音 | `douyin-xhs-video-harvest` |
| 多个场景都要用，但内容不重叠 | 按需安装，各跑各的流水线 |
| 没有 REDFOX Key | 贴图技能支持纯 RSS 通道（见其 `docs/setup-questionnaire.md` Q11） |

---

## 平台与边界

- 三个技能都在 **macOS** 上完整验证；公众号自动存草稿依赖 ego lite 桌面端，视频采集依赖 ego lite 登录态。
- 公众号技能遵守同一条底线：**只存草稿，不群发**。
- 公众号采集与改写只取选题信号，成稿重写（默认卡 15% 字面重合），配图重绘，不搬运原文与图片。
- 视频采集只处理用户有权使用的内容；发布、商用或二次分发前仍需由用户确认素材授权。

## License

见 [LICENSE](LICENSE)。

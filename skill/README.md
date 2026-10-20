# 小红书单篇 Skill · 引擎 A（匿名快读）

把一条小红书分享链接抓成结构化 Markdown：正文、原图、官方字幕；无字幕视频可选用本地 Whisper 转写。**匿名、免登录、单篇**。

本目录是 [xhs-curator](../README.md) 仓库里的 Skill 发布包；批量采集、博主评论、Obsidian 导出由仓库根目录的引擎 B 负责。

> **标准安装 = 克隆仓库 → `python install.py`**（在仓库根运行，自动复制本 Skill 到 Agent 技能目录并写入仓库位置标记）。
> 仅复制本目录的安装**只支持单篇速读**，不能用于主页批量采集。

## 能力边界

| 能做 | 不做 |
|---|---|
| 单篇图文/视频直抓 | 博主主页整号列表 |
| 正文、原图、官方字幕 | 博主评论 |
| 无字幕视频本地转写（可选） | 关键词搜索 |

**默认最小依赖**：只想快速单篇入库时，用本 Skill；需要评论或批量时，走引擎 B。

## 安装

**标准安装（完整功能）** = 克隆 xhs-curator 仓库 → 在仓库根运行 `python install.py`
（详见仓库 README 的「标准安装」一节；`--skill-dir` 可显式指定你所用 Agent 的技能目录，
未指定时若能可靠识别会自动选择，识别不了会列出各 Agent 的目录让你选）。

**受限安装（仅单篇速读）**：只把本目录复制到你所用 Agent 的技能目录
（目录名 `xhs-curator`），例如 Codex 的 `~/.codex/skills/xhs-curator/`。
⚠️ 这种方式**只支持单篇速读**（匿名单篇链接 → Markdown），
**不能用于主页批量采集**——批量能力依赖仓库根目录的完整工具链。

依赖：

```bash
pip install -r requirements.txt
```

无字幕视频本地转写是可选能力：

```bash
pip install "faster-whisper>=1.0.0" "av<15"
```

> `av>=15` 与 faster-whisper 1.2.1 不兼容，必须锁在 15 以下。

## 用法

在仓库根目录执行：

```bash
python skill/scripts/fetch_xhs_note.py "<分享链接>" "<输出目录>"
```

支持 `xhslink.cn` 短链、`explore` / `discovery` 链接，以及整段分享文字。产出：

```
<输出目录>/
├── metadata.json     # 标题/作者/正文/图片 URL/字幕 URL
├── imgs/note_01.jpg  # 原图
├── subtitle.srt      # 官方字幕（若有）
└── transcript.txt    # 本地转写（无字幕且安装了 faster-whisper）
```

常用参数：

```bash
python skill/scripts/fetch_xhs_note.py "<链接>" "<输出目录>" --no-asr
python skill/scripts/fetch_xhs_note.py "<链接>" "<输出目录>" --whisper-model small
```

## 交付物与接入 Obsidian

**单篇成功后直接产出 `.md` 文稿**（`<输出目录>/<标题>.md`：正文 + 图片相对引用 `imgs/` + 字幕/转写；视频封面留档不进文稿）——文件夹一起保存即可阅读、可分发。

要存入 Obsidian 时（**无需重抓、无需登录**）：

```bash
# 1. 引擎 A 原料包本地转成 downloads/ 契约（只转换已有数据，不访问小红书）
python skill/scripts/to_downloads.py "<引擎A输出目录>"

# 2. 用仓库根的导出器写进 Obsidian
python xhs_export_md.py --dest "<你的 Obsidian 库目录>"
```

需要博主评论时，改用引擎 B（评论是登录态独占能力）：

```bash
python xhs_fetch_selected.py --url "<链接>"
python xhs_export_md.py --dest "<你的 Obsidian 库目录>"
```

## 已知限制

- 小红书会做频率风控：短时间密集请求会返回降级页。脚本已带节流、退避与降级检测，仍请低频使用。
- 页面结构随时可能改版；脚本兼容 `note.data.noteData` 与旧 `noteDetailMap`，改版后需跟进。
- 分享链接里的 `xsec_token` 会过期，失败时请从 App 重新分享。

## 免责声明

仅供个人学习与研究，请遵守平台用户协议，自行控制访问频率，不要用于商业采集或传播受版权保护的内容。

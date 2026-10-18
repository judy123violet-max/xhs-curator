# AnyLink to Note · 引擎 A

把一条小红书分享链接抓成结构化 Markdown：正文、原图、官方字幕；无字幕视频可选用本地 Whisper 转写。**匿名、免登录、单篇**。

本目录是 [xhs-curator](../README.md) 仓库里的 Skill 发布包；批量采集、博主评论、Obsidian 导出由仓库根目录的引擎 B 负责。

## 能力边界

| 能做 | 不做 |
|---|---|
| 单篇图文/视频直抓 | 博主主页整号列表 |
| 正文、原图、官方字幕 | 博主评论 |
| 无字幕视频本地转写（可选） | 关键词搜索 |

**默认最小依赖**：只想快速单篇入库时，用本 Skill；需要评论或批量时，走引擎 B。

## 安装

把本目录复制到你所用 Agent 的 skills 目录（例如 Codex 的 `~/.codex/skills/xhs-note-reader/`），或在仓库内直接调用脚本。

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

## 接入 Obsidian（引擎 B 的导出管线）

```bash
# 1. 引擎 A 产物转成 downloads/ 结构
python skill/scripts/to_downloads.py "<引擎A输出目录>"

# 2. 用仓库根的导出器写进 Obsidian
python xhs_export_md.py --dest "<你的 Obsidian 库目录>"
```

需要博主评论时，改用引擎 B：

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

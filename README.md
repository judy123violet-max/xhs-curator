<div align="center">

# xhs-curator

**简体中文 | <a href="README_EN.md">English</a>**

[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue?style=flat-square&logo=python&logoColor=white)](#-快速开始)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat-square)](#-快速开始)
[![GitHub stars](https://img.shields.io/github/stars/judy123violet-max/xhs-curator?style=flat-square&color=fda7df)](https://github.com/judy123violet-max/xhs-curator/stargazers)

<p>🔥 <b>把小红书笔记「看完再挑、挑完再导」地收进 Obsidian</b></p>

</div>

---

> **⚠️ 免责声明**
>
> 本项目仅供**个人学习与研究**使用，请勿用于任何商业用途或规模化抓取。使用者需自行遵守《小红书用户协议》与相关法律法规，控制访问频率；因使用本项目产生的一切后果由使用者自行承担。详见文末「免责声明」。

## 📖 项目简介

一个把小红书笔记采集进 Obsidian 知识库的**可视化流水线**。

它和「贴一个链接就导入」的工具不同：它先把你关心的博主主页或搜索结果**摆出来给你看**，你点到哪篇存哪篇；然后把挑中的笔记抓下来——正文、原图、**博主本人的评论**，图片里的干货文字也转录成可检索的文字，最后按 Obsidian 规范落库，打开就能用。

**适合谁**：把小红书当信息源、需要长期沉淀到知识库的人（求职面经、行业经验、教程干货、竞品观察）。

### 🔧 技术原理

- **复用本机登录态**：Playwright 驱动真实 Chrome，扫码登录一次，登录态持久化在本地，不接触账号密码
- **不逆向签名**：直接读页面内存里的官方数据结构，避开加密参数逆向
- **列表双源采集**：首屏 SSR 直出数据 + 滚动加载的接口数据合并去重，**不漏最新一整屏**
- **评论按人过滤**：监听官方评论接口，只保留博主本人的发言（常藏干货补充）
- **断点续导**：中断后重跑自动跳过已完成笔记，适合分批、低频采集

## 🎁 你会得到什么

一篇导出成品（真实格式，内容已省略）：

```markdown
---
title: "面试讲项目其实也是一种“渐进式披露”"
author: "某博主"
published: 2026-08-06          # 原帖发布时间
created: 2026-10-15            # 抓取入库时间
description: "讲项目要像写 skill 一样，也是要渐进式披露……"
source: "https://www.xiaohongshu.com/explore/…"    # 原文链接，随时可回原帖
tags:
  - 小红书
  - 面试技巧
  - 渐进式披露                # 正文里的 #话题 自动收进 tags
类型: 图文
点赞: "465"
---

## 正文

最近准备面试的时候突然感到：讲项目要像写 skill 一样，也是要渐进式披露……
01｜总结了一个项目介绍结构：……
（全文照搬，去掉 #话题[话题]# 标签和 @提及，不留噪音）

## 图片与文字转录

![[_附件/01_面试讲项目…/img_01.jpg]]

### img_02.jpg
![[_附件/01_面试讲项目…/img_02.jpg]]
（这张图上的干货文字逐字转录，小标题、列表、Prompt 原文都在）
（自拍、风景类配图则只保留图片，不写任何说明）

## 博主的评论

> 03｜怎么埋词和钩子：现在我们已经把概括&细节都准备好了……
（正文写着“写不下了放评论区”，评论区的完整补充也帮你抓回来了）
```

一句话：**正文 + 图片里的干货文字 + 博主在评论区的补充**，三样都进库，标题不带 emoji，正文不带标签噪音。

## 📸 界面预览

![采集工作台](docs/images/picker.jpg)

工作台是一个本地网页，三个入口常驻同一页面：**博主主页 / 关键词搜索 / 已抓笔记**。卡片式浏览，支持全选 / 反选 / 仅视频 / 仅图文 / 关键词过滤，抓过的笔记自动打「已抓过」标记；**点卡片 = 勾选**，**点标题或「原文↗」= 在内嵌详情页看原文**（按 `Esc` 或左上角「← 返回列表」回来，勾选不丢）。

## ✨ 功能特性

**发现与采集**

- ✅ 采集工作台三入口常驻：博主主页 / 关键词搜索 / 已抓笔记
- ✅ 抓取博主主页全部笔记（主页链接 / 分享短链 / 用户ID 均可）
- ✅ 页内直接关键词搜索，不用另开终端
- ✅ 可视化勾选：全选 / 反选 / 仅视频 / 仅图文 / 关键词过滤 / **全选未抓**
- ✅ 抓过的笔记自动打「已抓过」标记，与本地抓取记录对账
- ✅ 窗口内预览原文，勾选状态自动保存不丢
- ✅ 勾完点「开始抓取」：后台自动跑抓取脚本，日志实时滚动，抓完自动刷新标记
- ✅ 抓取正文、原图，视频自动取官方字幕
- ✅ 只抓博主本人的评论（含子评论、置顶）
- ✅ 断点续导：中断后重跑自动跳过已完成项

**加工与导出**

- ✅ 图片文字 OCR 三级分级（干货逐字转录 / 界面留要点 / 照片只留图）
- ✅ 清洗正文：#话题 收进 frontmatter tags、去 @提及、去多余符号
- ✅ 标题自动去 emoji，文件名安全化
- ✅ Obsidian 规范导出：frontmatter + `![[wikilink]]` 附件目录

## 🆚 与同类工具的差异

| 项目 | 形态 | 输入 | 先看再挑 | 图片文字 | 博主评论 | 导出目标 |
|---|---|---|---|---|---|---|
| **xhs-curator** | 可视化工作台 + 脚本 | 博主主页 / 关键词 | ✅ 勾选式浏览 | ✅ OCR 分级 | ✅ 只抓博主发言 | Obsidian 库 |
| xhs-importer-pro | Obsidian 插件 | 单篇分享链接（可批量） | ❌ 贴链接即导 | ❌ | ❌ | Obsidian |
| feedgrab | 命令行 | 单 URL（多平台） | ❌ | 视频走语音转录 | ❌ | 通用 Markdown |
| XHS-Downloader | 命令行 / 用户脚本 | 作品链接、账号列表 | ❌ 列表提取后全量 | ❌ | ❌ | 本地文件 |
| MediaCrawler | 命令行爬虫 | 关键词 / 创作者主页 | ❌ | ❌ | 全量评论（非只看博主） | JSON / 数据库 |

**差异一句话**：别人解决「把某一篇或某一批存下来」，本项目解决「从一个博主的整号里，把值得存的挑出来，连图片干货和评论补充一起洗干净入仓」。

## 🔗 支持的输入

| 你手上有什么 | 用哪个 | 产出 |
|---|---|---|
| 博主主页链接 / 分享短链 / 用户ID | `xhs_creator_fetch.py` | `notes.json`（笔记列表） |
| 关键词 | `xhs_search_fetch.py` | `search_notes.json` |
| 单篇帖子链接 | ☑️ 计划中（见开发计划） | — |

两个入口都内置在采集工作台里（切页即用）；`--notes` 参数仍可自定义清单源。

## 🚀 快速开始

### 环境要求

| | 要求 |
|---|---|
| Python | 3.10 或更高 |
| 浏览器 | 本机安装 Chrome |
| 账号 | 一个小红书账号（**首次运行弹窗扫码，一次即可**，登录态存 `browser_profile/`，工具不接触密码） |

### 1. 安装依赖

```bash
pip install -r requirements.txt
python -m playwright install chrome
```

### 2. 抓取笔记列表

```bash
# 首次运行会弹出 Chrome 窗口，扫码登录（最多等 10 分钟）
python xhs_creator_fetch.py https://www.xiaohongshu.com/user/profile/xxxx
```

或者按关键词发现：

```bash
python xhs_search_fetch.py --keyword "AI产品经理 面试" --count 40
```

### 3. 打开采集工作台

```bash
python xhs_picker_server.py
```

浏览器打开 `http://127.0.0.1:8788`，三个入口随意切换：

- **勾选**想保存的笔记（「全选未抓」一键跳过已抓的；勾选自动保存）
- **关键词搜索**：切到「关键词搜索」页，输入关键词直接搜，不用另开终端
- **开始抓取**：点左下角按钮，后台自动跑抓取脚本，日志实时可见，抓完卡片自动打「已抓过」
- **已抓笔记**：随时查看抓取进度，一键打开每篇的本地文件夹

### 4. 抓取正文与原图（也可用工作台里的「开始抓取」代替）

```bash
python xhs_fetch_selected.py              # 抓清单里全部
python xhs_fetch_selected.py --count 5    # 一次只抓 5 篇，怕触发风控时用
python xhs_fetch_selected.py --offset 5   # 接着往下抓（断点续导）
```

### 5. OCR 分级

抓下来的原图在 `downloads/<笔记>/img_*.jpg`，**图片里的文字需要多模态 AI 来读**——本项目只定义格式，不替你调用模型。把下面这段发给任意能看图的 AI：

> 读取 `downloads` 下每篇笔记的图片，逐张转录图片上的文字，按下面格式输出到该笔记目录的 `ocr.md`：
> 每张图一节 `## img_01.jpg` 后跟转录全文；纯自拍/风景照片写 `（照片）`；界面截图只留关键内容和指令原文，跳过按钮和菜单。

### 6. 导出到 Obsidian

```bash
python xhs_export_md.py --dest "/path/to/your/vault"
```

## 📁 目录结构

```
downloads/01_笔记标题/
├── raw.json        # 结构化原始字段
├── note.md         # 正文骨架
├── img_01.jpg ...  # 原图
├── subtitle.srt    # 视频笔记的官方字幕（若有）
└── ocr.md          # OCR 分级结果（第 5 步生成）

<vault>/
├── 01_笔记标题.md
└── _附件/01_笔记标题/img_*.jpg    # 用 ![[wikilink]] 引用
```

`ocr.md` 的写法：

```markdown
## img_01.jpg
（这张图上的干货文字，逐字转录）
## img_02.jpg
（照片）
```

## 💻 在哪些环境里能用

**不绑定任何 Agent。** 本质是 5 个 Python 脚本 + 一个本地网页：

- 任何能执行命令的 AI Agent 都能用（Claude Code、Cursor、Codex CLI），或你自己开终端
- 勾选台就是普通网页（`http://127.0.0.1:8788`），在哪儿打开都行：系统浏览器标签页（推荐）、WorkBuddy 内嵌预览、VS Code / Cursor 的 `Simple Browser: Show`
- 服务只绑本机 `127.0.0.1`，同一 WiFi 下手机打不开（安全考虑）

## ❓ 常见问题

<details>
<summary><b>需要登录吗？会不会拿我的密码？</b></summary>

需要登录，首次扫码一次，登录态本地复用。工具不接触账号密码，`browser_profile/` 已在 `.gitignore` 中排除，请勿提交到公开仓库。
</details>

<details>
<summary><b>会封号吗？</b></summary>

只做只读浏览（看主页、看搜索、看详情页），不做自动点赞、发布等写操作。但请自行控制频率，不要高频批量；搜索入口偶尔会触发风控导致页面一直转圈，隔一会儿再试即可。
</details>

<details>
<summary><b>抓一半断了怎么办？</b></summary>

直接重跑，已完成（`raw.json` 标记 ok）的会自动跳过。
</details>

<details>
<summary><b>能抓其他人的评论吗？</b></summary>

只抓博主本人发的评论——那通常是干货补充或追问回应；路人评论一概不收。
</details>

<details>
<summary><b>视频笔记呢？</b></summary>

抓官方字幕（`subtitle.srt`）；没有字幕时抽关键帧，交给 OCR 那步一起处理。
</details>

<details>
<summary><b>为什么标题里的 emoji 没了？</b></summary>

默认去掉（导入 Obsidian 更干净），源码里可以关。
</details>

<details>
<summary><b>点开详情为什么弹出小红书登录框？</b></summary>

详情是嵌在内嵌视图里打开的，浏览器的跨站安全机制决定了它不带登录态。关掉登录框就能看笔记内容；要看评论等完整信息，点详情页左上角「浏览器打开↗」。这只影响"看"，不影响勾选和抓取。
</details>

## 🗺️ 开发计划

- [x] 博主主页整号抓取（SSR + 接口双源去重）
- [x] 常驻采集工作台（三入口 + 页内搜索 / 页内抓取）
- [x] 正文 / 原图 / 官方字幕抓取
- [x] 博主评论过滤抓取
- [x] 图片文字 OCR 三级分级
- [x] Obsidian 规范导出
- [x] 断点续导（offset / count）
- [ ] 单篇帖子链接直抓
- [ ] 配置文件化：路径、端口、抓取节奏可配
- [ ] 一键安装脚本（免手动装 Playwright）

## ⭐ Star 趋势

如果这个项目对你有帮助，点个 Star 支持一下 ⭐

[![Star History Chart](https://api.star-history.com/chart?repos=judy123violet-max/xhs-curator&type=timeline&legend=bottom-right)](https://www.star-history.com/#judy123violet-max/xhs-curator&Timeline)

## ⚠️ 免责声明

1. 本项目仅供**个人学习与研究**使用，不得用于任何商业用途。
2. 使用者应在遵守《小红书用户协议》及相关法律法规的前提下使用本项目，并自行控制访问频率。
3. 使用者不得利用本项目获取、传播受版权保护的内容，不得用于侵犯他人合法权益的行为。
4. 本项目不提供登录态、Cookie 等任何账号凭证，使用者需自行登录并自行承担账号风险。
5. 因使用本项目所产生的任何法律责任与损失，均由使用者自行承担，项目作者不承担任何责任。
6. 使用本项目即表示你已阅读并同意上述条款。

## 📄 License

[MIT](LICENSE)

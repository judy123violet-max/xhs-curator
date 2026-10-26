---
name: xhs-curator
displayName: xhs-curator · 小红书笔记采集与 Obsidian 入库（单篇速读 + 博主主页批量）
description: 小红书笔记采集与知识库入库一站式工具（xhs-curator）。覆盖三种入口——①单篇笔记链接（xhslink.cn 短链 / explore 链接）：匿名免登录直接产出 Markdown 文稿（正文/原图/字幕/转写）；②博主主页链接（含手机端 App 分享的主页文本）：弹出登录态工作台，勾选批量抓取，可带博主评论；③关键词搜索发现笔记。抓完支持"导入 Obsidian"入库（frontmatter/附件/索引）。当用户给一个 xiaohongshu.com / xhslink.cn 链接或博主主页链接、发来手机端分享文字、要求"整理笔记/抓图片/导出文档/抓这个号所有笔记/批量采集/复盘面经/导入 Obsidian"时使用。
---

# 小红书图文笔记 → 结构化文档（xhs-curator 统一入口）

> **安装形态（2026-10-20 P0 定稿）**：本 Skill 必须与 xhs-curator 仓库配套安装——
> 标准安装 = `git clone` 本仓库 → 运行 `python install.py`（自动复制本 Skill 到
> Agent 技能目录并写入仓库位置标记）。**仅复制 skill/ 目录**的安装只支持单篇速读，
> 不能用于主页批量采集。

## 🧭 仓库根定位与统一入口路由（2026-10-20 P0：硬判定，不靠模型猜测）

**第一步 · 定位仓库根**（按优先级，找到即止）：
1. 环境变量 `XHS_CURATOR_HOME`（指向含 xhs_export_md.py 的仓库根）
2. 本 Skill 目录下的 `.xhs-curator-root` marker 文件（install.py 写入仓库绝对路径）
3. 向上逐级探测（开发场景：本 Skill 就在仓库里）
4. 全部失败 → **输出安装引导**（见下方固定话术），不得臆测路径

**第二步 · 链接分类**（对用户发来的链接/分享文字，必跑）：
```
python <仓库根>/skill/scripts/fetch_xhs_note.py --classify "<原文>"
```
输出 JSON `link_type: single | profile | invalid | unknown`——**AI 按此结果路由，禁止按文字内容猜测**：
- `single` → 引擎 A 匿名快读（单篇 .md 交付）
- `profile` → 引擎 B 登录态工作台（有效链接！需要登录态，不是无效链接）
- `invalid` → 如实说明无法识别，请重新分享
- `unknown` → 短链解析暂不可达，如实说明请稍后重试

**第三步 · 运行脚本**（依赖一致性，2026-10-20 实测教训）：
- 所有脚本**必须用 marker 记录的 Python 解释器**运行（install.py 安装时装依赖用的就是它），
  避免「依赖装在 A 解释器、脚本用 B 解释器跑」的缺模块问题
- marker 是 JSON：`{"repo_root": "...", "python": "..."}`——读 python 字段；
  旧版纯文本 marker（只有仓库路径）→ 退回 `python`，依赖缺失时提示重跑 install.py --with-deps

**安装引导固定话术**（仓库根定位失败时输出）：
> 你发的是博主主页链接，批量采集需要完整安装 xhs-curator（一次性，约 2 分钟）：
> 1. `git clone https://github.com/judy123violet-max/xhs-curator.git`
> 2. `cd xhs-curator && python install.py`
> 3. 重启对话后再发一次主页链接即可

## 🎯 交互原则（2026-10-20 定稿：最小询问 + 勾选主权）

收到链接后按「🧭 仓库根定位与统一入口路由」分类执行，**询问最小化**：

| # | 环节 | 规则 |
|---|---|---|
| 0 | **解析链接（不问）** | 一律先跑 `--classify` 拿 link_type，按结果硬路由（见上节），**禁止按文字内容猜** |
| 1 | **博主评论偏好** | **对话层绝不弹窗询问**——进工作台后，底栏「抓取博主评论」复选框由用户自行勾选（默认不勾）；AI 只需引导用户注意该开关，不代问不代选。⚠️ 在对话里问"要不要评论"= 违规行为 |
| 2 | **存哪里？** | 单篇成功后**直接产出可下载 .md 文稿**；弱提示"如需存入 Obsidian，请说『导入 Obsidian』"，不阻断。**打开工作台时，对话回复必须同步一句固定约定**（2026-10-20 Codex 评审口径）："抓取完成后，工作台会显示结果；如需入库，在本对话发送『导入 Obsidian』。"——不得只说"抓完后跟我说一声"，不得假定用户知道 OCR/导出步骤；采集台成功卡上也持久显示同一句话 |

> **历史沿革（避免旧文档误读）**：旧版"三问：抓多少？要评论吗？存哪里？"已于 10-19/20 拆解废除——
> "抓多少"由工作台勾选天然取代；"要评论吗"**不再由对话询问**（工作台复选框承接，且已有代码
> `--no-comments`，不再是纯对话约定）；"存哪里"降为弱提示。若旧记忆里还有"先问评论"的流程，
> 一律以本表为准。

## 🔑 ASR 升级引导（无字幕视频 + 用户无百炼 key 时，主动提供）

触发时机：遇到无字幕视频且用户未配置百炼 key → **先无感走本地 faster-whisper 兜底，同时在结果里附带升级引导**（不打断流程）。

引导话术模板（照此发给用户，可按语气微调）：

> 这篇视频没有官方字幕，我已用**本地离线转写**出好了逐字稿（完全免费，准确率不错）。
> 如果你希望**英文内容、品牌词（如 Claude Code）识别更准**，可以免费开通阿里云百炼，1 分钟搞定：
>
> **开通步骤**：
> 1. 打开 👉 https://bailian.console.aliyun.com/?apiKey=1#/api-key （用阿里云/淘宝账号登录即可）
> 2. 首次进入点「开通百炼」（免费，不扣费）
> 3. 页面里点「创建我的 API-KEY」→ 复制那串 sk- 开头的密钥发给我
>
> **你关心的两点**：
> - 🔒 **安全承诺**：key 只保存在你电脑本地的配置文件里，我不会把它写进任何导出文档、Git 仓库或对外传输，放心发
> - 💰 **额度规则**：每月免费 10 小时转写（个人用绰绰有余——一条 3 分钟视频只吃 3 分钟额度，每月够转 200 条）；就算哪天用超了，也**按量计费很便宜**（约 ¥0.29/小时），不充值的话我自动切回本地转写，**服务不中断**

AI 行为准则：用户的 key **只写入本地配置文件**（如 `~/.dashscope_key`）；绝不将其写入导出物、Git、日志展示或告知第三方；用户要求删除时立即删除。

## 📦 Obsidian 批量导出规范（2026-10-15 确认，整号抓取导入库时必须遵守）

**⚡ 导出硬性规则速查（改脚本前先看这里；2026-10-16 更新）**：
1. **照片/自拍类图注一律不输出** —— 自拍、风景、氛围照旁边的文字全删；App 界面截图保留一行 `（配图 · 一句话说明）`。
2. **`## 博主的评论` 固定放全文最末**（正文 / 图片 / 字幕 / 关键帧 之后）。
3. **重导前先备份**（把 dest 下 `*.md` 复制到库外），并靠 `load_prev_img_params` 继承手工加的 `|orig|left|0|400` 参数——**绝不让手工排版被覆盖**。
4. 导出后必须校验三件事：嵌入链接 0 缺失、照片类图注 0 残留、评论在文末。
5. **图片逐图判定去图**（2026-10-16 拍板，学 xhs-claude-skills）：**逐张图**判断——图内是干货长文 → **去图留文**（文字已转录，图冗余）；图内只有一行说明或没文字（界面截图、照片）→ **保留图**。同一篇里可混合（如「阿宝」9 图保留 4、转文字 5）。实现：`has_substantive_text()`（去掉纯括号说明后仍 ≥15 字即干货图）。**注意**：这取代了早期的「整篇覆盖率」一刀切；正文与图内文字重复的段落仍会剔除（`analyze_image_note()` 现只做正文去重）。
6. **正文小标题还原成真标题**（2026-10-16）：小红书 `desc` 是**纯文本、不含任何加粗标记**（实测 0 个 `**`），App 里的标题感全靠渲染。`boldify_headings()` 按句式还原：`01｜xxx`、`第N层/步/点`、`总结/写在最后/食用指南` 等 → 默认输出 `### 真标题`（可进 Obsidian 大纲），`--heading-style bold` 可回退成加粗。
7. **博主评论筛选**（2026-10-16 拍板）：评论和图片一样分「有用 / 装饰」——`is_meaningful_comment()`：归一化 **≥20 字**或**点赞 ≥10** → 保留；寒暄短评（"往我心里埋来""想你了宝宝[doge]"）、纯表情 → 丢弃；全部被筛掉则**不输出评论章节**。被过滤的评论仍留在 raw.json，调规则重导可找回。
8. **勾选主权（2026-10-19 拍板，批量场景铁律）**：主页/搜索批量的**勾选永远是用户的动作**——AI 只负责把列表抓回来、把工作台开给用户，**等用户勾完再跑**。**严禁**代替用户编辑 `selection.json`、代挑笔记、或跳过勾选直接运行 `xhs_fetch_selected.py` 批量模式——**即使用户说"测试/先跑通看看"也不例外**（测试可以只抓列表，不能代勾选抓正文）。违反即等同"交互没说就问"铁律的反向越权：AI 替用户做了决策。

工具：`<仓库根>/xhs_export_md.py`（`--dest <你的 Obsidian 库目录>`；仓库根定位见上方「仓库根定位与统一入口路由」）。

**md 结构（每篇一个文件，文件名=清洗后的标题）**：

```markdown
---
title: "…"
author: "谷谷谷雨（秋招版）"
published: 2026-09-05      # 笔记发布日期
created: 2026-10-15        # 导出日
description: "正文首行压成单行截 90 字（含换行会破坏 YAML）"
source: "原文链接（带 xsec_token）"
tags:
  - 小红书
  - 秋招/AI产品
  - <从正文 #话题[话题]# 提取的话题，去掉外壳，最多 15 个>
类型: 图文|视频
点赞: "29"
---

## 正文                      ← 正文清洗后（见下）
## 图片与文字转录             ← 每张图一节：图片行 + 该图转录（照片类不写任何文字）
![[<笔记标题>--img_01.jpg]]
<该图的转录文字，或一行配图说明>
## 视频字幕 / ## 视频关键帧    ← 视频笔记（无字幕时）
## 博主的评论                 ← 固定放**全文最末**（2026-10-16 拍板）
```

**正文清洗规则**（`clean_body`，实测踩坑）：
1. 小红书用 `\t` 当换行/缩进——直接输出会被 Markdown 当代码块，必须转成换行并去缩进。
2. `#话题[话题]#` 全部剔除（注意 `[话题]#` 是 5 个字符；有的话题名和 `[话题]#` 之间有空格，正则要允许 `\s*`），**提取进 frontmatter tags**，不丢信息。
3. `@提及` 剔除，但 **@ 前是字母/数字/汉字/点的不动**（保护邮箱 `xxx@163.com`）。
4. 纯符号/emoji 残行丢弃。
5. **禁止**在正文前重复输出 H1 大标题和「日期·类型·点赞·原文链接」引用块——属性面板里都有，纯重复。

**⚡ OCR 成本启发式（2026-10-16 借鉴自 xhs-claude-skills，省 token）**：
> ⚠️ **与逐图价值闸门的关系（2026-10-20 澄清）**：脚本侧的 `ocr_status.json` 四类闸门（informational/ui/decorative/uncertain）是**权威判定**，本节启发式是脚本判定前的**粗筛参考**，冲突时以闸门为准。分级对应：干货图≈informational、配图·界面≈ui、配图·照片≈decorative。先看数字再决定跑不跑——
- `desc` 已 **> 500 字** → 正文自带完整内容，**跳过 OCR**（图多半是配图）；
- `desc` 很短（仅标题/几句引言）且 **图 ≥ 3 张** → 图就是内容载体，**必须 OCR**；
- 中间地带按「图是不是干货图」人工判断。
- 实测案例：《面试讲项目…》desc 995 字 + 1 张封面图 → 按此规则可直接跳过，省一轮多模态。

**图片 OCR 分级（2026-10-15 二次拍板：不要无脑全转）**：
- **干货图**（文章卡片、教程步骤、框架总结、干货列表）→ 逐字转录，保留结构。
- **配图·界面**（App 界面截图、广告位、二维码）→ 只写一行 `（配图 · 一句话说明）`，**不转录界面文字**——用户明确说过界面文字转录"很没有用，浪费浏览"。
- **配图·照片**（自拍、风景、氛围照、表情包、宠物）→ 在 ocr.md 里只写 `（照片）`，导出时**只保留图片本身，不加标题也不加说明**（用户明确要求：发自拍的、拍景色的旁边什么都不要写）。
  - ⚠️ **OCR 常不遵守**（写成 `（照片 · 封面图：玩偶与笔记本电脑…）` 这类长描述）→ 导出层已有兜底：`xhs_export_md.py` 的 `filter_photo_captions()` 会把「以『照片』开头」或「含 自拍/照片/人物/拼图/表情包/贴纸」的整段括号说明删掉（2026-10-16 补）。**含自拍的拼图说明（如 `（配图 · 群面截图与"xxx.jpg"自拍照片的拼图…）`）也归此类删除**；纯界面截图说明仍保留。
- **聊天截图** → 只转录对话本身，跳过按钮/菜单等 UI 元素。
- 封面大字报：只录封面那几句，不当正文。

**评论位置（2026-10-16 拍板）**：`## 博主的评论` 由 `render_author_comments()` 输出，固定放在正文 / 图片 / 字幕 / 关键帧**全部之后**，即全文最末。

**标题一律无 emoji（2026-10-15 三次拍板）**：文件名和 frontmatter 的 title 都要去掉 emoji（`strip_emoji`，覆盖 U+1F000-1FAFF、2600-27BF、FE0F、200D 等），"AI产品实习📝"→"AI产品实习"。后续所有导入照此办理。

**其他**：图片附件放**库根 `attachments/`**（2026-10-21 雅旭拍板：全库单附件目录，对齐 Obsidian 全局设置；脚本会从 dest 向上找 `.obsidian` 自动定位库根，非 vault 目录回退 `<dest>/attachments/`），文件名 `<笔记标题>--<原名>`，正文用 `![[<笔记标题>--<原名>]]` 引用；每批导出生成 `00 索引.md`（日期|笔记|类型|图片数 表格）；导出后必须校验嵌入链接 0 缺失。

**已知遗留（下次看到别当成新 bug，2026-10-16 体检发现）**：
- **OCR 去重只做「相邻两张图之间」**（`dedup_ocr` 只跟紧邻前一张比）→ 两类重复会漏：
  - ① **正文 ↔ 图内文字**：小红书正文常就是封面图的引导语，两边只差**弯引号 `“”` 和直引号 `""`**，比对不过去；
  - ② **非相邻图之间**：如 img_01 ↔ img_03 是同一段内容。
  - 实测整号 18 篇里 **7 篇命中**。要根治需把比对范围扩到「正文 + 之前全部图的文字」并做标点归一化（**尚未修，待确认**）。
- **旧 `_附件/` 目录编号可能撞号**（v2 已改为单层 `attachments/` + 标题前缀，新导出不再产生目录编号）：历史批次曾出现两个 `05_`、两个 `06_`，**同名笔记会互相覆盖，导致数据丢失**。⚠️ 实锤案例：`面试讲项目其实也是一种"渐进式披露"` 有 05_（含 4 条博主评论）和 06_（早期无评论），导出时 06_ 覆盖 05_ → **博主评论在成品里凭空消失**。历史重复目录已移到仓库外的备份目录（未删除）。**排查方法**：成品缺评论时先看 `downloads/` 有没有同名目录、评论是否抓在另一个目录里。
- **重导会重写全部 md**：`00 索引.md` 和所有笔记都会刷新，改前务必先备份（见上「硬性规则 3」）。

---

## 👤 博主整号抓取（主页 → 全部笔记列表 → 勾选下载）

需要"抓某个博主主页的所有笔记"时，用仓库根目录的现成工具链，**不要临时重写**：

### 链路选择（按需求走不同路径，2026-10-16 梳理）

| 需求 | 链路 |
|---|---|
| **整号批量采集** | `xhs_creator_fetch.py 主页链接` → 工作台「博主主页」勾选 → 「开始抓取」→ OCR → 导出 |
| **关键词发现** | 工作台「关键词搜索」页内直接搜（或 CLI 跑 `xhs_search_fetch.py`）→ 勾选 → 同上后段 |
| **单篇/少量帖子** | ✅ **单篇一律匿名（2026-10-19 定稿）**：`fetch_xhs_note.py "<链接>"`（引擎 A·免登录）成功后**直接产出可下载 .md 文稿**（正文+图片相对引用+字幕/转写，封面不进交付）；用户说**「导入 Obsidian」**时，跑 `to_downloads.py "<输出目录>" --downloads "<仓库根>/downloads"` 本地转换成 downloads 契约（**不重抓、不要求登录**；`--downloads` 必须指向仓库根的 downloads，否则默认路径会错位），再 `xhs_export_md.py` 进库。要**博主评论**时才走引擎 B：`xhs_fetch_selected.py --url "<链接>"` 或工作台「单篇导入」，后接同一条导出管线 |

> **架构（2026-10-16 确认：单 Skill 双引擎路由，不拆分）**：
> - **引擎 A** = 匿名 HTTP 直抓，吃分享 `xsec_token`——快、免登录，但拿不到博主评论/官方字幕，且**小红书改 SSR 结构就要跟着修**（2026-10-16 已修：`note.data.noteData` + `imageList[].url` 双兼容）。
> - **引擎 B** = 本机 Chrome 登录态（Playwright，`browser_profile/`）——数据全、抗改版，但要登录。
> - 入口唯一，按「输入类型 + 目的地」分流；入库一律走 `downloads/ → OCR → export_md`，单篇和整号合集格式天然一致。
> - 已知数据怪点：平台在列表页和详情页**都**存截断昵称「谷谷谷雨（秋招版」（少右括号），脚本忠于平台数据，勿自作聪明补全。

| **已抓过要重导/补抓** | 工作台「已抓笔记」页看状态 → 直接重跑 `xhs_export_md.py`（不用重抓）；中断的用 `xhs_fetch_selected.py`（或页内开始抓取）自动续 |

### 工具链四步

1. `xhs_creator_fetch.py <主页URL/短链/用户ID>` — 用 Playwright 驱动本机 Chrome（独立 user-data-dir，登录态存 `browser_profile/`，首次扫码一次即可长期复用），滚动加载全部笔记 → `notes.json`
2. `xhs_picker_server.py --port 8788` — **常驻采集工作台**（2026-10-16 升级，同页三入口，切换不用重启服务）：
   - 三个入口：**博主主页**（notes.json）/ **关键词搜索**（search_notes.json）/ **已抓笔记**（downloads/_manifest.json 状态表，可一键打开本地文件夹）
   - 卡片：封面/标题/类型/点赞/置顶，支持全选、反选、仅视频、仅图文、关键词过滤、**全选未抓**（对照 manifest 自动打「已抓过」标记）
   - 交互不变：点卡片=勾选（即时自动落盘+localStorage 持久化，主页/搜索结果可混选一起抓）；点标题或「原文↗」= 走 `/detail?url=` **包装页内嵌打开**（顶部「← 返回列表」/Esc 返回，工作台页面不离开、勾选零风险；⚠️ 嵌套 iframe 不带登录态——XHS Cookie 是 SameSite 严格，跨站一律不发，会弹登录框，关掉可看内容，完整版走「浏览器打开↗」；勿用 target=_blank 直跳，内嵌预览会甩给系统浏览器）
   - **页内搜索**：「关键词搜索」页输关键词 → 后台自动跑 xhs_search_fetch.py，日志实时滚动
   - **页内抓取**：勾完点「开始抓取」→ 后台自动跑 xhs_fetch_selected.py（subprocess，PYTHONIOENCODING=utf-8 防子进程 GBK 乱码），抓完自动刷新「已抓过」标记
   - 清单每次进页面重新读文件：重跑抓取脚本后刷新页面即最新数据，服务不用重启
3. `xhs_fetch_selected.py` — 按 selection.json 逐篇抓正文/原图/字幕，产出 `downloads/<序号>_<标题>/`。**支持断点续导**（2026-10-15 从 xhs-note-batch-export 借鉴）：`--offset N` 跳过前 N 篇、`--count N` 本次最多抓 N 篇、已完成项（raw.json ok=true）自动跳过、`--no-resume` 强制重抓；序号取全量清单位置保证目录编号稳定，manifest 按 note_id 增量合并。也可由工作台「开始抓取」按钮代替手动运行
4. `xhs_export_md.py --dest <库目录> [--extra-tags "秋招/AI产品"]` — 按下方「Obsidian 批量导出规范」入库。**作者按篇自动读取**（2026-10-16 起 fetch_selected 把博主昵称写进 raw.json/manifest），老数据无 author 字段时用 `--author` 指定、或兜底读 selection.json；标签默认只带「小红书」+正文话题，个人固定分类用 `--extra-tags` 逗号分隔传入。**2026-10-16 起**：照片/自拍类图注自动剔除（`filter_photo_captions`）、`## 博主的评论` 固定置于全文最末（`render_author_comments`）、重导会**继承上次手工加的图片显示参数**（`|orig|left|0|400` 之类，`load_prev_img_params`）

### 两个致命坑（都已在脚本里修掉，重写时务必注意）

1. **首屏第一页是 SSR 直出的，不产生任何网络请求。** 只监听 `user_posted` 接口必然漏掉最新一整屏（实测 97 条只抓到 66）。
   - 权威数据源 = 页面 SPA store：`window.__INITIAL_STATE__.user.notes._rawValue[0]`（Vue 把数组包成了 ref，**必须走 `_rawValue`**，直接读 `.notes[0]` 拿不到）。
   - `_rawValue` 会把 SSR 首屏 + 后续分页**自动累积合并**，是唯一完整来源；滚动只是驱动它增长。
   - 判断是否到底：读 `_rawValue[0].length` 是否稳定（别只看接口的 `has_more`）。
2. **同一条笔记在 SSR 与接口里的 id 后缀不同**（如 `6a197b43…020603df85` vs `…0006035abf`），按 id 去重会重复计数。除 id 外必须再按「标题+发布日期」去重。

其他要点：
- 博主主页**必须登录**才能拿列表：匿名请求 `/user/profile/<uid>` 会 302 跳登录；带分享链接里的 `xsec_token` 虽能拿到 SSR 页壳，但笔记数组是空的。
- 登录态判断不能看 `web_session` cookie（访客也有），要看页面特征：有 `section.note-item` 且无「手机号登录」弹窗。
- CSS 选择器：卡片 `section.note-item`（带 `data-note-id` / `data-index`），置顶卡片内含 `class="top-wrapper">置顶<`（文字，不是 icon，可直接 grep）。
- 页内可直接用 `window._webmsxyw(path, data)` 产出 `x-s`/`x-t` 签名自调接口，但缺 `x-s-common` 等头会在服务端被判 300011（安全限制），不如直接读 store。
- 笔记详情（正文/原图）仍走本文档的匿名 SSR 路径，`notes.json` 里每条都带了 `xsec_token` 可直接拼 URL。
- **抓取原理同行三大流派（2026-10-16 调研）**：①**浏览器路线**（MediaCrawler 用 CDP 连本机 Chrome 9222、ljb1020、lexielin99）= 主流，**与本项目相同**；②**HTTP + TLS 指纹直抓 SSR**（XHS-Downloader 用 `curl_cffi impersonate=chrome146`，匿名免登录）—— 本质与本项目老引擎同源，但它用 TLS 指纹模拟过风控，**值得借鉴**（现用 urllib/requests 桌面 UA 容易被拦成空壳）；③签名 API + 多层兜底（feedgrab：xhshow→Pinia→Jina→Playwright）。风控共性：随机延时、复用真实浏览器指纹、代理池、指数退避。
- **图片处理同行对比（2026-10-16 调研）**：主流是「只下图、不识字」（MediaCrawler / XHS-Downloader / Obsidian 插件都不做 OCR）；唯一同路线的是 xhs-claude-skills（多模态逐图 OCR，但只做"文字图/装饰图"二分流）。**本项目三级分级 + 「内容全在图里则去图留文」更细一档**。可借鉴它的**成本启发式**：按 `desc 字数 × 图片数` 预判是否值得跑 OCR（desc > 500 字跳过、图 < 3 张才跑），省 token。

---

## 🎬 视频笔记专用路径（2026-10-12 实战验证，优先检查）

> **⚡ 视频转写能力（2026-10-16 晚已上线，基础版）**：视频笔记双层兜底——**官方字幕优先**（平台只给部分视频生成，实测约 2/3 有），**无字幕 → 自动下载视频 + 本地 faster-whisper 语音转写**（`transcript.txt`，按语义段分行；转写完视频即删）。参数：`--whisper-model`（默认 small，base 同音字误差明显如"流暖戏"=浏览器）、`--no-asr` 跳过。模型在 `<仓库根>/models/faster-whisper-<name>/`，首次自动从 hf-mirror 逐文件流式下载。
> - **两个环境坑（已规避，改动前先看）**：①**不要用 huggingface_hub 下载器拿模型**——本环境实测对 hf-mirror 会拿到 0 字节文件，代码里是用 urllib 流式逐文件下载（`_model_dir()`）；②**PyAV 锁 16.x**——av 19 移除了 `metadata_errors` 参数，faster-whisper 1.2.1 会崩。
> - **分工（2026-10-16 确认）**：本 skill 做**基础版**（字幕 + 本地 Whisper，够用就好）；通用型多级降级链（百炼/妙记）作为后续扩展。
> - **认知修正存档（交叉验证）**：官方字幕**存在但覆盖不全**——曾误写为「web 端没有独立字幕轨道」。「时灵时不灵」机制 = 短时密集请求后 SSR 返回降级页面（54KB vs 57KB），冷却 2-3 分钟恢复；**urllib/requests 稳定命中降级页 → 假阴性**；Playwright 路线不受影响。
> - **⚠️ HTTP 层再升级（2026-10-17 批准）**：普通 curl 的 TLS 指纹也**已被平台识别**（实验记录：连续两天降级恶化）。脚本现走 **curl_cffi 指纹模拟**（iPhone UA 配 `safari_ios`、桌面 UA 配 `chrome146`，指纹与 UA 配套），curl 子进程仅作回退。**手写 curl 命令做手动诊断时也可能命中降级**——判「真没有字幕/数据」前先用脚本（curl_cffi）复核一轮。变更 spec 见仓库提交记录。
> - **抽关键帧 + OCR 仍保留**：无字幕且未装 faster-whisper 时的退路（只能读画面上的字，口播拿不到——装了 faster-whisper 就走转写）。
> - 下面这套「从 SSR HTML 抽官方 SRT」的路径**只对有字幕的视频有效**；遇到无字幕视频要如实告知用户，别硬撑。

分享链接的 redirect query 里 `type=video` 即视频笔记。**当平台带了官方字幕时**，不需要下视频跑 ASR —— SSR HTML 里直接有官方生成的 SRT（若字幕为空，按上面的「能力边界」如实告知用户，别硬撑）：

1. 按「手动路径 A/B/C」正常拉 `discovery/item/<noteId>` SSR HTML（带完整分享 query）。
2. **先全局把 `\u002F` 还原为 `/`**（node：`html.replace(/\\u002F/g,'/')`），否则 URL 匹配会失败（字幕 URL 深藏在多层 `\\\"` 转义的 JSON 里）。
3. 用正则抽字幕：`/https:\/\/sns-subtitle[^"\\]+/g`（`[^"\\]` 遇到转义引号自动截断）。一般有 2~3 条：
   - `*_1.srt` = 源字幕（可能是英文）、`*_11.srt` = 中文翻译、`*_12.srt` = 源字幕副本
   - 脚本按内容检测语言：**优先中文轨**（中文里取信息最全的一条）；没有中文时回退 `_1` 源字幕。
4. 下载带 `Referer: https://www.xiaohongshu.com/` + 移动 UA。SRT 就是逐字稿，按时间戳分段整理成 markdown 即可。
5. 元数据：title/nickname/desc（通常是纯话题标签）/ipLocation/likedCount 等都在 HTML 里；视频时长在 `"duration":<ms>`（毫秒）。
6. ASR 常见同音错误按上下文修正（实测案例："Web coding"→Vibe Coding、"get/gate"→Git、"spike"→spec、"agent点money down"→AGENTS.md），文档里注明"已修正同音错别字"。
7. 失败兜底：SRT 拿不到再考虑下 mp4（`master_url`，带 sign 参数）+ ffmpeg 抽音频 + ASR；或请用户发字幕。

---

## 📄 视频笔记结构化整理 SOP（v2 标准，2026-10-16 验收）

> 依据：《变更提案-视频笔记产物形态v2》（Obsidian `AI学习笔记/📺视频转笔记skill调研/`）。**散碎逐字稿直接进笔记已被否决**——视频笔记的产物是结构化文档，不是转写原文堆砌。

**触发时机**：视频笔记转写完成（transcript.txt 生成，或官方 SRT 已取得）后，**AI 主动执行本 SOP**，产出结构化内容写入产物目录 `structured.md`（引擎 B 为 `downloads/<序号>_<标题>/structured.md`）。原始转写文件不删（transcript.txt / subtitle.srt），结构化版 md 里注明来源。

**模板骨架**（照验收样品的结构，缺项可省）：

```markdown
## 执行摘要          ← 3-5 句话讲清这支视频说了什么，加粗核心结论
## 核心论点          ← 编号列表，一条一句，去掉所有口水
## 论证链路          ← 按内容逻辑分节（不按时间轴），含案例、数据、表格
## 金句              ← 原话摘录（仅修同音错，不改写）
## 名词解释          ← 可选：转写里听错的专有名词做考据（如 EvoSet←"EVO/AvoSet"）
## 逐字稿（整理版）   ← 口播转书面、按语义段分节；开头注明同音错修正清单
## 速览表            ← 全文压成一张速查表，最有复用价值
```

**整理规则**：
1. **同音错修正**：按上下文修正并逐条注明（格式照样品：`SaaS（原"SARS"）`）；拿不准的原样保留不硬猜。已知高频错照历史积累：Vibe Coding←"Web coding"、Git←"get/gate"、spec←"spike"、AGENTS.md←"agent点money down"。
2. **忠实原文**：整理是「洗稿不洗观点」——不添自己的观点、不删作者的限定语；金句保持原话。
3. **关键帧**：默认不进笔记（2026-10-16 确认）；仅当帧内是**完整干货图**（框架图/表格/步骤图，非口播人脸或空镜头）才保留为附录章节。
4. **frontmatter**：视频笔记补 `类型: 视频`、`时长`、`转写: 官方字幕|本地 Whisper` 三字段。⚠️ **duration 单位两个来源不一样**：引擎 B raw.json 是**秒**（实测 239 秒存 239，xhs-curator 勘误 2026-10-16）；SSR 页面原始字段是**毫秒**（见上第 5 条）。换算前先看数值大小判断单位。
5. **原始转写可溯源**：逐字稿章节注明「完整原声见 transcript.txt / subtitle.srt」。
6. **export 对接**：引擎 B 导出时 `xhs_export_md.py` 检测产物目录有 `structured.md` 即用它替换「语音转写」章节正文（已实施）。

**成本参考**：3900 字转写 → 约 2000 字成品，AI 整理每篇 1-2 分钟。

---

## 👁 查看 / 预览已抓取结果（不导出 Obsidian）

用户说「看看已抓的 / 导出已抓完的 / 给我看看结果 / 把抓到的给我」但**未指定 Obsidian 库**时：
- **禁止**只回一句「都躺在 downloads/」或甩文件夹路径——用户要的是**能点开直接看**的结果。
- 运行 `python <仓库根>/xhs_preview.py` → 生成 `downloads/00-预览.html`（一篇卡片一张：封面、标题、类型、日期 + 「打开笔记 .md / 打开原文 / 打开文件夹」三个可点击链接）。
- 用 `present_files` 打开该 HTML（内置预览面板即可逐张点开，无需去文件夹翻找）；同时把路径告诉用户，方便他们本地双击。
- **与「导入 Obsidian」区分清楚**：
  - 「看看 / 预览」= 看 `downloads/` 里的原始素材包（抓取完成即可看，无需进一步处理）→ 走本流程；
  - 「导入 Obsidian / 入库 / 导出到我的库」= 生成带 frontmatter 的正式笔记 → 走上面的 Obsidian 导出（`xhs_export_md.py --dest`）。

> 边界：用户明确要入库时才导出；没说目标库时，默认只给**可点击预览**，不顺手替用户决定存哪。

---

## 一句话工作流

小红书短链 → 解析真实 noteId/URL → 直接拉服务端 SSR HTML → 在 HTML 里找笔记数据块（**新结构 `"data":{"noteData":{…}}` ／ 老结构 `noteDetailMap`，脚本双兼容**）→ 抽出每张图的 `imageList[].url`（新，**须按末尾 fileId 去重**）或 `urlDefault`（老）（高清无水印原图 URL）→ 全部下载到本地 → 多模态视觉逐张识别 → 拼成结构化 markdown。

## 为什么这样做（反爬理解）

小红书的反爬分层：

1. **JS 渲染 + 登录墙**：浏览器开页面，看到的几乎都是登录/风控壳子，正文和图都拿不到。
2. **服务端其实渲染了一份 HTML**：未登录请求详情页时，服务端为了 SSR 友好，会把笔记数据塞进 HTML 里的一个 JSON 块（老 key：`noteDetailMap` / `urlDefault`；**2026-10 起新 key：`"data":{"noteData":…}` / `imageList[].url`**），里头就含**高清无水印**原图地址。注意数据常有**两份拷贝**（`__INITIAL_STATE__` + `__SETUP_SERVER_STATE__`），提取后必须整体去重。
3. 所以**根本不要打开浏览器**去等 JS 渲染，直接发 HTTP 请求拿 HTML 就行，绕开风控。

## 步骤

### ⭐ 推荐：优先跑现成脚本（自动处理全部坑）

`scripts/fetch_xhs_note.py` 已把"短链解析 → 抓 SSR HTML → 正则提取元数据/图片URL → 防盗链下载原图 → 写 metadata.json"全自动处理（含 `__INITIAL_STATE__` 非标准 JSON、URL 转义、时间戳时区、防盗链、幂等重试等所有已知坑）。**第一步先跑它**，除非脚本因链接过期/风控失败，才降级走下方手动 curl 步骤。

```bash
python3 "<仓库根目录>/skill/scripts/fetch_xhs_note.py" "<分享链接>" "<输出目录>"
```

产出 `<目录>/metadata.json`（title/author/desc/stats/tags/image_urls/local_images）+ `<目录>/imgs/note_XX.jpg`。然后直接跳第 5 步「多模态识别」。

**脚本关键实现**（手动降级时复用其思路）：
- note_id 正则：`/(?:discovery/item|explore|item)/([0-9a-f]{24})`；xsec_token 保留原编码（`%3D`）
- 有 token 走 `discovery/item/<id>?xsec_token=..&xsec_source=app_share`，无 token 走 `explore/<id>`
- **用正则从笔记数据区提取**（不用整体 JSON.parse）。⚠️ **2026-10-16 实测页面结构已变，脚本已双兼容**：
  - 定位：新 `"data":{"noteData":{"atUserList"` ／ 老 `noteDetailMap`
  - 字段：`"title"` / `"desc"` / `"nickname"` / `"userId"`（后者用于**评论按篇归属**）
  - 图片：新结构在 `imageList[].url`，**同一张图有两个 URL**（详情图 `!h5_1080jpg` + 预览图 `!style_…`），差别在 hash 段、末尾 fileId 相同 → **必须按 fileId 去重并保留详情图**（否则 9 张图会翻成 18 张，还混进 14KB 预览垃圾图）；老结构 `urlDefault`。含 `\u002F` 转义需还原 `/` 并升级 `https`
  - ⚠️ 笔记数据在 HTML 里**有两份拷贝**（`__INITIAL_STATE__` + `__SETUP_SERVER_STATE__`）→ 全局正则会把 `tags` 等收两遍，**必须整体去重**
  - 短链跳登录页时 `xsec_token` 藏在 `redirectPath` 参数里，**只解析外层 query 会漏**；请求要带**移动端 UA + 完整分享参数**才拿得到数据
- 时间戳毫秒 → GMT+8 北京时间
- 图片下载带 UA_IPHONE + `Referer: https://www.xiaohongshu.com/`，且**限速 sleep 0.4s**
- 脚本内用的桌面 UA 与移动 UA 双常量，可在遇风控时互换

### 手动路径 A. 链接归一化（仅当脚本失败时降级用）

短链 `https://xhslink.cn/o/xxxxx` 会 302 到真实 URL，从重定向里抓 `Location` 或 body 里的 `noteId`，形如 `https://www.xiaohongshu.com/explore/<24位hex>?...`。

### 手动路径 B. 先解析短链拿真实 noteId + 分享参数

```bash
curl -s -A "<移动端UA>" "https://xhslink.cn/o/<code>" -D - -o /dev/null | grep -i location
# Location 形如 https://www.xiaohongshu.com/discovery/item/<noteId>?xsec_token=...&app_platform=android&...
```
从重定向 URL 里取 **noteId** 和 **整串 query（尤其 xsec_token、app_platform、app_version、ignoreEngage、type、xhsshare 等分享参数）**。

### 手动路径 C. 拉 SSR HTML —— 关键：必须带分享参数 + 走 discovery/item 路径

> **实测核心教训**：请求干净的 `/explore/<noteId>` **会被 `xhs_sec_server` 风控拦成 404 壳**（拿不到任何内容）。必须用**短链分享参数里的完整 query**（含 xsec_token）+ `app_platform=android` 等特征，去请求 **`/discovery/item/<noteId>`**，才能拿到带数据的完整 SSR HTML。

```bash
curl -s -A "<移动端UA>" -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
  -H "Accept-Language: zh-CN,zh;q=0.9" \
  "https://www.xiaohongshu.com/discovery/item/<noteId>?xsec_token=<token>&xsec_source=app_share&app_platform=android&ignoreEngage=true&app_version=9.38.0&type=normal" \
  -o note.html
# 成功标志：文件 >100KB，且含 window.__INITIAL_STATE__
```

关键：
- 用**移动端 UA**（小红书对 PC UA 风控更严，移动端更宽松）
- **不**带 Cookie
- 若干净 explore 路径被拦，**改用 discovery/item + 完整分享 query**
- 返回文件 <1KB 多半是被拦（`xhs_sec_server` / 404 壳），换个路径或补全 query 重试

### 手动路径 D. 从 HTML 里抽原图 URL

**优先**：HTML 内含 `window.__INITIAL_STATE__ = {...};</script>`。它其实是 JS 对象字面量（可能含裸 `undefined`，**不是严格 JSON**）。解析方式：
- 正则切出 `window\.__INITIAL_STATE__\s*=\s*(\{.*?)\}\s*<\/script>`（用 node，别用 python，node 对尾部 `}` 匹配更稳）
- 把 `undefined` 清洗为 `null`：`raw.replace(/([\[,{:]\s*)undefined(?=\s*[,\]}])/g,'$1null')`
- 补一个 `}` 再 `JSON.parse`
- 笔记正文在 `noteData.data.noteData`：字段含 `title / desc / imageList / user / interactInfo / tagList / cover / time / type`

图片 URL 在 `imageList[i].urlDefault`（或 `.url`），形如：
`http://sns-webpic-qc.xhscdn.com/<时间戳>/<hash>/notes_pre_post/<xxx>!h5_1080jpg`
- 末尾 `!h5_1080jpg` 即 1080 宽压缩图，识别够用
- 若想更高清可尝试去掉该后缀或换 `!nd_dft_wlteh_webp_3`

### 手动路径 E. 下载全部图到本地

```bash
mkdir -p imgs
# 逐张下载，必须带 Referer: https://www.xiaohongshu.com/
curl -sL -A "<UA>" -H "Referer: https://www.xiaohongshu.com/" -o imgs/note_01.jpg "<urlDefault>"
```
注意：图 URL 是 `http://`，curl/node 直接下即可；若 403 加 Referer；下载后用文件头 `FF D8` 校验是否为有效 JPEG（成功通常每张 100~180KB）。

### 5. 多模态识别（脚本与手动路径共用，必做）

> **若当前主会话模型不支持读图**（Read 图片返回 "Content filtered"），**不要硬编造内容**。正确做法：**派一个 general-purpose 子代理**（Agent 工具）去逐张 Read 图片并完整 OCR 转录，让它原样输出文字（不要改写概括）。
>
> **⚠️ 实测注意**：general-purpose 子代理**默认可能路由到不支持视觉的模型**（曾命中 Hy3 返回 "Content filtered"），分配不稳定。策略：让子代理**先读 note_01 验证有无视觉**，若返回 `NO_VISION`/Content filtered，就**再派一个**重试（多试几次通常能命中支持视觉的模型）；已实测其中一次成功转录 12 张图。备选：腾讯文档 `mcp__tencent-docs__ocr.extract`（走云端 OCR，不依赖模型视觉，输入本地图 base64，单张<10MB）——但 base64 走工具参数很耗 token，适合少量图。

每张图要求子代理：
- 原文逐字转录（标题/小标题/正文/列表/底部署名都保留）
- 标清图号，保留分段层级（段落用空行、列表用 `-`）
- 纯视觉配图无文字则明确说明
- **读不出就如实说，严禁编造**

### 6. 拼成结构化 markdown（脚本与手动路径共用，必做）

**整理原则**：忠实原文（识别什么写什么，不添观点）；按图片内容逻辑重组章节（面经按"一面/二面/leader面"，非"图1图2"罗列）；问答/清单结构给完整 Q；每章末尾内嵌对应原图保证图文对照；文末给"速览表"压缩全文。

文档骨架（参考成品）：

```markdown
# <笔记标题>

> 来源：小红书笔记，作者 **<author>**
> 链接：<source_url>
> 发布：<publish_time> ｜ IP：<ip_location> ｜ 抓取：<今天日期>
> 数据：赞 <liked> / 评 <comments> / 收藏 <collected>
> 话题：<tags>

---

## 说明
- 笔记内容由 N 张图片组成，按 <逻辑结构> 逐图整理；原图在同目录 imgs/note_XX.jpg。

---

## <按图片内容逻辑分组的章节标题>
### <小节标题>
<图片文字，忠实整理为 markdown>
![note_XX](imgs/note_XX.jpg)

---

## 速览：<一句话总结全文>
| 要点 | 说明 |
|---|---|
| <把全文压成速查表，最有复用价值> |

---

> 基于小红书笔记图片识别整理；原图保留在 imgs/ 下供查阅。
```

## 失败兜底

- **HTML 里没找到 `window.__INITIAL_STATE__` / 文件只有 1KB 内**：多半被 `xhs_sec_server` 拦截。换 **`discovery/item/<noteId>` + 完整分享 query（含 xsec_token）** 重试；或加 `-H "Accept: text/html,*/*"`。
- **`__INITIAL_STATE__` 解析报错 `Unexpected token`**：是裸 `undefined`，清洗为 `null` 后重试。
- **图片下载 403/空**：加 `-H "Referer: https://www.xiaohongshu.com/"`；或换网络。
- **主模型读不了图（Content filtered）**：**别编**！派 general-purpose 子代理走视觉 OCR。
- **全程被风控挡住**：礼貌要求用户手动保存图片直接发你，走多模态识别 + 整理（最稳兜底）。

## 反模式（不要做）

- ❌ 不要用 agent-browser 打开登录墙等 JS 渲染——99% 看不到正文
- ❌ 不要只试一次干净 `/explore/` 路径就放弃——**必须带分享参数走 discovery/item**
- ❌ 主模型不支持读图时，不要假装"已识别"编造图片文字——要么派视觉子代理，要么请用户发图
- ❌ 不要尝试登录态抓取（需要 cookie + 处理风控验证码，代价极高）

## 已验证案例

- 如何在面试前快速建立产品思维？讲清楚项目：xhslink.cn/o/3XN5hm4sika → **用现成脚本 `fetch_xhs_note.py` 类方案**抓 9 张原图 + SSR HTML 取正文 → OCR 后整理成完整方法论文档。
- 字节红果 AI 产品经理新鲜面经（已复盘）：xhslink.cn/o/9X3sVyr6YRR → 13 张 1080×1440 原图 → 一面 7 题 / 二面 3 题 / leader 面 3 题完整结构化输出。
- 如何用 AI 准备面试：Prompt 篇：xiaohongshu.com/explore/6a8bb6020000000014026ba7 → **fetch_xhs_note.py 一条命令 8.4s** 抓 12 张原图（含限速）→ 视觉子代理转录 4 个可复用 Prompt → 完整方法论文档。

## 脚本来源与参考

`scripts/fetch_xhs_note.py` 源自资料库里的 `xhs-note-to-md.skill` 成品（小红书官方/社区沉淀的可复用打包），经核对与本 skill 的手动流程一致，现作为本 skill 的首选执行引擎。

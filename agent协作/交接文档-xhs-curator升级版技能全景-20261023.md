---
产出方: xhs-curator 窗口（WorkBuddy）
日期: 2026-10-23
状态: 交接文档 v1，供 Codex / 升级版 AnyLink2Note 参照改造
范围: xhs-curator 技能体系（发布包 + 工作台 + 长任务协议）的完整现状
---

# 交接文档：xhs-curator 升级版技能全景

## 一、一句话定位

**一个「单一入口、双引擎、可安装可观察」的小红书采集技能**：用户给链接或主页，技能自动硬路由到对应引擎；批量采集在本地工作台里进行，有实时进度、协作式停止、持久结果卡；装一次覆盖全部能力。

## 二、三层架构（先分清这三个概念，否则会改错层）

| 层 | 位置 | 职责 |
|---|---|---|
| **项目/仓库** | `xhs-curator`（Git） | 全部代码：单篇抓取、批量工作台、导出管线、install.py |
| **Skill 发布包** | 仓库内 `skill/`（安装后为 `~/.workbuddy/skills/xhs-curator/`） | 只含 `SKILL.md` + 单篇脚本 + README；**轻入口** |
| **工作台服务** | 仓库根 `xhs_picker_server.py`（端口 8788） | 登录态批量采集的 UI + 任务调度 |

**关键设计（2026-10-20 P0 定稿）**：采用「仓库即安装包 + 轻入口 Skill」——
- 标准安装 = `git clone` 仓库 → `python install.py`（复制 skill/ 到技能目录 + 写 marker + 依赖检测）
- 运行时通过 marker 定位仓库根：`环境变量 XHS_CURATOR_HOME → skill 目录 .xhs-curator-root(JSON) → 向上探测`
- **禁止**把 skill/ 目录单独复制作为完整安装（那只支持单篇速读）；此约束已写入 README 与 SKILL.md
- **解释器一致性**：marker 记录安装时的 Python 路径，所有脚本必须用它运行（防「依赖装在 A、脚本用 B」）；解释器失效 → 路由停止 + 修复引导，不静默回退

## 三、统一入口路由（硬判定，AI 不许猜）

```
用户发链接/分享文字
 → 必跑: <仓库根>/skill/scripts/fetch_xhs_note.py --classify "<原文>"
 → link_type = single | profile | invalid | unknown
    single  → 引擎 A（匿名 HTTP 单篇，产出 .md）
    profile → 引擎 B（登录态工作台，勾选批量）
    invalid → 如实说无法识别
    unknown → 短链解析不可达/短码失效（诚实态，绝不误报「链接无效」）
```

- classify 先 resolve 短链再看 URL 形态；手机端主页分享文字同理
- 实测坑：真实 xhslink 对无效短码会**重定向到首页**——必须判为 unknown 而非 invalid

## 四、双引擎分工

| 引擎 | 方式 | 能力 | 限制 |
|---|---|---|---|
| **A** | curl_cffi 直抓 SSR HTML（匿名） | 单篇正文/原图/字幕 | 拿不到博主评论；平台改版需跟修 |
| **B** | Playwright 驱动本机 Chrome（登录态存 `browser_profile/`） | 整号列表、批量、博主评论 | 需扫码登录一次；抓取中勿关浏览器窗口 |

## 五、工作台能力全景（2026-10-21/22 上线，本次升级核心）

1. **三入口 + 单篇导入**：博主主页 / 关键词搜索 / 已抓笔记 / 单篇导入
2. **结构化进度**：日志面板顶部实时进度条（已处理 N/M、成功/失败/跳过、当前篇标题）
   - 契约：`total = 全部选中项（含断点跳过）`，`processed = success + failed + skipped`
3. **协作式停止**：`POST /job/stop` 写控制文件 `<job_id>.control.json`，抓取脚本每篇开始前读 → 抓完当前篇停、不再开始下一篇、已完成全保留、终态 `stopped`（≠ failed）；`p.terminate()` 只保留在 `/job/kill` 内部兜底
4. **持久结果卡（页面级隔离）**：sessionStorage 记录本页发起的 job_id，只渲染该任务；新开标签页不串历史卡；同页刷新仍在
   - 四态：`done`（成功卡：素材已保存至 downloads + 打开保存位置 + 查看已抓笔记 + 复制「生成 Markdown」请求）/ `stopped`（已停止 N/M + 继续抓取剩余）/ `partial`（失败明细 + 仅重试失败项 + 查看运行日志）/ `failed`（日志 + 知道了）
   - 按钮可见性由后端 `compute_card_actions()` 下发（可单测）
5. **任务记录持久化**：`runtime/jobs/<job_id>.json`（主记录）+ `.stats.json`（进度）+ `.log`（完整日志）+ `.control.json`（控制）
   - API：`GET /api/jobs`（只读主记录，排除 stats，schema 必含 job_id+status）、`GET /api/jobs/<id>/log`、`POST /api/jobs/<id>/confirm`、`POST /api/retry_failed`、`GET /open-downloads`
6. **诚实边界**：素材抓取完成 ≠ Markdown 已生成 ≠ 已导入 Obsidian；卡上文案严格区分；「继续整理」只复制「生成 Markdown」请求回对话，工作台不假装执行 OCR

## 六、SKILL.md 的行为约定（改这个文件前必读）

1. **评论偏好绝不弹窗问**：由工作台底栏「抓取博主评论」复选框承接（默认不勾）；在对话里问"要不要评论"=违规
2. **勾选主权**：AI 严禁代勾选、禁止跳过用户勾选直接跑批量（即使用户说"测试"）
3. **classify 硬路由**：禁止按文字内容猜链接类型
4. **状态三态不混称**：素材包/ Markdown / 已入库
5. **SKILL 文档纪律（血的教训）**：规则自相矛盾对 AI 是随机骰子（读到哪行算哪行）——改规则必须全文检索旧表述同步删除；单句省略主语（如"只对主页问"）必被字面执行

## 七、测试基线与验证

- 全量：`python -W error::ResourceWarning -m unittest discover -s tests` → **75 tests, OK**
- 额外要求：`-W always` 下 ResourceWarning 计数必须为 0（Codex 复验门槛）
- 关键测试：`test_cooperative_stop.py`（fake 5 篇任务 2/5 停止 → stopped/ok=2/后 3 篇未启动/磁盘重读一致，含确定性门消除竞态）、`test_classify_install.py`（分类器 + 安装流程 + 技能目录识别）、`test_job_finalize.py`（进程级终态/竞态窗口）、`test_job_record.py`（统计契约/持久化/actions）

## 八、升级时间线（关键提交，供对照改造）

```
83cae7e docs 发布包完整性设计与测试计划
b733819/c085605 feat 安装器 + classify + SKILL 重写（方案 B）
e0b70e7 fix 旧安装说明清零 + 技能目录识别不猜测
71bb69c fix 对话层不问评论 + 解释器一致性（marker JSON）
8b4004e docs SKILL 全文误读审计（5 处歧义）
09f93d2 fix stats.json 误渲染假失败 + 继续整理引导
4759db8 feat 结果卡页面级隔离（sessionStorage）
5c68331 feat P0-A 协作式停止 + 结构化进度 + stopped
e8063c3 feat P0-C 素材已保存/打开保存位置/文案对齐
18540e4/aa35fa4 fix 统计契约统一 + 停止诚实化 + 测试卫生
dafab8a docs README 同步长任务能力 + 新版截图
```

## 九、未完成 / 待决（别踩重叠）

| 项 | 状态 |
|---|---|
| P0-A+ `/job/control` 带 job_id 校验 | spec 已交（`Spec-P0A+控制接口job_id校验-20261023.md`），待 Codex 批复；含 legacy `/job/stop` 兼容 |
| P1-A Markdown 独立阶段（OCR 成本闸门） | 待雅旭确认 OCR 成本口径后设计 |
| P1-B 对话控制形态 | **已定：不含邮件**（雅旭 2026-10-23 决断，邮件链路技术可行但产品不采用）；完成感知=结果卡 + 回对话问 AI |
| 桌面通知 | P2 未做 |

## 十、给 Codex 改造 AnyLink2Note 的建议

**可直接复用**：
1. 「仓库即安装包 + marker 定位 + 解释器一致性」三件套（install.py 约 240 行，改路径常量即可复用）
2. classify 硬路由模式（`link_type` 四态 + unknown 诚实态）
3. 协作式停止契约（控制文件 + 每篇检查 + stopped 终态）
4. 结果卡页面级隔离（sessionStorage job_id + 后端 actions 下发）
5. 测试护栏三条：`-W error::ResourceWarning`、fake 子进程契约测试、确定性门消竞态

**必须避免**：
1. 双份同源代码（skill/ 与根目录各一份脚本）→ 必然漂移
2. 用一次性 Toast 当唯一完成反馈
3. 在 UI 上伪装已执行的动作（复制提示词却叫"继续 OCR"）
4. 让 AI 按文字内容猜路由
5. 静默降级（解释器失效回退、状态抢跑改 failed）

---
产出方: xhs-curator 窗口（WorkBuddy）
日期: 2026-10-23
状态: 最小 spec，待 Codex 批复；批准前不改生产代码
来源: P0-B Spike 验证记录（Spike验证记录-P0B对话桥接-20261022.md）V3 缺口：控制接口无 job_id 定位
---

# P0-A+ 最小 Spec：/job/control 带 job_id 校验

## 问题（Spike 实证）

- 现状 `POST /job/stop` 完全忽略请求体中的 job_id，按「全局当前进程」语义执行
- 实测：带无关 job_id `{"job_id": "完全不相干的job_id-12345"}` → 仍按全局状态响应
- 风险：多窗口同时抓取时，任一窗口的停止请求会误停别的窗口发起的任务

## 方案（最小改动）

### 1. 新增接口 `POST /job/control`

请求体：`{"job_id": "<目标任务>", "action": "stop"}`

校验顺序：
1. `job_id` 与当前运行中任务一致 → 写控制文件，返回 `{"ok": true, "mode": "cooperative"}`
2. `job_id` 不匹配但当前有运行中任务 → **拒绝**，返回 `{"ok": false, "error": "job_id 不匹配当前任务（当前运行: <实际 id>）"}`，不写控制文件
3. 无运行中任务 → `{"ok": false, "error": "当前没有运行中的任务"}`
4. 请求体缺 job_id → **拒绝**（强制显式指定，不给默认全局语义）

### 2. `/job/stop` 兼容处理

- 保留为 `job_id` 缺省时的显式兜底（前端旧页面仍在用），但响应中附 `"legacy": true` 提示
- 前端 `stopJob()` 改为携带 `sessionStorage.xhs_current_job` 调 `/job/control`；无 session key 时回退 `/job/stop`（附 legacy 标记）

### 3. 测试（新增 4 用例，test_cooperative_stop.py 扩展）

1. 正确 job_id → 停止成功、终态 stopped
2. 错误 job_id + 有运行任务 → 拒绝、任务继续跑、控制文件未被写
3. 缺 job_id → 拒绝（不执行全局停止）
4. 无运行任务 → 拒绝并说明

## 不做（边界）

- 不改 selection.json、不改勾选主权逻辑
- 不做发起来源绑定（对话 ID ↔ job_id 的强绑定需要 P1-B 桥接验证，超出本增量）
- 不动 P1-A（Markdown 阶段）

## 影响面

- `xhs_picker_server.py`：+1 路由、stopJob 前端 3 行
- `tests/test_cooperative_stop.py`：+4 用例
- 不改抓取脚本、不改 install/marker

# -*- coding: utf-8 -*-
"""
小红书笔记 采集工作台（常驻版）

用法:
    python xhs_picker_server.py [--port 8788] [--notes notes.json]

同一页面四个常驻入口（切换不用重启服务）:
    [博主主页]   notes.json（--notes 可换源），卡片可勾选
    [关键词搜索] search_notes.json；页内输入关键词即可后台跑 xhs_search_fetch.py
    [单篇导入]   粘贴笔记链接/短链/分享文字 → 解析 → 抓取这一篇（最初的单篇直抓）
    [已抓笔记]   downloads/_manifest.json 状态一览，可一键打开本地文件夹

其他:
    - 卡片自动打「已抓过」标记（对照 _manifest.json），「全选未抓」一键勾选没抓过的
    - 页内「开始抓取」: 后台跑 xhs_fetch_selected.py，日志实时滚动，抓完自动刷新标记
    - 勾选 localStorage 持久化 + 自动保存 selection.json（主页/搜索结果可混选一起抓）
    - 清单每次进页面都重新读文件：重跑抓取脚本后刷新页面即最新数据
    - 封面图经本地代理转发，绕过 CDN 防盗链
"""
import argparse
import collections
import glob
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
MAIN_NOTES = os.path.join(BASE, "notes.json")          # 可被 --notes 覆盖
SEARCH_NOTES = os.path.join(BASE, "search_notes.json")
SEL = os.path.join(BASE, "selection.json")
DOWNLOADS = os.path.join(BASE, "downloads")
FETCH_SCRIPT = os.path.join(BASE, "xhs_fetch_selected.py")
SEARCH_SCRIPT = os.path.join(BASE, "xhs_search_fetch.py")
RUNTIME_DIR = os.path.join(BASE, "runtime")
JOBS_DIR = os.path.join(RUNTIME_DIR, "jobs")


def jobs_dir():
    """任务记录目录（测试可重定向）"""
    return JOBS_DIR


def new_job_id(jtype):
    ms = (time.time_ns() // 10**6) % 1000
    return time.strftime("%Y%m%d-%H%M%S") + f"-{ms:03d}-{jtype}"


def new_job_record(jtype, selected=0, with_comments=True, only_ids=None):
    return {"job_id": new_job_id(jtype), "type": jtype,
            "with_comments": bool(with_comments),
            "only_ids": list(only_ids or []),
            "selected": selected,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "ended_at": "", "exit_code": None, "status": "running",
            "confirmed": False, "stats": None}


def save_job(rec):
    os.makedirs(jobs_dir(), exist_ok=True)
    with open(os.path.join(jobs_dir(), rec["job_id"] + ".json"),
              "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)


def load_jobs():
    """最近任务记录（倒序）。数据源是文件——服务重启后仍可追溯。
    2026-10-21 复验 P0-5：只读主任务记录 <job_id>.json，明确排除
    <job_id>.stats.json 等附属文件；且必须 schema 完整（有 job_id+status）
    才返回，防止附属文件被误渲染成假失败卡。"""
    out = []
    d = jobs_dir()
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d), reverse=True):
            if not fn.endswith(".json") or fn.endswith(".stats.json"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    rec = json.load(f)
            except Exception:
                continue
            if not isinstance(rec, dict) or not rec.get("job_id") \
                    or not rec.get("status"):
                continue   # schema 不完整 = 不是任务记录
            out.append(rec)
    return out


def confirm_job(job_id):
    for r in load_jobs():
        if r.get("job_id") == job_id:
            r["confirmed"] = True
            save_job(r)
            return True
    return False


def extract_failed_ids(rec):
    return [f.get("note_id") for f in (rec.get("stats") or {}).get("failures") or []
            if f.get("note_id")]


def compute_card_actions(rec):
    """结果卡按钮可见性（后端下发 → 前端只渲染，行为可单测）：
    - done：查看已抓笔记
    - partial/failed 且有失败条目：查看失败原因 + 仅重试失败项
    - failed 且无失败条目（崩溃无统计）：查看运行日志（不是必然可重试）
    """
    failed_ids = extract_failed_ids(rec)
    status = rec.get("status")
    return {"view_notes": status in ("done", "stopped", "partial"),
            "continue_flow": status == "done",
            "resume": status == "stopped",   # 继续抓取剩余（重跑即自动续）
            "retry": status in ("partial", "failed") and bool(failed_ids),
            "failures": status in ("partial", "failed") and bool(failed_ids),
            "log": status == "failed"}


def compute_job_status(jtype, stats, exit_code):
    """不以 exit=0 笼统判定：fetch/one 依赖脚本回写的逐篇统计"""
    if jtype == "search":
        return "done" if exit_code == 0 else "failed"
    if not isinstance(stats, dict):
        return "failed"               # 子进程异常终止，无统计 → failed
    if stats.get("user_stopped"):
        return "stopped"          # 用户协作式停止：诚实终态，非 failed
    ok = stats.get("ok") or 0
    planned = stats.get("total") or stats.get("planned") or 0
    if planned > 0 and ok == planned:
        return "done"
    if 0 < ok < planned:
        return "partial"
    return "failed"

try:  # 单篇直抓的链接解析复用抓取脚本里的实现
    from xhs_fetch_selected import resolve_note_link
except Exception:
    resolve_note_link = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ---------------- 后台任务（页内搜索 / 页内抓取） ----------------

JOB = {"proc": None, "lines": collections.deque(maxlen=800),
       "status": "idle", "type": "", "exit": None}
JOB_LOCK = threading.Lock()


def build_cmd(jtype, keyword="", url="", with_comments=True, only_ids=None):
    """构造后台任务命令行（纯函数，2026-10-19 便于测试评论开关接线）

    返回 (cmd, err)：err 非 None 表示参数无效。
    with_comments=False 且任务涉及抓取时追加 --no-comments
    （承接工作台「要保留博主评论吗」询问的「不要」答案）。
    only_ids 非 None 时（fetch）追加 --only-ids ——「仅重试失败项」。
    """
    if jtype == "fetch":
        cmd = [sys.executable, FETCH_SCRIPT]
    elif jtype == "one":
        if not (url or "").strip():
            return None, "缺少要抓取的笔记链接"
        cmd = [sys.executable, FETCH_SCRIPT, "--url", url]
    elif jtype == "search":
        if not (keyword or "").strip():
            return None, "关键词不能为空"
        cmd = [sys.executable, SEARCH_SCRIPT, "--keyword", keyword]
    else:
        return None, f"未知任务类型 {jtype}"
    if jtype in ("fetch", "one") and not with_comments:
        cmd.append("--no-comments")
    if jtype == "fetch" and only_ids:
        cmd += ["--only-ids", ",".join(only_ids)]
    return cmd, None


def request_cooperative_stop():
    """协作式停止（2026-10-21 P0-A）：写控制文件，抓取循环在当前篇结束后
    停止；已完成内容保留，终态记为 stopped（不用 p.terminate()）。
    返回 (ok, mode)。"""
    with JOB_LOCK:
        rec = JOB.get("record") or {}
        if rec.get("job_id") and JOB["status"] == "running":
            cpath = os.path.join(jobs_dir(), rec["job_id"] + ".control.json")
            with open(cpath, "w", encoding="utf-8") as f:
                json.dump({"stop_requested": True}, f)
            return True, "cooperative"
        return False, "当前没有运行中的任务"


def start_job(jtype, keyword="", url="", with_comments=True, only_ids=None):
    with JOB_LOCK:
        p = JOB.get("proc")
        if p and p.poll() is None:
            return False, "已有任务在跑（请先停止或等它结束）", ""
        cmd, err = build_cmd(jtype, keyword, url, with_comments, only_ids)
        if err:
            return False, err, ""
        script = cmd[1]
        if not os.path.exists(script):
            return False, f"找不到 {script}", ""
        selected = 0
        if jtype == "fetch":
            selected = len((load_json(SEL) or {}).get("notes") or [])
        elif jtype == "one":
            selected = 1
        rec = new_job_record(jtype, selected=selected,
                             with_comments=with_comments, only_ids=only_ids)
        save_job(rec)
        JOB["lines"].clear()
        JOB["type"] = jtype
        JOB["exit"] = None
        JOB["status"] = "running"
        JOB["job_id"] = rec["job_id"]
        JOB["record"] = rec
        try:
            os.makedirs(jobs_dir(), exist_ok=True)
            env = {**os.environ,
                   "PYTHONIOENCODING": "utf-8",
                   "XHS_JOB_STATS": os.path.join(jobs_dir(), rec["job_id"] + ".stats.json"),
                   "XHS_JOB_CONTROL": os.path.join(jobs_dir(), rec["job_id"] + ".control.json")}
            logf = open(os.path.join(jobs_dir(), rec["job_id"] + ".log"),
                        "w", encoding="utf-8")
            p = subprocess.Popen(cmd, cwd=BASE, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True,
                                 encoding="utf-8", errors="replace",
                                 bufsize=1, env=env)
        except Exception as e:
            JOB["status"] = "failed"
            JOB["exit"] = -1
            JOB["lines"].append(f"[X] 启动失败: {e}")
            rec["status"] = "failed"
            rec["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            rec["exit_code"] = -1
            save_job(rec)
            return False, str(e), rec["job_id"]
        JOB["proc"] = p
        job_id = rec["job_id"]

        def pump():
            for ln in p.stdout:
                JOB["lines"].append(ln.rstrip())
                try:
                    logf.write(ln.rstrip() + "\n")
                    logf.flush()
                except Exception:
                    pass
            try:
                p.stdout.close()
            except Exception:
                pass
            rc = p.wait()
            try:
                logf.close()
            except Exception:
                pass
            JOB["exit"] = rc
            JOB["lines"].append("")
            JOB["lines"].append(f"=== 任务结束（{'成功' if rc == 0 else f'退出码 {rc}'}）===")

        def finalize():
            """任务结束 → 读脚本回写的统计 → 算状态 → 持久化记录。
            全程 try/except：任何异常都会把记录明确落为 failed，
            绝不把任务永久留在 running（2026-10-21 复验修正）。"""
            rec = dict(JOB.get("record") or {})
            try:
                rc = p.wait()
            except Exception as e:
                rec["status"] = "failed"
                rec["error"] = f"等待进程退出失败: {e}"
                rec["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                JOB["record"] = rec
                JOB["status"] = "failed"
                save_job(rec)
                return
            try:
                logf.close()
            except Exception:
                pass
            try:
                if rec.get("job_id") != job_id:
                    return
                rec["exit_code"] = rc
                rec["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                sp = os.path.join(jobs_dir(), job_id + ".stats.json")
                stats = None
                if os.path.exists(sp):
                    try:
                        with open(sp, encoding="utf-8") as f:
                            stats = json.load(f)
                    except Exception:
                        stats = None
                rec["stats"] = stats
                rec["status"] = compute_job_status(rec["type"], stats, rc)
            except Exception as e:
                rec["status"] = "failed"
                rec["error"] = f"统计汇总失败: {e}"
            JOB["record"] = rec
            JOB["status"] = rec["status"]
            save_job(rec)

        threading.Thread(target=pump, daemon=True).start()
        threading.Thread(target=finalize, daemon=True).start()
        return True, "started", job_id


def job_state():
    """任务状态查询。2026-10-21 复验修正：移除「running 且 exit 未设 → failed」
    的抢跑兜底——子进程退出后、finalize 写入权威状态前的窗口内，必须继续
    报告可等待的 running，让前端保持轮询；永久 running 由 finalize 的
    try/except/finally 兜底防住（异常也会落为 failed）。"""
    with JOB_LOCK:
        p = JOB.get("proc")
        running = bool(p and p.poll() is None)
        st = {}
        sp = os.path.join(jobs_dir(), ((JOB.get("record") or {}).get("job_id") or "") + ".stats.json")
        if running and os.path.exists(sp):
            try:
                with open(sp, encoding="utf-8") as f:
                    st = json.load(f)
            except Exception:
                st = {}
        return {"status": JOB["status"], "type": JOB["type"], "exit": JOB["exit"],
                "job_id": (JOB.get("record") or {}).get("job_id", ""),
                "stats": st,
                "running": running, "lines": list(JOB["lines"])[-300:]}


def manifest_items():
    """downloads/_manifest.json → [{note_id, seq, title, type, date, ok, folder, comments}]"""
    recs = load_json(os.path.join(DOWNLOADS, "_manifest.json")) or []
    # note_id → 本地文件夹（老 manifest 记录可能没有 _seq，用 raw.json 反查最可靠）
    folder_by_note = {}
    if os.path.isdir(DOWNLOADS):
        for d in os.listdir(DOWNLOADS):
            full = os.path.join(DOWNLOADS, d)
            if not os.path.isdir(full):
                continue
            r = load_json(os.path.join(full, "raw.json")) or {}
            if r.get("note_id"):
                folder_by_note[r["note_id"]] = d
    out = []
    for r in recs:
        if not isinstance(r, dict) or not r.get("note_id"):
            continue
        folder = folder_by_note.get(r["note_id"], "")
        if not folder:
            seq0 = int(r.get("_seq") or 0)
            hits = glob.glob(os.path.join(DOWNLOADS, f"{seq0:02d}_*"))
            if hits:
                folder = os.path.basename(hits[0])
        seq = r.get("_seq")
        if not seq and folder:
            try:
                seq = int(folder.split("_", 1)[0])
            except ValueError:
                seq = 0
        out.append({"note_id": r["note_id"], "seq": int(seq or 0),
                    "title": r.get("list_title") or r.get("title") or "",
                    "type": r.get("list_type") or "", "date": r.get("list_date") or "",
                    "ok": bool(r.get("ok")), "folder": folder,
                    "comments": len(r.get("author_comments") or []),
                    "url": r.get("url") or ""})
    out.sort(key=lambda x: (x["seq"], x["title"]))
    return out


DETAIL_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>详情预览 · 采集工作台</title>
<style>
body{margin:0;font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}
.bar{height:48px;background:#1d2129;color:#fff;display:flex;align-items:center;gap:12px;
  padding:0 14px;position:sticky;top:0;z-index:9}
.bar button{background:#ff2e4d;border:0;color:#fff;font-weight:600;font-size:14px;
  padding:7px 16px;border-radius:8px;cursor:pointer}
.bar button:hover{opacity:.88}
.bar a{color:#ffd7dd;font-size:13px;text-decoration:none;
  border:1px solid rgba(255,255,255,.28);padding:6px 12px;border-radius:8px}
.bar .tip{color:rgba(255,255,255,.55);font-size:12px;margin-left:auto;text-align:right}
iframe{width:100%;height:calc(100vh - 48px);border:0;display:block;background:#fff}
</style>
</head>
<body>
<div class="bar">
  <button onclick="back()">&larr; 返回列表</button>
  <a href="__URL__" target="_blank">浏览器打开&#8599;</a>
  <span class="tip">按 Esc 也可返回<br>嵌套视图若提示登录属正常（不带登录态），点「浏览器打开」看完整版</span>
</div>
<iframe src="__URL__" allow="fullscreen"></iframe>
<script>
function back(){ location.href = '/'; }
document.addEventListener('keydown', e => { if(e.key === 'Escape') back(); });
</script>
</body>
</html>
"""

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>采集工作台</title>
<style>
:root{
  --bg:#f6f7f9; --card:#fff; --line:#e6e8ec; --txt:#1d2129; --sub:#86909c;
  --brand:#ff2e4d; --brand-soft:#fff1f3; --ok:#00b42a; --teal:#0aa88f; --teal-soft:#e2f6f1;
}
@media (prefers-color-scheme: dark){
  :root{ --bg:#17181c; --card:#1f2126; --line:#303238; --txt:#e8e9ec; --sub:#8a8f99;
         --brand:#ff5c78; --brand-soft:#2a1d21; --teal:#2cc6a8; --teal-soft:#143029; }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
  font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:20;background:var(--bg);border-bottom:1px solid var(--line);
  padding:14px 22px 10px}
h1{margin:0 0 6px;font-size:18px;display:flex;align-items:baseline;gap:10px}
h1 .who{font-size:13px;color:var(--sub);font-weight:400}
.tabs{display:flex;gap:6px;margin:8px 0 2px}
.tab{border:1px solid var(--line);background:var(--card);color:var(--sub);
  padding:6px 14px;border-radius:999px;font-size:13px;cursor:pointer}
.tab.active{background:var(--brand);border-color:var(--brand);color:#fff;font-weight:600}
.meta{color:var(--sub);font-size:12.5px}
.tools{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}
button{font:inherit;cursor:pointer;border:1px solid var(--line);background:var(--card);
  color:var(--txt);padding:7px 13px;border-radius:8px;transition:.15s}
button:hover{border-color:var(--brand);color:var(--brand)}
button.primary{background:var(--brand);border-color:var(--brand);color:#fff;font-weight:600}
button.primary:hover{opacity:.9;color:#fff}
button.primary:disabled{opacity:.5;cursor:not-allowed}
button.teal{background:var(--teal);border-color:var(--teal);color:#fff;font-weight:600}
button.teal:hover{opacity:.9;color:#fff}
input[type=search],input[type=text]{font:inherit;padding:7px 12px;border:1px solid var(--line);
  border-radius:8px;background:var(--card);color:var(--txt);min-width:220px}
.count{margin-left:auto;font-weight:600;color:var(--brand)}
.grid{display:grid;gap:14px;padding:18px 22px 150px;
  grid-template-columns:repeat(auto-fill,minmax(215px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;
  position:relative;transition:.15s;display:flex;flex-direction:column}
.card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(0,0,0,.08)}
.card.on{border-color:var(--brand);box-shadow:0 0 0 2px var(--brand-soft)}
.card img{width:100%;aspect-ratio:3/4;object-fit:cover;display:block;background:var(--line)}
.ph{width:100%;aspect-ratio:3/4;display:flex;align-items:center;justify-content:center;
  color:var(--sub);font-size:12px;background:var(--line)}
.card .body{padding:10px 11px 12px;display:flex;flex-direction:column;gap:6px;flex:1}
.card .t{font-size:13.5px;font-weight:600;line-height:1.45;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
  word-break:break-word}
.card .s{color:var(--sub);font-size:12px;margin-top:auto}
.tag{position:absolute;top:8px;left:8px;background:rgba(0,0,0,.62);color:#fff;font-size:11px;
  padding:2px 7px;border-radius:6px;backdrop-filter:blur(4px)}
.tag-top{top:34px;background:rgba(255,46,77,.92)}
.tag-done{top:60px;background:var(--teal);color:#fff}
.cb{position:absolute;top:7px;right:7px;width:23px;height:23px;border-radius:6px;
  border:2px solid #fff;background:rgba(0,0,0,.42);display:flex;align-items:center;
  justify-content:center;color:#fff;font-size:14px;font-weight:700}
.card.on .cb{background:var(--brand);border-color:var(--brand)}
.card a{color:inherit;text-decoration:none}
.card a.t:hover{color:var(--brand)}
.card .s a{color:var(--brand);font-weight:600;white-space:nowrap}
.card .s a:hover{text-decoration:underline}
.bar{position:fixed;left:0;right:0;bottom:0;z-index:30;background:var(--card);
  border-top:1px solid var(--line);padding:12px 22px;display:flex;gap:12px;align-items:center}
.bar .tip{color:var(--sub);font-size:12.5px}
.toast{position:fixed;left:50%;top:22px;transform:translateX(-50%);z-index:50;
  background:var(--ok);color:#fff;padding:10px 20px;border-radius:10px;font-weight:600;
  opacity:0;pointer-events:none;transition:.25s}
.toast.show{opacity:1}
.empty{padding:60px 22px;text-align:center;color:var(--sub);line-height:2}
.empty code{background:var(--card);border:1px solid var(--line);border-radius:6px;
  padding:2px 8px;font-size:12.5px}
.logpanel{position:fixed;left:0;right:0;bottom:57px;z-index:29;background:var(--card);
  border-top:1px solid var(--line);display:flex;flex-direction:column}
.logpanel .lh{display:flex;gap:10px;align-items:center;padding:8px 22px;border-bottom:1px solid var(--line)}
.logpanel .lh .st{font-weight:600}
.logpanel pre{margin:0;padding:10px 22px;height:170px;overflow-y:auto;font:12px/1.55 Consolas,
  "Courier New",monospace;white-space:pre-wrap;word-break:break-all}
table.done{width:calc(100% - 44px);margin:18px 22px 150px;border-collapse:collapse;
  background:var(--card);border-radius:12px;overflow:hidden;font-size:13px}
table.done th,table.done td{border-bottom:1px solid var(--line);padding:9px 12px;text-align:left}
table.done th{color:var(--sub);font-weight:500;font-size:12.5px;white-space:nowrap}
table.done td.t{font-weight:600;max-width:420px}
.okb{display:inline-block;background:var(--teal-soft);color:var(--teal);border-radius:6px;
  padding:1px 8px;font-size:12px;font-weight:600}
.nob{display:inline-block;background:var(--brand-soft);color:var(--brand);border-radius:6px;
  padding:1px 8px;font-size:12px;font-weight:600}
</style>
</head>
<body>
<header>
  <h1>采集工作台 <span class="who" id="who"></span></h1>
  <nav class="tabs">
    <button class="tab active" data-tab="main" onclick="switchTab('main')">博主主页</button>
    <button class="tab" data-tab="search" onclick="switchTab('search')">关键词搜索</button>
    <button class="tab" data-tab="one" onclick="switchTab('one')">单篇导入</button>
    <button class="tab" data-tab="done" onclick="switchTab('done')">已抓笔记</button>
  </nav>
  <div class="tools" id="toolsList">
    <input type="search" id="q" placeholder="搜索标题关键词…">
    <button onclick="pick('all')">全选</button>
    <button onclick="pick('none')">清空</button>
    <button onclick="pick('invert')">反选</button>
    <button onclick="pick('video')">仅视频</button>
    <button onclick="pick('normal')">仅图文</button>
    <button class="teal" onclick="pick('undone')">全选未抓</button>
    <span class="count" id="cnt">已选 0 篇</span>
  </div>
  <div class="tools" id="toolsSearch" style="display:none">
    <input type="text" id="kw" placeholder="输入关键词，如：AI产品经理 面试" style="min-width:300px">
    <button class="primary" id="btnSearch" onclick="startSearch()">搜 索</button>
    <span class="meta">后台跑搜索脚本，结果存 search_notes.json，可与主页清单混选一起抓</span>
  </div>
  <div class="tools" id="toolsOne" style="display:none">
    <input type="text" id="oneUrl" placeholder="粘贴笔记分享链接或整段分享文字（支持 xhslink.cn 短链）" style="min-width:430px;flex:1">
    <button id="btnResolve" onclick="resolveOne()">解 析</button>
    <button class="teal" id="btnFetchOne" onclick="fetchOne()" disabled>抓取这篇</button>
  </div>
  <div class="meta" id="oneMeta" style="margin-top:6px;display:none"></div>
  <div class="meta" id="listMeta" style="margin-top:6px"></div>
</header>

<div id="jobCard" style="display:none"></div>
<div class="grid" id="grid"></div>
<div id="doneWrap" style="display:none"></div>
<div id="oneWrap" style="display:none"></div>

<div class="logpanel" id="logpanel" style="display:none">
  <div class="lh">
    <span class="st" id="logStatus">任务运行中…</span>
    <button onclick="stopJob()">停止</button>
    <button onclick="toggleLog()">收起</button>
  </div>
  <div id="progWrap" style="display:none;padding:10px 14px 0">
    <div class="bar" style="margin:0 0 6px"><div id="progBar" style="width:0%"></div></div>
    <div class="stats" style="margin:0 0 4px">
      <span><b id="progText">已处理 0 / 0</b></span>
      <span class="tag ok" id="progOk">成功 0</span>
      <span class="tag fail" id="progFail">失败 0</span>
      <span class="tag skip" id="progSkip">跳过 0</span>
    </div>
    <div class="note" id="progCurrent"></div>
  </div>
  <pre id="log"></pre>
</div>

<div class="bar" id="bar">
  <label style="display:flex;align-items:center;gap:4px;font-size:12px;font-weight:700;color:#1a1a1a">
    <input type="checkbox" id="withComments"> 抓取博主评论
  </label>
  <button class="primary" id="btnFetch" onclick="startFetch()">开始抓取</button>
  <button onclick="save()">保存选中清单</button>
  <button onclick="copySel()">复制清单文本</button>
  <span class="tip" id="barTip">点卡片=勾选；点标题或「原文↗」在本窗口看详情，按 Esc 或「← 返回列表」回来，勾选不会丢。⚠ 抓取时会弹出一个专用 Chrome 窗口，抓取进行中请勿关闭它，否则本轮中断（已抓完的不受影响，重新点「开始抓取」自动续）</span>
</div>
<div class="toast" id="toast"></div>

<script>
const LSKEY = 'xhs_picker_sel';
const state = new Set();          // 全局勾选（主页+搜索可混选）
const DATA = {main:null, search:null};
const DONE = new Map();           // note_id -> manifest 记录
let cur = 'main';
let polling = false;

try{ JSON.parse(localStorage.getItem(LSKEY)||'[]').forEach(id=>state.add(id)); }catch(e){}

const $ = id => document.getElementById(id);
const grid = $('grid');
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function notes(){ const d = DATA[cur]; return (d && d.notes) || []; }
function toast(msg, bg){
  const t = $('toast'); t.textContent = msg; t.style.background = bg || 'var(--ok)';
  t.classList.add('show'); setTimeout(()=>t.classList.remove('show'), 2400);
}

/* ---------- 数据加载 ---------- */
async function loadList(src, force){
  if(DATA[src] && !force) return DATA[src];
  try{
    const r = await fetch('/api/list?src=' + src);
    const j = await r.json();
    DATA[src] = j.ok ? j : {ok:false, error:j.error, notes:[]};
  }catch(e){ DATA[src] = {ok:false, error:String(e), notes:[]}; }
  return DATA[src];
}
async function loadManifest(){
  try{
    const r = await fetch('/api/manifest');
    const j = await r.json();
    DONE.clear();
    (j.items||[]).forEach(it=>DONE.set(it.note_id, it));
    return j.items || [];
  }catch(e){ return []; }
}

/* ---------- Tab 切换 ---------- */
async function switchTab(t){
  cur = t;
  document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active', b.dataset.tab===t));
  $('toolsList').style.display  = (t==='done' || t==='one') ? 'none' : 'flex';
  $('toolsSearch').style.display= (t==='search') ? 'flex' : 'none';
  $('toolsOne').style.display   = (t==='one') ? 'flex' : 'none';
  $('oneMeta').style.display    = (t==='one') ? 'block' : 'none';
  grid.style.display = (t==='done' || t==='one') ? 'none' : 'grid';
  $('doneWrap').style.display = (t==='done') ? 'block' : 'none';
  $('oneWrap').style.display  = (t==='one') ? 'block' : 'none';
  $('listMeta').style.display = (t==='done' || t==='one') ? 'none' : 'block';
  $('bar').style.display = (t==='one') ? 'none' : 'flex';
  $('logpanel').style.bottom = (t==='one') ? '0' : '57px';
  if(t==='done'){ await loadManifest(); renderDone(); return; }
  if(t==='one'){
    await loadManifest();
    $('oneWrap').innerHTML = `<div class="empty">把小红书笔记链接粘贴到上面框里，点「解 析」<br>
      支持 <code>xhslink.cn</code> 短链、<code>xiaohongshu.com</code> 完整链接，或整段分享文字<br>
      解析成功后会显示笔记信息，点「抓取这篇」即可（抓完自动进「已抓笔记」）<br>
      <span class="meta">之后导出 Obsidian：<code>python xhs_export_md.py --dest &lt;你的库目录&gt;</code></span></div>`;
    return;
  }
  $('grid').innerHTML = '<div class="empty">加载中…</div>';
  const d = await loadList(t);
  $('who').textContent = (DATA.main && DATA.main.ok) ? (DATA.main.nickname||'') : '';
  if(!d.ok){
    $('listMeta').textContent = '';
    grid.innerHTML = '<div class="empty">' + (t==='search'
      ? '还没有搜索结果<br>在上方输入关键词点「搜 索」，结果会出现在这里'
      : '找不到笔记清单 notes.json<br>先运行 <code>python xhs_creator_fetch.py 博主主页链接</code>') + '</div>';
    updCnt(); return;
  }
  if(!d.count && t==='search'){
    $('listMeta').textContent = '';
    grid.innerHTML = '<div class="empty">上次搜索结果为空<br>在上方输入关键词重新搜一次</div>';
    updCnt(); return;
  }
  $('listMeta').textContent = `共 ${d.count} 条笔记 · 抓取时间 ${d.fetched_at||''} · 数据每次进页面自动刷新`;
  render();
}

/* ---------- 卡片渲染 ---------- */
function render(){
  const q = $('q').value.trim().toLowerCase();
  grid.innerHTML = '';
  let shown = 0;
  notes().forEach(n=>{
    const hay = (n.title||'').toLowerCase();
    if(q && !hay.includes(q)) return;
    shown++;
    const d = document.createElement('div');
    d.className = 'card' + (state.has(n.note_id) ? ' on' : '');
    d.dataset.id = n.note_id;
    const isVideo = n.type === 'video';
    const cover = n.cover
      ? `<img loading="lazy" src="/img?u=${encodeURIComponent(n.cover)}" alt="">`
      : `<div class="ph">无封面</div>`;
    const link = n.url || ('https://www.xiaohongshu.com/explore/' + n.note_id);
    d.innerHTML = `${cover}
      <div class="tag">${isVideo ? '视频' : '图文'}</div>
      ${n.sticky ? '<div class="tag tag-top">置顶</div>' : ''}
      ${DONE.has(n.note_id) ? '<div class="tag tag-done">已抓过</div>' : ''}
      <div class="cb">${state.has(n.note_id) ? '✓' : ''}</div>
      <div class="body">
        <a class="t" href="/detail?url=${encodeURIComponent(link)}" title="点开查看笔记详情（返回按 Esc 或左上角「返回列表」，勾选已自动保存）" onclick="event.stopPropagation()">${esc(n.title) || '<span style="color:var(--sub)">(无标题)</span>'}</a>
        <div class="s">${n.date || ''}　♥ ${n.liked || 0}　<a href="/detail?url=${encodeURIComponent(link)}" onclick="event.stopPropagation()">原文↗</a></div>
      </div>`;
    d.onclick = ()=>{
      if(state.has(n.note_id)) state.delete(n.note_id); else state.add(n.note_id);
      d.classList.toggle('on');
      d.querySelector('.cb').textContent = state.has(n.note_id) ? '✓' : '';
      updCnt(); persist();
    };
    grid.appendChild(d);
  });
  if(!shown) grid.innerHTML = '<div class="empty">没有匹配的笔记</div>';
  updCnt();
}

/* ---------- 勾选 ---------- */
let saveTimer = null;
function persist(){
  try{ localStorage.setItem(LSKEY, JSON.stringify([...state])); }catch(e){}
  clearTimeout(saveTimer);
  saveTimer = setTimeout(()=>autoSave(), 400);
}
async function autoSave(){
  if(!state.size){ $('barTip').textContent = '选好后点「开始抓取」，我会按清单去抓正文和图片'; return; }
  try{
    const r = await fetch('/save', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ids:[...state]})});
    const j = await r.json();
    if(j.ok){
      const t = new Date().toLocaleTimeString('zh-CN',{hour12:false});
      $('barTip').textContent = `✓ 已自动保存 ${j.count} 篇（${t}）`;
    }
  }catch(e){}
}
function visibleNotes(){
  const q = $('q').value.trim().toLowerCase();
  return notes().filter(n => !q || (n.title||'').toLowerCase().includes(q));
}
function pick(mode){
  const vis = visibleNotes();
  if(mode==='all') vis.forEach(n=>state.add(n.note_id));
  if(mode==='none') state.clear();
  if(mode==='invert') vis.forEach(n=> state.has(n.note_id)?state.delete(n.note_id):state.add(n.note_id));
  if(mode==='video') vis.filter(n=>n.type==='video').forEach(n=>state.add(n.note_id));
  if(mode==='normal') vis.filter(n=>n.type!=='video').forEach(n=>state.add(n.note_id));
  if(mode==='undone'){
    const un = vis.filter(n=>!DONE.has(n.note_id));
    un.forEach(n=>state.add(n.note_id));
    toast(un.length ? `已勾选 ${un.length} 篇未抓的` : '这一页全抓过了', 'var(--teal)');
  }
  render(); persist();
}
function updCnt(){ $('cnt').textContent = `已选 ${state.size} 篇`; }

/* ---------- 已抓笔记 tab ---------- */
function renderDone(){
  const items = [...DONE.values()].sort((a,b)=>a.seq-b.seq);
  const okN = items.filter(x=>x.ok).length;
  let html = `<table class="done"><tr><th>状态</th><th>#</th><th>标题</th><th>类型</th><th>日期</th><th>博主评论</th><th>操作</th></tr>`;
  if(!items.length){
    $('doneWrap').innerHTML = '<div class="empty">还没有抓取记录<br>回「博主主页」勾几篇，点左下角「开始抓取」试试</div>';
    return;
  }
  items.forEach(it=>{
    html += `<tr>
      <td>${it.ok ? '<span class="okb">✓ 完成</span>' : '<span class="nob">未完成</span>'}</td>
      <td>${it.seq}</td>
      <td class="t">${esc(it.title) || '(无标题)'}</td>
      <td>${it.type==='video' ? '视频' : '图文'}</td>
      <td>${it.date || ''}</td>
      <td>${it.comments ? it.comments + ' 条' : '—'}</td>
      <td>${it.folder ? `<button onclick="openFolder('${it.note_id}')">打开文件夹</button>` : ''}
          ${it.url ? `<a href="/detail?url=${encodeURIComponent(it.url)}" style="color:var(--brand);margin-left:6px">原文↗</a>` : ''}</td>
    </tr>`;
  });
  html += `</table><div class="meta" style="margin:-130px 22px 0">共 ${items.length} 篇 · 完成 ${okN} 篇 · 未完成 ${items.length-okN} 篇（未完成多是中断的，重跑「开始抓取」会自动续）</div>`;
  $('doneWrap').innerHTML = html;
}
async function openFolder(nid){
  try{
    const r = await fetch('/open?note_id=' + nid);
    const j = await r.json();
    if(!j.ok) toast(j.error || '打开失败', '#e64545');
  }catch(e){ toast('打开失败: ' + e, '#e64545'); }
}

/* ---------- 后台任务（搜索 / 抓取） ---------- */
async function jobStart(payload){
  try{
    const r = await fetch('/job/start', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload)});
    const j = await r.json();
    if(!j.ok){ toast(j.error || '启动失败', '#e64545'); return false; }
    $('logpanel').style.display = 'flex';
    $('log').textContent = '';
    $('logStatus').textContent = payload.type==='fetch' ? '抓取运行中…'
      : payload.type==='one' ? '单篇抓取运行中…' : '搜索运行中…';
    if(payload.type==='fetch' || payload.type==='one'){
      $('barTip').innerHTML = '<b style="color:#B45309">抓取进行中：会弹出一个专用 Chrome 窗口自动操作，请勿关闭它或按 Esc 关页，避免中断。</b>已抓完的笔记自动跳过；若不小心关了，重新点「开始抓取」会从断点续抓。';
    }
    $('btnFetch').disabled = true; $('btnSearch').disabled = true;
    $('btnResolve').disabled = true; $('btnFetchOne').disabled = true;
    try{
      const r2 = await (await fetch('/api/job')).json();
      if(r2.job_id) sessionStorage.setItem('xhs_current_job', r2.job_id);
    }catch(e){}
    pollJob();
    return true;
  }catch(e){ toast('启动失败: ' + e, '#e64545'); return false; }
}
function startFetch(){
  if(!state.size){ toast('先勾选要抓的笔记', '#e64545'); return; }
  jobStart({type:'fetch', with_comments: $('withComments').checked});
}
function startSearch(){
  const kw = $('kw').value.trim();
  if(!kw){ toast('先输入关键词', '#e64545'); return; }
  jobStart({type:'search', keyword:kw});
}

/* ---------- 单篇导入 ---------- */
let oneResolved = null;   // {note_id, type, url}
async function resolveOne(){
  const txt = $('oneUrl').value.trim();
  if(!txt){ toast('先粘贴笔记链接', '#e64545'); return; }
  $('btnResolve').disabled = true;
  try{
    const r = await fetch('/api/resolve', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({text:txt})});
    const j = await r.json();
    if(!j.ok){
      oneResolved = null;
      $('btnFetchOne').disabled = true;
      $('oneMeta').innerHTML = '<span style="color:var(--brand)">解析失败：' + esc(j.error||'') + '</span>';
      return;
    }
    oneResolved = j;
    const done = DONE.has(j.note_id);
    $('oneMeta').innerHTML = '解析成功 · note_id <code>' + j.note_id + '</code> · '
      + (j.type==='video' ? '视频' : '图文')
      + (done ? ' · <b style="color:var(--teal)">已抓过（重抓会覆盖原目录）</b>' : ' · 尚未抓过');
    $('btnFetchOne').disabled = false;
    $('btnFetchOne').textContent = done ? '重新抓取' : '抓取这篇';
  }catch(e){
    oneResolved = null;
    $('btnFetchOne').disabled = true;
    $('oneMeta').innerHTML = '<span style="color:var(--brand)">解析失败：' + esc(String(e)) + '</span>';
  }
  $('btnResolve').disabled = false;
}
function fetchOne(){
  if(!oneResolved){ toast('先点「解 析」认出这篇笔记', '#e64545'); return; }
  jobStart({type:'one', url: oneResolved.url, with_comments: $('withComments').checked});
}
$('oneUrl').addEventListener('keydown', e=>{ if(e.key==='Enter') resolveOne(); });
function stopJob(){
  fetch('/job/stop', {method:'POST'});
  const b = document.querySelector('.lh button');
  if(b){ b.textContent = '⏳ 停止请求已接收（正在停止，已完成内容会保留）'; b.disabled = true; }
}
function toggleLog(){ $('logpanel').style.display = 'none'; }

function pollJob(){
  if(polling) return; polling = true;
  const timer = setInterval(async ()=>{
    let j;
    try{ j = await (await fetch('/api/job')).json(); }catch(e){ return; }
    const pre = $('log');
    pre.textContent = (j.lines||[]).join('\n');
    pre.scrollTop = pre.scrollHeight;
    // 完成竞态（2026-10-20 复验）：子进程退出后 finalize 可能尚未写完
    // 最终 status——running=false 但 status 仍是 running 时继续轮询，
    // 直到后端写入权威状态，再以持久结果卡作为完成反馈
    if(j.running || j.status === 'running'){
      $('logStatus').textContent = (j.type==='fetch' ? '抓取'
        : j.type==='one' ? '单篇抓取' : '搜索') + '运行中…';
      // 结构化进度（2026-10-21 P0-A）：进度条/统计/当前篇，日志降为辅助
      const st = j.stats || {};
      if(st.total){
        const processed = st.processed ?? 0;
        $('progWrap').style.display = 'block';
        $('progBar').style.width = Math.round(processed / st.total * 100) + '%';
        $('progText').textContent = `已处理 ${processed} / ${st.total}`;
        $('progOk').textContent = `成功 ${st.ok ?? 0}`;
        $('progFail').textContent = `失败 ${st.failed ?? 0}`;
        $('progSkip').textContent = `跳过 ${st.skipped ?? 0}`;
        $('progCurrent').textContent = st.current_note_title
          ? `正在处理：${st.current_note_title}` : '正在汇总…';
      }
      return;
    }
    clearInterval(timer); polling = false;
    $('btnFetch').disabled = false; $('btnSearch').disabled = false;
    $('btnResolve').disabled = false;
    $('btnFetchOne').disabled = !oneResolved;
    $('barTip').textContent = '点卡片=勾选；点标题或「原文↗」在本窗口看详情，勾选不会丢。⚠ 抓取进行中请勿关闭弹出的专用 Chrome 窗口，否则本轮中断（已抓完的不受影响，重跑自动续）';
    $('logStatus').textContent = j.status==='done' ? '✓ 任务完成'
      : j.status==='partial' ? '⚠ 部分完成（详见下方结果卡）' : '任务失败（详见下方结果卡）';
    await loadManifest();
    if(j.type==='search'){ await loadList('search', true); if(cur==='search') render(); }
    if(cur==='done') renderDone(); else if(cur!=='done' && cur!=='one') render();
    if(j.type==='fetch' && j.status==='done'){
      toast('抓取完成！卡片已打上「已抓过」标记', 'var(--teal)');
      if(cur!=='done') switchTab('done');
    } else if(j.type==='one' && j.status==='done'){
      toast('抓取完成！已加入「已抓笔记」', 'var(--teal)');
      if(cur!=='done') switchTab('done');
    } else if(j.status==='done'){
      toast('完成');
    } else {
      toast('任务结束：' + j.status + '——结果与下一步见下方结果卡', '#B45309');
    }
    // 完成反馈以持久结果卡为准（P0），不再只靠一次性 Toast
    await loadJobCard();
  }, 1200);
}

/* ---------- 保存 / 复制 ---------- */
async function save(){
  if(!state.size){ toast('还没有选任何笔记', '#e64545'); return; }
  try{
    const r = await fetch('/save', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ids:[...state]})});
    const j = await r.json();
    if(j.ok) toast(`已保存 ${j.count} 篇 → selection.json`);
    else toast('保存失败: ' + (j.error||''), '#e64545');
  }catch(e){ toast('保存失败: ' + e, '#e64545'); }
}
function copySel(){
  const all = [...(DATA.main?.notes||[]), ...(DATA.search?.notes||[])];
  const txt = [...state].map(id=>{
    const n = all.find(x=>x.note_id===id);
    return n ? `${n.title}\t${n.url}` : id;
  }).join('\n');
  navigator.clipboard.writeText(txt).then(()=>toast('已复制到剪贴板'));
}

$('q').addEventListener('input', render);
$('kw').addEventListener('keydown', e=>{ if(e.key==='Enter') startSearch(); });

/* ---------- 持久任务结果卡（2026-10-20 P0） ---------- */
const TIP_DEFAULT = '点卡片=勾选；点标题或「原文↗」在本窗口看详情，勾选不会丢。⚠ 抓取进行中请勿关闭弹出的专用 Chrome 窗口，否则本轮中断（已抓完的不受影响，重跑自动续）';
async function loadJobCard(){
  let j;
  try{ j = await (await fetch('/api/jobs')).json(); }catch(e){ return; }
  const card = $('jobCard');
  // 2026-10-21 雅旭/Codex 定稿：结果卡只属于「发起它的页面」——
  // sessionStorage 记录本页发起的 job_id：本页刷新仍可见（持久结果卡），
  // 新开标签页/其他窗口绝不串出历史卡；确认「知道了」后清除
  const myJob = sessionStorage.getItem('xhs_current_job');
  if(!myJob){ card.style.display='none'; card.innerHTML=''; return; }
  const latest = (j.jobs||[]).find(x => x.job_id === myJob);
  if(!latest){ card.style.display='none'; card.innerHTML=''; return; }
  const st = latest.stats || {};
  const okN = st.ok ?? 0, fN = st.failed ?? 0, skN = st.skipped ?? 0;
  const act = latest.actions || {};
  let head = '', btns = '';
    if(latest.status === 'done'){
    head = `<b style="color:var(--teal)">✓ 上次抓取完成：成功 ${okN} 篇` + (skN?` · 跳过 ${skN} 篇`:'') + '</b>';
    if(act.view_notes) btns = `<button class="teal" onclick="switchTab('done')">查看已抓笔记</button>`;
    if(act.continue_flow) btns += ` <button onclick="continueFlow('${latest.job_id}')">复制「生成 Markdown」请求</button>`;
  }else if(latest.status === 'stopped'){
    head = `<b style="color:var(--amber)">⏹ 上次抓取已停止（用户请求）：已完成 ${okN} / ${st.total ?? okN} 篇` + (skN?` · 跳过 ${skN}`:'') + '</b>';
    if(act.open_location) btns = `<button class="ghost" onclick="openDownloads()">打开保存位置</button>`;
    if(act.view_notes) btns += ` <button class="teal" onclick="switchTab('done')">查看已抓笔记</button>`;
    if(act.resume) btns += ` <button class="primary" onclick="startFetch()">继续抓取剩余（自动续，不重抓已完成）</button>`;
  }else if(latest.status === 'partial'){
    head = `<b style="color:#B45309">⚠ 上次抓取部分完成：成功 ${okN} · 失败 ${fN}` + (skN?` · 跳过 ${skN}`:'') + '</b>';
  }else{
    head = `<b style="color:#e64545">✗ 上次抓取失败</b>` + (latest.stats ? `（成功 ${okN} · 失败 ${fN}）` : '（进程异常终止，无统计；已抓完的自动跳过）');
  }
  // 按钮按后端下发的 actions 渲染：失败有明细→重试+原因；崩溃无统计→查看日志
  if(act.log) btns += ` <button onclick="viewJobLog('${latest.job_id}')">查看运行日志</button>`;
  if(act.failures) btns += ` <button onclick="toggleFailures()">查看失败原因</button>`;
  if(act.retry) btns += ` <button class="teal" onclick="retryFailed('${latest.job_id}')">仅重试失败项</button>`;
  btns += ` <button onclick="confirmJob('${latest.job_id}')">知道了</button>`;
  const fails = act.failures ? (st.failures||[]).map(f=>`<li>「${(f.title||f.note_id||'').slice(0,36)}」：${(f.error||'').slice(0,80)}</li>`).join('') : '';
  const nextStep = latest.status === 'done'
    ? '📁 素材已保存至工作台目录的 downloads/（原始素材包，Markdown 尚未生成）。如需生成 Markdown，请回到当前 Agent 对话发送「生成 Markdown」。'
    : latest.status === 'stopped'
    ? '📁 已完成内容已保存至工作台目录的 downloads/。可点「继续抓取剩余」自动续，或回 Agent 对话查询。'
    : '📁 部分素材已保存至工作台目录的 downloads/。失败原因与下一步可回 Agent 对话查询。';
  card.innerHTML = `<div style="border:1px solid var(--border);border-radius:10px;padding:10px 14px;margin:10px 16px;background:var(--bg2,#F7F8FA)">
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">${head}
      <span style="font-size:11px;color:#888">${latest.started_at||''} · ${latest.type}${latest.with_comments===false?' · 不抓评论':''}</span>
      <span style="flex:1"></span>${btns}
    </div>
    <div class="meta" style="margin-top:6px">${nextStep}</div>
  </div>`;
  card.style.display = 'block';
}
function openDownloads(){
  fetch('/open-downloads');
}
async function viewJobLog(jid){
  try{
    const j = await (await fetch('/api/jobs/' + jid + '/log')).json();
    $('logpanel').style.display = 'flex';
    $('log').textContent = j.ok ? (j.log || '(空)') : (j.error || '(无日志)');
    $('log').scrollTop = 0;
    $('logStatus').textContent = '上次任务运行日志';
  }catch(e){ toast('读取日志失败: ' + e, '#e64545'); }
}
async function continueFlow(jid){
  const guide = '生成 Markdown';
  let copied = false;
  try{ await navigator.clipboard.writeText(guide); copied = true; }catch(e){}
  toast(copied ? '已复制「生成 Markdown」——粘贴到当前 Agent 对话发送'
               : '请回到当前 Agent 对话手动发送「生成 Markdown」', 'var(--teal)');
}
async function confirmJob(jid){
  try{ await fetch('/api/jobs/' + jid + '/confirm', {method:'POST'}); }catch(e){}
  if(sessionStorage.getItem('xhs_current_job') === jid){
    sessionStorage.removeItem('xhs_current_job');
  }
  await loadJobCard();
}
async function retryFailed(jid){
  try{
    const r = await fetch('/api/retry_failed', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({job_id: jid})});
    const j = await r.json();
    if(!j.ok){ toast(j.error || '重试启动失败', '#e64545'); return; }
    if(j.job_id) sessionStorage.setItem('xhs_current_job', j.job_id);
    $('jobCard').style.display = 'none';
    $('logpanel').style.display = 'flex';
    $('log').textContent = '';
    $('logStatus').textContent = '失败项重试运行中…';
    if(payloadTypeWarn) payloadTypeWarn();
    $('btnFetch').disabled = true; $('btnSearch').disabled = true;
    $('btnResolve').disabled = true; $('btnFetchOne').disabled = true;
    pollJob();
  }catch(e){ toast('重试启动失败: ' + e, '#e64545'); }
}
function payloadTypeWarn(){
  $('barTip').innerHTML = '<b style="color:#B45309">抓取进行中：会弹出一个专用 Chrome 窗口自动操作，请勿关闭它或按 Esc 关页，避免中断。</b>已抓完的笔记自动跳过；若不小心关了，重新点「开始抓取」会从断点续抓。';
}

(async function init(){
  await loadManifest();
  loadJobCard();
  await switchTab('main');
  persist();
  try{
    const j = await (await fetch('/api/job')).json();
    if(j.running){
      $('logpanel').style.display = 'flex';
      $('btnFetch').disabled = true; $('btnSearch').disabled = true;
      $('btnResolve').disabled = true; $('btnFetchOne').disabled = true;
      pollJob();
    }
  }catch(e){}
})();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        self._send(200, json.dumps(obj, ensure_ascii=False),
                   "application/json; charset=utf-8")

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)

        if u.path == "/img":
            src = qs.get("u", [""])[0]
            if not src.startswith("http"):
                self._send(404, b"bad", "text/plain")
                return
            try:
                req = urllib.request.Request(src, headers={
                    "User-Agent": UA,
                    "Referer": "https://www.xiaohongshu.com/",
                    "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
                })
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
                    ct = r.headers.get("Content-Type", "image/jpeg")
                self._send(200, data, ct)
            except Exception as e:
                self._send(502, f"img fail: {e}".encode(), "text/plain")
            return

        if u.path == "/open-downloads":
            dpath = os.path.join(BASE, "downloads")
            os.makedirs(dpath, exist_ok=True)
            try:
                os.startfile(dpath)   # Windows 资源管理器
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})
            return

        if u.path == "/api/jobs":
            jobs = load_jobs()[:20]     # load_jobs 已倒序：取最新的 20 条
            for j in jobs:
                j["actions"] = compute_card_actions(j)
            self._json({"ok": True, "jobs": jobs,
                        "running": (JOB.get("record") or {}).get("job_id", "")
                        if JOB.get("status") == "running" else ""})
            return

        if u.path.startswith("/api/jobs/") and u.path.endswith("/log"):
            jid = u.path[len("/api/jobs/"):-len("/log")]
            lp = os.path.join(jobs_dir(), jid + ".log")
            if os.path.exists(lp):
                with open(lp, encoding="utf-8", errors="replace") as f:
                    self._json({"ok": True, "log": f.read()[-20000:]})
            else:
                self._json({"ok": False, "error": "无该任务日志"})
            return

        if u.path == "/api/list":
            src = qs.get("src", ["main"])[0]
            path = SEARCH_NOTES if src == "search" else MAIN_NOTES
            d = load_json(path)
            if d is None:
                msg = ("search_notes.json 还没生成 —— 在本页输入关键词点「搜 索」即可"
                       if src == "search" else f"找不到 {path}，先运行 xhs_creator_fetch.py")
                self._json({"ok": False, "error": msg, "notes": []})
                return
            self._json({"ok": True, "src": src,
                        "nickname": d.get("nickname") or "",
                        "count": d.get("count", len(d.get("notes") or [])),
                        "fetched_at": d.get("fetched_at", ""),
                        "notes": d.get("notes") or []})
            return

        if u.path == "/api/manifest":
            self._json({"ok": True, "items": manifest_items()})
            return

        if u.path == "/api/job":
            self._json(job_state())
            return

        if u.path == "/open":
            nid = qs.get("note_id", [""])[0]
            rec = next((x for x in manifest_items() if x["note_id"] == nid), None)
            if not rec or not rec["folder"]:
                self._json({"ok": False, "error": "找不到对应的本地文件夹"})
                return
            p = os.path.join(DOWNLOADS, rec["folder"])
            if not os.path.isdir(p):
                self._json({"ok": False, "error": "文件夹不存在（可能已被移动）"})
                return
            try:
                os.startfile(p)  # Windows 资源管理器
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})
            return

        if u.path == "/detail":
            src = qs.get("url", [""])[0]
            host = urllib.parse.urlparse(src).netloc
            if host not in ("www.xiaohongshu.com", "xiaohongshu.com"):
                self._send(400, "bad url", "text/plain")
                return
            safe_src = src.replace('"', "%22")
            self._send(200, DETAIL_PAGE.replace("__URL__", safe_src))
            return

        self._send(200, PAGE)
        return

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            payload = {}

        if self.path == "/save":
            try:
                ids = payload.get("ids") or []
                main = load_json(MAIN_NOTES) or {}
                pool = {x["note_id"]: x for x in (main.get("notes") or [])
                        if x.get("note_id")}
                meta = {"user_id": main.get("user_id"),
                        "nickname": main.get("nickname"),
                        "profile_url": main.get("profile_url")}
                srch = load_json(SEARCH_NOTES) or {}
                for x in (srch.get("notes") or []):
                    if x.get("note_id") and x["note_id"] not in pool:
                        pool[x["note_id"]] = x
                if not meta.get("nickname") and srch.get("nickname"):
                    meta["nickname"] = srch.get("nickname")
                chosen = [pool[i] for i in ids if i in pool]
                out = {**meta, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "count": len(chosen), "notes": chosen}
                with open(SEL, "w", encoding="utf-8") as f:
                    json.dump(out, f, ensure_ascii=False, indent=2)
                self._json({"ok": True, "count": len(chosen)})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})
            return

        if self.path.startswith("/api/jobs/") and self.path.endswith("/confirm"):
            jid = self.path[len("/api/jobs/"):-len("/confirm")]
            self._json({"ok": confirm_job(jid)})
            return

        if self.path == "/api/retry_failed":
            jid = (payload.get("job_id") or "").strip()
            rec = next((r for r in load_jobs() if r.get("job_id") == jid), None)
            if not rec:
                self._json({"ok": False, "error": "找不到该任务记录"})
                return
            failed = extract_failed_ids(rec)
            if not failed:
                self._json({"ok": False, "error": "该任务没有可重试的失败条目"})
                return
            ok, msg, njid = start_job("fetch", with_comments=rec.get("with_comments", True),
                                      only_ids=failed)
            self._json({"ok": ok, "error": None if ok else msg, "job_id": njid})
            return

        if self.path == "/job/start":
            ok, msg, jid = start_job(payload.get("type", ""),
                                     payload.get("keyword", ""),
                                     payload.get("url", ""),
                                     bool(payload.get("with_comments", True)),
                                     payload.get("only_ids") or None)
            self._json({"ok": ok, "error": None if ok else msg, "job_id": jid})
            return

        if self.path == "/api/resolve":
            text = (payload.get("text") or "").strip()
            if not resolve_note_link:
                self._json({"ok": False, "error": "链接解析模块加载失败（xhs_fetch_selected.py 不在目录？）"})
                return
            try:
                nid, _tok, canon, ntype = resolve_note_link(text)
                self._json({"ok": True, "note_id": nid, "type": ntype,
                            "url": canon})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})
            return

        if self.path == "/job/stop":
            # 2026-10-21 P0-A：正常停止改协作式（p.terminate() 仅 /job/kill 兜底）
            ok, mode = request_cooperative_stop()
            self._json({"ok": ok, "mode": mode,
                        "error": None if ok else mode})
            return

        if self.path == "/job/kill":
            with JOB_LOCK:
                p = JOB.get("proc")
                if p and p.poll() is None:
                    p.terminate()
                    self._json({"ok": True, "mode": "kill"})
                else:
                    self._json({"ok": False, "error": "没有运行中的进程"})
            return

        if self.path == "/job/stop_legacy":
            with JOB_LOCK:
                p = JOB.get("proc")
                if p and p.poll() is None:
                    try:
                        p.terminate()
                        JOB["lines"].append("[!] 已手动停止")
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                        return
                    self._json({"ok": True})
                else:
                    self._json({"ok": False, "error": "没有正在运行的任务"})
            return

        self._send(404, b"no", "text/plain")


def main():
    global MAIN_NOTES
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--notes", default=MAIN_NOTES,
                    help="博主主页清单 JSON（默认 notes.json）")
    args = ap.parse_args()
    MAIN_NOTES = args.notes if os.path.isabs(args.notes) else os.path.join(BASE, args.notes)

    print(f"[√] 采集工作台已启动: http://127.0.0.1:{args.port}")
    print("    四个入口: 博主主页 / 关键词搜索 / 单篇导入 / 已抓笔记（同页切换）")
    d = load_json(MAIN_NOTES)
    if d:
        print(f"    博主主页: {d.get('nickname')} | {d.get('count')} 条 | {MAIN_NOTES}")
    else:
        print(f"    [!] 暂无主页清单（{MAIN_NOTES}），可先在页内用关键词搜索")
    if load_json(SEARCH_NOTES):
        print(f"    关键词搜索: {SEARCH_NOTES}")
    else:
        print("    关键词搜索: 暂无结果，可在页内直接搜")
    print(f"    已抓记录: {len(manifest_items())} 篇（downloads/_manifest.json）")
    print("    Ctrl+C 停止")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    srv.serve_forever()


if __name__ == "__main__":
    main()

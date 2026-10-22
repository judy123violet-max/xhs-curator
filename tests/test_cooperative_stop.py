# -*- coding: utf-8 -*-
"""协作式停止的进程级验收测试（2026-10-21 P0-A，Codex 验收 4）。

场景：5 篇 fake 任务在 2/5 时请求停止 →
- 终态 stopped（不是 failed）
- 已完成 2 篇保留、后 3 篇未启动
- 刷新页面/重启服务后统计一致（从磁盘重读）
"""
import json
import os
import sys
import tempfile
import time
import unittest
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import xhs_picker_server as srv     # noqa: E402

# fake 批量脚本：遵守 XHS_JOB_CONTROL/XHS_JOB_STATS 契约（与真实脚本一致）
FAKE_BATCH = '''
import json, os, sys, time
sp = os.environ["XHS_JOB_STATS"]; cp = os.environ["XHS_JOB_CONTROL"]
def ctrl():
    try:
        with open(cp, encoding="utf-8") as f:
            return json.load(f).get("stop_requested")
    except Exception: return False
def write(stats):
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False)
manifest = []
for i in range(1, 6):
    if ctrl():
        with open(sp, encoding="utf-8") as f:
            s = json.load(f)
        s["user_stopped"] = True; s["stage"] = "stopped"
        write(s); sys.exit(0)
    time.sleep(0.15)
    manifest.append({"note_id": "n%d" % i, "ok": True, "list_title": "N%d" % i})
    ok = len(manifest)
    write({"stage": "fetching", "total": 5, "processed": ok, "ok": ok,
           "failed": 0, "skipped": 0, "current_note_title": "",
           "failures": []})
    if i == 2:
        # 停在 2/5 的确定性门：冻结等测试写入控制文件（模拟用户决策窗口）
        t0 = time.time()
        while time.time() - t0 < 8 and not os.path.exists(cp):
            time.sleep(0.05)
write({"stage": "done", "total": 5, "processed": 5, "ok": 5, "failed": 0,
       "skipped": 0, "user_stopped": False, "failures": []})
'''


class CooperativeStopTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.jobs = os.path.join(self._tmp.name, "jobs")
        srv.JOBS_DIR = self.jobs
        self._orig_fetch = srv.FETCH_SCRIPT
        self._orig_sel = srv.SEL
        # selection.json：5 篇
        self.sel = os.path.join(self._tmp.name, "selection.json")
        with open(self.sel, "w", encoding="utf-8") as f:
            json.dump({"nickname": "t", "notes": [
                {"note_id": f"n{i}", "title": f"N{i}"} for i in range(1, 6)]}, f)
        srv.SEL = self.sel
        # fake 批量脚本
        self.fake = os.path.join(self._tmp.name, "fake_batch.py")
        with open(self.fake, "w", encoding="utf-8") as f:
            f.write(FAKE_BATCH)
        srv.FETCH_SCRIPT = self.fake
        srv.JOB.update({"proc": None, "status": "idle", "exit": None,
                        "record": None, "lines": deque(maxlen=50)})

    def tearDown(self):
        srv.FETCH_SCRIPT = self._orig_fetch
        srv.SEL = self._orig_sel
        proc = srv.JOB.get("proc")
        if proc and proc.poll() is None:
            proc.terminate()
        self._tmp.cleanup()

    def _wait_settled(self, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            rec = srv.JOB.get("record") or {}
            if rec.get("status") not in (None, "running"):
                return rec
            time.sleep(0.05)
        return srv.JOB.get("record") or {}

    def test_stop_at_2_of_5_yields_stopped(self):
        """5 篇任务 2/5 请求停止 → stopped、成功 2、后 3 篇未启动"""
        ok, msg, jid = srv.start_job("fetch", with_comments=True)
        self.assertTrue(ok, msg)
        # 等 2 篇完成（读运行期 stats）
        deadline = time.time() + 10
        stats = {}
        while time.time() < deadline:
            sp = os.path.join(self.jobs, jid + ".stats.json")
            if os.path.exists(sp):
                try:
                    stats = json.load(open(sp, encoding="utf-8"))
                except Exception:
                    stats = {}
                if stats.get("processed", 0) >= 2:
                    break
            time.sleep(0.05)
        self.assertGreaterEqual(stats.get("processed", 0), 2, "fake 未跑到 2 篇")
        # 2/5 请求协作式停止
        ok_stop, mode = srv.request_cooperative_stop()
        self.assertTrue(ok_stop)
        self.assertEqual(mode, "cooperative")
        # 等终态
        rec = self._wait_settled()
        self.assertEqual(rec["status"], "stopped")          # 不是 failed
        self.assertTrue(rec["stats"].get("user_stopped"))
        self.assertEqual(rec["stats"]["ok"], 2)             # 已完成 2 篇保留
        self.assertEqual(rec["exit_code"], 0)               # 协作式退出非崩溃
        # 后 3 篇未启动：stats.total=5，processed=2
        self.assertEqual(rec["stats"]["processed"], 2)
        # 刷新/重启一致：从磁盘重读
        jobs = srv.load_jobs()
        self.assertEqual(jobs[0]["status"], "stopped")
        self.assertEqual(jobs[0]["stats"]["ok"], 2)

    def test_run_to_completion_yields_done(self):
        """不停止 → 正常跑完，终态 done（对照组）"""
        ok, msg, jid = srv.start_job("fetch", with_comments=True)
        self.assertTrue(ok, msg)
        rec = self._wait_settled()
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["stats"]["ok"], 5)
        self.assertFalse(rec["stats"]["user_stopped"])


if __name__ == "__main__":
    unittest.main()

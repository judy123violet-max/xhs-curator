# -*- coding: utf-8 -*-
"""任务收尾的进程级回归测试（2026-10-20 复验，2026-10-21 Codex 复验补充）。

覆盖「进程已退出、统计尚未落盘」的完成竞态与三态判定——
用真实子进程（fake 抓取脚本）而非纯函数模拟。
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import xhs_picker_server as srv     # noqa: E402

FAKE_OK = ("import json, os, sys\n"
           "p = os.environ['XHS_JOB_STATS']\n"
           "json.dump({'total': 1, 'processed': 1, 'ok': 1, 'failed': 0, 'skipped': 0,\n"
           "           'failures': []}, open(p, 'w'))\n")

FAKE_PARTIAL = ("import json, os, sys\n"
                "p = os.environ['XHS_JOB_STATS']\n"
                "json.dump({'total': 2, 'processed': 1, 'ok': 1, 'failed': 1, 'skipped': 0,\n"
                "           'failures': [{'note_id': 'bad', 'title': '坏的一篇',\n"
                "                         'error': 'goto: Timeout'}]}, open(p, 'w'))\n")

FAKE_CRASH = "import sys\nprint('boom')\nsys.exit(3)\n"


class JobFinalizeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.jobs = os.path.join(self._tmp.name, "jobs")
        srv.JOBS_DIR = self.jobs
        self._orig_fetch = srv.FETCH_SCRIPT
        self._orig_sel = srv.SEL
        self.sel = os.path.join(self._tmp.name, "selection.json")
        with open(self.sel, "w", encoding="utf-8") as f:
            json.dump({"nickname": "t", "notes": [
                {"note_id": "a", "title": "A"},
                {"note_id": "bad", "title": "坏的一篇"}]}, f)
        srv.SEL = self.sel
        # 复位共享任务状态，避免用例间串扰
        srv.JOB.update({"proc": None, "status": "idle", "exit": None,
                        "record": None, "lines": __import__("collections").deque(maxlen=50)})

    def tearDown(self):
        srv.FETCH_SCRIPT = self._orig_fetch
        srv.SEL = self._orig_sel
        self._tmp.cleanup()

    def _fake_script(self, body):
        p = os.path.join(self._tmp.name, f"fake_{abs(hash(body)) % 10**8}.py")
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
        srv.FETCH_SCRIPT = p
        return p

    def _wait_settled(self, timeout=8):
        deadline = time.time() + timeout
        while time.time() < deadline:
            rec = srv.JOB.get("record") or {}
            if rec.get("status") not in (None, "running"):
                return rec
            time.sleep(0.1)
        return srv.JOB.get("record") or {}

    def _start(self, **kw):
        ok, msg, jid = srv.start_job("fetch", with_comments=True, **kw)
        self.assertTrue(ok, msg)
        return jid

    def test_partial_stats_yield_partial(self):
        self._start() if False else None
        self._fake_script(FAKE_PARTIAL)
        jid = self._start()
        rec = self._wait_settled()
        self.assertEqual(rec["status"], "partial")
        self.assertEqual(rec["stats"]["failed"], 1)
        self.assertEqual(srv.extract_failed_ids(rec), ["bad"])

    def test_crash_without_stats_is_failed(self):
        """进程已退出、统计尚未落盘（崩溃）→ failed 而非笼统 done"""
        self._fake_script(FAKE_CRASH)
        jid = self._start()
        rec = self._wait_settled()
        self.assertEqual(rec["status"], "failed")
        self.assertIsNone(rec["stats"])
        self.assertFalse(srv.compute_card_actions(rec)["retry"])
        self.assertTrue(srv.compute_card_actions(rec)["log"])   # 提供查看运行日志

    def test_all_ok_stats_yield_done(self):
        self._fake_script(FAKE_OK)
        jid = self._start()
        rec = self._wait_settled()
        self.assertEqual(rec["status"], "done")
        self.assertTrue(srv.compute_card_actions(rec)["view_notes"])
        self.assertFalse(srv.compute_card_actions(rec)["retry"])
        # 日志文件落盘
        self.assertTrue(os.path.exists(os.path.join(self.jobs, rec["job_id"] + ".log")))

    def test_job_state_keeps_running_in_race_window(self):
        """复验 P0（2026-10-21）：进程已退出、finalize 落盘前的窗口内，
        job_state() 不得抢跑改 failed——API 必须继续报告可等待的 running，
        前端才会保持轮询；随后 finalize 落盘为 failed，结果卡才出现。

        窗口态用「真实子进程已退出 + 手工构造快照」确定性复现：
        （status=running / exit=None / 记录=running，与竞态瞬间完全一致）。
        """
        self._fake_script(FAKE_CRASH)
        jid = self._start()
        dead_proc = srv.JOB["proc"]            # 真实子进程引用
        rec = self._wait_settled()             # 等正常终态（failed）
        self.assertEqual(rec["status"], "failed")

        # —— 重放竞态窗口快照 ——
        running_rec = {"job_id": jid, "type": "fetch", "status": "running",
                       "confirmed": False, "stats": None}
        srv.JOB["status"] = "running"
        srv.JOB["exit"] = None
        srv.JOB["record"] = running_rec
        srv.JOB["proc"] = dead_proc            # 已退出的真实进程

        st = srv.job_state()                   # 窗口内轮询 /api/job 的等价调用
        self.assertEqual(st["status"], "running")   # 不被抢跑改 failed
        self.assertFalse(st["running"])             # 进程确实已退出
        # 前端条件 j.running || j.status==='running' 仍成立 → 继续轮询 ✓

        # finalize 落盘后（此处记录已是 failed）→ 结果卡可见
        jobs = srv.load_jobs()
        latest = next(r for r in jobs if r["job_id"] == jid)
        self.assertEqual(latest["status"], "failed")
        self.assertFalse(latest.get("confirmed"))
        # 恢复全局任务状态，避免污染其他用例
        srv.JOB["status"] = rec["status"]
        srv.JOB["exit"] = 3
        srv.JOB["record"] = rec

    def test_missing_script_returns_three_tuple(self):
        """脚本缺失分支必须返回三元组，否则 /job/start 解包 500（复验 P1）"""
        srv.FETCH_SCRIPT = os.path.join(self._tmp.name, "no_such_script.py")
        ok, msg, jid = srv.start_job("fetch", with_comments=True)
        self.assertFalse(ok)
        self.assertIn("找不到", msg)
        self.assertEqual(jid, "")

    def test_card_actions_matrix(self):
        base = {"job_id": "j", "type": "fetch", "status": "done", "stats": None}
        self.assertTrue(srv.compute_card_actions(base)["view_notes"])
        p = dict(base, status="partial",
                 stats={"planned": 2, "ok": 1, "failed": 1,
                        "failures": [{"note_id": "x"}]})
        a = srv.compute_card_actions(p)
        self.assertTrue(a["retry"] and a["failures"] and not a["log"])
        f = dict(base, status="failed", stats=None)
        a = srv.compute_card_actions(f)
        self.assertFalse(a["retry"])       # 无失败明细 → 不显示必然空转的重试
        self.assertTrue(a["log"])          # → 提供查看运行日志


class LatestTwentyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        srv.JOBS_DIR = os.path.join(self._tmp.name, "jobs")
        os.makedirs(srv.JOBS_DIR)

    def tearDown(self):
        self._tmp.cleanup()

    def test_load_jobs_takes_newest_twenty(self):
        """复验 P1：load_jobs 倒序，/api/jobs 应取 [:20]（最新），不是最旧"""
        for i in range(21):
            rec = srv.new_job_record("fetch", selected=1)
            rec["marker"] = i
            # 手动保证文件名唯一且时间可辨（new_job_id 毫秒可能同秒碰撞）
            rec["job_id"] = f"20260101-000000-{i:03d}-fetch"
            srv.save_job(rec)
        jobs = srv.load_jobs()
        newest = jobs[:20]
        self.assertEqual(len(newest), 20)
        self.assertNotIn(0, [j["marker"] for j in newest])   # 最旧的被排除
        self.assertIn(20, [j["marker"] for j in newest])     # 最新的在内


if __name__ == "__main__":
    unittest.main()

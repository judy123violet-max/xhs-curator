# -*- coding: utf-8 -*-
"""工作台持久任务结果的最小回归测试（2026-10-20 P0，不启动服务、不开浏览器）。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import xhs_picker_server as srv     # noqa: E402
import xhs_fetch_selected as fsc    # noqa: E402


class JobStatsPayloadTest(unittest.TestCase):
    def manifest(self, ok_list, fail_list):
        recs = [{"note_id": n, "ok": True} for n in ok_list]
        recs += [{"note_id": n, "ok": False, "list_title": t, "error": e}
                 for n, t, e in fail_list]
        return recs

    def test_counts_and_failures(self):
        m = self.manifest(["a", "b"], [("c", "标题C", "goto: Timeout"), ("d", "", "")])
        s = fsc.job_stats_payload(["a", "b", "c", "d"], m, skipped=3)
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["processed"], 4)
        self.assertEqual(s["ok"], 2)
        self.assertEqual(s["failed"], 2)
        self.assertEqual(s["skipped"], 3)
        self.assertEqual(len(s["failures"]), 2)
        self.assertEqual(s["failures"][0]["error"], "goto: Timeout")
        self.assertEqual(s["failures"][1]["error"], "未取得笔记数据")  # 缺省摘要

    def test_all_ok(self):
        s = fsc.job_stats_payload(["a", "b"], self.manifest(["a", "b"], []), 1)
        self.assertEqual((s["ok"], s["failed"]), (2, 0))
        self.assertEqual(s["failures"], [])


class ComputeJobStatusTest(unittest.TestCase):
    def test_matrix(self):
        self.assertEqual(srv.compute_job_status("search", None, 0), "done")
        self.assertEqual(srv.compute_job_status("search", None, 1), "failed")
        stats = {"planned": 4, "ok": 4, "failed": 0}
        self.assertEqual(srv.compute_job_status("fetch", stats, 0), "done")
        stats["ok"] = 2
        self.assertEqual(srv.compute_job_status("fetch", stats, 0), "partial")
        stats["ok"] = 0
        self.assertEqual(srv.compute_job_status("fetch", stats, 0), "failed")

    def test_crash_without_stats_is_failed(self):
        """子进程异常终止拿不到统计 → failed 而非笼统 done"""
        self.assertEqual(srv.compute_job_status("fetch", None, 1), "failed")
        self.assertEqual(srv.compute_job_status("one", None, -1), "failed")


class JobRecordPersistenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        srv.JOBS_DIR = os.path.join(self._tmp.name, "jobs")

    def tearDown(self):
        self._tmp.cleanup()

    def test_roundtrip_and_order(self):
        r1 = srv.new_job_record("fetch", selected=3, with_comments=True)
        r2 = srv.new_job_record("one", selected=1, with_comments=False)
        srv.save_job(r1)
        srv.save_job(r2)
        jobs = srv.load_jobs()
        self.assertEqual([j["job_id"] for j in jobs], [r2["job_id"], r1["job_id"]])
        self.assertEqual(jobs[0]["status"], "running")

    def test_confirm_persists(self):
        r = srv.new_job_record("fetch", selected=1, with_comments=True)
        srv.save_job(r)
        srv.confirm_job(r["job_id"])
        self.assertTrue(srv.load_jobs()[0]["confirmed"])

    def test_survives_restart(self):
        """数据源是文件而非内存：模拟服务重启（重新读目录）仍可追溯"""
        r = srv.new_job_record("fetch", selected=2, with_comments=True)
        r["status"] = "partial"
        srv.save_job(r)
        jobs = srv.load_jobs()          # 不经过任何内存 JOB 状态
        self.assertEqual(jobs[0]["status"], "partial")


class RetryWiringTest(unittest.TestCase):
    def test_only_ids_appended(self):
        cmd, err = srv.build_cmd("fetch", only_ids=["a", "b"])
        self.assertIsNone(err)
        self.assertIn("--only-ids", cmd)
        self.assertIn("a,b", cmd)

    def test_search_unaffected(self):
        cmd, _ = srv.build_cmd("search", keyword="x", only_ids=["a"])
        self.assertNotIn("--only-ids", cmd)

    def test_no_selection_writes(self):
        """勾选主权：retry 接线只构造命令，不触碰 selection.json"""
        sel = ROOT / "selection.json"
        before = sel.read_bytes() if sel.exists() else None
        srv.build_cmd("fetch", only_ids=["a", "b"])
        if sel.exists():
            self.assertEqual(sel.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

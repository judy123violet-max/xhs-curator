# -*- coding: utf-8 -*-
"""链接分类器与安装流程的回归测试（2026-10-20 P0，不联网）。"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = ROOT / "skill" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))
sys.path.insert(0, str(ROOT))

import fetch_xhs_note as fa         # noqa: E402
import install as installer         # noqa: E402
import xhs_picker_server as srv     # noqa: E402


class ClassifyLinkTest(unittest.TestCase):
    def fake_resolver(self, mapping):
        return lambda u: mapping.get(u, u)

    def test_single_explore(self):
        r = fa.classify_link("https://www.xiaohongshu.com/explore/abc123def456abc789012345?xsec_token=1")
        self.assertEqual(r["link_type"], "single")
        self.assertEqual(r["note_id"], "abc123def456abc789012345")

    def test_single_discovery_item(self):
        r = fa.classify_link("https://www.xiaohongshu.com/discovery/item/0123456789abcdef01234567")
        self.assertEqual(r["link_type"], "single")

    def test_profile_direct(self):
        r = fa.classify_link("https://www.xiaohongshu.com/user/profile/5ff0e6410000000001008400")
        self.assertEqual(r["link_type"], "profile")

    def test_share_text_with_shortlink_resolved_to_profile(self):
        """手机端主页分享文字：短链 resolve 后指向 profile → 硬判定 profile"""
        text = "来我的小红书主页看看：http://xhslink.com/aBcD12 敬请关注"
        r = fa.classify_link(
            text, resolver=self.fake_resolver({
                "http://xhslink.com/aBcD12":
                    "https://www.xiaohongshu.com/user/profile/5ff0e6410000000001008400"}))
        self.assertEqual(r["link_type"], "profile")
        self.assertIn("user/profile", r["resolved_url"])

    def test_share_text_with_shortlink_resolved_to_single(self):
        text = "看这篇 http://xhslink.com/Zz99Yy 面经整理得不错"
        r = fa.classify_link(
            text, resolver=self.fake_resolver({
                "http://xhslink.com/Zz99Yy":
                    "https://www.xiaohongshu.com/explore/abc123def456abc789012345?xsec_token=9"}))
        self.assertEqual(r["link_type"], "single")

    def test_shortlink_resolve_failure_is_unknown_not_invalid(self):
        """短链解析暂不可达 → unknown（诚实态），绝不误报「链接无效」"""
        def broken(u):
            raise RuntimeError("temporarily unreachable")
        r = fa.classify_link("看看这个 http://xhslink.com/aBcD12", resolver=broken)
        self.assertEqual(r["link_type"], "unknown")
        self.assertIn("请稍后重试", r["reason"])

    def test_no_link_invalid(self):
        r = fa.classify_link("这句话里没有链接")
        self.assertEqual(r["link_type"], "invalid")

    def test_shortlink_falling_to_homepage_is_unknown(self):
        """无效短码被平台重定向到首页 → unknown（短码可能已失效），不误报无效"""
        r = fa.classify_link(
            "看我主页 http://xhslink.com/aBcD12", resolver=self.fake_resolver({
                "http://xhslink.com/aBcD12": "http://www.xiaohongshu.com/"}))
        self.assertEqual(r["link_type"], "unknown")
        self.assertIn("短码可能已失效", r["reason"])

    def test_non_xhs_domain_invalid(self):
        r = fa.classify_link("https://github.com/judy123violet-max/xhs-curator")
        self.assertEqual(r["link_type"], "invalid")

    def test_mixed_text_picks_first_xhs_link(self):
        """分享文字常混中文标点；非 xhs 链接跳过，取第一个 xhs 链接"""
        text = ("先看 https://example.com/other 无关链接，"
                "正文：https://www.xiaohongshu.com/explore/abc123def456abc789012345（含说明）。")
        r = fa.classify_link(text)
        self.assertEqual(r["link_type"], "single")


class InstallFlowTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self._tmp.name, "repo")
        self.skills = os.path.join(self._tmp.name, "skills")
        # 构造最小"仓库"骨架
        os.makedirs(os.path.join(self.repo, "skill", "scripts"))
        for s in installer.REQUIRED:
            path = os.path.join(self.repo, s)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("# dummy\n")
        with open(os.path.join(self.repo, "skill", "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: xhs-curator\n---\nbody")

    def tearDown(self):
        self._tmp.cleanup()

    def _install(self, **kw):
        return installer.install(self.repo if "repo_root" not in kw else kw.pop("repo_root"),
                                 self.skills, **kw) if False else installer.install(
            kw.pop("repo_root", self.repo), kw.pop("skill_dir", self.skills), **kw)

    def test_install_copies_skill_and_writes_marker(self):
        self.assertTrue(self._install())
        dest = os.path.join(self.skills, "xhs-curator")
        self.assertTrue(os.path.exists(os.path.join(dest, "SKILL.md")))
        self.assertTrue(os.path.exists(os.path.join(dest, "scripts")))
        marker = os.path.join(dest, installer.MARKER_NAME)
        with open(marker, encoding="utf-8") as f:
            m = json.load(f)                                # JSON: 仓库路径+解释器
        self.assertEqual(m["repo_root"], self.repo)
        self.assertTrue(os.path.exists(m["python"]))        # 记录的解释器真实存在
        root, py = installer.read_marker(dest)
        self.assertEqual((root, py), (self.repo, m["python"]))

    def test_marker_verification_pass_and_fail(self):
        self._install()
        dest = os.path.join(self.skills, "xhs-curator")
        ok, detail = installer.verify_marker(dest)
        self.assertTrue(ok)
        # 仓库被移走（真实改名目录）→ marker 失效，给出可执行修复提示
        moved = os.path.join(self._tmp.name, "moved_away")
        os.rename(self.repo, moved)
        try:
            ok, detail = installer.verify_marker(dest)
            self.assertFalse(ok)
            self.assertIn("install.py", detail)             # 修复提示可执行
        finally:
            os.rename(moved, self.repo)                     # 还原

    def test_incomplete_repo_rejected(self):
        """仓库缺批量脚本 → 拒绝安装并列明缺失（防"缺胳膊少腿的包"）"""
        bad = os.path.join(self._tmp.name, "bad_repo")
        os.makedirs(os.path.join(bad, "skill"))
        with open(os.path.join(bad, "skill", "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("x")
        ok = installer.install(bad, self.skills)
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(os.path.join(self.skills, "xhs-curator")))

    def test_reinstall_idempotent(self):
        self.assertTrue(self._install())
        before = os.listdir(os.path.join(self.skills, "xhs-curator"))
        self.assertTrue(self._install())
        after = os.listdir(os.path.join(self.skills, "xhs-curator"))
        self.assertEqual(sorted(before), sorted(after))

    def test_dead_interpreter_stops_routing(self):
        """复验 P0-4：marker 记录的解释器失效 → 验证失败、路由返回 None，
        绝不静默回退到当前解释器（防「装在 A、跑在 B」重现）"""
        self._install()
        dest = os.path.join(self.skills, "xhs-curator")
        marker = os.path.join(dest, installer.MARKER_NAME)
        with open(marker, encoding="utf-8") as f:
            m = json.load(f)
        dead = os.path.join(self._tmp.name, "gone_python.exe")
        m["python"] = dead
        with open(marker, "w", encoding="utf-8") as f:
            json.dump(m, f)
        # resolve_repo_root → None（路由停止，不回退）
        self.assertIsNone(installer.resolve_repo_root(dest))
        # verify_marker → 失败 + 修复引导
        ok, detail = installer.verify_marker(dest)
        self.assertFalse(ok)
        self.assertIn("重新运行 install.py", detail)
        self.assertIn("--with-deps", detail)

    def test_resolve_repo_root_priority(self):
        self._install()
        dest = os.path.join(self.skills, "xhs-curator")
        # ① 环境变量优先
        os.environ["XHS_CURATOR_HOME"] = self.repo
        try:
            root, _py = installer.resolve_repo_root(dest)
            self.assertEqual(root, self.repo)
        finally:
            del os.environ["XHS_CURATOR_HOME"]
        # ② marker（返回元组：root + 记录的解释器）
        root, py = installer.resolve_repo_root(dest)
        self.assertEqual(root, self.repo)
        self.assertTrue(os.path.exists(py))
        # ④ 全部失败 → None
        empty = os.path.join(self._tmp.name, "empty_skill")
        os.makedirs(empty)
        self.assertIsNone(installer.resolve_repo_root(empty))


class DefaultSkillDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self._tmp.name, "home")
        # 记录原变量是否存在及原值（2026-10-21 复验 P0-3：
        # 原本不存在的变量恢复时不得 os.environ[...] = None，会 TypeError）
        self._orig_env = {k: os.environ[k] for k in ("USERPROFILE", "HOME")
                          if k in os.environ}

    def tearDown(self):
        for k in ("USERPROFILE", "HOME"):
            if k in self._orig_env:
                os.environ[k] = self._orig_env[k]
            else:
                os.environ.pop(k, None)   # 原本不存在 → 恢复为不存在
        self._tmp.cleanup()

    def _set_home(self):
        os.environ["USERPROFILE"] = self.home
        os.environ["HOME"] = self.home

    def test_reliable_autodetect_when_dir_exists(self):
        """已存在的 WorkBuddy 技能目录 → 自动选择（可靠识别）"""
        self._set_home()
        os.makedirs(os.path.join(self.home, ".workbuddy", "skills"))
        self.assertEqual(installer.default_skill_dir(),
                         os.path.join(self.home, ".workbuddy", "skills"))

    def test_unknown_agent_lists_commands_and_returns_none(self):
        """识别不了 → None（绝不猜测），print_agent_dirs 列出各 Agent 命令"""
        self._set_home()
        self.assertIsNone(installer.default_skill_dir())
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            installer.print_agent_dirs()
        out = buf.getvalue()
        self.assertIn("无法自动识别", out)
        for agent in ("WorkBuddy", "Codex", "Claude Code", "Cursor"):
            self.assertIn(agent, out)
            self.assertIn("--skill-dir", out)


class LoadJobsExclusionTest(unittest.TestCase):
    """复验 P0-5：stats.json 不得被误读成任务记录（现场缺陷回归）"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        srv.JOBS_DIR = os.path.join(self._tmp.name, "jobs")
        os.makedirs(srv.JOBS_DIR)

    def tearDown(self):
        self._tmp.cleanup()

    def test_stats_json_and_broken_json_excluded(self):
        rec = srv.new_job_record("fetch", selected=3)
        rec["status"] = "done"
        rec["stats"] = {"planned": 3, "ok": 3, "failed": 0, "skipped": 0,
                        "failures": []}
        rec["confirmed"] = False
        srv.save_job(rec)
        jid = rec["job_id"]
        # 同任务的附属文件：stats.json + 日志
        with open(os.path.join(srv.JOBS_DIR, jid + ".stats.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"planned": 3, "ok": 3, "failed": 0, "skipped": 0}, f)
        with open(os.path.join(srv.JOBS_DIR, jid + ".log"), "w", encoding="utf-8") as f:
            f.write("log")
        # schema 不完整的杂乱 json（无 job_id/status）
        with open(os.path.join(srv.JOBS_DIR, "zz-broken.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"planned": 1, "ok": 1}, f)

        jobs = srv.load_jobs()
        self.assertEqual(len(jobs), 1)                       # 只有主记录一条
        self.assertEqual(jobs[0]["job_id"], jid)
        self.assertEqual(jobs[0]["status"], "done")
        self.assertEqual(jobs[0]["stats"]["ok"], 3)          # 完整记录带统计

    def test_done_record_card_actions(self):
        rec = srv.new_job_record("fetch", selected=1)
        rec["status"] = "done"
        rec["stats"] = {"planned": 1, "ok": 1, "failed": 0, "skipped": 0,
                        "failures": []}
        a = srv.compute_card_actions(rec)
        self.assertTrue(a["view_notes"])
        self.assertTrue(a["continue_flow"])                  # 成功卡给继续整理入口
        self.assertFalse(a["retry"])                         # 成功无重试


if __name__ == "__main__":
    unittest.main()

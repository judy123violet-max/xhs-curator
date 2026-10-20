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
            self.assertEqual(f.read().strip(), self.repo)   # marker = 仓库绝对路径

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

    def test_resolve_repo_root_priority(self):
        self._install()
        dest = os.path.join(self.skills, "xhs-curator")
        # ① 环境变量优先
        os.environ["XHS_CURATOR_HOME"] = self.repo
        try:
            self.assertEqual(installer.resolve_repo_root(dest), self.repo)
        finally:
            del os.environ["XHS_CURATOR_HOME"]
        # ② marker
        self.assertEqual(installer.resolve_repo_root(dest), self.repo)
        # ④ 全部失败 → None
        empty = os.path.join(self._tmp.name, "empty_skill")
        os.makedirs(empty)
        self.assertIsNone(installer.resolve_repo_root(empty))


if __name__ == "__main__":
    unittest.main()

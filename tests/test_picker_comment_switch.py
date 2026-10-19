# -*- coding: utf-8 -*-
"""工作台评论开关接线的最小回归测试（2026-10-19，不启动服务、不开浏览器）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import xhs_picker_server as srv


class BuildCmdTest(unittest.TestCase):
    def test_fetch_default_captures_comments(self):
        """开关默认勾选 → 命令不带 --no-comments（评论全量捕获，现状不变）"""
        cmd, err = srv.build_cmd("fetch")
        self.assertIsNone(err)
        self.assertFalse(any("--no-comments" in c for c in cmd))

    def test_fetch_unchecked_appends_no_comments(self):
        """开关取消勾选 → 追加 --no-comments（承接「不要评论」的回答）"""
        cmd, err = srv.build_cmd("fetch", with_comments=False)
        self.assertIsNone(err)
        self.assertIn("--no-comments", cmd)

    def test_one_url_also_honours_switch(self):
        cmd, err = srv.build_cmd("one", url="https://xhslink.com/abc",
                                 with_comments=False)
        self.assertIsNone(err)
        self.assertIn("--url", cmd)
        self.assertIn("--no-comments", cmd)

    def test_one_missing_url_rejected(self):
        cmd, err = srv.build_cmd("one")
        self.assertIsNone(cmd)
        self.assertIn("链接", err)

    def test_search_unaffected_by_comment_switch(self):
        """搜索任务不含评论环节，开关无论如何都不影响命令"""
        cmd_on, _ = srv.build_cmd("search", keyword="职场")
        cmd_off, _ = srv.build_cmd("search", keyword="职场", with_comments=False)
        self.assertNotIn("--no-comments", cmd_on)
        self.assertNotIn("--no-comments", cmd_off)
        self.assertIn("--keyword", cmd_off)

    def test_unknown_type_rejected(self):
        cmd, err = srv.build_cmd("magic")
        self.assertIsNone(cmd)
        self.assertIn("未知任务类型", err)


if __name__ == "__main__":
    unittest.main()

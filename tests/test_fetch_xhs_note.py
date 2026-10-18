# -*- coding: utf-8 -*-
"""引擎 A 解析回归测试：转义 URL、视频/字幕提取、正文反转义。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill" / "scripts"))

import fetch_xhs_note as mod


HTML = r'''<html><script>window.__INITIAL_STATE__ = {"note":{"data":{"noteData":{
"noteId":"6ad40a23000000001d02df3e","title":"测试视频","desc":"第一行\n\t第二行",
"comment":{"user":{"userId":"c1","nickname":"评论者"}},"ipLocation":"上海","type":"video",
"user":{"avatar":"x","redOfficialVerifyType":0,"userId":"u1","nickName":"笔记作者"},
"imageList":[{"url":"http:\u002F\u002Fimg.example\u002F1.jpg"}]}}}}</script>
<script>"stream":{"h264":[{"masterUrl":"http:\u002F\u002Fsns-video-v6.xhscdn.com\u002Fstream\u002F1\u002Ftest.mp4?sign=1"}]}</script>
<script>https:\u002F\u002Fsns-subtitle-s2.xhscdn.com\u002Fsubtitle\u002F1\u002Ftest_11.srt?sign=1</script>
</html>'''


class ExtractNoteTest(unittest.TestCase):
    def test_escaped_video_and_subtitle_urls_are_extracted(self):
        meta = mod.extract_note(HTML)
        self.assertEqual(meta["title"], "测试视频")
        self.assertEqual(len(meta["video_urls"]), 1)
        self.assertEqual(len(meta["subtitle_urls"]), 1)
        self.assertTrue(meta["video_urls"][0].startswith("https://sns-video"))
        self.assertTrue(meta["subtitle_urls"][0].startswith("https://sns-subtitle"))

    def test_desc_is_unescaped(self):
        meta = mod.extract_note(HTML)
        self.assertIn("\n", meta["desc"])
        self.assertNotIn("\\n", meta["desc"])

    def test_author_prefers_note_user_over_commenter(self):
        meta = mod.extract_note(HTML)
        self.assertEqual(meta["author"], "笔记作者")
        self.assertEqual(meta["author_id"], "u1")

    def test_cjk_ratio(self):
        self.assertGreater(mod._cjk_ratio("你好世界"), 0.9)
        self.assertEqual(mod._cjk_ratio("hello world"), 0.0)


if __name__ == "__main__":
    unittest.main()

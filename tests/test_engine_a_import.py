# -*- coding: utf-8 -*-
"""引擎 A → Markdown 交付 与 to_downloads 入库链路的回归测试（2026-10-19，不访问网络）。

覆盖实施计划验收标准：
- A 原料包转换后可被导出器读取；
- transcript.txt 不丢失；
- A 入库路径不调用抓取函数（全流程断网仍成功）；
- 视频默认不输出封面图。
"""
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = ROOT / "skill" / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SKILL_SCRIPTS))

import fetch_xhs_note as fa          # noqa: E402
import to_downloads as td            # noqa: E402
import xhs_export_md as ex           # noqa: E402

MS = 1760000000000  # 固定时间戳，避免时区干扰

JPG = (b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9")  # 最小 JPEG 字节


def make_a_package(src, video=True, with_transcript=True, with_cover=True):
    """构造引擎 A 原料包 fixture"""
    imgdir = os.path.join(src, "imgs")
    os.makedirs(imgdir, exist_ok=True)
    local_images = []
    if video and with_cover:
        p = os.path.join(imgdir, "note_01.jpg")
        with open(p, "wb") as f:
            f.write(JPG)
        local_images = [p]
    meta = {
        "note_id": "testnote000000000000ab",
        "title": "测试笔记标题",
        "desc": "这是正文内容，足够长。",
        "type": "video" if video else "normal",
        "time_ms": MS,
        "source_url": "https://www.xiaohongshu.com/explore/test",
        "author": "测试作者",
        "stats": {"liked": "42"},
        "ip_location": "上海",
        "local_images": local_images,
        "failed_images": 0,
        "subtitle_urls": [],
    }
    if video and with_transcript:
        with open(os.path.join(src, "transcript.txt"), "w", encoding="utf-8") as f:
            f.write("这是语音转写的内容。")
        meta["transcript_file"] = "transcript.txt"
    with open(os.path.join(src, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


class EngineAMarkdownTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self._tmp.name, "src")
        os.makedirs(self.src)

    def tearDown(self):
        self._tmp.cleanup()

    def _read_md(self, meta):
        path = os.path.join(self.src, fa.safe_stem(meta.get("title")) + ".md")
        self.assertTrue(os.path.exists(path), f"缺少文稿: {path}")
        with open(path, encoding="utf-8") as f:
            return path, f.read()

    def test_video_md_has_transcript_but_no_cover(self):
        meta = make_a_package(self.src, video=True)
        fa.write_markdown(meta, self.src)
        _, txt = self._read_md(meta)
        self.assertIn("语音转写", txt)
        self.assertIn("这是语音转写的内容。", txt)
        self.assertNotIn("imgs/", txt)          # 封面不进交付（拍板 B）
        self.assertIn("本地 Whisper", txt)

    def test_video_without_transcript_annotated_not_failed(self):
        meta = make_a_package(self.src, video=True, with_transcript=False)
        fa.write_markdown(meta, self.src)
        _, txt = self._read_md(meta)
        self.assertIn("未取得字幕/转写", txt)

    def test_image_note_md_references_images(self):
        meta = make_a_package(self.src, video=False, with_cover=False)
        imgdir = os.path.join(self.src, "imgs")
        p = os.path.join(imgdir, "note_01.jpg")
        with open(p, "wb") as f:
            f.write(JPG)
        meta["local_images"] = [p]
        fa.write_markdown(meta, self.src)
        _, txt = self._read_md(meta)
        self.assertIn("](imgs/note_01.jpg)", txt)   # 相对引用
        self.assertIn("这是正文内容", txt)


class ToDownloadsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self._tmp.name, "src")
        self.dl = os.path.join(self._tmp.name, "downloads")
        os.makedirs(self.src)
        make_a_package(self.src, video=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_convert_produces_contract_with_transcript(self):
        self.assertTrue(td.convert(self.src, self.dl))
        folders = [d for d in os.listdir(self.dl) if d != "_manifest.json"]
        self.assertEqual(len(folders), 1)
        folder = os.path.join(self.dl, folders[0])
        with open(os.path.join(folder, "raw.json"), encoding="utf-8") as f:
            rec = json.load(f)
        self.assertTrue(rec["ok"])
        self.assertEqual(rec["via"], "engineA")
        self.assertTrue(os.path.exists(os.path.join(folder, "transcript.txt")),
                        "transcript.txt 不得丢失")
        self.assertEqual(rec["transcript_file"], "transcript.txt")
        self.assertTrue(os.path.exists(os.path.join(folder, "img_01.jpg")))

    def test_convert_is_purely_local(self):
        """A 入库路径不调用抓取函数：断网环境下转换仍成功"""
        real = socket.socket.connect
        socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(
            OSError("测试期间禁止联网"))
        try:
            self.assertTrue(td.convert(self.src, self.dl))
        finally:
            socket.socket.connect = real


class ExportIntegrationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self._tmp.name, "src")
        self.dl = os.path.join(self._tmp.name, "downloads")
        self.dest = os.path.join(self._tmp.name, "vault")
        os.makedirs(self.src)
        make_a_package(self.src, video=True)
        self.assertTrue(td.convert(self.src, self.dl))

    def tearDown(self):
        self._tmp.cleanup()

    def _export(self, extra=()):
        old_argv, old_src = sys.argv[:], ex.SRC
        ex.SRC = self.dl
        sys.argv = ["xhs_export_md.py", "--dest", self.dest, *extra]
        try:
            ex.main()
        finally:
            sys.argv = old_argv
            ex.SRC = old_src

    def test_converted_package_exportable_and_cover_skipped(self):
        self._export()
        mds = [f for f in os.listdir(self.dest) if f.endswith(".md")]
        self.assertTrue(any("测试笔记标题" in f for f in mds), mds)
        with open(os.path.join(self.dest, "测试笔记标题.md"),
                  encoding="utf-8") as f:
            txt = f.read()
        self.assertIn("语音转写", txt)              # 转写进入最终成果
        self.assertNotIn("![[", txt)                # 视频默认不输出封面
        att = os.path.join(self.dest, "attachments")
        self.assertEqual([f for f in os.listdir(att)
                          if f.startswith("测试笔记标题")], [])
        self.assertTrue(os.path.exists(os.path.join(self.dest, "00 索引.md")))

    def test_video_cover_exportable_opt_in(self):
        self._export(extra=["--video-cover"])
        att = os.path.join(self.dest, "attachments")
        self.assertIn("测试笔记标题--img_01.jpg", os.listdir(att))


if __name__ == "__main__":
    unittest.main()

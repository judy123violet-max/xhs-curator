# -*- coding: utf-8 -*-
"""OCR 价值闸门 · 消费端的最小回归测试（2026-10-19，不访问网络）。

覆盖 Codex 审计规则的四类逐图状态、旧版启发式回退、--force-ocr 覆盖、
ocr_status.json 读取容错。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import xhs_export_md as mod

LONG_TEXT = "这是一段足够长的干货转录文字，用来越过十五个字的实质判定阈值，确保被判为信息图。"
SHORT_TEXT = "（App 界面截图）"


def _status(fn, cls, skip_reason="", note=""):
    return {"file": fn, "class": cls,
            "action": {"informational": "full_ocr", "ui": "one_line",
                       "decorative": "skip", "uncertain": "pending"}[cls],
            "skip_reason": skip_reason, "note": note}


class OcrGatePlanTest(unittest.TestCase):
    def test_legacy_fallback_matches_old_behaviour(self):
        """无状态文件 → 退回 has_substantive_text 启发式（2026-10-16 行为）"""
        plan = mod.plan_images(["img_01.jpg", "img_02.jpg"],
                               {"img_01.jpg": LONG_TEXT, "img_02.jpg": SHORT_TEXT})
        self.assertFalse(plan[0]["keep"])     # 干货长文 → 去图留文
        self.assertTrue(plan[1]["keep"])      # 一行说明 → 保留图
        self.assertFalse(plan[0]["pending"])
        self.assertEqual(plan[0]["src_class"], "legacy")

    def test_informational_full_ocr_drops_image(self):
        plan = mod.plan_images(["img_01.jpg"], {"img_01.jpg": LONG_TEXT},
                               [_status("img_01.jpg", "informational")])
        self.assertFalse(plan[0]["keep"])
        self.assertTrue(plan[0]["text"])

    def test_informational_without_substantive_text_keeps_image(self):
        """信息图但转录无实质（如纯 UI 长截图标了 informational）→ 不丢图"""
        plan = mod.plan_images(["img_01.jpg"], {"img_01.jpg": SHORT_TEXT},
                               [_status("img_01.jpg", "informational")])
        self.assertTrue(plan[0]["keep"])

    def test_ui_keeps_image_and_uses_note(self):
        plan = mod.plan_images(["img_01.jpg"], {"img_01.jpg": LONG_TEXT},
                               [_status("img_01.jpg", "ui", "UI 噪声", "设置页截图")])
        self.assertTrue(plan[0]["keep"])
        self.assertEqual(plan[0]["one_line"], "设置页截图")

    def test_decorative_suppresses_text(self):
        """装饰图：即使 ocr.md 有文字也只保留原图，不输出转录"""
        plan = mod.plan_images(["img_01.jpg"], {"img_01.jpg": LONG_TEXT},
                               [_status("img_01.jpg", "decorative", "照片")])
        self.assertTrue(plan[0]["keep"])
        self.assertEqual(plan[0]["text"], "")

    def test_uncertain_marks_pending_never_silent(self):
        """无法判定 → 保留图 + 待复核标记，绝不静默丢失"""
        plan = mod.plan_images(["img_01.jpg"], {"img_01.jpg": ""},
                               [_status("img_01.jpg", "uncertain", "待复核")])
        self.assertTrue(plan[0]["keep"])
        self.assertTrue(plan[0]["pending"])
        self.assertEqual(plan[0]["skip_reason"], "待复核")

    def test_force_ocr_overrides_skip(self):
        sts = [_status("img_01.jpg", "ui", "UI 噪声", "设置页截图"),
               _status("img_02.jpg", "decorative", "照片")]
        ocr = {"img_01.jpg": LONG_TEXT,
               "img_02.jpg": "另一张装饰图上恰好也印了足够长的文字内容，同样能去图留文。"}
        plan = mod.plan_images(["img_01.jpg", "img_02.jpg"], ocr, sts, force_ocr=True)
        self.assertFalse(plan[0]["keep"])    # 有转录 → 去图留文
        self.assertFalse(plan[1]["keep"])
        self.assertEqual(plan[0]["one_line"], "")   # 一句说明不再输出

    def test_force_ocr_without_text_never_fakes(self):
        """force-ocr 遇到无转录的图 → 保留原图，不伪称已转录"""
        plan = mod.plan_images(["img_01.jpg"], {"img_01.jpg": ""},
                               [_status("img_01.jpg", "decorative")], force_ocr=True)
        self.assertTrue(plan[0]["keep"])
        self.assertEqual(plan[0]["text"], "")

    def test_dedup_and_photo_caption_still_apply(self):
        """相邻图去重、照片图注过滤与闸门正交叠加"""
        dup = "这一段在两张图里重复出现的引导语，长度超过十二个字方便比对。"
        ocr = {"img_01.jpg": dup, "img_02.jpg": dup + "\n\n（照片：自拍）"}
        plan = mod.plan_images(["img_01.jpg", "img_02.jpg"], ocr,
                               [_status("img_01.jpg", "informational"),
                                _status("img_02.jpg", "decorative")])
        self.assertEqual(mod.norm_para(plan[1]["text"]), "")   # 重复段被去重 + 装饰不输出


class OcrStatusLoadTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, content):
        with open(os.path.join(self.folder, "ocr_status.json"), "w", encoding="utf-8") as f:
            f.write(content)

    def test_missing_file_returns_none(self):
        self.assertIsNone(mod.load_ocr_status(self.folder))

    def test_valid_file_parsed(self):
        self._write(json.dumps([_status("img_01.jpg", "ui", "UI", "说明")],
                               ensure_ascii=False))
        data = mod.load_ocr_status(self.folder)
        self.assertEqual(data[0]["class"], "ui")

    def test_corrupt_file_returns_none(self):
        self._write("{oops not json")
        self.assertIsNone(mod.load_ocr_status(self.folder))

    def test_non_dict_entries_dropped(self):
        self._write(json.dumps(["junk", _status("img_01.jpg", "ui")], ensure_ascii=False))
        data = mod.load_ocr_status(self.folder)
        self.assertEqual(len(data), 1)


if __name__ == "__main__":
    unittest.main()

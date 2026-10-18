# -*- coding: utf-8 -*-
"""断点续导与序号分配的最小回归测试（不访问网络）。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import xhs_fetch_selected as mod


class FetchSelectedPlanTest(unittest.TestCase):
    def setUp(self):
        self._orig_outdir = mod.OUTDIR
        self._tmp = tempfile.TemporaryDirectory()
        mod.OUTDIR = self._tmp.name

    def tearDown(self):
        mod.OUTDIR = self._orig_outdir
        self._tmp.cleanup()

    def _note_dir(self, dirname, note_id, ok=True):
        path = os.path.join(self._tmp.name, dirname)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "raw.json"), "w", encoding="utf-8") as f:
            json.dump({"note_id": note_id, "ok": ok}, f)

    def test_done_index_is_keyed_by_note_id(self):
        self._note_dir("01_foreign", "AAA")
        self.assertEqual(mod.load_done_index(), {"AAA": "01_foreign"})

    def test_resume_does_not_skip_by_list_position(self):
        self._note_dir("01_foreign", "AAA")
        notes = [{"note_id": "BBB"}, {"note_id": "AAA"}]
        todo = mod.plan_batch(notes, mod.load_done_index())
        self.assertEqual([n["note_id"] for _, n in todo], ["BBB"])

    def test_batch_avoids_existing_single_import_seq(self):
        self._note_dir("01_single", "ZZZ")
        notes = [{"note_id": "AAA"}, {"note_id": "BBB"}]
        todo = mod.plan_batch(notes, {})
        self.assertEqual([seq for seq, _ in todo], [2, 3])

    def test_existing_note_reuses_its_seq(self):
        self._note_dir("05_AAA", "AAA")
        todo = mod.plan_batch([{"note_id": "AAA"}, {"note_id": "BBB"}], {})
        self.assertEqual([seq for seq, _ in todo], [5, 2])


if __name__ == "__main__":
    unittest.main()

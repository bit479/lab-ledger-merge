# -*- coding: utf-8 -*-
"""化验结果解析测试（对应计划书验收第 1 条）。"""
from __future__ import annotations

import os
import unittest

import base
from core import filetype, reader_lab


class TestFiletype(unittest.TestCase):
    def test_biff_and_ooxml(self):
        self.assertEqual(filetype.detect(base.LEDGER), "xlsx")

    def test_broken_file_detected(self):
        """扩展名 .xls、内容 PK 开头但 zip 结构不合法的那份。"""
        bad = os.path.join(base.LAB_DIR, "送样单20261020-07-BG1分析报告.xls")
        self.assertTrue(os.path.exists(bad), "样本文件不在了，测试需要更新")
        self.assertEqual(filetype.detect(bad), "xlsx")  # 魔数是 OOXML，扩展名骗人


class TestLabReader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scan = base.get_scan()

    def test_file_count(self):
        self.assertEqual(self.scan.file_count, 80)

    def test_record_count(self):
        self.assertEqual(len(self.scan.records), 4802)

    def test_unique_ana(self):
        self.assertEqual(len({r.ana for r in self.scan.records}), 4720)

    def test_broken_file_skipped_not_fatal(self):
        names = [os.path.basename(s.path) for s in self.scan.skipped]
        self.assertIn("送样单20261020-07-BG1分析报告.xls", names)
        self.assertEqual(len(self.scan.records), 4802, "坏文件不能中断整批")

    def test_three_column_file_has_empty_location(self):
        recs = [r for r in self.scan.records
                if r.source_file.startswith("20260928上库选厂矿石Au -2")]
        self.assertTrue(recs)
        self.assertTrue(all(r.location == "" for r in recs))
        self.assertTrue(all(r.grade is not None for r in recs))

    def test_fields_parsed(self):
        rec = next(r for r in self.scan.records if r.ana == "2026004349-1")
        self.assertEqual(rec.sample_no, "BS-3940-1022-P43")
        self.assertAlmostEqual(rec.grade, 0.5835, places=6)
        self.assertEqual(rec.location, "北部山头3940平台炮孔样")

    def test_ana_normalized(self):
        for rec in self.scan.records[:500]:
            self.assertRegex(rec.ana, reader_lab.ANA_RE)
            self.assertEqual(rec.ana, rec.ana.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)

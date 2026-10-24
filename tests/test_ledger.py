# -*- coding: utf-8 -*-
"""台账结构与列标定测试（计划书「难点 3」「难点 6」）。

这些断言就是防回归的底线：一旦有人改坏了列识别，写错表、写错列都会在这里炸。
"""
from __future__ import annotations

import unittest

import base
from core.reader_ledger import STAGING_SHEET


class TestLedgerIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = base.get_ledger()

    def test_sheet_count(self):
        self.assertEqual(len(self.led.sheets), 28)

    def test_total_ana(self):
        self.assertEqual(self.led.total_ana, 34646)

    def test_no_staging_sheet_initially(self):
        self.assertIsNone(self.led.staging_sheet, "原始台账不该有暂存表")

    def test_unusable_sheets(self):
        """这三张编号形态不符，必须排除，否则会写错列。"""
        for name in ("筛分矿样", "构造点", "选厂原矿数据"):
            info = self.led.sheet(name)
            self.assertIsNotNone(info)
            self.assertFalse(info.usable, f"{name} 不该被识别为可写表")

    def test_excluded_sheets(self):
        rules = base.get_rules()
        self.assertIn("多元素分析实验", rules["excluded_sheets"])


class TestColumnRole(unittest.TestCase):
    """列序标定：表头写反的 7 张表 + 送样在前的 2 张表。"""

    @classmethod
    def setUpClass(cls):
        cls.led = base.get_ledger()

    def role(self, sheet, idx=0):
        return self.led.sheet(sheet).groups[idx].role

    def test_normal_order(self):
        r = self.role("中心矿段炮孔")
        self.assertEqual((r.ana, r.sample, r.grade, r.loc), (0, 1, 2, 3))

    def test_sample_first(self):
        """1-1剥离 / 前山Ⅱ号矿体：送样编号在 A，分析编号在 B。"""
        for name in ("1-1剥离", "前山Ⅱ号矿体-炮孔"):
            r = self.role(name)
            self.assertEqual(r.ana, 1, f"{name} 的分析编号应在 B 列")
            self.assertEqual(r.sample, 0, f"{name} 的送样编号应在 A 列")

    def test_header_mismatch_tables(self):
        """北部山头炮孔表头写「样品编号/分析编号」，实际 A 是分析编号。"""
        r = self.role("北部山头炮孔")
        self.assertEqual(r.ana, 0)
        self.assertEqual(r.sample, 1)

    def test_multi_group_offsets(self):
        """剥离样 3 组：A-D / E-H / I-L，第 2、3 组的位置列不能借到第 1 组的 D 列。"""
        groups = self.led.sheet("剥离样").groups
        self.assertEqual(len(groups), 3)
        for g, expected in zip(groups, [(0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 11)]):
            self.assertEqual((g.role.ana, g.role.sample, g.role.grade, g.role.loc), expected)

    def test_gap_column_group(self):
        """原矿堆场第 2 组是 F-I（E 列是空分隔），不能按固定步长算。"""
        groups = self.led.sheet("原矿堆场山顶运矿样").groups
        self.assertEqual(len(groups), 2)
        g2 = groups[1]
        self.assertEqual((g2.role.ana, g2.role.loc), (5, 8))

    def test_no_location_column(self):
        """十道弯倒运矿石只有 3 列，没有位置列。"""
        r = self.role("十道弯倒运矿石")
        self.assertIsNone(r.loc)


class TestNextWriteRow(unittest.TestCase):
    """追加位置必须用「最后一条分析编号行 + 1」，不是 max_row + 1。"""

    @classmethod
    def setUpClass(cls):
        cls.led = base.get_ledger()

    def test_zhongtie_has_500_trailing_blank_rows(self):
        info = self.led.sheet("中铁十九局低品位堆场样")
        self.assertGreater(info.max_row, 1700, "该表 max_row 应超过 1700")
        grp = max(info.groups, key=lambda g: g.last_row)
        self.assertEqual(grp.last_row, 1264, "真实最后数据行是 1264，不是 max_row")
        self.assertEqual(grp.last_row + 1, 1265)

    def test_dizhizuan(self):
        info = self.led.sheet("地质钻")
        grp = info.groups[0]
        self.assertEqual(grp.last_row, 232)
        self.assertGreater(info.max_row, 700)

    def test_normal_sheet(self):
        grp = self.led.sheet("北部山头炮孔").groups[0]
        self.assertEqual(grp.last_row + 1, grp.last_row + 1)
        self.assertGreater(grp.last_row, 11000)


class TestStagingSheetName(unittest.TestCase):
    def test_name_is_expected(self):
        self.assertEqual(STAGING_SHEET, "未知位置待定")


if __name__ == "__main__":
    unittest.main(verbosity=2)

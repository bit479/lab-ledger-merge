# -*- coding: utf-8 -*-
"""归档与判重测试（计划书「难点 1」「难点 2」，验收第 3、4 条）。"""
from __future__ import annotations

import unittest

import base
from core import dedup, router
from core.reader_ledger import STAGING_SHEET


class TestRoutingBaseline(unittest.TestCase):
    """现有 80 个文件的基线：169 条待写（154 进业务表 + 15 进暂存表）。"""

    @classmethod
    def setUpClass(cls):
        cls.a = base.get_analysis()

    def test_total(self):
        self.assertEqual(self.a.total, 169)

    def test_by_target(self):
        got = dict(self.a.by_target)
        self.assertEqual(got.get("北部山头炮孔"), 106)
        self.assertEqual(got.get("中铁十九局低品位堆场样"), 24)
        self.assertEqual(got.get("剥离样"), 24)
        self.assertEqual(got.get(STAGING_SHEET), 15)

    def test_staging_excludes_existing_numbers(self):
        """位置判不出、但编号台账里已有的 15 条，不应进暂存表。"""
        self.assertEqual(len(self.a.staged), 15)
        for dec in self.a.staged:
            self.assertNotIn(dec.rec.ana, self.a.ledger.by_ana)

    def test_confidence_distribution(self):
        """148 条位置唯一对应（high）、6 条走关键词/多义（mid）、15 条兜底（low）。"""
        counts = {}
        for d in self.a.decisions:
            counts[d.confidence] = counts.get(d.confidence, 0) + 1
        self.assertEqual(counts.get("high"), 148)
        self.assertEqual(counts.get("mid"), 6)
        self.assertEqual(counts.get("low"), 15)

    def test_cross_sheet_written(self):
        """台账别的表有、目标表没有的 11 条要照写并标记。"""
        self.assertEqual(len(self.a.crossed), 11)
        for c in self.a.crossed:
            self.assertTrue(c.sheets)

    def test_skipped_all_because_existing(self):
        self.assertEqual(len(self.a.skipped), 4720 - 169)
        for sk in self.a.skipped:
            self.assertTrue(sk.reason)

    def test_plans_start_after_last_data(self):
        led = self.a.ledger
        for plan in self.a.plans:
            if plan.sheet == STAGING_SHEET and led.staging_sheet is None:
                self.assertEqual(plan.start_row, 2)
                continue
            info = led.sheet(plan.sheet)
            if not info or not info.groups:
                continue
            self.assertEqual(plan.start_row, max(g.last_row for g in info.groups) + 1)


class TestKeywordRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = base.get_rules()
        cls.led = base.get_ledger()

    def test_short_shelf(self):
        sheet, hit = router._match_keyword("北部山头3930平台0.5-1.0g/t-低品位堆场", self.rules)
        self.assertEqual(sheet, "中铁十九局低品位堆场样")
        self.assertIn("0.5-1.0g/t", hit)

    def test_pit_by_mine(self):
        cases = {
            "北部山头4020平台炮孔样": "北部山头炮孔",
            "南部山头3920平台炮孔样": "南部山头炮孔",
            "中心矿段3570平台炮孔样": "中心矿段炮孔",
        }
        for loc, want in cases.items():
            got, _ = router._match_keyword(loc, self.rules)
            self.assertEqual(got, want, loc)

    def test_screening_yard_before_generic(self):
        """1.0-999g/t 要命中筛分临时堆场，不能被后面的「剥离」抢走。"""
        sheet, _ = router._match_keyword("中心矿段筛分临时堆场剥离样1.0-999g/t", self.rules)
        self.assertEqual(sheet, "中心矿段筛分氧化矿临时堆场")

    def test_bomb_pile_rule(self):
        """「爆堆」要比通用「剥离」先命中（爆堆样是独立的一张表）。"""
        sheet, _ = router._match_keyword("北部山头4040平台爆堆出矿样", self.rules)
        self.assertEqual(sheet, "爆堆样")


class TestPrefixSuggestion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = base.get_rules()

    def test_shift_prefix_stripped(self):
        """Y-YKDC / B-YKDC 要能剥掉班次前缀后命中 YKDC-。"""
        self.assertEqual(router._suggest_prefix("Y-YKDC-0927-P1", self.rules),
                         "原矿堆场山顶运矿样")
        self.assertEqual(router._suggest_prefix("B-YKDC-0807-LC1", self.rules),
                         "原矿堆场山顶运矿样")
        self.assertEqual(router._suggest_prefix("B-CRCC-SD-0815-D15", self.rules),
                         "五道弯、十道弯运矿样")

    def test_plain_prefix(self):
        self.assertEqual(router._suggest_prefix("BS-3940-1022-P43", self.rules), "北部山头炮孔")

    def test_unknown(self):
        self.assertEqual(router._suggest_prefix("XXXX-1", self.rules), "")


class TestDedup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = base.get_ledger()

    def test_skip_when_in_target(self):
        ana = next(iter(self.led.by_sheet["北部山头炮孔"]))
        res = dedup.check(ana, "北部山头炮孔", self.led)
        self.assertTrue(res.skip)

    def test_cross_sheet_not_skip(self):
        """2026004123-1 在北部山头炮孔里有、剥离样里没有 → 目标表是剥离样时要照写。"""
        ana = "2026004123-1"
        self.assertIn(ana, self.led.by_ana)
        self.assertIn("北部山头炮孔", self.led.by_ana[ana])
        self.assertNotIn(ana, self.led.by_sheet.get("剥离样", set()))

        res = dedup.check(ana, "剥离样", self.led)
        self.assertFalse(res.skip, "目标表里没有就不算重复，应该照写")
        self.assertIn("北部山头炮孔", res.cross_sheets)

    def test_unknown_number(self):
        res = dedup.check("2099000000-1", "北部山头炮孔", self.led)
        self.assertFalse(res.skip)
        self.assertEqual(res.cross_sheets, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)

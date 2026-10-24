# -*- coding: utf-8 -*-
"""分级判重。

实测：台账里有 340 个分析编号**合法地出现在两张表**（如 2026001205-2 同时在
「北部山头炮孔」和「爆堆样」），是人工按不同业务口径重复登记的，不是脏数据。
所以判重分两级：
  - 目标表内已有 → 跳过（真重复）
  - 只在别的表有 → 照写，但标「跨表存在」供人工过目
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .reader_ledger import Ledger


@dataclass
class DedupResult:
    skip: bool = False
    reason: str = ""
    cross_sheets: set[str] = field(default_factory=set)

    @property
    def cross_note(self) -> str:
        if not self.cross_sheets:
            return ""
        return "跨表存在：" + "、".join(sorted(self.cross_sheets))


def check(ana: str, target: str | None, ledger: Ledger) -> DedupResult:
    """判断一条记录在目标表里是否已存在。target 为 None 时只看全局。"""
    if target:
        existing = ledger.by_sheet.get(target, set())
        if ana in existing:
            return DedupResult(skip=True, reason=f"「{target}」中已存在")

    everywhere = ledger.by_ana.get(ana, set())
    if not everywhere:
        return DedupResult()

    # 暂存表里的编号不算「跨表」告警依据（计划书「难点 6」）
    from .reader_ledger import STAGING_SHEET
    others = {s for s in everywhere if s != STAGING_SHEET and s != target}
    if others:
        return DedupResult(cross_sheets=others)
    return DedupResult()

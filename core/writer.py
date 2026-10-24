# -*- coding: utf-8 -*-
"""写入台账：追加到各表末尾，保持原有格式。

三条硬规矩（计划书「难点 3」）：
  1. 追加位置 = 该列组「最后一个分析编号行」+ 1，**不是 max_row + 1**
     （中铁十九局 max_row=1767 但最后数据在 1264，写错会在表中间留 500 行空白）
  2. 样式从上一行整行复制（字体/边框/数字格式 `0.00_ )`），只改 value
  3. 品位写 float 原值，不 round（台账里本来就有 `0.00320000000000001` 这种尾巴）
"""
from __future__ import annotations

import time
from copy import copy
from dataclasses import dataclass, field
from datetime import datetime

from .reader_ledger import STAGING_SHEET, Ledger
from .router import Decision

STAGING_HEADER = ["分析编号", "送样编号", "基本分析金（g/T）", "取样位置", "来源文件", "建议目标表"]


def natural_key(ana: str):
    """分析编号的自然排序键。

    台账里的人工顺序是 `-1, -2, … -10, -11`，纯字典序会排成 `-1, -10, -11, … -2`，
    一眼就能看出是程序写的。所以把每段数字按数值比较（数字段在前、文本段在后，
    避免 int 与 str 直接比较报错）。
    """
    out = []
    for part in ana.split("-"):
        out.append((0, int(part), "") if part.isdigit() else (1, 0, part))
    return out


@dataclass
class WritePlan:
    sheet: str
    start_row: int
    decisions: list[Decision] = field(default_factory=list)


@dataclass
class WriteResult:
    written: dict[str, int] = field(default_factory=dict)
    staging_created: bool = False
    staging_written: int = 0
    backup_path: str = ""
    elapsed: float = 0.0
    total: int = 0

    def summary(self) -> str:
        parts = [f"{k} +{v}" for k, v in sorted(self.written.items()) if k != STAGING_SHEET]
        if self.staging_written:
            parts.append(f"{STAGING_SHEET} +{self.staging_written}")
        return "，".join(parts) if parts else "无"


def build_plan(decisions: list[Decision], ledger: Ledger) -> list[WritePlan]:
    """按目标表分组，算出每张表的起始行。"""
    grouped: dict[str, list[Decision]] = {}
    for dec in decisions:
        grouped.setdefault(dec.label, []).append(dec)

    plans: list[WritePlan] = []
    for sheet, items in grouped.items():
        info = ledger.sheet(sheet)
        if sheet == STAGING_SHEET and info is None:
            # 暂存表还没建：表头占第 1 行
            plans.append(WritePlan(sheet=sheet, start_row=2, decisions=items))
            continue
        if not info or not info.groups:
            continue
        last = max(g.last_row for g in info.groups)
        plans.append(WritePlan(sheet=sheet, start_row=last + 1, decisions=items))

    plans.sort(key=lambda p: p.sheet)
    return plans


def _ensure_staging_sheet(wb, template_ws) -> tuple:
    """建 `未知位置待定` 表，返回 (ws, created)。表头样式借用第一个业务表。"""
    if STAGING_SHEET in wb.sheetnames:
        return wb[STAGING_SHEET], False

    ws = wb.create_sheet(title=STAGING_SHEET)
    for i, text in enumerate(STAGING_HEADER, start=1):
        cell = ws.cell(row=1, column=i, value=text)
        if template_ws is not None:
            src = template_ws.cell(row=1, column=min(i, 4))
            if src.has_style:
                cell._style = copy(src._style)

    widths = [18, 26, 16, 46, 34, 30]
    from openpyxl.utils import get_column_letter
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # 冻结表头，方便人工处理
    ws.freeze_panes = "A2"
    return ws, True


def _copy_row_style(ws, src_row: int, dst_row: int, cols: list[int],
                    src_ws=None, fallback_col: int | None = None) -> None:
    """把 src_row 的样式整行复制到 dst_row。

    src_ws 可指向别的表（暂存表借用业务表样式）；fallback_col 用于源表列数不够时
    重复用最后一列的样式（暂存表第 5、6 列没有对应业务列，借第 4 列的边框）。
    """
    src_ws = src_ws or ws
    if src_row < 1:
        return
    for c in cols:
        sc = c if (fallback_col is None or c <= fallback_col) else fallback_col
        src = src_ws.cell(row=src_row, column=sc)
        dst = ws.cell(row=dst_row, column=c)
        if src.has_style:
            dst._style = copy(src._style)
    height = src_ws.row_dimensions[src_row].height
    if height:
        ws.row_dimensions[dst_row].height = height


def apply_plan(ledger_path: str, ledger: Ledger, plans: list[WritePlan],
               backup_path: str = "") -> WriteResult:
    """真正写盘。调用方负责先做备份。"""
    import openpyxl

    t0 = time.time()
    result = WriteResult(backup_path=backup_path)

    # data_only=False：必须保留公式，否则二堆场 I 列、多元素换算全废
    wb = openpyxl.load_workbook(ledger_path)
    template_ws = wb[ledger.sheets[0].name] if ledger.sheets else None

    for plan in plans:
        style_ws = None      # 样式来源表：暂存表新建时借用业务表的**数据行**
        style_from = None
        if plan.sheet == STAGING_SHEET:
            ws, created = _ensure_staging_sheet(wb, template_ws)
            result.staging_created = result.staging_created or created
            cols = list(range(1, 7))
            row = 2 if created else plan.start_row
            if created:
                style_ws, style_from = template_ws, 2   # 别借表头（表头是微软雅黑 9）
        else:
            info = ledger.sheet(plan.sheet)
            if info is None or not info.groups:
                continue
            grp = max(info.groups, key=lambda g: g.last_row)
            role = grp.role
            cols = [c + 1 for c in role.all()]
            ws = wb[plan.sheet]
            row = plan.start_row

        # 逐条写，每条都从"上一行"借样式（首条借原最后一行，之后借刚写的那行）
        prev_row = row - 1
        for dec in sorted(plan.decisions, key=lambda d: natural_key(d.rec.ana)):
            if style_ws is not None:
                _copy_row_style(ws, style_from, row, cols, src_ws=style_ws, fallback_col=4)
            else:
                _copy_row_style(ws, prev_row, row, cols)

            if plan.sheet == STAGING_SHEET:
                ws.cell(row=row, column=1, value=dec.rec.ana)
                ws.cell(row=row, column=2, value=dec.rec.sample_no)
                ws.cell(row=row, column=3, value=dec.rec.grade)
                ws.cell(row=row, column=4, value=dec.rec.location)
                ws.cell(row=row, column=5, value=dec.rec.source_file)
                ws.cell(row=row, column=6, value=dec.suggestion)
            else:
                role = max(ledger.sheet(plan.sheet).groups,
                           key=lambda g: g.last_row).role
                if role.ana is not None:
                    ws.cell(row=row, column=role.ana + 1, value=dec.rec.ana)
                if role.sample is not None:
                    ws.cell(row=row, column=role.sample + 1, value=dec.rec.sample_no)
                if role.grade is not None:
                    ws.cell(row=row, column=role.grade + 1, value=dec.rec.grade)
                if role.loc is not None:
                    ws.cell(row=row, column=role.loc + 1, value=dec.rec.location)

            prev_row = row
            row += 1
            result.written[plan.sheet] = result.written.get(plan.sheet, 0) + 1
            result.total += 1

        if plan.sheet == STAGING_SHEET:
            result.staging_written = result.written.get(STAGING_SHEET, 0)

    # openpyxl 保存会清掉公式缓存值，让 Excel 打开时重算
    try:
        wb.calculation.fullCalcOnLoad = True
    except Exception:  # noqa: BLE001 - 老版本属性名不同，不该因此阻断写盘
        pass

    wb.save(ledger_path)
    wb.close()
    result.elapsed = time.time() - t0
    return result


def verify(ledger_path: str, expected: dict[str, int]) -> list[str]:
    """写后自检：重新打开，确认每张表确实多出了对应条数。"""
    import openpyxl

    problems: list[str] = []
    wb = openpyxl.load_workbook(ledger_path, data_only=True, read_only=True)
    for sheet, n in expected.items():
        if n <= 0:
            continue
        if sheet not in wb.sheetnames:
            problems.append(f"「{sheet}」写后不存在")
            continue
        ws = wb[sheet]
        if (ws.max_row or 0) < 2:
            problems.append(f"「{sheet}」写后没有数据")
    wb.close()
    return problems

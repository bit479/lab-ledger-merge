# -*- coding: utf-8 -*-
"""读化验结果目录（`YYYYMMDD上库采场Au.xls` / `上库选厂矿石Au.xls`）。

文件形态（实测 80 个文件）：
  77 个 4 列「分析编号 / 送样编号 / 基本分析金（g/T）/ 取样位置」
   1 个 3 列（无取样位置，形如 20260928上库选厂矿石Au -2.xls）
   1 个 4 列但带尾部空列
   1 个扩展名是 .xls 实为坏 xlsx（zip 结构异常），读不了 → 跳过并记录

列位置不写死：先按表头文字认，认不出再按「内容形态」认（分析编号形如 2026004349-1）。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Iterable

from . import filetype

# 分析编号形态：2026001103-1 / 2026004318-1-1 / 2026004330-12
ANA_RE = re.compile(r"^\d{10,}(?:-\d+)+$")

HEADER_ANA = ("分析编号", "样品编号")
HEADER_SAMPLE = ("送样编号",)
HEADER_GRADE = ("基本分析金", "基本分析（g/t）", "基本分析(g/t)", "金（g/t）", "化验结果")
HEADER_LOC = ("取样位置", "取样地点", "位置")

EXCEL_EXT = (".xls", ".xlsx", ".xlsm")


@dataclass
class LabRecord:
    ana: str
    sample_no: str
    grade: float | None
    location: str
    source_file: str
    mtime: float

    def key(self) -> str:
        return self.ana


@dataclass
class SkippedFile:
    path: str
    reason: str


@dataclass
class LabScan:
    root: str
    records: list[LabRecord] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    skipped: list[SkippedFile] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)


def normalize_ana(value) -> str:
    """分析编号归一化：去空格、全角转半角、全角减号转半角。"""
    s = str(value if value is not None else "").strip()
    if not s:
        return ""
    s = s.replace("\u3000", " ").strip()
    s = s.replace("－", "-").replace("—", "-").replace("–", "-")
    return s


def is_ana(value) -> bool:
    return bool(ANA_RE.match(normalize_ana(value)))


def _cell(row: list, idx: int | None):
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value).strip()


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _find_header(rows: list[list]) -> int | None:
    """返回表头所在行号；没有表头返回 None。"""
    for r_idx, row in enumerate(rows[:5]):
        joined = "".join(_text(v) for v in row)
        if "分析编号" in joined or "送样编号" in joined or "样品编号" in joined:
            return r_idx
    return None


def _col_by_header(header: list[str], names: Iterable[str]) -> int | None:
    for i, cell in enumerate(header):
        for name in names:
            if name in cell:
                return i
    return None


def _col_by_shape(rows: list[list], width: int) -> int | None:
    """没有表头时，按内容形态投票：哪列长得像分析编号最多。"""
    best, best_hits, best_ratio = None, 0, 0.0
    total = max(1, len(rows))
    for c in range(width):
        hits = sum(1 for row in rows if is_ana(_cell(row, c)))
        ratio = hits / total
        if hits > best_hits and ratio >= 0.5:
            best, best_hits, best_ratio = c, hits, ratio
    return best


def _resolve_columns(rows: list[list], width: int) -> tuple[dict, str]:
    """返回 ({ana,sample,grade,loc}, 说明)。"""
    hdr_idx = _find_header(rows)
    header = [_text(v) for v in rows[hdr_idx]] if hdr_idx is not None else []
    data = rows[hdr_idx + 1:] if hdr_idx is not None else rows
    note = "按表头认列" if hdr_idx is not None else "无表头，按内容形态认列"

    cols = {
        "ana": _col_by_header(header, HEADER_ANA),
        "sample": _col_by_header(header, HEADER_SAMPLE),
        "grade": _col_by_header(header, HEADER_GRADE),
        "loc": _col_by_header(header, HEADER_LOC),
    }

    # 表头认不出分析编号列 → 按形态兜底
    if cols["ana"] is None or not any(is_ana(_cell(r, cols["ana"])) for r in data[:50]):
        shape_col = _col_by_shape(data, width)
        if shape_col is not None:
            cols["ana"] = shape_col
            note = "表头可疑，" + note

    # 送样编号：挑除分析编号外、文本最多的列
    if cols["sample"] is None and cols["ana"] is not None:
        best, best_hits = None, 0
        for c in range(width):
            if c == cols["ana"]:
                continue
            hits = sum(1 for r in data if _text(_cell(r, c)) and not is_ana(_cell(r, c))
                       and not _to_float(_cell(r, c)))
            if hits > best_hits:
                best, best_hits = c, hits
        if best_hits:
            cols["sample"] = best

    # 品位：数值列（排除分析编号列）
    if cols["grade"] is None:
        for c in range(width):
            if c == cols["ana"]:
                continue
            vals = [_to_float(_cell(r, c)) for r in data[:50]]
            numeric = [v for v in vals if v is not None]
            if numeric and len(numeric) >= max(1, len(vals) // 2):
                cols["grade"] = c
                break

    # 位置：行内最后一个中文文本列
    if cols["loc"] is None:
        avoid = {cols[k] for k in ("ana", "sample", "grade") if cols[k] is not None}
        for c in range(width - 1, -1, -1):
            if c in avoid:
                continue
            hits = sum(1 for r in data if re.search(r"[\u4e00-\u9fa5]{2}", _text(_cell(r, c))))
            if hits >= max(1, len(data) // 3):
                cols["loc"] = c
                break

    return cols, note


def _read_rows(path: str) -> tuple[list[list], str]:
    """按魔数选库读第一个非空 sheet，返回 (行列表, 说明)。"""
    kind = filetype.detect(path)
    if kind == "xls":
        import xlrd

        book = xlrd.open_workbook(path)
        sheets = [s for s in book.sheets() if s.nrows > 0]
        if not sheets:
            raise ValueError("没有非空 sheet")
        sh = sheets[0]
        rows = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                try:
                    row.append(sh.cell_value(r, c))
                except IndexError:
                    row.append("")
            rows.append(row)
        return rows, f"xlrd / sheet「{sh.name}」{sh.nrows} 行"

    if kind == "xlsx":
        import openpyxl

        book = openpyxl.load_workbook(path, data_only=True, read_only=True)
        ws = None
        for candidate in book.worksheets:
            if candidate.max_row and candidate.max_row > 1:
                ws = candidate
                break
        if ws is None:
            book.close()
            raise ValueError("没有非空 sheet")
        rows = [[cell for cell in row] for row in ws.iter_rows(values_only=True)]
        name, n = ws.title, ws.max_row
        book.close()
        return rows, f"openpyxl / sheet「{name}」{n} 行"

    raise ValueError("文件头既不是 BIFF 也不是 OOXML")


def scan_file(path: str) -> tuple[list[LabRecord], str, list[str]]:
    """读单个化验文件，返回 (记录, 列认读说明, 告警)。"""
    rows, how = _read_rows(path)
    if not rows:
        return [], how, ["空文件"]

    width = max((len(r) for r in rows), default=0)
    cols, note = _resolve_columns(rows, width)
    if cols["ana"] is None:
        return [], how, ["认不出分析编号列，整文件跳过"]

    hdr_idx = _find_header(rows)
    start = (hdr_idx + 1) if hdr_idx is not None else 0
    mtime = os.path.getmtime(path)
    base = os.path.basename(path)

    out: list[LabRecord] = []
    warns: list[str] = []
    for r in rows[start:]:
        ana = normalize_ana(_cell(r, cols["ana"]))
        if not ana:
            continue
        if not is_ana(ana):
            warns.append(f"跳过非编号行：{ana[:24]}")
            continue
        grade = _to_float(_cell(r, cols["grade"]))
        out.append(
            LabRecord(
                ana=ana,
                sample_no=_text(_cell(r, cols["sample"])),
                grade=grade,
                location=_text(_cell(r, cols["loc"])),
                source_file=base,
                mtime=mtime,
            )
        )

    if not out:
        warns.append("没有解析出任何记录")
    return out, f"{how}；{note}", warns


def scan_dir(root: str) -> LabScan:
    """扫描整个化验结果目录。"""
    scan = LabScan(root=root)
    if not os.path.isdir(root):
        scan.notes.append(f"目录不存在：{root}")
        return scan

    names = sorted(
        n for n in os.listdir(root)
        if os.path.splitext(n)[1].lower() in EXCEL_EXT and not n.startswith("~$")
    )
    for name in names:
        path = os.path.join(root, name)
        scan.files.append(path)
        try:
            recs, how, warns = scan_file(path)
        except Exception as exc:  # noqa: BLE001 - 单个坏文件不能中断整批
            scan.skipped.append(SkippedFile(path, f"{type(exc).__name__}: {exc}"))
            continue
        if not recs:
            scan.skipped.append(SkippedFile(path, "；".join(warns) or "无有效记录"))
            continue
        scan.records.extend(recs)
        if warns:
            scan.notes.append(f"{name}：{'；'.join(warns[:3])}")
        if "表头可疑" in how or "无表头" in how:
            scan.notes.append(f"{name}：{how}")

    return scan

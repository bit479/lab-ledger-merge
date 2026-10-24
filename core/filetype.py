# -*- coding: utf-8 -*-
"""按文件头魔数判断 Excel 真实格式，不看扩展名。

教训来源：`送样单20261020-07-BG1分析报告.xls` 扩展名是 .xls、内容是 PK 开头的 xlsx，
按扩展名选库必然翻车（xlrd 报 "Excel xlsx file; not supported"）。
"""
from __future__ import annotations

import os

OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # BIFF (xls)
ZIP_MAGIC = b"PK\x03\x04"                          # OOXML (xlsx/xlsm)


def detect(path: str) -> str:
    """返回 'xls' / 'xlsx' / 'unknown'。只看文件头，不看扩展名。"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return "unknown"

    if head.startswith(OLE2_MAGIC):
        return "xls"
    if head.startswith(ZIP_MAGIC):
        return "xlsx"
    return "unknown"


def is_excel(path: str) -> bool:
    return detect(path) != "unknown"


def describe(path: str) -> str:
    """给人看的说明：判断结果 + 扩展名是否一致。"""
    kind = detect(path)
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if kind == "unknown":
        return f"无法识别（扩展名 {ext or '无'}）"
    if ext in ("xls", "xlsx") and ext != kind:
        return f"⚠ 扩展名 {ext} 实为 {kind}"
    return kind

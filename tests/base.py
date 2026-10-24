# -*- coding: utf-8 -*-
"""测试公共夹具。

台账读一次要 10 秒，所以整个测试进程只读一次（lru_cache）。
测试用真数据，不用造样本 —— 这份台账的坑（表头写反、多组并排、尾部空行、
跨表重复编号）正是要测的东西，造出来的数据测不到。
"""
from __future__ import annotations

import os
import time
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from functools import lru_cache  # noqa: E402

from core import pipeline, reader_lab, reader_ledger, router  # noqa: E402

LEDGER, LAB_DIR = pipeline.default_paths(BASE)
OUT_DIR = os.path.join(BASE, "_out")
TEST_DIR = os.path.join(OUT_DIR, "test")


@lru_cache(maxsize=1)
def get_ledger() -> reader_ledger.Ledger:
    return reader_ledger.read_ledger(LEDGER)


@lru_cache(maxsize=1)
def get_scan() -> reader_lab.LabScan:
    return reader_lab.scan_dir(LAB_DIR)


@lru_cache(maxsize=1)
def get_analysis() -> pipeline.Analysis:
    return pipeline.analyze(LEDGER, LAB_DIR)


@lru_cache(maxsize=1)
def get_rules() -> dict:
    return router.load_rules()


def copy_ledger(name: str = "台账副本.xlsx") -> str:
    """把台账复制到 _out/test/ 下，写入类测试只碰副本。

    不删旧文件（执行环境可能禁止删除），用时间戳命名，shutil.copy2 直接覆盖同名。
    """
    os.makedirs(TEST_DIR, exist_ok=True)
    stem, ext = os.path.splitext(name)
    dst = os.path.join(TEST_DIR, f"{stem}_{int(time.time() * 1000) % 100000}{ext}")
    shutil.copy2(LEDGER, dst)
    return dst

# -*- coding: utf-8 -*-
"""一键自检：跑完解析 / 台账 / 归档 / 写入四套测试。

    python tests/test_selftest.py          # 命令行
    python main.py --selftest              # exe 里也能跑（不开窗口）

exe 打包后没法跑 pytest，所以这条是验包的唯一手段。
"""
from __future__ import annotations

import io
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, BASE)
sys.path.insert(0, HERE)

MODULES = ["test_reader", "test_ledger", "test_router", "test_write"]


def run(verbose: bool = True) -> tuple[bool, str]:
    """返回 (是否全过, 汇总文本)。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in MODULES:
        try:
            suite.addTests(loader.loadTestsFromName(name))
        except Exception as exc:  # noqa: BLE001
            return False, f"加载 {name} 失败：{exc}"

    stream = sys.stdout if (verbose and sys.stdout is not None) else io.StringIO()
    t0 = time.time()
    result = unittest.TextTestRunner(stream=stream, verbosity=2 if verbose else 1).run(suite)
    cost = time.time() - t0

    ok = result.wasSuccessful()
    total = result.testsRun
    bad = len(result.failures) + len(result.errors)

    lines = [
        "",
        "=" * 56,
        f"自检{'通过' if ok else '未通过'}：{total - bad}/{total} 项，用时 {cost:.1f}s",
    ]
    fallback = [
        ("失败", result.failures),
        ("错误", result.errors),
    ]
    for label, items in fallback:
        for case, trace in items:
            lines.append(f"  ✗ {label}：{case}")
            lines.append("    " + trace.strip().splitlines()[-1])
    lines.append("=" * 56)
    text = "\n".join(lines)
    if sys.stdout is not None:
        print(text)
    return ok, text


def smoke() -> tuple[bool, str]:
    """轻量自检：现场没有训练材料时用（exe 双击验包）。"""
    lines = ["", "=" * 56, "冒烟自检（未找到训练材料，只验程序完整性）"]
    ok = True

    checks = []
    try:
        import tkinter as tk
        checks.append(("tkinter", tk.TkVersion))
    except Exception as exc:  # noqa: BLE001
        checks.append(("tkinter", f"✗ {exc}"))
        ok = False

    for mod in ("openpyxl", "xlrd"):
        try:
            m = __import__(mod)
            checks.append((mod, getattr(m, "__version__", "?")))
        except Exception as exc:  # noqa: BLE001
            checks.append((mod, f"✗ {exc}"))
            ok = False

    for label, value in checks:
        lines.append(f"  {label}: {value}")

    try:
        from core import pipeline

        ledger, lab = pipeline.default_paths(BASE)
        found = os.path.exists(ledger) and os.path.isdir(lab)
        lines.append(f"  训练材料: {'找到' if found else '不在（正常，现场用真实数据）'}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"  ✗ 核心模块导入失败：{exc}")
        ok = False

    lines.append(f"冒烟{'通过' if ok else '失败'}")
    lines.append("=" * 56)
    text = "\n".join(lines)
    if sys.stdout is not None:
        print(text)
    return ok, text


def auto() -> tuple[bool, str]:
    """有训练材料就跑全量测试，没有就冒烟。"""
    from core import pipeline

    ledger, lab = pipeline.default_paths(BASE)
    if os.path.exists(ledger) and os.path.isdir(lab):
        return run(verbose=True)
    return smoke()


if __name__ == "__main__":
    ok, _ = auto()
    raise SystemExit(0 if ok else 1)

# -*- coding: utf-8 -*-
"""核心流程：扫化验结果 → 归档 → 判重 → 生成写入计划。

CLI 和 GUI 都调这里，业务逻辑不写在界面里。
"""
from __future__ import annotations

import os
import time
from collections import Counter
from dataclasses import dataclass, field

from . import backup, dedup, reader_lab, reader_ledger, router, writer
from .reader_lab import LabRecord


@dataclass
class CrossHit:
    decision: router.Decision
    sheets: set[str]


@dataclass
class Skipped:
    decision: router.Decision
    reason: str


@dataclass
class Analysis:
    ledger_path: str
    lab_dir: str
    ledger: reader_ledger.Ledger
    scan: reader_lab.LabScan
    decisions: list[router.Decision] = field(default_factory=list)
    plans: list[writer.WritePlan] = field(default_factory=list)
    staged: list[router.Decision] = field(default_factory=list)
    crossed: list[CrossHit] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    duplicate_in_batch: dict[str, int] = field(default_factory=dict)
    elapsed: float = 0.0

    @property
    def by_target(self) -> Counter:
        return Counter(d.label for d in self.decisions)

    @property
    def total(self) -> int:
        return len(self.decisions)

    @property
    def staging_count(self) -> int:
        return len(self.staged)

    @property
    def cross_count(self) -> int:
        return len(self.crossed)

    @property
    def staging_total(self) -> int:
        """台账里暂存表当前有多少条待处理（写盘前的老数）。"""
        info = self.ledger.staging_sheet
        return info.ana_count if info else 0


def _noop(_msg: str) -> None:
    pass


def analyze(ledger_path: str, lab_dir: str,
            rules: dict | None = None,
            on_progress=_noop) -> Analysis:
    """只读分析，不碰台账。

    判重口径（两种，别搞混）：

    * **业务表**：按「目标表内是否已有」判。台账别处有、目标表没有的记录**照写**
      （现场确实存在同一编号按不同口径双登记，实测 11 条）。
    * **暂存表**：按「台账全局是否已有」判。位置判不出来、但编号台账里已经登记的，
      再塞进暂存表只是垃圾，直接跳过（实测 15 条，编号其实都在「原矿堆场山顶运矿样」里）。
    """
    t0 = time.time()

    on_progress("读取样品台账 …")
    ledger = reader_ledger.read_ledger(ledger_path)

    on_progress("扫描化验结果 …")
    scan = reader_lab.scan_dir(lab_dir)

    # 同一编号在多个文件里出现 → 取修改时间最新的那份
    counts = Counter(r.ana for r in scan.records)
    repeated = {a: n for a, n in counts.items() if n > 1}
    latest: dict[str, LabRecord] = {}
    for rec in scan.records:
        old = latest.get(rec.ana)
        if old is None or rec.mtime > old.mtime:
            latest[rec.ana] = rec

    rules = rules or router.load_rules()
    on_progress(f"归档 {len(latest)} 条 …")
    decisions = router.route_all(sorted(latest.values(),
                                        key=lambda r: writer.natural_key(r.ana)),
                                 ledger, rules)

    result = Analysis(ledger_path=ledger_path, lab_dir=lab_dir,
                      ledger=ledger, scan=scan, duplicate_in_batch=repeated)

    for dec in decisions:
        if dec.staging:
            # 暂存表：编号只要在台账任何一张表出现过，就不再重复登记
            if dec.rec.ana in ledger.by_ana:
                exists = "、".join(sorted(ledger.by_ana[dec.rec.ana]))
                result.skipped.append(Skipped(
                    dec, f"位置未识别，但编号已在「{exists}」，不重复写入"))
                continue
            result.staged.append(dec)
            result.decisions.append(dec)
            continue

        hit = dedup.check(dec.rec.ana, dec.target, ledger)
        if hit.skip:
            result.skipped.append(Skipped(dec, hit.reason))
            continue
        if hit.cross_sheets:
            result.crossed.append(CrossHit(dec, hit.cross_sheets))
        result.decisions.append(dec)

    result.plans = writer.build_plan(result.decisions, ledger)
    result.elapsed = time.time() - t0
    return result


def apply(analysis: Analysis, base_dir: str, do_backup: bool = True,
          on_progress=_noop) -> writer.WriteResult:
    """真正写盘：先备份，再写，再自检。"""
    ledger_path = analysis.ledger_path

    if backup.is_locked(ledger_path):
        raise RuntimeError("台账正被 Excel 打开（检测到 ~$ 锁文件），请先关闭再运行。")
    if not analysis.decisions:
        return writer.WriteResult()

    bak = ""
    if do_backup:
        on_progress("备份台账 …")
        bak = backup.make_backup(ledger_path, base_dir)
        backup.prune(backup.backup_dir(base_dir))

    on_progress(f"写入 {len(analysis.decisions)} 条 …")
    result = writer.apply_plan(ledger_path, analysis.ledger, analysis.plans, bak)

    problems = writer.verify(ledger_path, result.written)
    if problems:
        raise RuntimeError("写后自检未通过：" + "；".join(problems))
    return result


def default_paths(base_dir: str) -> tuple[str, str]:
    """没有配置时的默认路径（训练材料那套）。"""
    root = os.path.dirname(base_dir)
    return (os.path.join(root, "训练材料", "上库采矿厂2026-样品台账.xlsx"),
            os.path.join(root, "训练材料", "化验结果"))

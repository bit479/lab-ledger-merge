# -*- coding: utf-8 -*-
"""化验数据台账并入工具 · 命令行入口

用法：
    python cli.py                           # 预演：扫一遍出清单，不动任何文件
    python cli.py --apply                   # 真写（先备份）
    python cli.py --profile                 # 额外导出 config/sheet_profile.json
    python cli.py --ledger X.xlsx --lab Y   # 临时指定路径
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from core import reader_ledger, router, settings as cfg_mod, writer  # noqa: E402
from core import pipeline  # noqa: E402
from core.reader_ledger import STAGING_SHEET  # noqa: E402

OUT_DIR = os.path.join(BASE, "_out")


def parse_args(argv=None):
    d_ledger, d_lab = pipeline.default_paths(BASE)
    saved = cfg_mod.load(d_ledger, d_lab)

    p = argparse.ArgumentParser(description="化验结果 → 样品台账 自动归档")
    p.add_argument("--ledger", default=saved.get("ledger") or d_ledger, help="样品台账 xlsx 路径")
    p.add_argument("--lab", default=saved.get("lab_dir") or d_lab, help="化验结果目录")
    p.add_argument("--profile", action="store_true", help="导出 sheet_profile.json")
    p.add_argument("--apply", action="store_true",
                   help="真正写入台账（默认只预演，一个字节都不写）")
    p.add_argument("--no-backup", action="store_true", help="写入前不备份（不建议）")
    p.add_argument("--quiet", action="store_true", help="少打日志")
    return p.parse_args(argv)


def _log(msg: str, quiet: bool = False):
    if not quiet:
        print(msg, flush=True)


def _fmt_grade(v) -> str:
    """品位按 4 位小数显示（台账原始数据就是 4 位；浮点尾巴 1.0731000000000002 不给人看）。"""
    if v is None:
        return ""
    s = f"{float(v):.4f}".rstrip("0").rstrip(".")
    return s or "0"


def write_reports(analysis: pipeline.Analysis, stamp: str) -> tuple[str, str]:
    """出 CSV 明细 + MD 摘要，返回两个路径。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    csv_path = os.path.join(OUT_DIR, f"归档建议_{stamp}.csv")
    md_path = os.path.join(OUT_DIR, f"归档摘要_{stamp}.md")

    cross_map = {id(c.decision): c.sheets for c in analysis.crossed}

    fields = ["文件", "分析编号", "送样编号", "品位", "取样位置",
              "判定表", "依据", "置信度", "建议目标表", "跨表已存在", "备注"]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for dec in analysis.decisions:
            w.writerow({
                "文件": dec.rec.source_file,
                "分析编号": dec.rec.ana,
                "送样编号": dec.rec.sample_no,
                "品位": _fmt_grade(dec.rec.grade),
                "取样位置": dec.rec.location,
                "判定表": dec.label,
                "依据": dec.reason,
                "置信度": dec.confidence,
                "建议目标表": dec.suggestion,
                "跨表已存在": "、".join(sorted(cross_map.get(id(dec), set()))),
                "备注": " / ".join(dec.notes),
            })

    led = analysis.ledger
    scan = analysis.scan
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(f"# 归档预演摘要 {datetime.now():%Y-%m-%d %H:%M}\n\n")
        fh.write(f"- 台账：`{analysis.ledger_path}`\n- 化验结果：`{analysis.lab_dir}`\n")
        fh.write(f"- 台账 {len(led.sheets)} 张表 / {led.total_ana:,} 个分析编号\n")
        fh.write(f"- 化验 {scan.file_count} 个文件 / {len(scan.records):,} 条；"
                 f"待写入 **{analysis.total}** 条\n")
        if analysis.skipped:
            fh.write(f"- 跳过 {len(analysis.skipped)} 条（编号已在台账，未重复写入）\n")
        if analysis.crossed:
            fh.write(f"- 其中 {len(analysis.crossed)} 条编号在台账**别的表**里出现过（照写，见下）\n")

        fh.write("\n## 按目标表汇总\n\n| 目标表 | 条数 | 依据 |\n|---|---|---|\n")
        groups = defaultdict(list)
        for dec in analysis.decisions:
            groups[dec.label].append(dec)
        for name, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            reasons = Counter(d.reason.split("（")[0] for d in items)
            fh.write(f"| {name} | {len(items)} | "
                     f"{'；'.join(f'{k}×{v}' for k, v in reasons.most_common())} |\n")

        # 核对清单：同一位置只判一次，看这节最省事
        fh.write("\n## 按位置核对（同一位置只判一次，逐行核对这一节就够）\n\n")
        fh.write("| 取样位置 | 条数 | 判定表 | 依据 | 置信 |\n|---|---|---|---|---|\n")
        by_loc = defaultdict(list)
        for dec in analysis.decisions:
            by_loc[(dec.rec.location, dec.label, dec.reason, dec.confidence)].append(dec)
        for (loc, name, reason, conf), items in sorted(by_loc.items(), key=lambda kv: -len(kv[1])):
            fh.write(f"| {loc or '（空）'} | {len(items)} | {name} | {reason} | {conf} |\n")

        if analysis.staged:
            fh.write(f"\n## 暂存表（{len(analysis.staged)} 条，需要人工定表）\n\n")
            fh.write("| 分析编号 | 送样编号 | 品位 | 取样位置 | 建议 |\n|---|---|---|---|---|\n")
            for dec in analysis.staged:
                fh.write(f"| {dec.rec.ana} | {dec.rec.sample_no} | "
                         f"{_fmt_grade(dec.rec.grade)} | {dec.rec.location or '（空）'} | "
                         f"{dec.suggestion or '—'} |\n")

        if analysis.crossed:
            fh.write(f"\n## 跨表已存在（{len(analysis.crossed)} 条，照写但需留意）\n\n")
            fh.write("| 分析编号 | 判定表 | 台账里已存在于 |\n|---|---|---|\n")
            for c in analysis.crossed:
                fh.write(f"| {c.decision.rec.ana} | {c.decision.label} | "
                         f"{'、'.join(sorted(c.sheets))} |\n")

        if analysis.skipped:
            fh.write(f"\n## 跳过（{len(analysis.skipped)} 条）\n\n")
            fh.write("| 分析编号 | 送样编号 | 原因 |\n|---|---|---|\n")
            for sk in analysis.skipped:
                fh.write(f"| {sk.decision.rec.ana} | {sk.decision.rec.sample_no} | {sk.reason} |\n")

    return csv_path, md_path


def main(argv=None) -> int:
    args = parse_args(argv)
    t0 = time.time()
    quiet = args.quiet

    if not os.path.exists(args.ledger):
        print(f"✗ 台账不存在：{args.ledger}")
        return 2
    if not os.path.isdir(args.lab):
        print(f"✗ 化验结果目录不存在：{args.lab}")
        return 2

    # 首次运行落地一份默认规则
    if not os.path.exists(router.RULES_PATH):
        router.save_rules(router.DEFAULT_RULES)
        _log(f"已生成默认规则：{router.RULES_PATH}", quiet)

    _log("读取样品台账 …", quiet)
    try:
        analysis = pipeline.analyze(
            args.ledger, args.lab,
            on_progress=lambda m: _log("  " + m, quiet))
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 分析失败：{type(exc).__name__}: {exc}")
        return 2

    led, scan = analysis.ledger, analysis.scan
    _log(f"  {len(led.sheets)} 张表 / {led.total_ana:,} 个分析编号 / "
         f"学到 {len(led.vote):,} 种位置写法  （{analysis.elapsed:.1f}s）", quiet)
    usable = router.usable_sheet_names(led, router.load_rules())
    _log(f"  可自动写入的表 {len(usable)} 张", quiet)
    for note in led.notes:
        _log(f"  · {note}", quiet)

    if args.profile:
        import json
        rules = router.load_rules()
        path = os.path.join(BASE, "config", "sheet_profile.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(reader_ledger.profile_dict(led, set(rules.get("excluded_sheets") or [])),
                      fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        _log(f"  列标定已导出：{path}", quiet)

    _log("", quiet)
    _log(f"化验结果 {scan.file_count} 个文件 / {len(scan.records):,} 条记录", quiet)
    for sk in scan.skipped:
        _log(f"  ⊘ 跳过 {os.path.basename(sk.path)}：{sk.reason[:70]}", quiet)

    _log("", quiet)
    _log(f"待写入 {analysis.total} 条", quiet)
    for name, n in analysis.by_target.most_common():
        flag = "（暂存）" if name == STAGING_SHEET else ""
        _log(f"  {n:4d}  →  {name}{flag}", quiet)
    if analysis.skipped:
        _log(f"   跳过 {len(analysis.skipped)} 条（编号已在台账，不重复写入）", quiet)
    if analysis.crossed:
        _log(f"   其中 {len(analysis.crossed)} 条在台账别的表里也出现过（照写，日志已标）", quiet)
    if analysis.duplicate_in_batch:
        _log(f"   ⚠ {len(analysis.duplicate_in_batch)} 个编号在多份文件里重复，已取最新一份", quiet)

    stamp = datetime.now().strftime("%m%d-%H%M")
    csv_path, md_path = write_reports(analysis, stamp)
    _log("", quiet)
    _log(f"明细清单：{csv_path}", quiet)
    _log(f"摘要报告：{md_path}", quiet)

    if not args.apply:
        _log("", quiet)
        _log(f"完成，共 {time.time() - t0:.1f}s"
             f"（预演，台账未改动；加 --apply 才写入）", quiet)
        return 0

    if not analysis.decisions:
        _log("", quiet)
        _log("没有需要写入的记录，跳过。", quiet)
        return 0

    _log("", quiet)
    _log("开始写入台账 …", quiet)
    try:
        result = pipeline.apply(analysis, OUT_DIR, do_backup=not args.no_backup,
                                on_progress=lambda m: _log("  " + m, quiet))
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 写入失败：{type(exc).__name__}: {exc}")
        return 3

    _log(f"  写入 {result.total} 条：{result.summary()}", quiet)
    if result.staging_created:
        _log(f"  已新建「{STAGING_SHEET}」暂存表", quiet)
    if result.backup_path:
        _log(f"  备份 → {result.backup_path}", quiet)
    _log(f"  写后自检通过，耗时 {result.elapsed:.1f}s", quiet)
    _log("", quiet)
    _log(f"完成，共 {time.time() - t0:.1f}s（已写入台账）", quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

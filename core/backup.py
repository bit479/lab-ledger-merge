# -*- coding: utf-8 -*-
"""备份与轮转。

生产数据不可重来（34,649 条），所以每次写盘前必须留一份可回退的副本。
命名沿用现场习惯：`<原名>_并入<MMDD-HHmm>.bak.xlsx`。
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime

KEEP = 10
BACKUP_DIRNAME = "backup"


def backup_dir(base_dir: str) -> str:
    path = os.path.join(base_dir, BACKUP_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


def make_backup(ledger_path: str, base_dir: str, tag: str | None = None) -> str:
    """复制一份备份，返回备份文件路径。"""
    folder = backup_dir(base_dir)
    stem, ext = os.path.splitext(os.path.basename(ledger_path))
    stamp = tag or datetime.now().strftime("%m%d-%H%M")
    dst = os.path.join(folder, f"{stem}_并入{stamp}.bak{ext}")

    # 同一分钟内重复写，序号递增而不是覆盖
    n = 2
    while os.path.exists(dst):
        dst = os.path.join(folder, f"{stem}_并入{stamp}-{n}.bak{ext}")
        n += 1

    shutil.copy2(ledger_path, dst)
    return dst


def prune(folder: str, keep: int = KEEP) -> list[str]:
    """只保留最近 keep 份备份，返回被删掉的文件。"""
    if not os.path.isdir(folder):
        return []
    files = [
        os.path.join(folder, n) for n in os.listdir(folder)
        if ".bak" in n and os.path.isfile(os.path.join(folder, n))
    ]
    files.sort(key=os.path.getmtime, reverse=True)
    removed = []
    for path in files[keep:]:
        try:
            os.remove(path)
            removed.append(path)
        except OSError:
            pass
    return removed


def is_locked(ledger_path: str) -> bool:
    """Excel 打开文件时会在同目录建 `~$<name>` 锁文件。"""
    folder = os.path.dirname(ledger_path)
    name = os.path.basename(ledger_path)
    return os.path.exists(os.path.join(folder, f"~${name}"))

# -*- coding: utf-8 -*-
"""记住上次用的两个目录（计划书第五章第 5 条）。

存 `%LOCALAPPDATA%\\lab-ledger-merge\\settings.json`，不写进程序目录，
这样换机器/升级 exe 都不会丢。
"""
from __future__ import annotations

import json
import os

APP_NAME = "lab-ledger-merge"


def settings_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME, "settings.json")


def load(default_ledger: str = "", default_lab: str = "") -> dict:
    data = {
        "ledger": default_ledger,
        "lab_dir": default_lab,
        "one_click": False,
        "geometry": "",
    }
    path = settings_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                data.update({k: v for k, v in stored.items() if k in data})
        except (OSError, json.JSONDecodeError):
            pass
    return data


def save(data: dict) -> None:
    path = settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except OSError:
        pass

# -*- coding: utf-8 -*-
"""打包成单文件 exe。

    python _build/build_exe.py

产出 `dist/化验数据并入台账.exe`，双击即开；带 `--selftest` 时不开窗口，
跑一遍自检并写 `selftest.log`（远程验包就靠这一条）。

⚠ 必须用带 tkinter 的解释器打包 —— managed 的 `envs/default` 没有 tkinter，
   用 `envs/gui`（3.13.x / tk 8.6）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="pyi_lab_")
NAME = "化验数据并入台账"
BUILD = os.path.join(BASE, "_build")
DIST = os.path.join(BASE, "dist")

EXCLUDES = [
    "numpy", "pandas", "matplotlib", "PIL", "scipy", "IPython",
    "pytest", "setuptools", "pip", "wheel",
    "PyQt5", "PySide2", "PySide6", "wx",
]


def main() -> int:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("✗ 当前解释器没有 tkinter，换 envs/gui 那个：")
        print(r"   C:\Users\Administrator\.workbuddy\binaries\python\envs\gui\Scripts\python.exe")
        return 2

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile", "--windowed",
        "--name", NAME,
        # 也输出到临时目录：PyInstaller 会先删同名旧 exe，本机安全策略会拦删除
        "--distpath", os.path.join(WORK, "dist"),
        # 每次用全新临时 work 目录：PyInstaller 会先删旧产物，本机安全策略会拦截删除
        "--workpath", WORK,
        "--specpath", WORK,
        # 自检要 import tests/ 里的模块
        "--add-data", f"{os.path.join(BASE, 'tests')};tests",
        # 自检是运行时 import，静态分析看不到，要显式带上
        "--hidden-import", "unittest",
        "--hidden-import", "unittest.loader",
        "--hidden-import", "unittest.runner",
    ]
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]
    icon = os.path.join(BASE, "_build", "app.ico")
    if os.path.exists(icon):
        args += ["--icon", icon]
    args.append(os.path.join(BASE, "main.py"))

    print("打包中 …（首次约 1~2 分钟）")
    done = subprocess.run(args, cwd=BASE)
    if done.returncode != 0:
        print("✗ 打包失败")
        return done.returncode

    built = os.path.join(WORK, "dist", f"{NAME}.exe")
    os.makedirs(DIST, exist_ok=True)
    exe = os.path.join(DIST, f"{NAME}.exe")
    shutil.copy2(built, exe)   # 覆盖写，不删旧文件
    if not os.path.exists(exe):
        print("✗ 没找到产物：", exe)
        return 3

    size = os.path.getsize(exe) / 1048576
    print(f"\n✓ {exe}  ({size:.1f} MB)")

    md5 = hashlib_md5(exe)
    print(f"  MD5 {md5}")
    return 0


def hashlib_md5(path: str) -> str:
    import hashlib

    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())

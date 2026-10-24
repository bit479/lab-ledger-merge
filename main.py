# -*- coding: utf-8 -*-
"""化验数据并入样品台账 · 图形界面（双击即开）

一屏两按钮：更新数据（预演，不写盘）→ 确认写入台账（写盘 + 备份）。
勾了「一键直写」则「更新数据」一路走到底。
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from collections import Counter
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

# 打包成 exe 后 __file__ 在 PyInstaller 的解压临时目录里，_out / config 写在那儿会随进程消失。
# 所以拆两个路径：可写的用 exe 所在目录，只读资源（tests）用解压目录。
FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
BASE = APP_DIR
sys.path.insert(0, RES_DIR)
sys.path.insert(0, APP_DIR)

from core import pipeline, router, settings, writer  # noqa: E402
from core.reader_ledger import STAGING_SHEET  # noqa: E402

# 规则文件必须落在可写目录，否则现场改不动
router.RULES_PATH = os.path.join(APP_DIR, "config", "rules.json")

OUT_DIR = os.path.join(APP_DIR, "_out")
APP_TITLE = "化验数据并入样品台账  v1.0"
FONT = ("Microsoft YaHei", 9)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(860, 620)

        d_ledger, d_lab = pipeline.default_paths(BASE)
        self.cfg = settings.load(d_ledger, d_lab)
        self.analysis: pipeline.Analysis | None = None
        self.busy = False
        self.queue: queue.Queue = queue.Queue()

        self._build()
        if self.cfg.get("geometry"):
            try:
                self.geometry(self.cfg["geometry"])
            except tk.TclError:
                pass
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll()

    # ---------------- 界面 ----------------
    def _build(self):
        pad = dict(padx=8, pady=4)

        top = ttk.LabelFrame(self, text="路径")
        top.pack(fill="x", **pad)
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="样品台账", font=FONT).grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.var_ledger = tk.StringVar(value=self.cfg.get("ledger", ""))
        ttk.Entry(top, textvariable=self.var_ledger, font=FONT).grid(row=0, column=1, sticky="ew")
        ttk.Button(top, text="浏览…", width=8, command=self._pick_ledger).grid(row=0, column=2, padx=6)

        ttk.Label(top, text="化验结果", font=FONT).grid(row=1, column=0, sticky="w", padx=6, pady=6)
        self.var_lab = tk.StringVar(value=self.cfg.get("lab_dir", ""))
        ttk.Entry(top, textvariable=self.var_lab, font=FONT).grid(row=1, column=1, sticky="ew")
        ttk.Button(top, text="浏览…", width=8, command=self._pick_lab).grid(row=1, column=2, padx=6)

        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        self.var_one_click = tk.BooleanVar(value=bool(self.cfg.get("one_click")))
        ttk.Checkbutton(bar, text="一键直写（跳过预览，仍会先备份）",
                        variable=self.var_one_click).pack(side="left", padx=6)
        self.btn_run = ttk.Button(bar, text="更 新 数 据", width=20, command=self._on_run)
        self.btn_run.pack(side="right", padx=4)
        self.btn_apply = ttk.Button(bar, text="确认写入台账", width=16,
                                    command=self._on_apply, state="disabled")
        self.btn_apply.pack(side="right", padx=4)

        self.lbl_status = ttk.Label(self, text="就绪", font=FONT, anchor="w")
        self.lbl_status.pack(fill="x", padx=14)

        mid = ttk.LabelFrame(self, text="扫描结果（双击某行看明细清单路径）")
        mid.pack(fill="both", expand=True, **pad)
        cols = ("sheet", "count", "reason")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=8)
        for key, text, width in (("sheet", "目标表", 260), ("count", "条数", 70), ("reason", "依据", 380)):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor="w" if key != "count" else "center")
        self.tree.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.tag_configure("staging", foreground="#b35c00")

        logf = ttk.LabelFrame(self, text="日志")
        logf.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(logf, height=10, font=FONT, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, side="left")
        lsb = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        lsb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=lsb.set)

    # ---------------- 交互 ----------------
    def _pick_ledger(self):
        path = filedialog.askopenfilename(
            title="选择样品台账", filetypes=[("Excel", "*.xlsx *.xlsm"), ("全部", "*.*")])
        if path:
            self.var_ledger.set(path)

    def _pick_lab(self):
        path = filedialog.askdirectory(title="选择化验结果目录")
        if path:
            self.var_lab.set(path)

    def _write_log(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, msg: str):
        self.lbl_status.configure(text=msg)

    def _set_busy(self, busy: bool):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.btn_run.configure(state=state)
        if busy:
            self.btn_apply.configure(state="disabled")
        self.configure(cursor="watch" if busy else "")

    def _on_run(self):
        if self.busy:
            return
        ledger = self.var_ledger.get().strip()
        lab = self.var_lab.get().strip()
        if not os.path.exists(ledger):
            messagebox.showerror("路径不对", f"台账不存在：\n{ledger}")
            return
        if not os.path.isdir(lab):
            messagebox.showerror("路径不对", f"化验结果目录不存在：\n{lab}")
            return

        self.tree.delete(*self.tree.get_children())
        self._set_busy(True)
        self._set_status("正在分析 …")
        direct = self.var_one_click.get()

        def work():
            try:
                def progress(msg):
                    self.queue.put(("log", msg))

                analysis = pipeline.analyze(ledger, lab, on_progress=progress)
                self.queue.put(("analysis", analysis))
                if direct:
                    self.queue.put(("log", ""))
                    self.queue.put(("log", "一键直写已开启，直接写入 …"))
                    result = pipeline.apply(analysis, OUT_DIR,
                                            on_progress=lambda m: self.queue.put(("log", "  " + m)))
                    self.queue.put(("applied", (result, analysis)))
                else:
                    self.queue.put(("done", None))
            except Exception as exc:  # noqa: BLE001 - 界面不能因为异常就卡死
                self.queue.put(("error", f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def _on_apply(self):
        if self.busy or not self.analysis:
            return
        analysis = self.analysis
        if not analysis.decisions:
            messagebox.showinfo("没有新数据", "化验结果里没有未并入的记录。")
            return
        n = len(analysis.decisions)
        staged = analysis.staging_count
        tail = f"\n其中 {staged} 条判不出归属，会写进「{STAGING_SHEET}」暂存表。" if staged else ""
        if not messagebox.askyesno(
                "确认写入",
                f"将向台账追加 {n} 条记录。{tail}\n\n写入前会自动备份，是否继续？"):
            return

        self._set_busy(True)
        self._set_status("正在写入 …")

        def work():
            try:
                result = pipeline.apply(
                    analysis, OUT_DIR,
                    on_progress=lambda m: self.queue.put(("log", "  " + m)))
                self.queue.put(("applied", (result, analysis)))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    # ---------------- 队列轮询 ----------------
    def _poll(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._write_log(payload)
                elif kind == "analysis":
                    self._show_analysis(payload)
                elif kind == "applied":
                    self._show_applied(*payload)
                elif kind == "done":
                    self._set_busy(False)
                    self._set_status("预演完成，台账未改动。确认无误后点「确认写入台账」。")
                elif kind == "error":
                    self._set_busy(False)
                    self._write_log("✗ " + payload)
                    self._set_status("出错，详见日志")
                    messagebox.showerror("执行失败", payload)
        except queue.Empty:
            pass
        self.after(120, self._poll)

    # ---------------- 展示 ----------------
    def _show_analysis(self, analysis: pipeline.Analysis):
        self.analysis = analysis
        self.tree.delete(*self.tree.get_children())

        for name, count in analysis.by_target.most_common():
            reasons = Counter(d.reason.split("（")[0] for d in analysis.decisions if d.label == name)
            detail = "；".join(f"{k}×{v}" for k, v in reasons.most_common())
            tag = ("staging",) if name == STAGING_SHEET else ()
            self.tree.insert("", "end", values=(name, count, detail), tags=tag)

        scan = analysis.scan
        self._write_log("─" * 56)
        self._write_log(f"台账 {len(analysis.ledger.sheets)} 张表 / "
                        f"{analysis.ledger.total_ana:,} 个分析编号")
        self._write_log(f"化验 {scan.file_count} 个文件 / {len(scan.records):,} 条记录")
        for sk in scan.skipped:
            self._write_log(f"  ⊘ 跳过 {os.path.basename(sk.path)}：{sk.reason[:80]}")

        self._write_log("")
        self._write_log(f"待并入 {analysis.total} 条"
                        f"（自动归档 {analysis.total - analysis.staging_count}，"
                        f"暂存 {analysis.staging_count}）")
        if analysis.skipped:
            self._write_log(f"  跳过 {len(analysis.skipped)} 条（目标表里已有）")
        if analysis.crossed:
            self._write_log(f"  ⚠ {len(analysis.crossed)} 条编号在别的表里也出现过（照写，日志已标黄）")
        if analysis.duplicate_in_batch:
            self._write_log(f"  ⚠ {len(analysis.duplicate_in_batch)} 个编号在多份文件里重复，已取最新一份")

        if analysis.staged:
            self._write_log("")
            self._write_log(f"判不出归属的 {len(analysis.staged)} 条（将进「{STAGING_SHEET}」）：")
            for dec in analysis.staged[:8]:
                self._write_log(f"  {dec.rec.ana}  {dec.rec.sample_no}  "
                                f"建议：{dec.suggestion or '—'}")
            if len(analysis.staged) > 8:
                self._write_log(f"  … 其余 {len(analysis.staged) - 8} 条见清单 CSV")

        if analysis.staging_total:
            self._write_log("")
            self._write_log(f"暂存表里还有 {analysis.staging_total} 条历史待处理记录")

        self.btn_apply.configure(state="normal" if analysis.decisions else "disabled")
        self._set_busy(False)
        self._set_status(f"预演完成：待并入 {analysis.total} 条，台账未改动")

    def _show_applied(self, result: writer.WriteResult,
                      analysis: pipeline.Analysis):
        self._write_log("")
        self._write_log(f"✓ 已写入 {result.total} 条：{result.summary()}")
        if result.staging_created:
            self._write_log(f"  已新建「{STAGING_SHEET}」暂存表（放在最后）")
        if result.backup_path:
            self._write_log(f"  备份 → {result.backup_path}")
        self._write_log(f"  耗时 {result.elapsed:.1f}s，写后自检通过")
        self._write_log("  提示：台账里若有公式，Excel 打开时会自动重算一次。")

        self._set_busy(False)
        self.btn_apply.configure(state="disabled")
        self._set_status(f"已写入 {result.total} 条")
        self.analysis = None
        messagebox.showinfo("完成", f"已写入 {result.total} 条记录。\n\n备份：{result.backup_path or '（未备份）'}")

    # ---------------- 收尾 ----------------
    def _on_close(self):
        self.cfg.update({
            "ledger": self.var_ledger.get().strip(),
            "lab_dir": self.var_lab.get().strip(),
            "one_click": bool(self.var_one_click.get()),
            "geometry": self.winfo_geometry(),
        })
        settings.save(self.cfg)
        self.destroy()


def main():
    # exe 验包用：不开窗口跑自检，结果写 selftest.log
    if "--selftest" in sys.argv:
        sys.path.insert(0, os.path.join(RES_DIR, "tests"))
        import test_selftest

        ok, text = test_selftest.auto()
        with open(os.path.join(APP_DIR, "selftest.log"), "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        raise SystemExit(0 if ok else 1)

    # 首次运行落地一份默认规则，方便以后手改
    if not os.path.exists(router.RULES_PATH):
        router.save_rules(router.DEFAULT_RULES)
    os.makedirs(OUT_DIR, exist_ok=True)
    App().mainloop()


if __name__ == "__main__":
    main()

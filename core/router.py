# -*- coding: utf-8 -*-
"""归档：一条化验记录该进哪张表。

三层规则（计划书第三章）：
  第 1 层 经验投票 —— 从台账历史反推「取样位置 → 表」频次，唯一对应直接用
  第 2 层 关键词    —— 位置里没见过的新写法，靠 config/rules.json 的规则
  第 3 层 兜底      —— 判不出来就进 `未知位置待定` 暂存表，附建议，绝不硬塞业务表
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field

from .reader_lab import LabRecord
from .reader_ledger import STAGING_SHEET, Ledger

RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "config", "rules.json")

# 多义位置采用门槛
MULTI_MIN_COUNT = 3
MULTI_MIN_SHARE = 0.80

DEFAULT_RULES: dict = {
    "_comment": "关键词规则按顺序匹配，先具体后通用；命中第一条即返回。prefix 只用来给建议，不决定归属。",
    "excluded_sheets": [
        "多元素分析实验",
        "筛分矿样",
        "选厂原矿数据",
        "构造点",
    ],
    "_excluded_reason": {
        "多元素分析实验": "只有 Ag/Cu/Pb/Bi/Sb，没有 Au 单值列，并入会写错列",
        "筛分矿样": "编号是 SFYK-0524-1 形态，且 7 列结构（序号/样品编号/取样地点/取样方式/化验结果/取样时间/备注）",
        "选厂原矿数据": "分析编号是纯数字 9/10/8，不是 2026xxxxxx-n",
        "构造点": "坐标表，不是化验数据",
    },
    "location_rules": [
        {"match": ["筛分临时堆场"], "sheet": "中心矿段筛分氧化矿临时堆场"},
        {"match": ["1.0-999g/t"], "sheet": "中心矿段筛分氧化矿临时堆场"},
        {"match": ["0.5-1.0g/t", "低品位堆场"], "sheet": "中铁十九局低品位堆场样"},
        {"match": ["0.5-1.0g/t", "剥离"], "sheet": "剥离样"},
        {"match": ["爆堆"], "sheet": "爆堆样"},
        {"match": ["炮孔", "北部山头"], "sheet": "北部山头炮孔"},
        {"match": ["炮孔", "南部山头"], "sheet": "南部山头炮孔"},
        {"match": ["炮孔", "中心矿段"], "sheet": "中心矿段炮孔"},
        {"match": ["炮孔", "前山"], "sheet": "前山Ⅱ号矿体-炮孔"},
        {"match": ["溜槽"], "sheet": "1 2号溜槽样"},
        {"match": ["山顶运矿"], "sheet": "原矿堆场山顶运矿样"},
        {"match": ["原矿堆场"], "sheet": "原矿堆场山顶运矿样"},
        {"match": ["二堆场"], "sheet": "二堆场"},
        {"match": ["入堆"], "sheet": "二堆场"},
        {"match": ["排土场"], "sheet": "排土场"},
        {"match": ["地质钻孔"], "sheet": "地质钻"},
        {"match": ["岩芯"], "sheet": "地质钻"},
        {"match": ["编录"], "sheet": "编录样"},
        {"match": ["探槽"], "sheet": "编录样"},
        {"match": ["潜孔钻"], "sheet": "探矿样"},
        {"match": ["探矿"], "sheet": "探矿样"},
        {"match": ["路边矿"], "sheet": "路边矿"},
        {"match": ["倒矿"], "sheet": "倒矿样"},
        {"match": ["倒运"], "sheet": "倒矿样"},
        {"match": ["转石"], "sheet": "前山转石探矿剥离样"},
        {"match": ["1-1"], "sheet": "1-1剥离"},
        {"match": ["Ⅰ-1"], "sheet": "1-1剥离"},
        {"match": ["十道弯", "倒运"], "sheet": "十道弯倒运矿石"},
        {"match": ["五道弯"], "sheet": "五道弯、十道弯运矿样"},
        {"match": ["十道弯"], "sheet": "五道弯、十道弯运矿样"},
        {"match": ["剥离"], "sheet": "剥离样"},
    ],
    "prefix_suggestions": {
        "BS-": "北部山头炮孔",
        "NS-": "南部山头炮孔",
        "ZX-": "中心矿段炮孔",
        "LB-": "路边矿",
        "EDC-": "二堆场",
        "CRCC-": "五道弯、十道弯运矿样",
        "SFYK-": "筛分矿样",
        "ZK": "地质钻",
        "YKDC-": "原矿堆场山顶运矿样",
    },
}


@dataclass
class Decision:
    rec: LabRecord
    target: str | None = None          # 业务表名；None = 进暂存表
    reason: str = ""
    confidence: str = "low"            # high / mid / low
    suggestion: str = ""               # 进暂存表时给的建议
    notes: list[str] = field(default_factory=list)

    @property
    def staging(self) -> bool:
        return self.target is None

    @property
    def label(self) -> str:
        return self.target if self.target else STAGING_SHEET


def load_rules(path: str = RULES_PATH) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return DEFAULT_RULES


def save_rules(rules: dict, path: str = "") -> bool:
    """保存规则。目录不可写时返回 False 而不是抛异常（程序要能继续跑）。"""
    path = path or RULES_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rules, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        return True
    except OSError:
        return False


def _usable(ledger: Ledger, name: str, rules: dict | None = None) -> bool:
    """该表能不能写（有锚点、不是暂存表、不在排除名单里）。"""
    if rules and name in set(rules.get("excluded_sheets") or []):
        return False
    info = ledger.sheet(name)
    return bool(info and info.usable)


def usable_sheet_names(ledger: Ledger, rules: dict | None = None) -> list[str]:
    """给界面/日志用：真正会写的表清单。"""
    rules = rules or DEFAULT_RULES
    return [s.name for s in ledger.usable_sheets if _usable(ledger, s.name, rules)]


def _suggest_prefix(sample_no: str, rules: dict) -> str:
    """按送样编号前缀给建议。

    台账里的送样编号常带一个班次前缀（`B-YKDC-0807-LC1` 白班 / `Y-YKDC-0927-P1` 夜班），
    所以先剥掉开头的「单字母-」再匹配，否则 `YKDC-` 这种规则永远打不中。
    """
    s = (sample_no or "").upper().strip()
    if not s:
        return ""
    candidates = [s]
    m = re.match(r"^[A-Z]-(.+)$", s)
    if m:
        candidates.append(m.group(1))

    for prefix, sheet in (rules.get("prefix_suggestions") or {}).items():
        p = prefix.upper()
        for cand in candidates:
            if cand.startswith(p):
                return sheet
    return ""


def _match_keyword(location: str, rules: dict) -> tuple[str, str]:
    """返回 (命中表名, 命中的关键词串)；未命中返回 ("", "")。"""
    loc = location or ""
    for rule in rules.get("location_rules") or []:
        words = [w for w in (rule.get("match") or []) if w]
        if words and all(w in loc for w in words):
            return rule.get("sheet", ""), " + ".join(words)
    return "", ""


def route(rec: LabRecord, ledger: Ledger, rules: dict | None = None) -> Decision:
    rules = rules or DEFAULT_RULES
    dec = Decision(rec=rec)
    loc = rec.location or ""

    # ---------- 第 1 层：经验投票 ----------
    votes = ledger.vote.get(loc) if loc else None
    if votes:
        pool = {s: n for s, n in votes.items() if _usable(ledger, s, rules)}
        if pool:
            total = sum(votes.values())
            if len(pool) == 1:
                sheet, n = next(iter(pool.items()))
                dec.target = sheet
                dec.reason = f"位置唯一对应（历史 {n} 次）"
                dec.confidence = "high"
                return dec

            sheet, n = max(pool.items(), key=lambda kv: kv[1])
            share = n / total
            if share >= MULTI_MIN_SHARE and total >= MULTI_MIN_COUNT:
                dec.target = sheet
                dec.reason = f"多义按主频（{n}/{total} = {share:.0%}）"
                dec.confidence = "mid"
                dec.notes.append("该位置历史上分散在多张表，建议抽查")
                others = "、".join(f"{s}({c})" for s, c in
                                   sorted(votes.items(), key=lambda kv: -kv[1])[1:4])
                dec.notes.append(f"其它落点：{others}")
                return dec
            dec.notes.append(f"位置多义且无明显主频（{n}/{total} = {share:.0%}）")

    # ---------- 第 2 层：关键词规则 ----------
    sheet, hit = _match_keyword(loc, rules)
    if sheet and _usable(ledger, sheet, rules):
        dec.target = sheet
        dec.reason = f"关键词「{hit}」"
        dec.confidence = "mid"
        return dec
    if sheet and not _usable(ledger, sheet, rules):
        dec.notes.append(f"关键词命中「{sheet}」，但该表不可写入")

    # ---------- 第 3 层：兜底进暂存表 ----------
    by_prefix = _suggest_prefix(rec.sample_no, rules)
    by_vote = ""
    if votes:
        pool = {s: n for s, n in votes.items() if _usable(ledger, s, rules)}
        if pool:
            by_vote = max(pool.items(), key=lambda kv: kv[1])[0]

    if by_prefix and by_vote and by_prefix != by_vote:
        dec.suggestion = f"{by_prefix}（送样编号前缀）/ {by_vote}（历史位置）"
    elif by_prefix:
        dec.suggestion = by_prefix
    elif by_vote:
        dec.suggestion = f"{by_vote}（历史位置）"

    if not loc:
        dec.reason = "取样位置为空"
    elif not votes:
        dec.reason = "位置写法在台账里从未出现过"
    else:
        dec.reason = "位置多义且无主频"

    dec.confidence = "low"
    return dec


def route_all(records: list[LabRecord], ledger: Ledger,
              rules: dict | None = None) -> list[Decision]:
    rules = rules or DEFAULT_RULES
    cache: dict[str, Decision] = {}
    out: list[Decision] = []
    for rec in records:
        cached = cache.get(rec.location)
        if cached is not None and cached.target and cached.confidence != "low":
            # 同一位置判过一次就直接复用结论（省掉重复计算）
            out.append(Decision(rec=rec, target=cached.target, reason=cached.reason,
                                confidence=cached.confidence, notes=list(cached.notes)))
            continue
        dec = route(rec, ledger, rules)
        if dec.target and dec.confidence != "low":
            cache[rec.location] = dec
        out.append(dec)
    return out

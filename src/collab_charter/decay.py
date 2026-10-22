"""条款折旧（Charter Decay）：为宪章条款登记「退休条件」并报告折旧状态。

定位
----
项目里所有子系统都在回答「如何让 AI 守规矩」；本模块回答相反的问题——
「哪条规矩已经可以不再需要」。它是「自我删除」这条主张的可执行仪器：
条款不是只增不减的资产，而是有半衰期的负债。

边界（诚实声明）
----------------
* 本模块只读：不修改 charter.yaml，不删除任何条款。
* ``status`` 目前由人工登记（active / candidate / retired / permanent），
  不是自动判定——自动判定需要结构化的 expiry 谓词，属于下一里程碑。
* 断链即错：登记表里的 id 必须存在于宪章；不存在的 id 视为错误而非忽略。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from .charter_loader import Charter

#: 登记表状态全集。顺序即报告中的展示顺序。
STATUSES: tuple[str, ...] = ("active", "candidate", "retired", "permanent")

#: 状态的中文标签（报告用）。
STATUS_LABELS: dict[str, str] = {
    "active": "服役",
    "candidate": "候补",
    "retired": "可退休",
    "permanent": "永不退休",
}

#: 登记表默认位置：源码树仓库根 / charter / expiry.yaml。
DEFAULT_EXPIRY = Path(__file__).resolve().parents[2] / "charter" / "expiry.yaml"


class DecayError(ValueError):
    """登记表不合法（断链 / 重复 / 状态非法 / 条件为空）。"""


@dataclass(frozen=True)
class ExpiryEntry:
    """一条条款的退休条件登记。"""

    id: str
    expiry_test: str
    status: str = "active"
    note: str | None = None

    @property
    def label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "expiry_test": self.expiry_test,
            "status": self.status,
            "label": self.label,
            "note": self.note,
        }


@dataclass
class DecayReport:
    """一次折旧盘点。"""

    entries: list[ExpiryEntry]
    clause_total: int
    source: str = ""

    def counts(self) -> dict[str, int]:
        """按状态的计数；未出现的状态也补 0，保证结构稳定。"""
        out = {s: 0 for s in STATUSES}
        for e in self.entries:
            out[e.status] = out.get(e.status, 0) + 1
        return out

    @property
    def coverage(self) -> float:
        """登记覆盖率：已写退休条件的条款 / 全部条款。0.0–1.0。"""
        if self.clause_total <= 0:
            return 0.0
        return len(self.entries) / self.clause_total

    def by_status(self, status: str) -> list[ExpiryEntry]:
        return [e for e in self.entries if e.status == status]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "clause_total": self.clause_total,
            "registered": len(self.entries),
            "coverage": round(self.coverage, 4),
            "counts": self.counts(),
            "entries": [e.to_dict() for e in self.entries],
        }

    def render(self) -> str:
        """三列文本报告：条款 / 退休条件 / 当前状态。"""
        counts = self.counts()
        lines = [
            f"折旧登记表：{self.source}",
            f"条款总数 {self.clause_total} · 已登记 {len(self.entries)}"
            f" · 覆盖率 {self.coverage:.0%}",
            "状态：" + " / ".join(f"{STATUS_LABELS[s]} {counts[s]}" for s in STATUSES),
            "",
        ]
        id_w = max([len(e.id) for e in self.entries] + [4])
        label_w = max(_width(STATUS_LABELS[s]) for s in STATUSES)
        for e in self.entries:
            label = STATUS_LABELS.get(e.status, e.status)
            lines.append(
                f"{e.id.ljust(id_w)}  {_pad(label, label_w)}  {e.expiry_test}"
            )
        return "\n".join(lines)


def _width(text: str) -> int:
    """近似显示宽度：CJK 字符按 2 计。"""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def load_expiry(
    path: str | Path | None = None,
    charter: Charter | None = None,
) -> DecayReport:
    """加载并校验退休条件登记表。

    Raises:
        DecayError: 文件缺失、结构错误、断链 id、重复 id、非法状态、
            空退休条件。
    """
    p = Path(path) if path is not None else DEFAULT_EXPIRY
    if not p.exists():
        raise DecayError(f"登记表不存在：{p}")

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - YAML 语法错误
        raise DecayError(f"登记表 YAML 解析失败：{exc}") from exc

    if not isinstance(raw, dict):
        raise DecayError("登记表顶层必须是映射（meta / entries）")

    rows = raw.get("entries")
    if not isinstance(rows, list) or not rows:
        raise DecayError("登记表缺少非空的 entries 列表")

    charter = charter or Charter.load()
    known = set(charter.clauses)

    entries: list[ExpiryEntry] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise DecayError(f"第 {index} 条登记不是映射")
        cid = str(row.get("id", "")).strip()
        test = str(row.get("expiry_test", "")).strip()
        status = str(row.get("status", "active")).strip()
        note = row.get("note")
        note = str(note).strip() if note is not None else None

        if not cid:
            raise DecayError(f"第 {index} 条登记缺少 id")
        if cid not in known:
            raise DecayError(f"断链：条款 {cid} 不存在于宪章（登记表第 {index} 条）")
        if cid in seen:
            raise DecayError(f"重复登记：条款 {cid}")
        if not test:
            raise DecayError(f"条款 {cid} 的退休条件为空——写不出条件就不该登记")
        if status not in STATUSES:
            raise DecayError(
                f"条款 {cid} 的状态非法：{status!r}（应为 {'/'.join(STATUSES)}）"
            )

        seen.add(cid)
        entries.append(ExpiryEntry(id=cid, expiry_test=test, status=status, note=note))

    return DecayReport(entries=entries, clause_total=len(charter.clauses), source=str(p))

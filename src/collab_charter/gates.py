"""安全闸门：路由管线第 1 站（0.3 第 1 站 + 第十章）。

裁决表不写在代码里，而是从 ``charter.yaml`` 的 ``enforcement.gate_matrix``
读入——保证「改宪章即改行为」，代码只是执行者。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .charter_loader import Charter, CharterError
from .flows import Flow, Permission, Sensitivity


class Verdict(str, Enum):
    """闸门裁决的五种终态。"""

    ALLOW = "allow"                # 常规放行
    STRIP = "strip"                # 剥离敏感部分后放行
    ALLOW_INTERNAL = "allow_internal"  # 放行但仅限内部，不得进入输出流
    CONFIRM = "confirm"            # 需用户显式确认后放行
    BLOCK = "block"                # 不过闸，后续全部终止

    def __str__(self) -> str:  # pragma: no cover
        return str(self.value)


_ZH = {
    Verdict.ALLOW: "放行",
    Verdict.STRIP: "剥离后放行",
    Verdict.ALLOW_INTERNAL: "仅内部放行",
    Verdict.CONFIRM: "待用户确认",
    Verdict.BLOCK: "拦截",
}

#: 可继续走完管线的裁决
_PASSING = {Verdict.ALLOW, Verdict.STRIP, Verdict.ALLOW_INTERNAL}


@dataclass(frozen=True)
class GateDecision:
    """闸门对单条流的裁决结果。"""

    flow_id: str
    verdict: Verdict
    reason: str
    clause: str

    @property
    def passed(self) -> bool:
        """是否允许继续走第 2–8 站。"""
        return self.verdict in _PASSING

    @property
    def terminates(self) -> bool:
        """0.3-I3：不过闸则第 2–8 站一律不执行。"""
        return self.verdict is Verdict.BLOCK

    @property
    def needs_user_input(self) -> bool:
        return self.verdict is Verdict.CONFIRM

    @property
    def verdict_zh(self) -> str:
        return _ZH[self.verdict]

    def explain(self) -> str:
        """按第十章「解释 + 替代」语义生成面向用户的说明。"""
        if self.verdict is Verdict.BLOCK:
            return (
                f"该内容被拦截（{self.reason}，依据 {self.clause}）。"
                "我可以改用不含敏感信息的表述，或只在本地为你分析、不外发。"
            )
        if self.verdict is Verdict.CONFIRM:
            return f"该内容需要你确认后才能继续（{self.reason}，依据 {self.clause}）。"
        if self.verdict is Verdict.STRIP:
            return f"将剥离敏感片段后继续（依据 {self.clause}）。"
        return ""


class SafetyGate:
    """执行 0.3 第 1 站的闸门。"""

    def __init__(self, charter: Charter) -> None:
        matrix = charter.section("enforcement", "gate_matrix")
        if not isinstance(matrix, list) or not matrix:
            raise CharterError("charter.yaml 缺少 enforcement.gate_matrix，无法启动闸门。")
        self._table: dict[tuple[str, str], tuple[Verdict, str]] = {}
        for row in matrix:
            key = (str(row["sensitivity"]), str(row["permission"]))
            self._table[key] = (Verdict(row["verdict"]), str(row.get("note", "")))
        self.charter = charter

    # -- 主入口 -----------------------------------------------------------
    def inspect(self, flow: Flow) -> GateDecision:
        """对单条流执行闸门检查。"""
        key = (flow.sensitivity.value, flow.permission.value)
        hit = self._table.get(key)
        if hit is None:
            # 表未覆盖的组合按最保守处理，并显式说明——绝不静默放行
            return GateDecision(
                flow_id=flow.id,
                verdict=Verdict.CONFIRM,
                reason=f"裁决表未覆盖「{key[0]} × {key[1]}」组合，按最保守处理",
                clause="10-R1",
            )
        verdict, note = hit
        clause = "10-R3" if flow.sensitivity is not Sensitivity.PUBLIC else "0.3"
        reason = note or f"{flow.sensitivity.value} × {flow.permission.value}"
        return GateDecision(flow_id=flow.id, verdict=verdict, reason=reason, clause=clause)

    def inspect_all(self, flows: Iterable[Flow]) -> list[GateDecision]:
        return [self.inspect(f) for f in flows]

    # -- 便捷判定 ---------------------------------------------------------
    @staticmethod
    def blocks_pipeline(decisions: Iterable[GateDecision]) -> bool:
        """是否存在导致管线终止的裁决（0.3-I3）。"""
        return any(d.terminates for d in decisions)

    @staticmethod
    def pending_confirmation(decisions: Iterable[GateDecision]) -> list[GateDecision]:
        """需要用户确认才能继续的裁决。"""
        return [d for d in decisions if d.needs_user_input]

    def internal_only_ids(self, decisions: Iterable[GateDecision]) -> set[str]:
        """仅内部放行的流 id——这些流不得进入输出流（0.7 / 第十章）。"""
        return {d.flow_id for d in decisions if d.verdict is Verdict.ALLOW_INTERNAL}

    # -- 敏感内容剥离 -----------------------------------------------------
    def strip(self, flow: Flow) -> Flow:
        """按 10-R3 剥离对外发送前的内容。

        这里不做启发式猜测：只有当流自身被标为「禁外发」时才剥离，
        并把剥离动作写进 notes 供回溯，避免「以为做了其实没做」。
        """
        clone = flow.clone()
        if clone.permission is Permission.NO_EGRESS:
            clone.notes.append("10-R3 已剥离：原始内容禁止外发")
            clone.text = "[已按 10-R3 剥离：原始内容禁止外发]"
            clone.permission = Permission.INTERNAL_ONLY
        return clone

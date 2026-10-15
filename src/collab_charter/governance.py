"""治理内核：把仲裁、闸门、路由各站的决策统一成结构化、可解释、可审计的
``DecisionRecord``。

这是「最终优化」第一梯队的第一块：让项目从「能拦截」变成「能解释、能复盘」。

设计原则（对齐方案"LLM 负责理解，Kernel 负责裁决"）
--------------------------------------------------
* 每次关键裁决（闸门 verdict、仲裁 conflict、管线 stage 拦截）都落成一条
  ``DecisionRecord``：谁在哪个生命周期点、做了什么决定、依据哪条条款、
  用了什么证据、风险如何、若被拦该怎么修复。
* 记录是可序列化的（``to_dict`` / ``from_dict``），因此可以进 AuditLedger、
  可以被 Replay 回放、可以被 ``why`` 命令逐条解释。
* 不改变任何裁决本身的逻辑——DecisionRecord 只是"旁路记录"，零侵入。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from .arbiter import ArbitrationResult, Conflict, Verdict_
from .flows import Flow
from .gates import GateDecision


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _risk_of_flow(f: Flow) -> float:
    """流风险启发式（确定性）：敏感度/权限/置信度加权，0–1。

    只用于 DecisionRecord 的 risk_score 展示与排序，不参与裁决。
    口径（标注为启发式）：
      HIGH_RISK 敏感 +0.4；NO_EGRESS 禁外发 +0.2；LOW 置信 +0.15；
      情感流 +0.05；其余基础 0.25。
    """
    score = 0.25
    if f.sensitivity.value == "高危":
        score += 0.4
    elif f.sensitivity.value == "隐私":
        score += 0.2
    if f.permission.value == "禁外发":
        score += 0.2
    elif f.permission.value == "仅内部":
        score += 0.1
    if f.confidence.value == "低":
        score += 0.15
    if f.type.value == "emotion":
        score += 0.05
    return round(min(score, 1.0), 3)


def _clause_ids_of(flow: Flow) -> list[str]:
    """从流上收集被触发的条款线索（payload 或 notes 中带 R 编号的）。"""
    ids: list[str] = []
    for note in flow.notes:
        for tok in note.split():
            if len(tok) >= 3 and tok[0].isdigit() and ("-" in tok or tok[1] == "."):
                ids.append(tok)
    for key in ("clause", "clause_id", "policy_clause"):
        val = flow.payload.get(key)
        if isinstance(val, str) and val:
            ids.append(val)
    return sorted(set(ids))


@dataclass
class DecisionRecord:
    """一次关键裁决的可解释记录。

    字段对齐方案的 P0-1 ``DecisionRecord``：
    decision_id / event / subject / action / outcome / clause_ids /
    evidence / risk_score / explanation / repair_actions / parent / trace_id。
    """

    decision_id: str
    event: str                      # 生命周期点，如 pre_tool_call / adjudicate
    subject: str                    # 谁被裁决：flow / session
    action: str                     # 被裁决的具体动作或流文本
    outcome: str                    # allow / deny / ask / degrade
    clause_ids: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    risk_score: float = 0.0
    explanation: str = ""
    repair_actions: list[str] = field(default_factory=list)
    parent_decision_id: str | None = None
    trace_id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: str = field(default_factory=_now_iso)

    # -- 构造 -------------------------------------------------------------
    @classmethod
    def from_gate(cls, decision: GateDecision, *, trace_id: str | None = None,
                  parent: str | None = None) -> "DecisionRecord":
        """闸门裁决 → 决策记录。"""
        outcome_map = {
            "allow": "allow",
            "strip": "degrade",
            "allow_internal": "degrade",
            "confirm": "ask",
            "block": "deny",
        }
        return cls(
            decision_id=uuid4().hex[:12],
            event="pre_flow",
            subject=f"flow:{decision.flow_id}",
            action=decision.reason,
            outcome=outcome_map.get(decision.verdict.value, "allow"),
            clause_ids=[decision.clause] if decision.clause else [],
            evidence=[],
            risk_score=0.5,
            explanation=decision.explain() or decision.reason,
            repair_actions=[],
            parent_decision_id=parent,
            trace_id=trace_id or uuid4().hex[:12],
        )

    @classmethod
    def from_conflict(cls, conflict: Conflict, *, trace_id: str | None = None,
                      parent: str | None = None) -> "DecisionRecord":
        """仲裁冲突 → 决策记录。"""
        outcome = "deny" if conflict.winner_id else "ask"
        return cls(
            decision_id=uuid4().hex[:12],
            event="adjudicate",
            subject=f"flow:{conflict.left_id} vs flow:{conflict.right_id}",
            action=f"{conflict.dimension}",
            outcome=outcome,
            clause_ids=[conflict.clause] if conflict.clause else [],
            evidence=[],
            risk_score=0.4,
            explanation=conflict.explain(),
            repair_actions=["请用户裁断（0.5-R4）"] if outcome == "ask" else [],
            parent_decision_id=parent,
            trace_id=trace_id or uuid4().hex[:12],
        )

    @classmethod
    def from_stage(cls, *, stage: str, detail: str, clause: str, ok: bool,
                   trace_id: str | None = None, parent: str | None = None,
                   risk: float = 0.0) -> "DecisionRecord":
        """管线单站执行 → 决策记录（终止站、拦截站都会记录）。"""
        return cls(
            decision_id=uuid4().hex[:12],
            event=stage,
            subject="session",
            action=detail,
            outcome="allow" if ok else "deny",
            clause_ids=[clause] if clause else [],
            evidence=[],
            risk_score=risk,
            explanation=detail,
            repair_actions=[],
            parent_decision_id=parent,
            trace_id=trace_id or uuid4().hex[:12],
        )

    # -- 序列化 -----------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "event": self.event,
            "subject": self.subject,
            "action": self.action,
            "outcome": self.outcome,
            "clause_ids": self.clause_ids,
            "evidence": self.evidence,
            "risk_score": self.risk_score,
            "explanation": self.explanation,
            "repair_actions": self.repair_actions,
            "parent_decision_id": self.parent_decision_id,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DecisionRecord":
        return cls(
            decision_id=d["decision_id"],
            event=d["event"],
            subject=d["subject"],
            action=d["action"],
            outcome=d["outcome"],
            clause_ids=list(d.get("clause_ids", [])),
            evidence=list(d.get("evidence", [])),
            risk_score=float(d.get("risk_score", 0.0)),
            explanation=d.get("explanation", ""),
            repair_actions=list(d.get("repair_actions", [])),
            parent_decision_id=d.get("parent_decision_id"),
            trace_id=d.get("trace_id", uuid4().hex[:12]),
            timestamp=d.get("timestamp", _now_iso()),
        )

    # -- 展示 -------------------------------------------------------------
    def explain(self) -> str:
        """面向人的解释（``why`` 命令的输出）。"""
        outcome_zh = {
            "allow": "放行", "deny": "拦截", "ask": "待确认", "degrade": "降级",
        }.get(self.outcome, self.outcome)
        lines = [
            f"决策：{outcome_zh}",
            f"事件：{self.event}",
        ]
        if self.subject:
            lines.append(f"对象：{self.subject}")
        if self.action:
            lines.append(f"动作：{self.action}")
        if self.clause_ids:
            lines.append(f"条款：{', '.join(self.clause_ids)}")
        if self.risk_score:
            lines.append(f"风险：{self.risk_score:.2f}")
        if self.explanation:
            lines.append(f"解释：{self.explanation}")
        if self.repair_actions:
            lines.append("修复：")
            lines.extend(f"  - {a}" for a in self.repair_actions)
        return "\n".join(lines)

    def __repr__(self) -> str:  # pragma: no cover - 展示用
        return f"<DecisionRecord {self.decision_id} {self.event}→{self.outcome}>"


def collect_arbitration_records(
    arb: ArbitrationResult | None,
    *,
    trace_id: str | None = None,
    parent: str | None = None,
) -> list[DecisionRecord]:
    """把一次仲裁结果展开成逐条冲突决策记录。"""
    if arb is None:
        return []
    records = [DecisionRecord.from_conflict(c, trace_id=trace_id, parent=parent)
               for c in arb.conflicts]
    for q in arb.tiebreak_questions:
        records.append(DecisionRecord(
            decision_id=uuid4().hex[:12],
            event="adjudicate",
            subject="session",
            action=q,
            outcome="ask",
            clause_ids=["0.5-R4"],
            evidence=[],
            risk_score=0.4,
            explanation="同级同源冲突，无法裁决，需用户裁断",
            repair_actions=["请用户裁断"],
            parent_decision_id=parent,
            trace_id=trace_id or uuid4().hex[:12],
        ))
    return records


def serialize(records: Iterable[DecisionRecord]) -> list[dict[str, Any]]:
    return [r.to_dict() for r in records]


def deserialize(items: Iterable[dict[str, Any]]) -> list[DecisionRecord]:
    return [DecisionRecord.from_dict(d) for d in items]


# 向后兼容导入：保持与旧模块名一致的别名，避免破坏已有 import。
def _json_default(o: Any) -> Any:  # pragma: no cover
    return o.to_dict() if isinstance(o, DecisionRecord) else str(o)

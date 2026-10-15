"""Policy IR 轻量版（最终优化·第二梯队·P2-10 的克制实现）。

对齐方案「把宪章编译成 Policy IR」——但只做**轻量中间表示**：
* 把 charter.yaml 编译成统一的策略条目（id / 章节 / 类型 / 优先级 / 风险档），
  不做 YAML→IR→msgpack bundle 的全套编译（那在进入多租户/企业阶段前是过度工程）。
* 用途：`why` 解释、宪章差分（charter diff）、规则清单导出、冲突/优先级预览。
* 零新依赖；与 governance/audit 打通，供 Replay / why 消费。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable
from uuid import uuid4

#: 条款类型（kind 字母 → 语义）
KIND_ZH = {
    "R": "义务/约定 (requirement)",
    "O": "禁令 (prohibition)",
    "P": "原则 (principle)",
    "I": "不变量 (invariant)",
    "C": "自检/约束 (check)",
    "G": "闸门 (gate)",
    "V": "元数据/验证 (verify)",
}


@dataclass
class PolicyRule:
    """一条轻量策略 IR 条目。"""

    policy_id: str
    chapter_key: str
    chapter_title: str
    section_key: str
    section_title: str
    kind: str
    kind_zh: str
    zh: str
    text: str
    risk_level: str = "low"      # low / medium / high / critical
    priority: int = 0            # 数字越大越优先（编译时归一化）
    triggers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "chapter_key": self.chapter_key,
            "chapter_title": self.chapter_title,
            "section_key": self.section_key,
            "section_title": self.section_title,
            "kind": self.kind,
            "kind_zh": self.kind_zh,
            "zh": self.zh,
            "text": self.text,
            "risk_level": self.risk_level,
            "priority": self.priority,
            "triggers": list(self.triggers),
        }


#: 章节 → 风险档（启发式：安全/隐私/文件章节更高危，用于 IR 排序与 why 展示）
_RISK_BY_CHAPTER: dict[str, str] = {
    "chapter_10_safety": "critical",
    "chapter_1_receipt": "medium",
    "chapter_6_local_files": "high",
    "chapter_7_cognition_memory": "medium",
    "chapter_12_symbolic_anchor": "medium",
    "chapter_11_knowledge_semantics": "medium",
}

#: 章节 key → 标题（用于 IR 展示）
_CHAPTER_TITLES = {
    "chapter_0_information_flow": "信息流与路由",
    "chapter_1_receipt": "接收自检",
    "chapter_2_user_profile": "用户画像",
    "chapter_3_communication": "沟通",
    "chapter_4_minimal_context": "极简上下文",
    "chapter_5_analysis": "分析",
    "chapter_6_local_files": "本地文件",
    "chapter_7_cognition_memory": "认知与记忆",
    "chapter_8_output_format": "输出格式",
    "chapter_9_shortcuts": "快捷词",
    "chapter_10_safety": "安全",
    "chapter_11_knowledge_semantics": "知识语义",
    "chapter_12_symbolic_anchor": "符号锚定",
}


def _risk_level(clause) -> str:
    return _RISK_BY_CHAPTER.get(clause.chapter_key, "low")


def _priority_of(kind: str, risk: str) -> int:
    """优先级归一化：kind 权重 + 风险档权重（仅供 IR 排序，不参与运行时裁决）。"""
    kind_w = {"O": 100, "R": 80, "I": 70, "G": 90, "P": 60, "C": 50, "V": 40}.get(kind, 50)
    risk_w = {"critical": 300, "high": 200, "medium": 100, "low": 0}[risk]
    return kind_w + risk_w


def _triggers_of(clause) -> list[str]:
    """从条款文本提取触发场景关键词（启发式，用于 IR 快速检索）。"""
    text = clause.text
    triggers = []
    for word in ("工具", "文件", "记忆", "输出", "联网", "删除", "覆盖", "提交",
                 "确认", "脱敏", "隐私", "风险", "回放", "审计", "反馈", "自检"):
        if word in text:
            triggers.append(word)
    return triggers


class PolicyIR:
    """宪章 → 轻量策略中间表示。"""

    def __init__(self, charter) -> None:
        self.charter = charter
        self.rules: list[PolicyRule] = []
        self.build()

    # -- 编译 -------------------------------------------------------------
    def build(self) -> None:
        for clause in self.charter:
            risk = _risk_level(clause)
            self.rules.append(PolicyRule(
                policy_id=clause.id,
                chapter_key=clause.chapter_key,
                chapter_title=_CHAPTER_TITLES.get(clause.chapter_key, clause.chapter_key),
                section_key=clause.section_key,
                section_title=clause.section_title,
                kind=clause.kind,
                kind_zh=KIND_ZH.get(clause.kind, clause.kind),
                zh=clause.zh or "",
                text=clause.text,
                risk_level=risk,
                priority=_priority_of(clause.kind, risk),
                triggers=_triggers_of(clause),
            ))

    # -- 查询 -------------------------------------------------------------
    def get(self, policy_id: str) -> PolicyRule | None:
        for r in self.rules:
            if r.policy_id == policy_id:
                return r
        return None

    def by_risk(self, level: str) -> list[PolicyRule]:
        return [r for r in self.rules if r.risk_level == level]

    def by_chapter(self, chapter_key: str) -> list[PolicyRule]:
        return [r for r in self.rules if r.chapter_key == chapter_key]

    def sorted(self, *, by: str = "priority") -> list[PolicyRule]:
        if by == "priority":
            return sorted(self.rules, key=lambda r: (-r.priority, r.policy_id))
        return sorted(self.rules, key=lambda r: (r.chapter_key, r.policy_id))

    # -- 导出 -------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.charter.version,
            "charter_id": self.charter.charter_id,
            "rule_count": len(self.rules),
            "rules": [r.to_dict() for r in self.rules],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    # -- 差分（宪章演进：改了什么、影响哪些章节） ------------------------
    def diff(self, other: "PolicyIR") -> dict[str, Any]:
        """与另一版宪章的 IR 差分。返回新增/变更/删除及受影响章节。"""
        mine = {r.policy_id: r for r in self.rules}
        theirs = {r.policy_id: r for r in other.rules}
        added = [pid for pid in theirs if pid not in mine]
        removed = [pid for pid in mine if pid not in theirs]
        changed = []
        for pid in set(mine) & set(theirs):
            if mine[pid].text != theirs[pid].text or mine[pid].priority != theirs[pid].priority:
                changed.append(pid)
        affected_chapters = sorted({self.get(pid).chapter_key for pid in changed + removed
                                    if self.get(pid)} | {other.get(pid).chapter_key for pid in added
                                                          if other.get(pid)})
        return {
            "added": added,
            "removed": removed,
            "changed": changed,
            "affected_chapters": affected_chapters,
            "counts": {"added": len(added), "removed": len(removed), "changed": len(changed)},
        }

    # -- 风险概览（供 Dashboard / 报告） ---------------------------------
    def risk_summary(self) -> dict[str, int]:
        counts = {}
        for r in self.rules:
            counts[r.risk_level] = counts.get(r.risk_level, 0) + 1
        return counts

    # -- 展示 -------------------------------------------------------------
    def format_rule(self, rule: PolicyRule) -> str:
        return (
            f"[{rule.policy_id}] {rule.kind_zh}（风险:{rule.risk_level} 优先:{rule.priority}）\n"
            f"  {rule.section_title} / {rule.chapter_title}\n"
            f"  {rule.zh or rule.text}"
            + (f"\n  触发场景：{'、'.join(rule.triggers)}" if rule.triggers else "")
        )


def compile_charter(charter) -> PolicyIR:
    return PolicyIR(charter)

"""回流前自检：0.8 的六项检查。

宪章原文：本自检即宪章层面的「完成前取证」——**先过闸，再断言**。
因此这里的每一项都必须产出可判定的 passed 布尔值与失败详情，禁止
「看起来没问题」式的软判断。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .charter_loader import Charter
from .flows import Confidence, Flow, FlowType, Source
from .gates import GateDecision, Verdict

#: 允许作为事实来源的标签（0.2 来源 + 5-R2 证据优先）
_FACTUAL_SOURCES = {
    Source.USER_STATED,
    Source.FILE_EVIDENCE,
    Source.RETRIEVED,
}


@dataclass(frozen=True)
class SelfCheckItem:
    id: str
    question: str
    passed: bool
    detail: str = ""

    def __str__(self) -> str:  # pragma: no cover
        mark = "PASS" if self.passed else "FAIL"
        return f"[{mark}] {self.id} {self.question} {self.detail}".rstrip()


@dataclass
class SelfCheckReport:
    """六项自检的完整报告。"""

    items: list[SelfCheckItem] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(i.passed for i in self.items)

    @property
    def failures(self) -> list[SelfCheckItem]:
        return [i for i in self.items if not i.passed]

    def explain(self) -> str:
        """0.8 原文要求：静默执行，不通过则显式说明。"""
        if self.passed:
            return ""
        lines = ["回流前自检未通过（0.8）："]
        lines += [f"- {i.id} {i.question} —— {i.detail}" for i in self.failures]
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self.items)


class SelfCheckRunner:
    """执行 0.8 的六项检查。"""

    CLAUSE_IDS = ("0.8-C1", "0.8-C2", "0.8-C3", "0.8-C4", "0.8-C5", "0.8-C6")

    def __init__(self, charter: Charter) -> None:
        self.charter = charter
        # 六项必须与宪章一致，否则说明代码与 SSOT 脱钩
        for cid in self.CLAUSE_IDS:
            charter.clause(cid)

    def run(
        self,
        *,
        flows: Sequence[Flow],
        decisions: Sequence[GateDecision],
        output_text: str,
        memory_updated: bool,
        constraints: Iterable[str] = (),
        emitted_ids: Iterable[str] = (),
        agent_cannot: Iterable[str] = (),
    ) -> SelfCheckReport:
        """执行自检。

        参数
        ----
        flows: 本次会话产生/触及的全部流。
        decisions: 闸门裁决记录。
        output_text: 即将流出的文本。
        memory_updated: 会话是否已完成记忆回流（0.6 / 0.3 第 8 站）。
        constraints: 用户给出的关键约束（原样字符串），用于核对是否丢失。
        emitted_ids: 实际进入输出流的流 id 集合，用于 0.7 过滤核对。
        agent_cannot: 本环境无法执行的宪章条款 id（第一章 1-C2 要求显式声明）。
        """
        checks: list[SelfCheckItem] = []

        # 0.8-C1 关键约束是否丢失？
        missing = [c for c in constraints if c and c not in output_text]
        checks.append(
            SelfCheckItem(
                "0.8-C1",
                "关键约束是否丢失？",
                not missing,
                f"未在输出中体现：{missing}" if missing else "全部约束均已在输出中体现",
            )
        )

        # 0.8-C2 推测是否已标注置信度？
        spec_unmarked = [
            f.id for f in flows if f.type is FlowType.SPECULATION and not f.confidence
        ]
        low_unmarked = [
            f.id
            for f in flows
            if f.needs_pending_mark and f.id in set(emitted_ids) and "待验证" not in f.text
        ]
        ok2 = not spec_unmarked and not low_unmarked
        checks.append(
            SelfCheckItem(
                "0.8-C2",
                "推测是否已标注置信度？",
                ok2,
                f"缺置信度：{spec_unmarked}；低置信未标「待验证」：{low_unmarked}" if not ok2 else "推测流均已携带置信度并通过 0.7-R3 标注",
            )
        )

        # 0.8-C3 来源是否可追溯？
        untraceable = [
            f.id
            for f in flows
            if f.is_factual and f.source not in _FACTUAL_SOURCES
        ]
        checks.append(
            SelfCheckItem(
                "0.8-C3",
                "来源是否可追溯？",
                not untraceable,
                f"事实流来源不可追溯：{untraceable}" if untraceable else "事实流来源均可追溯（用户明说/文件实证/检索所得）",
            )
        )

        # 0.8-C4 反馈是否已回流、记忆是否已更新？
        checks.append(
            SelfCheckItem(
                "0.8-C4",
                "反馈是否已回流、记忆是否已更新？",
                bool(memory_updated),
                "会话尚未完成记忆回流（0.3 第 8 站）" if not memory_updated else "记忆流已回流",
            )
        )

        # 0.8-C5 安全闸门是否生效？
        gate_ok = bool(decisions) and not any(
            d.terminates for d in decisions
        )
        checks.append(
            SelfCheckItem(
                "0.8-C5",
                "安全闸门是否生效？",
                gate_ok,
                "闸门未执行或存在拦截裁决" if not gate_ok else f"闸门已裁决 {len(list(decisions))} 条流",
            )
        )

        # 0.8-C6 输出是否只含必要信息？
        leaked = [
            f.id
            for f in flows
            if f.id in set(emitted_ids) and f.payload.get("internal_only")
        ]
        checks.append(
            SelfCheckItem(
                "0.8-C6",
                "输出是否只含必要信息？",
                not leaked,
                f"内部流误入输出：{leaked}" if leaked else "输出仅含必要信息（0.7 六件套）",
            )
        )

        # 第一章 1-C2：无法执行的条款必须已显式声明，否则视为静默忽略（7-R4）
        cannot = list(agent_cannot)
        if cannot:
            checks.append(
                SelfCheckItem(
                    "1-C2",
                    "不可执行的条款是否已显式声明降级方案？",
                    True,
                    f"已声明不可执行：{cannot}",
                )
            )
        return SelfCheckReport(items=checks)

    # -- 与宪章条款核对 ---------------------------------------------------
    def covered_clause_ids(self) -> list[str]:
        return list(self.CLAUSE_IDS)

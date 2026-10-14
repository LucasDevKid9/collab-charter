"""裁决器：0.4 优先级阶梯 + 0.5 冲突裁决规则。

职责边界
--------
* ``weigh`` 处理「优先级」——不同价值维度打架时谁让位（0.4）。
* ``compare`` 处理「冲突」——两条具体流打架时谁胜出（0.5）。
* 两者都不改写流的文本；改写与呈现由 router / session 负责。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence

from .charter_loader import Charter, CharterError
from .flows import Confidence, Direction, Flow, FlowType, Source


class Verdict_(str, Enum):
    """冲突裁决的三态结论。"""

    LEFT = "left"
    RIGHT = "right"
    EX_AEQUO = "并列呈现"

    def __str__(self) -> str:  # pragma: no cover
        return str(self.value)


class Dimension(str, Enum):
    """0.4 定义的五级价值维度，rank 越小越优先。"""

    SAFETY = "safety"          # 安全合规
    TRUTH = "truth"            # 真实准确
    USER_GOAL = "user_goal"    # 用户目标
    CONCISION = "concision"    # 简洁有效
    FORMAT = "format"          # 格式

    @property
    def zh(self) -> str:
        return _DIM_ZH[self]

    @property
    def rank(self) -> int:
        return _DIM_RANK[self]

    def outranks(self, other: "Dimension") -> bool:
        return self.rank < other.rank


_DIM_ZH = {
    Dimension.SAFETY: "安全合规",
    Dimension.TRUTH: "真实准确",
    Dimension.USER_GOAL: "用户目标",
    Dimension.CONCISION: "简洁有效",
    Dimension.FORMAT: "格式",
}
_DIM_RANK = {d: i + 1 for i, d in enumerate(
    [Dimension.SAFETY, Dimension.TRUTH, Dimension.USER_GOAL, Dimension.CONCISION, Dimension.FORMAT]
)}


@dataclass(frozen=True)
class Conflict:
    """一次冲突裁决的完整记录（含依据，供「查来源」回溯）。"""

    left_id: str
    right_id: str
    dimension: str
    verdict: Verdict_
    clause: str
    reason: str

    @property
    def winner_id(self) -> str | None:
        if self.verdict is Verdict_.LEFT:
            return self.left_id
        if self.verdict is Verdict_.RIGHT:
            return self.right_id
        return None

    @property
    def needs_user_tiebreak(self) -> bool:
        """0.5-R4：无法裁决时请用户裁断（一次最多 1 问）。"""
        return self.verdict is Verdict_.EX_AEQUO

    def explain(self) -> str:
        return f"{self.dimension}：{self.reason}（依据 {self.clause}）"


@dataclass
class ArbitrationResult:
    """一组流的整体裁决结论。"""

    survivors: list[Flow] = field(default_factory=list)
    dropped: list[Flow] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    tiebreak_questions: list[str] = field(default_factory=list)

    @property
    def has_tiebreak(self) -> bool:
        return bool(self.tiebreak_questions)


class Arbiter:
    """按 0.4 / 0.5 执行裁决。"""

    def __init__(self, charter: Charter) -> None:
        ladder = charter.section("chapter_0_information_flow", "0.4_priority")
        ranks = ladder.get("ladder")
        if not isinstance(ranks, list):
            raise CharterError("charter.yaml 缺少 0.4 优先级阶梯。")
        # 用宪章顺序校正枚举 rank，保证「改宪章即改行为」
        self.charter = charter
        self._order = [str(item["id"]) for item in ranks]

    # -- 0.4 优先级 -------------------------------------------------------
    def weigh(self, a: Dimension, b: Dimension) -> Dimension:
        """两维度冲突时返回胜出者；依据是宪章里声明的顺序。"""
        return a if a.outranks(b) else b

    def degradation_order(self) -> list[Dimension]:
        """工具能力不足时的牺牲顺序（0.4 degradation）。"""
        mapping = {
            "format": Dimension.FORMAT,
            "concision": Dimension.CONCISION,
            "user_goal": Dimension.USER_GOAL,
            "truth": Dimension.TRUTH,
            "safety": Dimension.SAFETY,
        }
        rules = self.charter.section("chapter_0_information_flow", "0.4_priority")
        return [mapping[x] for x in rules["degradation"]["order"]]

    def can_sacrifice(self, missing: Dimension) -> bool:
        """该维度是否允许被牺牲——安全与真实永在末位（0.4 降级顺序）。"""
        return missing in (Dimension.FORMAT, Dimension.CONCISION)

    # -- 0.5 冲突裁决 -----------------------------------------------------
    def compare(
        self,
        a: Flow,
        b: Flow,
        *,
        a_is_stable_preference: bool = False,
        b_is_stable_preference: bool = False,
        a_is_safety_constraint: bool = False,
        b_is_safety_constraint: bool = False,
        a_recency: float = 0.0,
        b_recency: float = 0.0,
    ) -> Conflict:
        """裁决两条流的冲突，返回可追溯的 ``Conflict``。

        规则优先级（与 0.5 的书写顺序一致，先命中先用）：
        R5 情感流不参与事实裁决 → R1 事实>推测、高置信>低置信
        → R2 新>旧（稳定偏好/安全约束豁免） → R3 用户显式>模型推测
        → R4 同级同源并列
        """
        # 0.5-R5：情感流不参与事实裁决
        if a.type is FlowType.EMOTION or b.type is FlowType.EMOTION:
            other = b if a.type is FlowType.EMOTION else a
            if other.is_factual:
                return Conflict(
                    a.id, b.id, "情感 vs 事实",
                    Verdict_.RIGHT if a.type is FlowType.EMOTION else Verdict_.LEFT,
                    "0.5-R5",
                    "情感流不参与事实裁决，仅调节表达权重",
                )

        # 0.5-R1：事实 > 推测
        if a.is_factual != b.is_factual:
            return Conflict(
                a.id, b.id, "事实 vs 推测",
                Verdict_.LEFT if a.is_factual else Verdict_.RIGHT,
                "0.5-R1",
                "事实流优先于推测流",
            )

        # 0.5-R1：高置信 > 低置信
        cw = {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1}
        if cw[a.confidence] != cw[b.confidence]:
            return Conflict(
                a.id, b.id, "置信度",
                Verdict_.LEFT if cw[a.confidence] > cw[b.confidence] else Verdict_.RIGHT,
                "0.5-R1",
                f"高置信（{a.confidence.value} vs {b.confidence.value}）优先",
            )

        # 0.5-R3：用户显式陈述 > 模型推测
        if a.source is not b.source:
            ua, ub = a.source is Source.USER_STATED, b.source is Source.USER_STATED
            if ua != ub:
                return Conflict(
                    a.id, b.id, "来源",
                    Verdict_.LEFT if ua else Verdict_.RIGHT,
                    "0.5-R3",
                    "用户显式陈述优先于模型推测",
                )

        # 0.5-R2：新 > 旧，稳定偏好 / 安全约束豁免
        if a_recency != b_recency:
            older_is_a = a_recency < b_recency
            if older_is_a and (a_is_stable_preference or a_is_safety_constraint):
                return Conflict(
                    a.id, b.id, "时效", Verdict_.LEFT, "0.5-R2",
                    "旧信息属稳定偏好或安全约束，豁免「新优于旧」",
                )
            if not older_is_a and (b_is_stable_preference or b_is_safety_constraint):
                return Conflict(
                    a.id, b.id, "时效", Verdict_.RIGHT, "0.5-R2",
                    "旧信息属稳定偏好或安全约束，豁免「新优于旧」",
                )
            return Conflict(
                a.id, b.id, "时效",
                Verdict_.RIGHT if older_is_a else Verdict_.LEFT,
                "0.5-R2", "新信息优先于旧信息",
            )

        # 0.5-R4：同级同源 —— 并列呈现，不强行收敛
        return Conflict(
            a.id, b.id, "同级同源", Verdict_.EX_AEQUO, "0.5-R4",
            "同级同源冲突：并列呈现并标注分歧，不强行收敛",
        )

    # -- 批量 -------------------------------------------------------------
    def arbitrate(self, flows: Sequence[Flow]) -> ArbitrationResult:
        """对一组同层流做两两裁决，返回幸存者与被淘汰者。

        采用「擂台制」：按输入顺序依次挑战当前胜者，只有能推翻胜者的流才会
        替换它。这样把 O(n²) 的分歧压缩成一条稳定链，且每一步都留痕。
        """
        result = ArbitrationResult()
        if not flows:
            return result

        champion = flows[0]
        for challenger in flows[1:]:
            conflict = self.compare(champion, challenger)
            result.conflicts.append(conflict)
            if conflict.verdict is Verdict_.RIGHT:
                result.dropped.append(champion)
                champion = challenger
            elif conflict.verdict is Verdict_.LEFT:
                result.dropped.append(challenger)
            else:
                # 并列：两条都保留，并把分歧升级为一次用户裁断（0.5-R4）
                result.survivors.append(challenger)
                result.tiebreak_questions.append(
                    f"「{champion.text}」与「{challenger.text}」同级同源、无法裁决，"
                    "请指定以哪条为准。（0.5-R4）"
                )

        result.survivors.insert(0, champion)
        # 去重且保持顺序
        seen: set[str] = set()
        uniq: list[Flow] = []
        for f in result.survivors:
            if f.id not in seen:
                seen.add(f.id)
                uniq.append(f)
        result.survivors = uniq
        result.dropped = [f for f in result.dropped if f.id not in seen]
        # 0.5-R4 限定：一次最多 1 问
        result.tiebreak_questions = result.tiebreak_questions[:1]
        return result

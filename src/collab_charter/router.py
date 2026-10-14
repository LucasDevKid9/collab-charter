"""路由管线：0.3 的八站 + 0.9 的快速通道。

这是整套宪章从「文档」变成「运行」的地方：每一站都有明确的输入、输出与
不变量，且每一站的执行都被记进 ``PipelineRun.records``，使「讲思路」可以
逐站展开、「查来源」可以逐站回溯。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, Sequence

from .arbiter import ArbitrationResult, Arbiter
from .charter_loader import Charter, CharterError
from .flows import (
    Confidence,
    Destination,
    Direction,
    Flow,
    FlowLayer,
    FlowType,
    Source,
)
from .gates import GateDecision, SafetyGate, Verdict
from .memory import MemoryStore
from .selfcheck import SelfCheckReport, SelfCheckRunner


class PipelineStage(str, Enum):
    """0.3 定义的八个站点。"""

    SAFETY_GATE = "safety_gate"
    INTENT = "intent"
    MIRROR = "mirror"
    RECALL = "recall"
    COUNCIL = "council"
    ADJUDICATE = "adjudicate"
    EMIT = "emit"
    REFLOW = "reflow"

    @property
    def zh(self) -> str:
        return _STAGE_ZH[self]

    @property
    def order(self) -> int:
        return _STAGE_ORDER[self]


_STAGE_ZH = {
    PipelineStage.SAFETY_GATE: "安全闸门",
    PipelineStage.INTENT: "意图解析",
    PipelineStage.MIRROR: "认知镜像",
    PipelineStage.RECALL: "记忆检索",
    PipelineStage.COUNCIL: "角色协作",
    PipelineStage.ADJUDICATE: "综合裁决",
    PipelineStage.EMIT: "输出",
    PipelineStage.REFLOW: "反馈回流",
}
_STAGE_ORDER = {s: i + 1 for i, s in enumerate(PipelineStage)}


class TaskLevel(str, Enum):
    """0.9 引用的任务分级（L1 最快，L4 最重）。"""

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


@dataclass(frozen=True)
class Route:
    """一次会话要走哪些站、以及为什么。"""

    stages: tuple[PipelineStage, ...]
    fast_path: bool
    reason: str

    def __str__(self) -> str:  # pragma: no cover
        arrow = " → ".join(s.zh for s in self.stages)
        return f"Route({'快速' if self.fast_path else '全量'}): {arrow}（{self.reason}）"


@dataclass
class StageRecord:
    """单站的执行记录。"""

    stage: PipelineStage
    ok: bool
    detail: str = ""
    clause: str = ""

    def __str__(self) -> str:  # pragma: no cover
        mark = "ok " if self.ok else "stop"
        return f"[{mark}] {self.stage.zh}：{self.detail}"


@dataclass
class PipelineRun:
    """一次管线执行的完整轨迹。"""

    route: Route
    records: list[StageRecord] = field(default_factory=list)
    gate_decisions: list[GateDecision] = field(default_factory=list)
    arbitration: ArbitrationResult | None = None
    selfcheck: SelfCheckReport | None = None
    emitted: list[Flow] = field(default_factory=list)
    terminated_at: PipelineStage | None = None
    mirror_text: str = ""

    @property
    def completed(self) -> bool:
        return self.terminated_at is None

    def trace(self) -> str:
        """「讲思路」所需的逐站展开。"""
        return "\n".join(str(r) for r in self.records)


FULL_PIPELINE: tuple[PipelineStage, ...] = tuple(PipelineStage)
FAST_PIPELINE: tuple[PipelineStage, ...] = (
    PipelineStage.SAFETY_GATE,
    PipelineStage.INTENT,
    PipelineStage.EMIT,
)

#: 触发全量路由的快捷词（第九章）
DEEP_WORDS = ("深挖", "展开")
FAST_WORDS = ("快速",)
SIMPLIFY_WORDS = ("简化",)


class Router:
    """按 0.3 / 0.9 规划并执行管线。"""

    def __init__(
        self,
        charter: Charter,
        *,
        memory: MemoryStore | None = None,
        gate: SafetyGate | None = None,
        arbiter: Arbiter | None = None,
        selfcheck: SelfCheckRunner | None = None,
    ) -> None:
        self.charter = charter
        self.memory = memory or MemoryStore()
        self.gate = gate or SafetyGate(charter)
        self.arbiter = arbiter or Arbiter(charter)
        self.selfcheck = selfcheck or SelfCheckRunner(charter)
        self._validate_against_charter()

    def _validate_against_charter(self) -> None:
        """站点集合必须与宪章 0.3 一致——防止代码悄悄多一个或少一个站。"""
        declared = self.charter.section("chapter_0_information_flow", "0.3_pipeline")
        ids = [str(s["id"]) for s in declared["stages"]]
        if ids != [s.value for s in PipelineStage]:
            raise CharterError(
                "路由站点与宪章 0.3 不一致：\n"
                f"  宪章：{ids}\n  代码：{[s.value for s in PipelineStage]}"
            )

    # -- 0.9 路由决策 -----------------------------------------------------
    def plan(
        self,
        *,
        level: TaskLevel = TaskLevel.L2,
        user_text: str = "",
        has_creative_output: bool = False,
        has_multi_step_plan: bool = False,
        has_local_files: bool = False,
        shortcuts: Iterable[str] = (),
    ) -> Route:
        """决定走全量还是快速通道，并给出可复述的理由。"""
        said = set(shortcuts) | {
            w for w in FAST_WORDS + DEEP_WORDS if w in user_text
        }
        deep_forcing = {
            "用户说「深挖 / 展开」",
        } if ({"深挖", "展开"} & said) else set()
        if has_creative_output:
            deep_forcing.add("任务涉及创造性产出")
        if has_multi_step_plan:
            deep_forcing.add("任务涉及多步计划")
        if has_local_files:
            deep_forcing.add("任务涉及本地文件")

        if deep_forcing:
            return Route(FULL_PIPELINE, False, "启用全量路由：" + "、".join(sorted(deep_forcing)))

        fast_reasons = []
        if level is TaskLevel.L1:
            fast_reasons.append("任务分级为 L1")
        if "快速" in said:
            fast_reasons.append("用户说「快速」")
        if fast_reasons:
            return Route(FAST_PIPELINE, True, "启用快速通道：" + "、".join(fast_reasons))

        return Route(FULL_PIPELINE, False, "默认走全量路由（非 L1、无快速词、无强制全量条件）")

    # -- 执行 -------------------------------------------------------------
    def execute(
        self,
        flows: Sequence[Flow],
        *,
        route: Route | None = None,
        mirror_text: str = "",
        constraints: Sequence[str] = (),
        memory_updated: bool = False,
        agent_cannot: Sequence[str] = (),
        stage_hooks: dict[PipelineStage, Callable[[list[Flow]], list[Flow]]] | None = None,
    ) -> tuple[PipelineRun, list[Flow]]:
        """执行管线，返回（轨迹, 输出流）。"""
        route = route or self.plan()
        run = PipelineRun(route=route)
        current: list[Flow] = list(flows)
        hooks = stage_hooks or {}

        for stage in route.stages:
            if stage is PipelineStage.SAFETY_GATE:
                decisions = self.gate.inspect_all(current)
                run.gate_decisions = decisions
                if SafetyGate.blocks_pipeline(decisions):
                    run.records.append(
                        StageRecord(stage, False, "存在拦截裁决，管线终止（0.3-I3）", "0.3-I3")
                    )
                    run.terminated_at = stage
                    return run, []
                stripped = self.gate.internal_only_ids(decisions)
                for f in current:
                    if f.id in stripped:
                        f.payload["internal_only"] = True
                run.records.append(
                    StageRecord(
                        stage, True,
                        f"裁决 {len(decisions)} 条流，无拦截"
                        + (f"；{len(stripped)} 条仅内部" if stripped else ""),
                        "0.3 第 1 站",
                    )
                )

            elif stage is PipelineStage.INTENT:
                # 意图解析：把输入流按类型分组，供后续站使用
                kinds = {}
                for f in current:
                    kinds[f.type.zh] = kinds.get(f.type.zh, 0) + 1
                run.records.append(
                    StageRecord(stage, True, "显性/隐含诉求拆解：" + "、".join(
                        f"{k}×{v}" for k, v in kinds.items()
                    ), "0.3 第 2 站")
                )

            elif stage is PipelineStage.MIRROR:
                # 0.3-I2 强制节点
                text = mirror_text or self._auto_mirror(current)
                run.mirror_text = text
                run.records.append(
                    StageRecord(stage, True, f"认知镜像：{text}", "0.3-I2")
                )

            elif stage is PipelineStage.RECALL:
                recalled = self.memory.recall(self._recall_query(current))
                current.extend(recalled)
                run.records.append(
                    StageRecord(stage, True, f"激活 {len(recalled)} 条记忆流", "0.6-O2")
                )

            elif stage is PipelineStage.COUNCIL:
                # 建构者 / 质疑者 / 验证者三角视角（第 7 章 7-R3）
                roles = self._council(current)
                current.extend(roles)
                run.records.append(
                    StageRecord(
                        stage, True,
                        f"三角视角并行：建构者{len(roles[0].payload['items'])}项 / "
                        f"质疑者{len(roles[1].payload['items'])}项 / "
                        f"验证者{len(roles[2].payload['items'])}项",
                        "7-R3",
                    )
                )

            elif stage is PipelineStage.ADJUDICATE:
                # 只对同层流做两两裁决；跨层不互相淘汰
                factual = [f for f in current if f.is_factual]
                arb = self.arbiter.arbitrate(factual) if factual else ArbitrationResult()
                run.arbitration = arb
                survivor_ids = {f.id for f in arb.survivors}
                current = [f for f in current if (not f.is_factual) or f.id in survivor_ids]
                run.records.append(
                    StageRecord(
                        stage, True,
                        f"裁决 {len(arb.conflicts)} 次冲突，保留 {len(arb.survivors)} 条"
                        + (f"；待用户裁断 {len(arb.tiebreak_questions)} 项" if arb.has_tiebreak else ""),
                        "0.4 / 0.5",
                    )
                )

            elif stage is PipelineStage.EMIT:
                if hooks.get(stage):
                    current = hooks[stage](current)
                emitted = [f for f in current if not f.payload.get("internal_only")]
                # 0.7-R3：低置信补标注
                emitted = [f.mark_pending() if f.needs_pending_mark else f for f in emitted]
                run.emitted = emitted
                run.records.append(
                    StageRecord(stage, True, f"按 0.7 只呈现必要信息，输出 {len(emitted)} 条流", "0.7")
                )

            elif stage is PipelineStage.REFLOW:
                run.records.append(
                    StageRecord(
                        stage,
                        bool(memory_updated),
                        "记忆与置信度已回流" if memory_updated else "未完成回流，系统处于开环（0.3-I1）",
                        "0.3-I1",
                    )
                )

        # 0.8 自检：只在全量路由下执行
        if not route.fast_path:
            run.selfcheck = self.selfcheck.run(
                flows=current,
                decisions=run.gate_decisions,
                output_text=" ".join(f.text for f in run.emitted),
                memory_updated=memory_updated,
                constraints=constraints,
                emitted_ids=[f.id for f in run.emitted],
                agent_cannot=agent_cannot,
            )
        return run, run.emitted

    # -- 内部辅助 ---------------------------------------------------------
    @staticmethod
    def _auto_mirror(flows: Sequence[Flow]) -> str:
        instructions = [f for f in flows if f.type is FlowType.INSTRUCTION]
        if not instructions:
            return "（无指令流可用于复述，将按默认参数推进）"
        head = instructions[0].text.strip().replace("\n", " ")
        if len(head) > 60:
            head = head[:60] + "…"
        return f"我理解你要的是「{head}」，对吗？"

    @staticmethod
    def _recall_query(flows: Sequence[Flow]) -> str:
        for f in flows:
            if f.type is FlowType.INSTRUCTION:
                return f.text.strip()[:32]
        return ""

    @staticmethod
    def _council(flows: Sequence[Flow]) -> list[Flow]:
        """生成三角视角的三条内部流（默认不展示，0.7-R1）。"""
        facts = [f.text for f in flows if f.is_factual]
        specs = [f.text for f in flows if f.type is FlowType.SPECULATION]
        builder = Flow(
            text="建构者：给出候选方案",
            layer=FlowLayer.INTERNAL, type=FlowType.DECISION,
            source=Source.MODEL_PRIOR, direction=Direction.INTERNAL,
            ttl=_ttl(), confidence=Confidence.MEDIUM,
            payload={"role": "builder", "items": facts or ["待补证据"]},
        )
        skeptic = Flow(
            text="质疑者：寻找方案漏洞",
            layer=FlowLayer.INTERNAL, type=FlowType.SPECULATION,
            source=Source.MODEL_GUESS, direction=Direction.INTERNAL,
            ttl=_ttl(), confidence=Confidence.LOW,
            payload={"role": "skeptic", "items": specs or ["待补反例"]},
        )
        verifier = Flow(
            text="验证者：核对证据",
            layer=FlowLayer.INTERNAL, type=FlowType.FACT,
            source=Source.RETRIEVED, direction=Direction.INTERNAL,
            ttl=_ttl(), confidence=Confidence.MEDIUM,
            payload={"role": "verifier", "items": facts or ["待补来源"]},
        )
        for f in (builder, skeptic, verifier):
            f.payload["internal_only"] = True
        return [builder, skeptic, verifier]


def _ttl():
    from .flows import TTL

    return TTL.SESSION

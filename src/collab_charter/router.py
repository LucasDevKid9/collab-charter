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

#: 轻量任务复杂度判定（0.9 自动兜底）。确定性规则：命中即判，不叠加外部状态。
_CREATIVE_MARKERS = (
    "设计", "创作", "策划", "画", "写一篇", "写份", "写一个", "做一份", "做一张",
    "生成图片", "生成视频", "海报", "剧本", "文案", "小说", "歌词", "方案书",
    "配色", "logo", "Logo", "品牌", "拍摄",
)
_MULTI_STEP_MARKERS = (
    "先", "再", "然后", "步骤", "分几步", "流程", "计划", "规划", "路线",
    "阶段", "第一", "第二", "第三", "梳理", "拆解", "部署", "迁移",
    "构建", "架构", "设计一个系统", "写代码", "实现", "开发",
)
_FILE_MARKERS = (
    "文件", "文档", "上传", "附件", "本地", "读取", "解析",
    "pdf", "PDF", "xlsx", "表格", "csv", "CSV", "word", "Word", "ppt", "PPT",
)


def _guess_task_complexity(user_text: str) -> dict[str, bool]:
    """从用户文本启发式判定三类复杂度标记（无模型、确定性、可复现）。

    规则口径：任一标记命中即认为该维度为真；全部未命中则保持 False。
    这只是一个**兜底**——调用方显式传参时以显式值为准（见 ``plan``）。
    """
    creative = any(m in user_text for m in _CREATIVE_MARKERS)
    multi_step = any(m in user_text for m in _MULTI_STEP_MARKERS)
    local_files = any(m in user_text for m in _FILE_MARKERS)
    return {"creative": creative, "multi_step": multi_step, "local_files": local_files}


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
        has_creative_output: bool | None = None,
        has_multi_step_plan: bool | None = None,
        has_local_files: bool | None = None,
        shortcuts: Iterable[str] = (),
        auto_guess: bool = True,
    ) -> Route:
        """决定走全量还是快速通道，并给出可复述的理由。

        复杂度标记语义：``None`` = 调用方未表态（``auto_guess=True`` 时由
        内核从 ``user_text`` 启发式补位）；``True``/``False`` = 显式值，
        显式值优先、不与猜测叠加。
        """
        said = set(shortcuts) | {
            w for w in FAST_WORDS + DEEP_WORDS if w in user_text
        }
        deep_forcing = {
            "用户说「深挖 / 展开」",
        } if ({"深挖", "展开"} & said) else set()

        if auto_guess and user_text:
            guess = _guess_task_complexity(user_text)
            has_creative_output = guess["creative"] if has_creative_output is None else has_creative_output
            has_multi_step_plan = guess["multi_step"] if has_multi_step_plan is None else has_multi_step_plan
            has_local_files = guess["local_files"] if has_local_files is None else has_local_files

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
        mirror_fn: Callable[[list[Flow]], str] | None = None,
        council_fn: Callable[[list[Flow]], list[Flow]] | None = None,
    ) -> tuple[PipelineRun, list[Flow]]:
        """执行管线，返回（轨迹, 输出流）。

        ``stage_hooks``：**所有站点统一生效**的拦截点——每个站点在执行默认逻辑
        前，若传入该站 hook，先对当前流列表做变换（可注入真实模型/工具结果）。
        与早期版本不同，hook 不再只对 EMIT 生效。

        ``mirror_fn`` / ``council_fn``：认知执行注入点。传入真实 LLM 回调时，
        认知镜像（第 3 站）与三角角色协作（第 5 站）由回调产出真实内容；
        未传入时回退到确定性模板（保持零依赖兜底）。
        """
        route = route or self.plan()
        run = PipelineRun(route=route)
        current: list[Flow] = list(flows)
        hooks = stage_hooks or {}

        def apply_hook(stage: PipelineStage) -> None:
            fn = hooks.get(stage)
            if fn:
                nonlocal current
                current = fn(current)

        for stage in route.stages:
            apply_hook(stage)
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
                text = mirror_text or (mirror_fn(current) if mirror_fn else self._auto_mirror(current))
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
                roles = council_fn(current) if council_fn else self._council(current)
                current.extend(roles)
                detail = "、".join(
                    f"{r.payload.get('role', r.text)}×{len(r.payload.get('items', []))}"
                    for r in roles[:3]
                ) or "（无角色视角）"
                run.records.append(
                    StageRecord(stage, True, f"三角视角并行：{detail}", "7-R3")
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

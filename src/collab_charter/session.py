"""会话门面：把路由、闸门、裁决、记忆、自检、快捷词收敛成一次调用。

对 Agent 而言，``Session`` 是唯一需要知道的入口：

    from collab_charter import Session
    s = Session()
    s.register_tool(ToolSpec("web_search", "检索", {...}, handler))
    out = s.handle("帮我查一下 z3 的最新版本")
    print(out.text)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence
from uuid import uuid4

from .charter_loader import Charter, CharterError
from .flows import (
    Confidence,
    Destination,
    Direction,
    Flow,
    FlowLayer,
    FlowType,
    Permission,
    Sensitivity,
    Source,
    TTL,
    user_instruction,
)
from .gates import GateDecision
from .memory import MemoryStore
from .router import PipelineRun, Route, Router, TaskLevel
from .selfcheck import SelfCheckReport

#: 第九章的六个快捷词 → 行为
SHORTCUT_BEHAVIOR: dict[str, str] = {
    "展开": "在当前结论上逐步展开推理与细节",
    "简化": "压到最短，只留结论和必要依据",
    "讲思路": "只讲方法论与推理路径，不铺陈细节",
    "查来源": "为关键结论补可核实的外部链接",
    "快速": "省掉对齐动作，直接干",
    "深挖": "多假设、多验证，主动找反例",
}

#: 声称不可执行时按第一章 1-C2 附带的降级方案
DEFAULT_DEGRADATIONS: dict[str, str] = {
    "0.6-O1": "无持久记忆 → 请用户把要沉淀的内容用「归档」指令交给我，我生成记忆文件给你保存",
    "0.6-O2": "无跨会话记忆 → 请用户在新会话开始时粘贴记忆文件",
    "6-R1": "无本地文件访问 → 请用户粘贴目标内容或文件片段",
    "8-R2": "无法联网核实 → 我会标注「待验证」，并给出建议核实的关键词",
}


@dataclass
class ToolSpec:
    """一个可被 Agent 调用的工具。"""

    name: str
    description: str
    handler: Callable[..., Any]
    parameters: dict[str, Any] = field(default_factory=dict)
    #: 该工具产出的流默认敏感度/权限
    sensitivity: Sensitivity = Sensitivity.PUBLIC
    permission: Permission = Permission.OUTPUTTABLE


@dataclass
class SessionOutcome:
    """一次 ``handle`` 的完整结果。"""

    text: str
    flows: list[Flow]
    run: PipelineRun
    mirror: str = ""
    tiebreak: str | None = None
    selfcheck: SelfCheckReport | None = None
    degraded: list[str] = field(default_factory=list)
    shortcut_effects: list[str] = field(default_factory=list)
    decisions: list[Any] = field(default_factory=list)

    @property
    def trace(self) -> str:
        return self.run.trace()

    def explain_failures(self) -> str:
        return self.selfcheck.explain() if self.selfcheck else ""


class Session:
    """一次协作会话。"""

    def __init__(
        self,
        charter: Charter | None = None,
        *,
        memory: MemoryStore | None = None,
        level: TaskLevel = TaskLevel.L2,
        agent_cannot: Sequence[str] = (),
        audit: Any | None = None,
        session_id: str | None = None,
    ) -> None:
        self.charter = charter or Charter.load()
        self.memory = memory or MemoryStore()
        self.router = Router(self.charter, memory=self.memory)
        self.level = level
        #: 审计账本。传入 ``audit=False`` 关闭；否则默认启用默认账本。
        self.audit = audit if audit is not False else None
        if self.audit is None and audit is not False:
            from .audit import default_ledger

            self.audit = default_ledger()
        self.session_id = session_id or uuid4().hex[:10]
        self.tools: dict[str, ToolSpec] = {}
        #: 本环境确实无法执行的条款 id；初始化时校验其存在于宪章
        self.agent_cannot: list[str] = []
        for cid in agent_cannot:
            self.charter.clause(cid)  # 不存在的条款立刻报错，避免空声明
            self.agent_cannot.append(cid)
        self._flows: list[Flow] = []
        self._memory_updated = False
        self._emitted_ids: set[str] = set()

    # -- 工具注册（Agent 调用面） -----------------------------------------
    def register_tool(self, spec: ToolSpec) -> None:
        self.tools[spec.name] = spec

    def tool_schemas(self) -> list[dict[str, Any]]:
        """导出工具定义，供外部 Agent 平台读取（OpenAI/Anthropic 风格）。"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": {"type": "object", "properties": t.parameters},
            }
            for t in self.tools.values()
        ]

    def call_tool(self, name: str, **kwargs: Any) -> Flow:
        """调用工具并把结果包成一条工具流（第〇章「工具流」）。

        结果先过``sanitize``（第二梯队：工具结果消毒 / 污点追踪）：
        清除提示词注入、脱敏密钥与 PII、超长截断，并把污点标签写入 payload，
        供内核判断能否提权 / 是否需要策略复核。
        """
        spec = self.tools.get(name)
        if spec is None:
            raise CharterError(f"未注册的工具：{name}")
        result = spec.handler(**kwargs)

        from .sanitize import default_taint_for_source, sanitize

        san = sanitize(str(result), taint=default_taint_for_source(name))
        flow = Flow(
            text=f"[工具 {name}] {san.text}",
            layer=FlowLayer.TOOL,
            type=FlowType.KNOWLEDGE,
            source=Source.RETRIEVED,
            direction=Direction.INTERNAL,
            ttl=TTL.SESSION,
            confidence=Confidence.HIGH,
            sensitivity=spec.sensitivity,
            permission=spec.permission,
            payload={
                "tool": name,
                "args": kwargs,
                "taint": san.taint,
                "sanitized": san.to_dict(),
            },
        )
        self._flows.append(flow)
        return flow

    # -- 第一章：接收自检 -------------------------------------------------
    def receipt(self) -> str:
        """第一章要求的 ≤3 行自检，禁止寒暄。"""
        cannot = self.agent_cannot or []
        lines = [f"已接收《用户协作宪章》v{self.charter.version}，路由管线就绪。"]
        if cannot:
            parts = [f"{cid}（降级：{DEFAULT_DEGRADATIONS.get(cid, '请求用户协助')}）" for cid in cannot]
            lines.append("不可执行：" + "；".join(parts))
        else:
            lines.append("第〇章各站均可执行。")
        lines.append("称呼：我 → 你。直接进入工作。")
        return "\n".join(lines[:3])

    # -- 记录流 -----------------------------------------------------------
    def add(self, flow: Flow) -> Flow:
        self._flows.append(flow)
        return flow

    def ask(self, text: str, **kw: Any) -> Flow:
        """把用户的一句话记为指令流。"""
        return self.add(user_instruction(text, **kw))

    # -- 主入口 -----------------------------------------------------------
    def handle(
        self,
        message: str,
        *,
        shortcuts: Iterable[str] = (),
        has_creative_output: bool | None = None,
        has_multi_step_plan: bool | None = None,
        has_local_files: bool | None = None,
        constraints: Sequence[str] = (),
        extra_flows: Sequence[Flow] = (),
        stage_hooks: dict[Any, Callable[[list[Flow]], list[Flow]]] | None = None,
        mirror_fn: Callable[[list[Flow]], str] | None = None,
        council_fn: Callable[[list[Flow]], list[Flow]] | None = None,
        auto_deposit_keys: Sequence[str] = (),
    ) -> SessionOutcome:
        """处理一条用户消息，跑完路由管线并返回可交付的结果对象。

        复杂度标记传 ``None``（默认）时由 Router 的 ``auto_guess`` 从文本
        自动判定；显式传 ``True``/``False`` 则以其为准。

        ``stage_hooks`` / ``mirror_fn`` / ``council_fn``：透传给 Router 的认知
        执行注入点（真实 LLM 回调或平台工具）。``auto_deposit_keys``：白名单
        流 key——命中且方向为内部/记忆的流会自动沉淀，使 0.8-C4 回流自检通过。
        """
        detected = [w for w in SHORTCUT_BEHAVIOR if w in message]
        said = list(dict.fromkeys([*shortcuts, *detected]))

        self.ask(message)
        for f in extra_flows:
            self.add(f)

        route: Route = self.router.plan(
            level=self.level,
            user_text=message,
            has_creative_output=has_creative_output,
            has_multi_step_plan=has_multi_step_plan,
            has_local_files=has_local_files,
            shortcuts=said,
        )

        # 0.9：用户说「快速」时跳过对齐动作
        skip_mirror_note = "快速" in said
        mirror_text = "" if skip_mirror_note else ""

        # auto-deposit（0.3 第 8 站）：白名单流自动沉淀 → 使 C4 回流自检通过。
        # 必须在 execute 之前完成，否则本次 handle 的自检仍会看到"未回流"。
        if auto_deposit_keys:
            keys = set(auto_deposit_keys)
            deposited = 0
            for f in self._flows:
                if f.destination is Destination.TOOL_CALL:
                    continue
                mem_key = str(f.payload.get("memory_key", ""))
                if mem_key and mem_key in keys:
                    self.memory.deposit(f)
                    deposited += 1
                elif any(k in f.text for k in keys):
                    self.memory.deposit(f)
                    deposited += 1
            if deposited:
                self._memory_updated = True
                self.memory.decay()

        run, emitted = self.router.execute(
            list(self._flows),
            route=route,
            mirror_text=mirror_text,
            constraints=constraints,
            memory_updated=self._memory_updated,
            agent_cannot=self.agent_cannot,
            stage_hooks=stage_hooks,
            mirror_fn=mirror_fn,
            council_fn=council_fn,
        )
        self._emitted_ids = {f.id for f in emitted}

        # 0.7-R2「简化」：只保留结论与必要依据
        if "简化" in said:
            emitted = [f for f in emitted if f.is_factual or f.type is FlowType.INSTRUCTION][:2]

        text = self._render(emitted, said)
        tiebreak = None
        if run.arbitration and run.arbitration.has_tiebreak:
            tiebreak = run.arbitration.tiebreak_questions[0]

        # 治理内核：写入审计账本（若启用）
        if self.audit is not None:
            try:
                self.audit.record_pipeline(
                    self.session_id,
                    route=str(route),
                    records=[str(r) for r in run.records],
                    decisions=run.decisions,
                    terminated=not run.completed,
                )
            except Exception:  # 审计失败不阻断主流程（防审计故障拖垮对话）
                pass

        return SessionOutcome(
            text=text,
            flows=emitted,
            run=run,
            mirror=run.mirror_text,
            tiebreak=tiebreak,
            selfcheck=run.selfcheck,
            degraded=[f"{cid}：{DEFAULT_DEGRADATIONS.get(cid, '请求用户协助')}" for cid in self.agent_cannot],
            shortcut_effects=[f"{w} → {SHORTCUT_BEHAVIOR[w]}" for w in said],
            decisions=run.decisions,
        )

    # -- 回流 -------------------------------------------------------------
    def reflow(self, *, deposit: Sequence[Flow] = ()) -> int:
        """0.3 第 8 站：把值得沉淀的流写回记忆，并刷新置信度。"""
        count = 0
        for f in deposit:
            self.memory.deposit(f)
            count += 1
        self.memory.decay()
        self._memory_updated = True
        return count

    # -- 呈现 -------------------------------------------------------------
    def _render(self, emitted: Sequence[Flow], said: Sequence[str]) -> str:
        if not emitted:
            return "（本次没有需要向你呈现的内容）"
        if "简化" in said:
            head = emitted[0]
            return f"{head.text}"
        lines: list[str] = []
        for f in emitted:
            prefix = "结论" if f.type is FlowType.INSTRUCTION else f.layer.zh
            lines.append(f"- [{prefix}] {f.text}")
        return "\n".join(lines)

    # -- 诊断 -------------------------------------------------------------
    @property
    def flow_count(self) -> int:
        return len(self._flows)

    def debug_meta(self) -> list[dict[str, Any]]:
        """0.2-V：元数据默认不展示，用户说「讲思路 / 深挖」时才需要。"""
        return [f.meta() for f in self._flows]

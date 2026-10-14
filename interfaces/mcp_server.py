#!/usr/bin/env python3
"""collab-charter MCP server —— 让任何支持 Model Context Protocol 的
AI 平台（Claude Code / Cursor / Codex / Gemini CLI / 自研 Agent）直接调用宪章内核。

设计取舍：**零外部依赖**。不引 `mcp` SDK，只用标准库实现 JSON-RPC over
stdio——这样可以把它塞进任何沙箱、任何平台的插件目录，不需要先建虚拟环境。
（做法参照 superpowers 的零依赖插件哲学。）

启动::

    python3 interfaces/mcp_server.py

协议::

    → {"jsonrpc":"2.0","id":1,"method":"initialize", ...}
    → {"jsonrpc":"2.0","id":2,"method":"tools/list"}
    → {"jsonrpc":"2.0","id":3,"method":"tools/call",
       "params":{"name":"charter_clause","arguments":{"clause_id":"0.5-R4"}}}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

# 允许直接从仓库根目录运行
_ROOT = Path(__file__).resolve().parents[1]
for extra in (_ROOT / "src", _ROOT / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from collab_charter import Charter, Flow, Session  # noqa: E402
from collab_charter.flows import (  # noqa: E402
    Confidence,
    Direction,
    FlowLayer,
    FlowType,
    Permission,
    Sensitivity,
    Source,
    TTL,
)
from collab_charter.router import TaskLevel  # noqa: E402
from collab_charter.anchor import solve as anchor_solve  # noqa: E402
from collab_charter.anchor import AnchorError, AnchorUnavailableError  # noqa: E402
from collab_charter.lexicon import (  # noqa: E402
    KnowledgeBase,
    MiningRequest,
    lexicon_search,
    mine,
)
from fcslint import analyze as fcslint_analyze  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "collab-charter"
SERVER_VERSION = "3.2.0"


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------
class ToolRegistry:
    """把宪章能力包装成 MCP 工具。"""

    def __init__(self) -> None:
        self.charter: Charter | None = None
        # 注意：属性名不得与下面的方法同名（曾因此把 _session 方法覆盖成 None）
        self._session_cache: Session | None = None

    def _charter(self) -> Charter:
        if self.charter is None:
            self.charter = Charter.load()
        return self.charter

    def _session(self) -> Session:
        if self._session_cache is None:
            self._session_cache = Session(self._charter())
        return self._session_cache

    # -- 工具 1：查条款 ---------------------------------------------------
    def charter_clause(self, clause_id: str) -> dict[str, Any]:
        """按 id 查回宪章条款原文与定位。"""
        c = self._charter().clause(clause_id)
        return {"id": c.id, "anchor": c.anchor, "text": c.text, "zh": c.zh}

    # -- 工具 2：列条款 ---------------------------------------------------
    def charter_clauses(self, chapter: str = "", grep: str = "") -> dict[str, Any]:
        """列出条款，可按章节 key 或关键词过滤。"""
        ch = self._charter()
        out = []
        for c in ch:
            if chapter and c.chapter_key != chapter:
                continue
            if grep and grep not in c.text and not (c.zh and grep in c.zh):
                continue
            out.append({"id": c.id, "section": c.section_title, "text": c.text})
        return {"count": len(out), "clauses": out}

    # -- 工具 3：接收自检 -------------------------------------------------
    def charter_receipt(self, agent_cannot: list[str] | None = None) -> dict[str, Any]:
        """生成第一章要求的 ≤3 行接收自检；传入无法执行的条款 id 会附降级方案。"""
        s = Session(self._charter(), agent_cannot=agent_cannot or [])
        return {"receipt": s.receipt()}

    # -- 工具 4：路由决策 -------------------------------------------------
    def charter_route(
        self,
        text: str,
        level: str = "L2",
        creative: bool = False,
        multi_step: bool = False,
        local_files: bool = False,
    ) -> dict[str, Any]:
        """决定这次请求走全量路由还是快速通道。"""
        s = Session(self._charter(), level=TaskLevel(level))
        route = s.router.plan(
            level=TaskLevel(level),
            user_text=text,
            has_creative_output=creative,
            has_multi_step_plan=multi_step,
            has_local_files=local_files,
        )
        return {
            "fast_path": route.fast_path,
            "reason": route.reason,
            "stages": [{"id": st.value, "zh": st.zh} for st in route.stages],
        }

    # -- 工具 5：跑管线 ---------------------------------------------------
    def charter_handle(
        self,
        text: str,
        level: str = "L2",
        constraints: list[str] | None = None,
        creative: bool = False,
        multi_step: bool = False,
        local_files: bool = False,
    ) -> dict[str, Any]:
        """跑完整路由管线，返回逐站轨迹、输出与自检结论。"""
        s = Session(self._charter(), level=TaskLevel(level))
        out = s.handle(
            text,
            constraints=constraints or [],
            has_creative_output=creative,
            has_multi_step_plan=multi_step,
            has_local_files=local_files,
        )
        return {
            "route": out.run.route.reason,
            "trace": [
                {"stage": r.stage.value, "zh": r.stage.zh, "ok": r.ok, "detail": r.detail}
                for r in out.run.records
            ],
            "output": out.text,
            "mirror": out.mirror,
            "tiebreak": out.tiebreak,
            "selfcheck_passed": bool(out.selfcheck and out.selfcheck.passed),
            "selfcheck_failures": [
                {"id": i.id, "question": i.question, "detail": i.detail}
                for i in (out.selfcheck.failures if out.selfcheck else [])
            ],
            "degraded": out.degraded,
        }

    # -- 工具 6：冲突裁决 -------------------------------------------------
    def charter_arbitrate(self, left: str, right: str) -> dict[str, Any]:
        """裁决两条互相冲突的陈述，返回胜出方与依据条款。"""
        s = self._session()
        a = Flow(
            text=left, layer=FlowLayer.INPUT, type=FlowType.FACT,
            source=Source.USER_STATED, direction=Direction.INBOUND,
            ttl=TTL.SESSION, confidence=Confidence.HIGH,
        )
        b = Flow(
            text=right, layer=FlowLayer.INTERNAL, type=FlowType.SPECULATION,
            source=Source.MODEL_GUESS, direction=Direction.INTERNAL,
            ttl=TTL.SESSION, confidence=Confidence.LOW,
        )
        conflict = s.router.arbiter.compare(a, b)
        return {
            "left_is_fact": True,
            "right_is_speculation": True,
            "dimension": conflict.dimension,
            "verdict": conflict.verdict.value,
            "clause": conflict.clause,
            "reason": conflict.reason,
            "needs_user_tiebreak": conflict.needs_user_tiebreak,
        }

    # -- 工具 7：安全闸门 -------------------------------------------------
    def charter_gate(self, sensitivity: str, permission: str) -> dict[str, Any]:
        """查询「敏感度 × 权限」组合的闸门裁决，落实第十章。"""
        s = self._session()
        flow = Flow(
            text="(probe)", layer=FlowLayer.OUTPUT, type=FlowType.KNOWLEDGE,
            source=Source.MODEL_PRIOR, direction=Direction.OUTBOUND,
            ttl=TTL.SESSION, confidence=Confidence.HIGH,
            sensitivity=Sensitivity(sensitivity), permission=Permission(permission),
        )
        d = s.router.gate.inspect(flow)
        return {
            "verdict": d.verdict.value,
            "verdict_zh": d.verdict_zh,
            "passed": d.passed,
            "terminates_pipeline": d.terminates,
            "needs_user_input": d.needs_user_input,
            "clause": d.clause,
            "explain": d.explain(),
        }

    # -- 工具 8：特征簇诊断 -----------------------------------------------
    def fcslint_analyze(self, prompt: str) -> dict[str, Any]:
        """对图像生成提示词执行《模块化特征簇标记语法》诊断 + 优化建议。"""
        return fcslint_analyze(prompt)

    # -- 工具 9：记忆沉淀 -------------------------------------------------
    def memory_deposit(self, text: str, key: str = "", tags: list[str] | None = None) -> dict[str, Any]:
        """把一条结论沉淀为记忆节点（0.6-O1）。"""
        s = self._session()
        flow = Flow(
            text=text, layer=FlowLayer.MEMORY, type=FlowType.KNOWLEDGE,
            source=Source.USER_STATED, direction=Direction.INTERNAL,
            ttl=TTL.STABLE, confidence=Confidence.HIGH,
        )
        node = s.memory.deposit(flow, key or None, tags=tags or [])
        return {"key": node.key, "text": node.text, "tags": node.tags}

    # -- 工具 10：记忆检索 ------------------------------------------------
    def memory_recall(self, query: str, limit: int = 5) -> dict[str, Any]:
        """按关键词激活记忆（0.6-O2）。"""
        s = self._session()
        flows = s.memory.recall(query, limit=limit)
        return {"count": len(flows), "items": [{"text": f.text, "meta": f.meta()} for f in flows]}

    # -- 工具 11：符号锚定求解 ---------------------------------------------
    def anchor_solve(
        self,
        declare: str,
        constraints: str,
        decisions: str,
        rounds: str = "",
        max_solutions: int = 100,
    ) -> dict[str, Any]:
        """把多条件权衡变成 0/1 符号问题交给 z3 硬算（宪章 12.1）。

        结论一律来自求解器枚举输出（12.1-A1）；警告原样返回（12.1-A3）；
        多轮漂移时 drift=True 必须转告用户（12.1-A4）。
        """
        return anchor_solve(
            declare=declare,
            constraints=constraints,
            decisions=decisions,
            rounds=rounds,
            max_solutions=max_solutions,
        )

    # -- 工具 12：知识库检索 ------------------------------------------------
    def lexicon_search(
        self,
        query: str,
        kinds: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """检索知识库（字典/语料/词条/风格/亚文化，宪章 11.1）。"""
        items = lexicon_search(query, kinds=kinds, limit=limit)
        return {
            "kb_digest": KnowledgeBase.load().digest(),
            "count": len(items),
            "items": items,
        }

    # -- 工具 13：语义场深挖 ------------------------------------------------
    def lexicon_mine(
        self,
        requirement: str,
        task_objectives: list[str] | None = None,
        semantic_state: str = "",
        domains: list[str] | None = None,
        limit: int = 12,
        allow_online: bool = False,
    ) -> dict[str, Any]:
        """按需求 + 目标 + 语义状态深挖知识库，返回加权词条、分布权重、
        特征级归因、闸门结论与语义场分析（宪章 11.2-V2 / 11.4）。"""
        result = mine(
            MiningRequest(
                requirement=requirement,
                task_objectives=task_objectives or [],
                semantic_state=semantic_state,
                domains=domains or [],
                limit=limit,
                allow_online=allow_online,
            ),
            charter=self._charter(),
        )
        return result.to_dict()

    # -- 工具 14：潜空间语义场 ----------------------------------------------
    def semantic_field(
        self,
        requirement: str,
        task_objectives: list[str] | None = None,
        semantic_state: str = "",
        domains: list[str] | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        """对一次挖掘的候选集建构潜空间语义场：关联网络、中心性、社群、
        覆盖缺口与密度/模块度（宪章 11.3）。"""
        result = mine(
            MiningRequest(
                requirement=requirement,
                task_objectives=task_objectives or [],
                semantic_state=semantic_state,
                domains=domains or [],
                limit=limit,
            ),
            charter=self._charter(),
        )
        return {
            "kb_digest": result.kb_digest,
            "space_digest": result.space_digest,
            "semantic_state": result.semantic_state,
            "field": result.field.to_dict(),
            "warnings": result.warnings,
        }


# ---------------------------------------------------------------------------
# JSON-RPC / MCP 传输层
# ---------------------------------------------------------------------------
def _tool_schemas() -> list[dict[str, Any]]:
    S = {"type": "string"}
    return [
        {
            "name": "charter_clause",
            "description": "按 id 查询《用户协作宪章》条款原文与定位（如 0.5-R4）。当需要引用规则依据、或用户问「这条规定是什么」时使用。",
            "inputSchema": {
                "type": "object",
                "properties": {"clause_id": {**S, "description": "条款 id，形如 0.4-R1 / 10-R4"}},
                "required": ["clause_id"],
            },
        },
        {
            "name": "charter_clauses",
            "description": "列出宪章条款，可按章节 key 或关键词过滤。当需要通览某一章的全部规则时使用。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "chapter": {**S, "description": "章节 key，如 chapter_5_analysis"},
                    "grep": {**S, "description": "关键词"},
                },
            },
        },
        {
            "name": "charter_receipt",
            "description": "生成宪章第一章要求的接收自检输出（≤3 行）。当会话开始、需要确认哪些条款在当前环境可执行时使用。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent_cannot": {
                        "type": "array",
                        "items": S,
                        "description": "本环境无法执行的条款 id，会附带降级方案",
                    }
                },
            },
        },
        {
            "name": "charter_route",
            "description": "判断一次请求应走全量路由还是快速通道（0.9 反仪式条款）。当不确定该用多重的处理流程时使用。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {**S, "description": "用户请求原文"},
                    "level": {**S, "enum": ["L1", "L2", "L3", "L4"]},
                    "creative": {"type": "boolean", "description": "是否创造性产出"},
                    "multi_step": {"type": "boolean", "description": "是否多步计划"},
                    "local_files": {"type": "boolean", "description": "是否涉及本地文件"},
                },
                "required": ["text"],
            },
        },
        {
            "name": "charter_handle",
            "description": "跑完整路由管线（安全闸门→意图→认知镜像→记忆检索→角色协作→裁决→输出→回流），返回逐站轨迹、输出与 0.8 自检结论。当需要一次可审计、可回溯的完整处理时使用。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {**S, "description": "用户请求原文"},
                    "level": {**S, "enum": ["L1", "L2", "L3", "L4"]},
                    "constraints": {
                        "type": "array",
                        "items": S,
                        "description": "用户给出的关键约束，用于 0.8-C1 核对是否丢失",
                    },
                    "creative": {"type": "boolean"},
                    "multi_step": {"type": "boolean"},
                    "local_files": {"type": "boolean"},
                },
                "required": ["text"],
            },
        },
        {
            "name": "charter_arbitrate",
            "description": "按 0.5 冲突裁决规则判定两条互相冲突的陈述哪条占优，给出依据条款。当用户的两条说法矛盾、或事实与推测打架时使用。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "left": {**S, "description": "第一条陈述（按事实流处理）"},
                    "right": {**S, "description": "第二条陈述（按推测流处理）"},
                },
                "required": ["left", "right"],
            },
        },
        {
            "name": "charter_gate",
            "description": "查询「敏感度 × 权限」组合的安全闸门裁决（第十章）。当要判断某内容能否对外发送、是否需用户确认时使用。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sensitivity": {**S, "enum": ["公开", "隐私", "高危"]},
                    "permission": {**S, "enum": ["可输出", "仅内部", "禁外发"]},
                },
                "required": ["sensitivity", "permission"],
            },
        },
        {
            "name": "fcslint_analyze",
            "description": "对图像生成提示词执行《模块化特征簇标记语法》诊断：六大功能簇归类、权重梯度、冲突识别、控制力量化，并给出同范式的簇结构保留优化稿。当用户给出或要求优化 SD/MJ 类提示词时使用。",
            "inputSchema": {
                "type": "object",
                "properties": {"prompt": {**S, "description": "待诊断的提示词原文"}},
                "required": ["prompt"],
            },
        },
        {
            "name": "memory_deposit",
            "description": "把一条值得留存的结论沉淀为记忆节点（0.6-O1）。当用户说「记一下」「留个底」或出现稳定偏好、里程碑结论时使用。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {**S, "description": "要沉淀的内容"},
                    "key": {**S, "description": "记忆键，省略时自动生成"},
                    "tags": {"type": "array", "items": S},
                },
                "required": ["text"],
            },
        },
        {
            "name": "memory_recall",
            "description": "按关键词激活此前沉淀的记忆（0.6-O2）。当需要跨会话一致性、或用户提到「之前说过的」时使用。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {**S, "description": "检索关键词"},
                    "limit": {"type": "integer", "description": "返回条数，默认 5"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "anchor_solve",
            "description": "认知锚定·符号求解（宪章 12.1）：把多条件权衡变成 0/1 符号问题交给 z3 全枚举硬算，输出档位投票、变量频率、分支表与多轮漂移检测。当用户给出多个条件要权衡、且结论不能靠感觉时使用。需要可选依赖 z3-solver。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "declare": {**S, "description": "变量声明，逗号分隔，格式 变量:含义，如 x:可行性,y:预算充足"},
                    "constraints": {**S, "description": "硬约束，分号分隔的 z3 表达式，如 x+y>=2; Implies(y==0,w==1)"},
                    "decisions": {**S, "description": "候选档位，分号分隔，格式 档名:谓词，如 做:x+y>=3; 观望:x+y==2; 不做:x+y<2"},
                    "rounds": {**S, "description": "多轮对齐，| 分隔，段数=轮数；第 1 段通常留空"},
                    "max_solutions": {"type": "integer", "description": "枚举上限，默认 100"},
                },
                "required": ["declare", "constraints", "decisions"],
            },
        },
        {
            "name": "lexicon_search",
            "description": "检索宪章知识库（字典/语料/词条/风格/互联网亚文化，第十一章）。当需要确认某个词是否有依据、属于什么簇/类型/风格域时使用。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {**S, "description": "检索词"},
                    "kinds": {"type": "array", "items": S, "description": "限定词条类型，如 entity/abstract/style/meme/slang/register/community/practice"},
                    "limit": {"type": "integer", "description": "返回条数，默认 20"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "lexicon_mine",
            "description": "按需求 + 任务目标 + 语义状态深挖知识库（宪章 11.4）：返回加权词条、分布权重、特征级归因、安全闸门结论与特征簇标记建议。语义状态决定探索/收敛/创意/校验策略。当需要为一次生成任务系统性地找依据词条时使用。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "requirement": {**S, "description": "需求原文"},
                    "task_objectives": {"type": "array", "items": S, "description": "任务目标"},
                    "semantic_state": {**S, "description": "语义状态：探索期/收敛期/创意期/校验期，留空为中性"},
                    "domains": {"type": "array", "items": S, "description": "限定域，如 复古/亚文化/风格"},
                    "limit": {"type": "integer", "description": "返回词条数，默认 12"},
                    "allow_online": {"type": "boolean", "description": "是否允许在线扩容（默认否；为真时只报闸门结论不执行，10-R4）"},
                },
                "required": ["requirement"],
            },
        },
        {
            "name": "semantic_field",
            "description": "对一次深挖的候选集建构潜空间语义场（宪章 11.3）：关联网络、特征向量中心性、标签传播社群、覆盖缺口与密度/模块度。当需要判断哪些词条互为语境、谁是中枢、哪些需求维度还缺覆盖时使用。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "requirement": {**S, "description": "需求原文"},
                    "task_objectives": {"type": "array", "items": S, "description": "任务目标"},
                    "semantic_state": {**S, "description": "语义状态：探索期/收敛期/创意期/校验期"},
                    "domains": {"type": "array", "items": S, "description": "限定域"},
                    "limit": {"type": "integer", "description": "候选集大小，默认 30"},
                },
                "required": ["requirement"],
            },
        },
    ]


def _ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _text_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def dispatch(req: dict[str, Any], registry: ToolRegistry) -> dict[str, Any] | None:
    """处理单条 JSON-RPC 消息。通知（无 id）返回 None。"""
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return _ok(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        return _ok(req_id, {})

    if method == "tools/list":
        return _ok(req_id, {"tools": _tool_schemas()})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn: Callable[..., Any] | None = getattr(registry, name, None)
        if fn is None or name not in {t["name"] for t in _tool_schemas()}:
            return _ok(req_id, _text_result(f"未知工具：{name}", is_error=True))
        try:
            result = fn(**args)
        except TypeError as exc:
            return _ok(req_id, _text_result(f"参数错误：{exc}", is_error=True))
        except Exception as exc:  # pragma: no cover - 兜底
            return _ok(req_id, _text_result(f"{type(exc).__name__}: {exc}", is_error=True))
        return _ok(req_id, _text_result(result))

    return _err(req_id, -32601, f"未实现的方法：{method}")


def main() -> int:
    registry = ToolRegistry()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps(_err(None, -32700, "JSON 解析失败")) + "\n")
            sys.stdout.flush()
            continue

        # 支持批量
        batch = req if isinstance(req, list) else [req]
        for one in batch:
            resp = dispatch(one, registry)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

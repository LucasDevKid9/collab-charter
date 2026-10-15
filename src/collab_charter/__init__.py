"""collab-charter · 用户协作宪章的 Agent 执行内核。

把用户侧的《用户协作宪章》从一份提示词文档，变成 Agent 可加载、可调用、
可验证的执行层。所有规则以 ``charter/charter.yaml`` 为单一事实源。

公开 API::

    from collab_charter import Charter, Flow, FlowLayer, FlowType, Session

    charter = Charter.load()
    session = Session(charter, tools=my_tools)
    result = session.handle(user_message)
"""

from .charter_loader import Charter, CharterError, Clause
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
)
from .gates import GateDecision, SafetyGate, Verdict
from .arbiter import Arbiter, Conflict, Verdict_
from .memory import MemoryNode, MemoryStore
from .selfcheck import SelfCheckItem, SelfCheckReport, SelfCheckRunner
from .router import PipelineStage, Route, Router
from .session import Session, SessionOutcome
from .anchor import solve as anchor_solve
from .lexicon import (
    KnowledgeBase,
    KnowledgeBaseError,
    MiningRequest,
    MiningResult,
    StatePolicy,
    SemanticField,
    MeasureSpace,
)

__version__ = "3.3.0"
__charter_version__ = "3.2"

__all__ = [
    "__version__",
    "__charter_version__",
    # loader
    "Charter",
    "CharterError",
    "Clause",
    # flows
    "Flow",
    "FlowLayer",
    "FlowType",
    "Source",
    "Direction",
    "TTL",
    "Confidence",
    "Sensitivity",
    "Permission",
    "Destination",
    # gates
    "SafetyGate",
    "GateDecision",
    "Verdict",
    # arbiter
    "Arbiter",
    "Conflict",
    "Verdict_",
    # memory
    "MemoryStore",
    "MemoryNode",
    # selfcheck
    "SelfCheckRunner",
    "SelfCheckItem",
    "SelfCheckReport",
    # router
    "Router",
    "Route",
    "PipelineStage",
    # session
    "Session",
    "SessionOutcome",
    # anchor（12.1 符号锚定，cognitive-anchor v2.0 并入）
    "anchor_solve",
    # lexicon（11 知识库与语义场）
    "KnowledgeBase",
    "KnowledgeBaseError",
    "MeasureSpace",
    "SemanticField",
    "MiningRequest",
    "MiningResult",
    "StatePolicy",
]

"""信息流：宪章第〇章 0.1 / 0.2 的可执行形态。

一条流 = 一个**分层** × 一个**类型**，再挂 8 个元数据标签。
本模块只负责「流的定义与自检」；路由、裁决、记忆分别见 router / arbiter / memory。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class StrEnum(str, Enum):
    """Python 3.11 前后行为一致的字符串枚举基类。"""

    def __str__(self) -> str:  # pragma: no cover - 展示用
        return str(self.value)


class FlowLayer(StrEnum):
    """0.1 分层——流在系统中所处的环节。"""

    INPUT = "input"
    INTERNAL = "internal"
    MEMORY = "memory"
    TOOL = "tool"
    COMPUTE = "compute"
    OUTPUT = "output"
    FEEDBACK = "feedback"

    @property
    def zh(self) -> str:
        return _LAYER_ZH[self]


_LAYER_ZH = {
    FlowLayer.INPUT: "输入流",
    FlowLayer.INTERNAL: "内部认知流",
    FlowLayer.MEMORY: "记忆流",
    FlowLayer.TOOL: "工具流",
    FlowLayer.COMPUTE: "算力流",
    FlowLayer.OUTPUT: "输出流",
    FlowLayer.FEEDBACK: "反馈流",
}


class FlowType(StrEnum):
    """0.1 类型——流承载的内容性质。"""

    INSTRUCTION = "instruction"
    FACT = "fact"
    SPECULATION = "speculation"
    EMOTION = "emotion"
    KNOWLEDGE = "knowledge"
    DECISION = "decision"
    FEEDBACK = "feedback"

    @property
    def zh(self) -> str:
        return _TYPE_ZH[self]


_TYPE_ZH = {
    FlowType.INSTRUCTION: "指令流",
    FlowType.FACT: "事实流",
    FlowType.SPECULATION: "推测流",
    FlowType.EMOTION: "情感流",
    FlowType.KNOWLEDGE: "知识流",
    FlowType.DECISION: "决策流",
    FlowType.FEEDBACK: "反馈流",
}


class Source(StrEnum):
    """0.2 来源标签。"""

    USER_STATED = "用户明说"
    FILE_EVIDENCE = "文件实证"
    RETRIEVED = "检索所得"
    MODEL_PRIOR = "模型先验"
    MODEL_GUESS = "模型推测"


class Direction(StrEnum):
    """0.2 方向标签。"""

    INBOUND = "入"
    INTERNAL = "内部"
    OUTBOUND = "出"
    REFLOW = "回流"


class TTL(StrEnum):
    """0.2 时效标签。"""

    REALTIME = "实时"
    SESSION = "会话内"
    STABLE = "长期稳定"


class Confidence(StrEnum):
    """0.2 置信度标签。低置信流出前必须标「待验证」（0.7-R3）。"""

    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


class Sensitivity(StrEnum):
    """0.2 敏感度标签。驱动安全闸门（0.3 第 1 站）。"""

    PUBLIC = "公开"
    PRIVATE = "隐私"
    HIGH_RISK = "高危"


class Permission(StrEnum):
    """0.2 权限标签。隐私条款与本地文件条款的执行机关。"""

    OUTPUTTABLE = "可输出"
    INTERNAL_ONLY = "仅内部"
    NO_EGRESS = "禁外发"


class Destination(StrEnum):
    """0.2 去向标签——决定路由终点与沉淀。"""

    REPLY = "答复"
    MEMORY = "记忆沉淀"
    TOOL_CALL = "工具调用"


# 内部一致性护栏：0.1 / 0.2 的中文标签必须齐备（否则提示词渲染会缺字）
for _t in FlowType:
    assert _t.zh.endswith("流"), f"FlowType {_t.value} 缺少中文标签"
for _l in FlowLayer:
    assert _l.zh.endswith("流"), f"FlowLayer {_l.value} 缺少中文标签"


@dataclass
class Flow:
    """一条信息流。携带 0.2 要求的 8 个元数据标签。"""

    text: str
    layer: FlowLayer
    type: FlowType
    source: Source
    direction: Direction
    ttl: TTL
    confidence: Confidence
    sensitivity: Sensitivity = Sensitivity.PUBLIC
    permission: Permission = Permission.OUTPUTTABLE
    destination: Destination = Destination.REPLY
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    payload: dict[str, Any] = field(default_factory=dict)
    #: 被裁决过程改写时不丢原始值，便于回溯
    superseded_by: str | None = None
    notes: list[str] = field(default_factory=list)

    # -- 语义辅助 ---------------------------------------------------------
    @property
    def is_factual(self) -> bool:
        """0.5-R5：只有事实流参与事实裁决，情感流不参与。"""
        return self.type in (FlowType.FACT, FlowType.KNOWLEDGE)

    @property
    def needs_pending_mark(self) -> bool:
        """0.7-R3：低置信流出前必须标「待验证」。"""
        return self.confidence is Confidence.LOW

    @property
    def is_egress_capable(self) -> bool:
        return self.permission is not Permission.NO_EGRESS

    def with_confidence(self, confidence: Confidence, *, note: str = "") -> "Flow":
        """返回带新置信度的副本（0.6-O3 刷新记忆置信度）。"""
        clone = self.clone()
        clone.confidence = confidence
        if note:
            clone.notes.append(note)
        return clone

    def mark_pending(self) -> "Flow":
        """给低置信流补「待验证」标注。"""
        clone = self.clone()
        if clone.needs_pending_mark and "待验证" not in clone.text:
            clone.text = f"{clone.text}（待验证）"
            clone.notes.append("0.7-R3 补标注")
        return clone

    def clone(self) -> "Flow":
        import copy

        return copy.deepcopy(self)

    def meta(self) -> dict[str, Any]:
        """0.2 元数据快照。默认不向用户展示（0.2-V）。"""
        return {
            "id": self.id,
            "layer": self.layer.value,
            "layer_zh": self.layer.zh,
            "type": self.type.value,
            "source": self.source.value,
            "direction": self.direction.value,
            "ttl": self.ttl.value,
            "confidence": self.confidence.value,
            "sensitivity": self.sensitivity.value,
            "permission": self.permission.value,
            "destination": self.destination.value,
            "superseded_by": self.superseded_by,
        }

    def __repr__(self) -> str:  # pragma: no cover - 展示用
        return (
            f"<Flow {self.id} {self.layer.zh}×{self.type.zh} "
            f"conf={self.confidence.value} sens={self.sensitivity.value}>"
        )


def user_instruction(text: str, **kw: Any) -> Flow:
    """便捷构造：用户明说的一条指令流。"""
    base: dict[str, Any] = {
        "layer": FlowLayer.INPUT,
        "type": FlowType.INSTRUCTION,
        "source": Source.USER_STATED,
        "direction": Direction.INBOUND,
        "ttl": TTL.SESSION,
        "confidence": Confidence.HIGH,
    }
    base.update(kw)
    return Flow(text=text, **base)


def model_speculation(text: str, confidence: Confidence = Confidence.LOW, **kw: Any) -> Flow:
    """便捷构造：模型的一条推测流（默认低置信）。"""
    base: dict[str, Any] = {
        "layer": FlowLayer.INTERNAL,
        "type": FlowType.SPECULATION,
        "source": Source.MODEL_GUESS,
        "direction": Direction.INTERNAL,
        "ttl": TTL.SESSION,
        "confidence": confidence,
    }
    base.update(kw)
    return Flow(text=text, **base)


def retrieved_fact(text: str, source: Source = Source.RETRIEVED, **kw: Any) -> Flow:
    """便捷构造：检索所得的事实流。"""
    base: dict[str, Any] = {
        "layer": FlowLayer.INPUT,
        "type": FlowType.FACT,
        "source": source,
        "direction": Direction.INBOUND,
        "ttl": TTL.STABLE,
        "confidence": Confidence.HIGH,
    }
    base.update(kw)
    return Flow(text=text, **base)

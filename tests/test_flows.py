"""信息流定义与元数据标签（宪章 0.1 / 0.2）。"""

from __future__ import annotations

import pytest

from collab_charter import Charter
from collab_charter.flows import (
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
    model_speculation,
    user_instruction,
)


def test_分层与宪章一致(charter: Charter) -> None:
    declared = [x["id"] for x in charter.section("chapter_0_information_flow", "0.1_dimensions")["layers"]]
    assert declared == [l.value for l in FlowLayer], "0.1 分层与 FlowLayer 枚举不一致"


def test_类型与宪章一致(charter: Charter) -> None:
    declared = [x["id"] for x in charter.section("chapter_0_information_flow", "0.1_dimensions")["types"]]
    assert declared == [t.value for t in FlowType], "0.1 类型与 FlowType 枚举不一致"


def test_八个元数据标签齐备(charter: Charter) -> None:
    labels = [x["id"] for x in charter.section("chapter_0_information_flow", "0.2_metadata_labels")["labels"]]
    assert labels == [
        "source", "type", "direction", "ttl",
        "confidence", "sensitivity", "permission", "destination",
    ]


def test_标签取值与宪章一致(charter: Charter) -> None:
    labels = {
        x["id"]: x.get("values", [])
        for x in charter.section("chapter_0_information_flow", "0.2_metadata_labels")["labels"]
    }
    assert labels["source"] == [s.value for s in Source]
    assert labels["direction"] == [d.value for d in Direction]
    assert labels["ttl"] == [t.value for t in TTL]
    assert labels["confidence"] == [c.value for c in Confidence]
    assert labels["sensitivity"] == [s.value for s in Sensitivity]
    assert labels["permission"] == [p.value for p in Permission]
    assert labels["destination"] == [d.value for d in Destination]


def test_中文标签齐备() -> None:
    for layer in FlowLayer:
        assert layer.zh.endswith("流")
    for ftype in FlowType:
        assert ftype.zh.endswith("流")


def test_元数据快照含全部标签() -> None:
    f = user_instruction("测试")
    meta = f.meta()
    for key in (
        "layer", "type", "source", "direction", "ttl",
        "confidence", "sensitivity", "permission", "destination",
    ):
        assert key in meta


def test_情感流不参与事实裁决的依据字段() -> None:
    emo = Flow(
        text="我有点焦虑", layer=FlowLayer.INPUT, type=FlowType.EMOTION,
        source=Source.USER_STATED, direction=Direction.INBOUND,
        ttl=TTL.SESSION, confidence=Confidence.HIGH,
    )
    assert emo.is_factual is False, "0.5-R5：情感流不得被当作事实"


def test_低置信需要待验证标注() -> None:
    spec = model_speculation("可能是 3.2 版本")
    assert spec.needs_pending_mark is True, "0.7-R3：低置信流出前必须标待验证"
    marked = spec.mark_pending()
    assert "待验证" in marked.text
    assert "待验证" not in spec.text, "标注必须是副本，不得就地改写原流"


def test_高置信不需要待验证标注() -> None:
    fact = user_instruction("需求是重构")
    assert fact.needs_pending_mark is False
    assert "待验证" not in fact.mark_pending().text


def test_禁外发的流不可外发() -> None:
    f = user_instruction("内部资料", permission=Permission.NO_EGRESS, sensitivity=Sensitivity.PRIVATE)
    assert f.is_egress_capable is False


def test_便捷构造器语义正确() -> None:
    a = user_instruction("x")
    assert (a.layer, a.type, a.source) == (FlowLayer.INPUT, FlowType.INSTRUCTION, Source.USER_STATED)

    b = model_speculation("x")
    assert (b.layer, b.source, b.confidence) == (FlowLayer.INTERNAL, Source.MODEL_GUESS, Confidence.LOW)

"""记忆流：0.6 的沉淀、再激活、衰减与刷新。"""

from __future__ import annotations

import time

import pytest

from collab_charter.flows import (
    Confidence,
    Destination,
    Direction,
    Flow,
    FlowLayer,
    FlowType,
    Sensitivity,
    Source,
    TTL,
)
from collab_charter.memory import HALF_LIFE, MemoryStore


def _mem(text: str, **kw) -> Flow:
    base = dict(
        layer=FlowLayer.MEMORY, type=FlowType.KNOWLEDGE, source=Source.USER_STATED,
        direction=Direction.INTERNAL, ttl=TTL.STABLE, confidence=Confidence.HIGH,
    )
    base.update(kw)
    return Flow(text=text, **base)


# -- 0.6-O1 沉淀 -----------------------------------------------------------
def test_沉淀生成记忆节点(memory: MemoryStore) -> None:
    node = memory.deposit(_mem("用户偏好先结论后展开"), "pref.answer", tags=["偏好"])
    assert node.key == "pref.answer"
    assert node.tags == ["偏好"]
    assert len(memory) == 1


def test_隐私字段自动标记(memory: MemoryStore) -> None:
    node = memory.deposit(_mem("内部信息", sensitivity=Sensitivity.PRIVATE))
    assert node.private is True
    assert len(memory.private_nodes) == 1


def test_重复沉淀同键更新而非新增(memory: MemoryStore) -> None:
    memory.deposit(_mem("v1"), "k1")
    first = memory.deposit(_mem("v2"), "k1")
    assert first.text == "v2"
    assert len(memory) == 1, "同键应更新而非堆叠"
    assert first.created_at <= first.updated_at


def test_带标签沉淀可被标签检索(memory: MemoryStore) -> None:
    memory.deposit(_mem("项目 A 的里程碑"), "m.pa", tags=["项目A", "里程碑"])
    hits = memory.recall(tags=["项目A"])
    assert len(hits) == 1


# -- 0.6-O2 再激活 ---------------------------------------------------------
def test_再激活还原为带元数据的流(memory: MemoryStore) -> None:
    memory.deposit(_mem("关键结论：先过闸再断言"), "c1")
    flows = memory.recall("关键结论")
    assert len(flows) == 1
    f = flows[0]
    assert f.layer is FlowLayer.MEMORY, "0.6-O2 要求还原为流，而非原文照搬"
    assert f.confidence is Confidence.HIGH
    assert f.payload["memory_key"] == "c1"
    assert any("recall" in n for n in f.notes)


def test_空查询返回最近记忆(memory: MemoryStore) -> None:
    memory.deposit(_mem("a"), "a")
    memory.deposit(_mem("b"), "b")
    flows = memory.recall("", limit=2)
    assert len(flows) == 2


def test_检索不到时返回空(memory: MemoryStore) -> None:
    memory.deposit(_mem("关于甲的内容"), "x")
    assert memory.recall("完全无关的词") == []


# -- 0.6-O3 衰减与刷新 -----------------------------------------------------
def test_长期稳定不衰减() -> None:
    assert HALF_LIFE[TTL.STABLE] is None
    store = MemoryStore()
    node = store.deposit(_mem("长期偏好"), "p")
    # 人为把时间推到很久以后
    node.updated_at = time.time() - 10 * 365 * 86400
    assert node.decayed_confidence() is Confidence.HIGH


def test_会话内记忆按半衰期衰减() -> None:
    store = MemoryStore()
    node = store.deposit(_mem("会话内约定", ttl=TTL.SESSION), "s")
    node.updated_at = time.time() - HALF_LIFE[TTL.SESSION] * 1.1  # 过了一个半衰期
    assert node.decayed_confidence() is Confidence.MEDIUM


def test_衰减可级联到最低档() -> None:
    store = MemoryStore()
    node = store.deposit(_mem("实时信息", ttl=TTL.REALTIME), "r")
    node.updated_at = time.time() - HALF_LIFE[TTL.REALTIME] * 5
    assert node.decayed_confidence() is Confidence.LOW


def test_decay_写回并留痕(memory: MemoryStore) -> None:
    node = memory.deposit(_mem("会衰减", ttl=TTL.REALTIME), "d")
    node.updated_at = time.time() - HALF_LIFE[TTL.REALTIME] * 1.1  # 刚过一个半衰期
    changed = memory.decay()
    assert len(changed) == 1
    assert changed[0].confidence is Confidence.MEDIUM
    kinds = [c["kind"] for c in changed[0].corrections]
    assert "decay" in kinds


def test_用户纠正刷新为高置信并记录来源(memory: MemoryStore) -> None:
    memory.deposit(_mem("旧说法"), "k")
    node = memory.correct("k", "新说法", by="用户纠正")
    assert node.text == "新说法"
    assert node.confidence is Confidence.HIGH
    assert node.source is Source.USER_STATED
    assert node.corrections[-1]["kind"] == "correction"
    assert node.corrections[-1]["from"] == "旧说法"


def test_纠正不存在的键必须报错(memory: MemoryStore) -> None:
    with pytest.raises(KeyError):
        memory.correct("nope", "x")


# -- 持久化 ----------------------------------------------------------------
def test_落盘与重载(tmp_path) -> None:
    path = tmp_path / "memory.json"
    s1 = MemoryStore(path)
    s1.deposit(_mem("要留存的结论"), "keep", tags=["t"])
    assert path.is_file()

    s2 = MemoryStore(path)
    assert len(s2) == 1
    flows = s2.recall("留存")
    assert flows and flows[0].payload["memory_key"] == "keep"

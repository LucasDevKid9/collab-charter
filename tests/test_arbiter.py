"""裁决器：0.4 优先级阶梯 + 0.5 冲突裁决规则。"""

from __future__ import annotations

import pytest

from collab_charter import Charter
from collab_charter.arbiter import Arbiter, Dimension, EVAL_ORDER, Verdict_
from collab_charter.flows import (
    Confidence,
    Direction,
    Flow,
    FlowLayer,
    FlowType,
    Source,
    TTL,
)
from collab_charter.charter_loader import CharterError


def _f(text: str, ftype: FlowType, conf: Confidence = Confidence.HIGH, src: Source = Source.USER_STATED) -> Flow:
    return Flow(
        text=text, layer=FlowLayer.INTERNAL, type=ftype, source=src,
        direction=Direction.INTERNAL, ttl=TTL.SESSION, confidence=conf,
    )


# -- 0.4 优先级阶梯 --------------------------------------------------------
def test_优先级阶梯与宪章一致(charter: Charter) -> None:
    ladder = charter.section("chapter_0_information_flow", "0.4_priority")["ladder"]
    assert [x["id"] for x in ladder] == ["safety", "truth", "user_goal", "concision", "format"]


def test_安全高于真实(charter: Charter) -> None:
    a = Arbiter(charter)
    assert a.weigh(Dimension.SAFETY, Dimension.TRUTH) is Dimension.SAFETY


def test_真实高于用户目标(charter: Charter) -> None:
    a = Arbiter(charter)
    assert a.weigh(Dimension.TRUTH, Dimension.USER_GOAL) is Dimension.TRUTH


def test_降级顺序先牺牲格式(charter: Charter) -> None:
    a = Arbiter(charter)
    order = a.degradation_order()
    assert order[0] is Dimension.FORMAT
    assert order[-1] is Dimension.SAFETY


def test_安全与真实不可牺牲(charter: Charter) -> None:
    a = Arbiter(charter)
    assert a.can_sacrifice(Dimension.FORMAT) is True
    assert a.can_sacrifice(Dimension.TRUTH) is False
    assert a.can_sacrifice(Dimension.SAFETY) is False


# -- 0.5 冲突裁决 ----------------------------------------------------------
def test_事实优于推测(charter: Charter) -> None:
    a = Arbiter(charter)
    c = a.compare(
        _f("事实", FlowType.FACT),
        _f("猜测", FlowType.SPECULATION, src=Source.MODEL_GUESS),
    )
    assert c.verdict is Verdict_.LEFT
    assert c.clause == "0.5-R1"


def test_高置信优于低置信(charter: Charter) -> None:
    a = Arbiter(charter)
    c = a.compare(
        _f("a", FlowType.FACT, Confidence.HIGH),
        _f("b", FlowType.FACT, Confidence.LOW),
    )
    assert c.verdict is Verdict_.LEFT
    assert c.dimension == "置信度"


def test_用户显式陈述优于模型推测(charter: Charter) -> None:
    a = Arbiter(charter)
    c = a.compare(
        _f("用户说的", FlowType.FACT, Confidence.MEDIUM, Source.USER_STATED),
        _f("模型推的", FlowType.FACT, Confidence.MEDIUM, Source.MODEL_GUESS),
    )
    assert c.verdict is Verdict_.LEFT
    assert c.clause == "0.5-R3"


def test_新信息优于旧信息(charter: Charter) -> None:
    a = Arbiter(charter)
    old = _f("旧", FlowType.FACT, Confidence.HIGH, Source.FILE_EVIDENCE)
    new = _f("新", FlowType.FACT, Confidence.HIGH, Source.FILE_EVIDENCE)
    c = a.compare(old, new, a_recency=1.0, b_recency=2.0)
    assert c.verdict is Verdict_.RIGHT
    assert c.clause == "0.5-R2"


def test_稳定偏好豁免新旧规则(charter: Charter) -> None:
    a = Arbiter(charter)
    old_pref = _f("我偏好简洁", FlowType.FACT, Confidence.HIGH, Source.USER_STATED)
    newer = _f("这次想详细", FlowType.FACT, Confidence.HIGH, Source.USER_STATED)
    c = a.compare(old_pref, newer, a_recency=1.0, b_recency=2.0, a_is_stable_preference=True)
    assert c.verdict is Verdict_.LEFT
    assert "豁免" in c.reason


def test_安全约束豁免新旧规则(charter: Charter) -> None:
    a = Arbiter(charter)
    c = a.compare(
        _f("不可外发", FlowType.FACT, Confidence.HIGH, Source.USER_STATED),
        _f("这次发出去", FlowType.FACT, Confidence.HIGH, Source.USER_STATED),
        a_recency=1.0, b_recency=9.0, a_is_safety_constraint=True,
    )
    assert c.verdict is Verdict_.LEFT


def test_同级同源并列呈现(charter: Charter) -> None:
    a = Arbiter(charter)
    c = a.compare(
        _f("方案甲", FlowType.FACT),
        _f("方案乙", FlowType.FACT),
    )
    assert c.verdict is Verdict_.EX_AEQUO
    assert c.clause == "0.5-R4"
    assert c.needs_user_tiebreak is True


def test_情感流不参与事实裁决(charter: Charter) -> None:
    a = Arbiter(charter)
    c = a.compare(
        _f("我好烦", FlowType.EMOTION),
        _f("这是事实", FlowType.FACT),
    )
    assert c.clause == "0.5-R5"
    assert c.verdict is Verdict_.RIGHT, "事实流应胜出，情感流只调节表达权重"


def test_批量裁决保留幸存者(charter: Charter) -> None:
    a = Arbiter(charter)
    flows = [
        _f("推测", FlowType.SPECULATION, src=Source.MODEL_GUESS),
        _f("事实", FlowType.FACT),
    ]
    r = a.arbitrate(flows)
    assert len(r.survivors) == 1
    assert r.survivors[0].text == "事实"
    assert len(r.dropped) == 1


def test_并列时最多只问一次(charter: Charter) -> None:
    a = Arbiter(charter)
    flows = [
        _f("甲", FlowType.FACT),
        _f("乙", FlowType.FACT),
        _f("丙", FlowType.FACT),
    ]
    r = a.arbitrate(flows)
    assert len(r.tiebreak_questions) <= 1, "0.5-R4 限定一次最多 1 问"


def test_空输入不报错(charter: Charter) -> None:
    a = Arbiter(charter)
    r = a.arbitrate([])
    assert r.survivors == []
    assert r.conflicts == []


def test_评估顺序与宪章SSOT一致(charter: Charter) -> None:
    """0.5 评估顺序必须被 Arbiter 启动断言锁住（防漂移）。"""
    a = Arbiter(charter)  # 顺序一致时应正常构建
    declared = charter.section("chapter_0_information_flow", "0.5_arbitration")
    assert [str(x) for x in declared["eval_order"]] == list(EVAL_ORDER)


def test_评估顺序漂移时立即报错(charter: Charter) -> None:
    """改宪章不改代码，或改代码不改宪章，都要立即抛错——绝不静默跑偏。"""
    # 用一个伪造的 charter 视图：eval_order 与代码不一致
    class _Bad(Charter):
        def section(self, chapter_key, section_key):
            if section_key == "0.5_arbitration":
                return {"eval_order": ["0.5-R5", "0.5-R1", "0.5-R4", "0.5-R2", "0.5-R3"]}
            return super().section(chapter_key, section_key)

    bad = _Bad(raw=charter.raw, clauses=charter.clauses, source=charter.source)
    with pytest.raises(CharterError):
        Arbiter(bad)


def test_新用户陈述优先于旧模型事实(charter: Charter) -> None:
    """R2 先于 R3：新用户陈述 vs 旧模型事实 → 新信息优先（除非豁免）。"""
    a = Arbiter(charter)
    old_model = _f("旧模型事实", FlowType.FACT, Confidence.HIGH, Source.MODEL_GUESS)
    new_user = _f("新用户陈述", FlowType.FACT, Confidence.HIGH, Source.USER_STATED)
    c = a.compare(old_model, new_user, a_recency=1.0, b_recency=2.0)
    assert c.verdict is Verdict_.RIGHT
    assert c.clause == "0.5-R2"

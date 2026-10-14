"""路由管线、自检与会话门面（0.3 / 0.7 / 0.8 / 0.9 / 第一章）。"""

from __future__ import annotations

import pytest

from collab_charter import Charter, Session
from collab_charter.flows import (
    Confidence,
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
from collab_charter.memory import MemoryStore
from collab_charter.router import FAST_PIPELINE, FULL_PIPELINE, PipelineStage, Router, TaskLevel
from collab_charter.selfcheck import SelfCheckRunner


# -- 0.3 管线结构 ----------------------------------------------------------
def test_八站与宪章一致(charter: Charter) -> None:
    declared = [
        s["id"] for s in charter.section("chapter_0_information_flow", "0.3_pipeline")["stages"]
    ]
    assert declared == [s.value for s in PipelineStage]
    assert len(declared) == 8


def test_构造即校验_station_一致性(charter: Charter) -> None:
    # Router.__init__ 内部会做一致性断言，构造成功即通过
    Router(charter)


def test_快速通道是三个站(charter: Charter) -> None:
    assert FAST_PIPELINE == (PipelineStage.SAFETY_GATE, PipelineStage.INTENT, PipelineStage.EMIT)


# -- 0.9 路由决策 ----------------------------------------------------------
def test_L1_走快速通道(charter: Charter) -> None:
    r = Router(charter).plan(level=TaskLevel.L1, user_text="今天几号")
    assert r.fast_path is True
    assert "L1" in r.reason


def test_快速词走快速通道(charter: Charter) -> None:
    r = Router(charter).plan(level=TaskLevel.L3, user_text="快速回答我")
    assert r.fast_path is True
    assert "快速" in r.reason


def test_深挖词强制全量(charter: Charter) -> None:
    r = Router(charter).plan(level=TaskLevel.L1, user_text="深挖一下这个问题")
    assert r.fast_path is False
    assert "深挖" in r.reason


@pytest.mark.parametrize("kw,label", [
    ({"has_creative_output": True}, "创造性产出"),
    ({"has_multi_step_plan": True}, "多步计划"),
    ({"has_local_files": True}, "本地文件"),
])
def test_三类任务强制全量(charter: Charter, kw: dict, label: str) -> None:
    r = Router(charter).plan(level=TaskLevel.L1, user_text="随便", **kw)
    assert r.fast_path is False
    assert label in r.reason


def test_默认走全量(charter: Charter) -> None:
    r = Router(charter).plan(level=TaskLevel.L2, user_text="帮我看看这个")
    assert r.fast_path is False


# -- 0.3-I3 不过闸即终止 ---------------------------------------------------
def test_不过闸时管线终止(charter: Charter) -> None:
    router = Router(charter)
    blocked = Flow(
        text="机密", layer=FlowLayer.INPUT, type=FlowType.FACT, source=Source.USER_STATED,
        direction=Direction.INBOUND, ttl=TTL.SESSION, confidence=Confidence.HIGH,
        sensitivity=Sensitivity.PRIVATE, permission=Permission.NO_EGRESS,
    )
    run, emitted = router.execute([blocked])
    assert run.terminated_at is PipelineStage.SAFETY_GATE
    assert emitted == []
    assert run.completed is False
    # 只应执行到第 1 站
    assert len(run.records) == 1


# -- 0.3-I2 认知镜像 -------------------------------------------------------
def test_全量路由包含认知镜像(charter: Charter) -> None:
    router = Router(charter)
    run, _ = router.execute([user_instruction("帮我重构这个模块")], route=router.plan(level=TaskLevel.L2))
    assert run.mirror_text
    assert "我理解你要的是" in run.mirror_text


def test_快速通道跳过认知镜像(charter: Charter) -> None:
    router = Router(charter)
    route = router.plan(level=TaskLevel.L1, user_text="1+1")
    assert PipelineStage.MIRROR not in route.stages


# -- 0.7 输出过滤 ----------------------------------------------------------
def test_内部流不进入输出(charter: Charter) -> None:
    router = Router(charter)
    run, emitted = router.execute(
        [user_instruction("分析一下")],
        route=router.plan(level=TaskLevel.L2),
    )
    # 角色协作产生的内部流应被标记且不进入输出（0.7-R1 / 0.7 六件套）
    council = next(r for r in run.records if r.stage is PipelineStage.COUNCIL)
    assert "三角视角" in council.detail
    assert all(not f.payload.get("internal_only") for f in emitted)


def test_低置信流出前补待验证(charter: Charter) -> None:
    router = Router(charter)
    run, emitted = router.execute(
        [user_instruction("查一下"), model_speculation("可能是 3.2")],
        route=router.plan(level=TaskLevel.L2),
    )
    low = [f for f in emitted if f.confidence is Confidence.LOW]
    assert low, "应有一条低置信流"
    assert all("待验证" in f.text for f in low), "0.7-R3：低置信流出前必须标注"


# -- 0.8 自检 --------------------------------------------------------------
def test_自检六项与宪章一致(charter: Charter) -> None:
    declared = [
        i["id"] for i in charter.section("chapter_0_information_flow", "0.8_selfcheck")["items"]
    ]
    assert declared == list(SelfCheckRunner.CLAUSE_IDS)


def test_未回流时自检失败(charter: Charter) -> None:
    runner = SelfCheckRunner(charter)
    report = runner.run(
        flows=[user_instruction("x")],
        decisions=[],  # 空裁决 → C5 失败
        output_text="x",
        memory_updated=False,  # C4 失败
    )
    failed_ids = {i.id for i in report.failures}
    assert "0.8-C4" in failed_ids
    assert "0.8-C5" in failed_ids
    assert report.passed is False
    assert "回流前自检未通过" in report.explain()


def test_约束丢失被检出(charter: Charter) -> None:
    runner = SelfCheckRunner(charter)
    report = runner.run(
        flows=[user_instruction("重构")],
        decisions=[_allow_dummy()],
        output_text="我会重构这个模块",
        memory_updated=True,
        constraints=["保持API兼容"],
    )
    assert any(i.id == "0.8-C1" and not i.passed for i in report.items)


def test_不可追溯的事实流被检出(charter: Charter) -> None:
    runner = SelfCheckRunner(charter)
    bad = Flow(
        text="某事实", layer=FlowLayer.INTERNAL, type=FlowType.FACT, source=Source.MODEL_GUESS,
        direction=Direction.INTERNAL, ttl=TTL.SESSION, confidence=Confidence.HIGH,
    )
    report = runner.run(
        flows=[bad], decisions=[_allow_dummy()], output_text="某事实", memory_updated=True,
    )
    assert any(i.id == "0.8-C3" and not i.passed for i in report.items)


def test_全部通过时报告为空(charter: Charter) -> None:
    runner = SelfCheckRunner(charter)
    report = runner.run(
        flows=[user_instruction("重构")],
        decisions=[_allow_dummy()],
        output_text="重构",
        memory_updated=True,
    )
    assert report.passed is True
    assert report.explain() == ""


def _allow_dummy():
    from collab_charter.gates import GateDecision, Verdict

    return GateDecision(flow_id="dummy", verdict=Verdict.ALLOW, reason="ok", clause="0.3")


# -- 第一章：接收自检 ------------------------------------------------------
def test_receipt_不超过三行(session: Session) -> None:
    lines = session.receipt().splitlines()
    assert len(lines) <= 3, "1-C1：自检输出不超过 3 行"


def test_receipt_无寒暄(session: Session) -> None:
    text = session.receipt()
    for bad in ("你好", "很高兴", "有什么可以帮"):
        assert bad not in text


def test_声明不可执行时附降级方案(session: Session, charter: Charter) -> None:
    s = Session(charter, agent_cannot=["0.6-O1"])
    text = s.receipt()
    assert "0.6-O1" in text
    assert "降级" in text


def test_声明不存在的条款必须报错(charter: Charter) -> None:
    from collab_charter.charter_loader import CharterError

    with pytest.raises(CharterError):
        Session(charter, agent_cannot=["9-Z9"])


# -- Session 门面 ----------------------------------------------------------
def test_handle_返回完整结果(session: Session) -> None:
    out = session.handle("帮我分析这个架构方案")
    assert out.run.route is not None
    assert out.trace
    assert out.text
    assert out.mirror


def test_简化快捷词压缩输出(session: Session) -> None:
    out = session.handle("详细分析一下这个方案，然后简化", constraints=[""])
    assert len(out.flows) <= 2


def test_快捷词被识别(session: Session) -> None:
    out = session.handle("深挖一下这个问题")
    assert any("深挖" in x for x in out.shortcut_effects)


def test_reflow_后自检通过(session: Session) -> None:
    session.handle("记录一下结论")
    session.reflow()
    out = session.handle("再确认一次", constraints=[])
    assert out.selfcheck is not None
    assert out.selfcheck.passed is True, out.explain_failures()


def test_工具注册与调用(session: Session) -> None:
    from collab_charter.session import ToolSpec

    session.register_tool(ToolSpec("search", "检索", lambda q: f"结果:{q}", {"q": {"type": "string"}}))
    flow = session.call_tool("search", q="z3")
    assert flow.layer is FlowLayer.TOOL
    assert "结果:z3" in flow.text


def test_未注册工具报错(session: Session) -> None:
    from collab_charter.charter_loader import CharterError

    with pytest.raises(CharterError):
        session.call_tool("nope")


def test_工具_schema_可导出(session: Session) -> None:
    from collab_charter.session import ToolSpec

    session.register_tool(ToolSpec("t", "d", lambda: 1))
    schemas = session.tool_schemas()
    assert schemas[0]["name"] == "t"
    assert "input_schema" in schemas[0]


def test_元数据默认不展示(session: Session) -> None:
    session.handle("随便聊聊")
    meta = session.debug_meta()
    assert meta and "confidence" in meta[0]

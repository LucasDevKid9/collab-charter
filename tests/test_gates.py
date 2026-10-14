"""安全闸门（0.3 第 1 站 / 第十章）。"""

from __future__ import annotations

import pytest

from collab_charter import Charter
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
)
from collab_charter.gates import SafetyGate, Verdict


def _flow(sens: Sensitivity, perm: Permission) -> Flow:
    return Flow(
        text="probe", layer=FlowLayer.OUTPUT, type=FlowType.KNOWLEDGE,
        source=Source.MODEL_PRIOR, direction=Direction.OUTBOUND,
        ttl=TTL.SESSION, confidence=Confidence.HIGH,
        sensitivity=sens, permission=perm,
    )


def test_闸门矩阵覆盖九种组合(charter: Charter) -> None:
    matrix = charter.section("enforcement", "gate_matrix")
    combos = {(r["sensitivity"], r["permission"]) for r in matrix}
    expected = {(s.value, p.value) for s in Sensitivity for p in Permission}
    assert combos == expected, f"未覆盖组合：{expected - combos}"


@pytest.mark.parametrize("sens,perm", [(s, p) for s in Sensitivity for p in Permission])
def test_每种组合都有裁决(charter: Charter, sens: Sensitivity, perm: Permission) -> None:
    gate = SafetyGate(charter)
    d = gate.inspect(_flow(sens, perm))
    assert isinstance(d.verdict, Verdict)
    assert d.reason


def test_禁外发一律拦截(charter: Charter) -> None:
    gate = SafetyGate(charter)
    for sens in Sensitivity:
        d = gate.inspect(_flow(sens, Permission.NO_EGRESS))
        assert d.verdict is Verdict.BLOCK, f"{sens.value} × 禁外发 应拦截"
        assert d.terminates is True, "0.3-I3：拦截必须终止后续站"


def test_高危需要用户确认(charter: Charter) -> None:
    gate = SafetyGate(charter)
    d = gate.inspect(_flow(Sensitivity.HIGH_RISK, Permission.OUTPUTTABLE))
    assert d.verdict is Verdict.CONFIRM
    assert d.needs_user_input is True
    assert d.passed is False, "待确认不算已过闸"


def test_公开可输出直接放行(charter: Charter) -> None:
    gate = SafetyGate(charter)
    d = gate.inspect(_flow(Sensitivity.PUBLIC, Permission.OUTPUTTABLE))
    assert d.verdict is Verdict.ALLOW
    assert d.passed is True
    assert d.terminates is False


def test_仅内部放行的流不得进入输出(charter: Charter) -> None:
    gate = SafetyGate(charter)
    flows = [_flow(Sensitivity.PRIVATE, Permission.INTERNAL_ONLY), _flow(Sensitivity.PUBLIC, Permission.OUTPUTTABLE)]
    decisions = gate.inspect_all(flows)
    internal = gate.internal_only_ids(decisions)
    assert flows[0].id in internal
    assert flows[1].id not in internal


def test_任一拦截即终止管线(charter: Charter) -> None:
    gate = SafetyGate(charter)
    decisions = gate.inspect_all([
        _flow(Sensitivity.PUBLIC, Permission.OUTPUTTABLE),
        _flow(Sensitivity.PRIVATE, Permission.NO_EGRESS),
    ])
    assert SafetyGate.blocks_pipeline(decisions) is True


def test_待确认可被单独取出(charter: Charter) -> None:
    gate = SafetyGate(charter)
    decisions = gate.inspect_all([
        _flow(Sensitivity.HIGH_RISK, Permission.OUTPUTTABLE),
        _flow(Sensitivity.PUBLIC, Permission.OUTPUTTABLE),
    ])
    pending = gate.pending_confirmation(decisions)
    assert len(pending) == 1


def test_拦截时给出解释与替代(charter: Charter) -> None:
    gate = SafetyGate(charter)
    d = gate.inspect(_flow(Sensitivity.HIGH_RISK, Permission.NO_EGRESS))
    msg = d.explain()
    assert "拦截" in msg
    assert "替代" in msg or "改用" in msg, "第十章要求用「解释 + 替代」取代生硬拒绝"


def test_剥离只对禁外发生效(charter: Charter) -> None:
    gate = SafetyGate(charter)
    blocked = gate.strip(_flow(Sensitivity.PUBLIC, Permission.NO_EGRESS))
    assert "剥离" in blocked.notes[-1]
    assert blocked.permission is Permission.INTERNAL_ONLY

    normal = gate.strip(_flow(Sensitivity.PUBLIC, Permission.OUTPUTTABLE))
    assert normal.text == "probe"
    assert normal.notes == []

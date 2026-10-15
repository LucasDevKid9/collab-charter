"""治理内核：DecisionRecord + AuditLedger + Replay（最终优化·第一梯队）。

覆盖：
* DecisionRecord：闸门 / 仲裁 / 管线拦截三路构造、序列化往返、explain。
* PipelineRun.decisions：handle() 自动挂载。
* AuditLedger：append-only、按 session 读取、决策提取、seq 跨重启递增。
* Replay CLI：会话列表 / 回放 / why / json。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from collab_charter import Charter, Session
from collab_charter.arbiter import Conflict, Verdict_
from collab_charter.audit import AuditEvent, AuditLedger
from collab_charter.cli import cmd_replay
from collab_charter.flows import retrieved_fact, user_instruction
from collab_charter.gates import GateDecision, SafetyGate, Verdict
from collab_charter.governance import DecisionRecord, collect_arbitration_records


# -- DecisionRecord -------------------------------------------------------
def test_gate_record_fields(charter: Charter) -> None:
    gate = SafetyGate(charter)
    f = user_instruction("正常指令")
    d = gate.inspect(f)
    rec = DecisionRecord.from_gate(d)
    assert rec.outcome == "allow"
    assert rec.event == "pre_flow"
    assert rec.clause_ids == ["0.3"]
    assert rec.explanation  # 非空
    assert rec.trace_id  # 有 trace


def test_block_gate_record(charter: Charter) -> None:
    # 构造一条会被拦截的流：高危 + 禁外发（直接构造裁决，不必走真实组合）
    f = user_instruction(
        "含高危内容",
        sensitivity=__import__("collab_charter.flows", fromlist=["Sensitivity"]).Sensitivity.HIGH_RISK,
        permission=__import__("collab_charter.flows", fromlist=["Permission"]).Permission.NO_EGRESS,
    )
    gate = SafetyGate(charter)
    d = gate.inspect(f)
    rec = DecisionRecord.from_gate(d)
    assert rec.outcome in ("deny", "ask")
    assert rec.clause_ids  # 有条款依据


def test_conflict_record() -> None:
    c = Conflict("a", "b", "时效", Verdict_.LEFT, "0.5-R2", "新信息优先于旧信息")
    rec = DecisionRecord.from_conflict(c)
    assert rec.outcome == "deny"
    assert rec.clause_ids == ["0.5-R2"]
    assert "时效" in rec.explanation


def test_arbitration_collection() -> None:
    conflicts = [
        Conflict("a", "b", "事实 vs 推测", Verdict_.LEFT, "0.5-R1", "事实流优先于推测流"),
    ]
    from collab_charter.arbiter import ArbitrationResult

    arb = ArbitrationResult(conflicts=conflicts, tiebreak_questions=["请指定以哪条为准"])
    recs = collect_arbitration_records(arb)
    assert len(recs) == 2  # 1 冲突 + 1 并列询问
    assert any(r.outcome == "ask" for r in recs)


def test_record_serialization_roundtrip() -> None:
    rec = DecisionRecord.from_stage(stage="safety_gate", detail="拦截", clause="0.3-I3", ok=False)
    d = rec.to_dict()
    back = DecisionRecord.from_dict(d)
    assert back.decision_id == rec.decision_id
    assert back.outcome == rec.outcome
    assert back.explanation == rec.explanation
    assert back.trace_id == rec.trace_id


def test_pipeline_run_attaches_decisions(charter: Charter) -> None:
    s = Session(charter, audit=False)
    out = s.handle("帮我查一下 z3 最新版本")
    assert isinstance(out.decisions, list)
    assert len(out.decisions) >= 1
    assert all(isinstance(d, DecisionRecord) for d in out.decisions)


# -- AuditLedger ----------------------------------------------------------
def test_ledger_append_and_read(tmp_path) -> None:
    ledger = AuditLedger(tmp_path / "audit")
    ev = ledger.record_pipeline("sess-1", route="Route(全量)", decisions=[])
    assert ev.seq == 1
    read_back = ledger.read("sess-1")
    assert len(read_back) == 1
    assert read_back[0].seq == 1
    assert read_back[0].session_id == "sess-1"


def test_ledger_seq_increments_across_restart(tmp_path) -> None:
    ledger = AuditLedger(tmp_path / "audit")
    ledger.record_pipeline("s-a", decisions=[])
    ledger.record_pipeline("s-b", decisions=[])
    # 重启（新实例，同一目录）应恢复 seq，不重号
    ledger2 = AuditLedger(tmp_path / "audit")
    ev = ledger2.record_pipeline("s-c", decisions=[])
    assert ev.seq == 3


def test_ledger_decisions_of(tmp_path, charter: Charter) -> None:
    ledger = AuditLedger(tmp_path / "audit")
    s = Session(charter, audit=ledger, session_id="demo")
    s.handle("帮我查一下 z3 最新版本")
    decs = ledger.decisions_of("demo")
    assert len(decs) >= 1
    assert all(isinstance(d, DecisionRecord) for d in decs)


def test_ledger_append_only(tmp_path, charter: Charter) -> None:
    ledger = AuditLedger(tmp_path / "audit")
    s = Session(charter, audit=ledger, session_id="demo")
    s.handle("任务一")
    n1 = len(ledger.read("demo"))
    s.handle("任务二")
    n2 = len(ledger.read("demo"))
    assert n2 == n1 + 1  # 只追加，不覆盖


def test_audit_disabled_explicitly(charter: Charter) -> None:
    # audit=False 时不写账本、不抛错
    s = Session(charter, audit=False, session_id="noaudit")
    out = s.handle("测试")
    assert out.decisions  # 决策仍挂载在结果里
    assert s.audit is None


# -- Replay CLI -----------------------------------------------------------
def _run_replay(*args: str) -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(root, "src")
    res = subprocess.run(
        [sys.executable, "-m", "collab_charter.cli", "replay", *args],
        capture_output=True, text=True, cwd=root, env=env,
    )
    return res.stdout + res.stderr


def test_replay_sessions_list(tmp_path, charter: Charter) -> None:
    ledger = AuditLedger(tmp_path / "audit")
    Session(charter, audit=ledger, session_id="sess-a").handle("hello")
    out = _run_replay("--sessions", "--audit-dir", str(tmp_path / "audit"))
    assert "sess-a" in out


def test_replay_why(tmp_path, charter: Charter) -> None:
    ledger = AuditLedger(tmp_path / "audit")
    s = Session(charter, audit=ledger, session_id="sess-b")
    out = s.handle("hello")
    assert out.decisions
    did = out.decisions[0].decision_id
    got = _run_replay("--why", did, "--audit-dir", str(tmp_path / "audit"))
    assert "决策" in got
    assert did in got


def test_replay_json(tmp_path, charter: Charter) -> None:
    ledger = AuditLedger(tmp_path / "audit")
    Session(charter, audit=ledger, session_id="sess-c").handle("hello")
    got = _run_replay("sess-c", "--json", "--audit-dir", str(tmp_path / "audit"))
    data = json.loads(got)
    assert isinstance(data, list)
    assert data[0]["session_id"] == "sess-c"


# -- Policy IR（P2-10 轻量版）--------------------------------------------
def test_policy_ir_compile(charter: Charter) -> None:
    from collab_charter.policy_ir import compile_charter

    ir = compile_charter(charter)
    assert len(ir.rules) == len(charter)
    assert ir.risk_summary()
    assert "critical" in ir.risk_summary()


def test_policy_ir_query_and_format(charter: Charter) -> None:
    from collab_charter.policy_ir import compile_charter

    ir = compile_charter(charter)
    r = ir.get("0.5-R4")
    assert r is not None
    assert r.policy_id == "0.5-R4"
    assert r.kind_zh
    assert r.chapter_title
    assert "0.5-R4" in ir.format_rule(r)


def test_policy_ir_self_diff_is_empty(charter: Charter) -> None:
    from collab_charter.policy_ir import compile_charter

    ir = compile_charter(charter)
    d = ir.diff(compile_charter(charter))
    assert d["counts"] == {"added": 0, "removed": 0, "changed": 0}


def test_policy_ir_risk_filter(charter: Charter) -> None:
    from collab_charter.policy_ir import compile_charter

    ir = compile_charter(charter)
    crit = ir.by_risk("critical")
    assert crit  # 安全章节至少应有高危条款
    assert all(r.risk_level == "critical" for r in crit)

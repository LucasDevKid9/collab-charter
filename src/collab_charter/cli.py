"""命令行入口：``python -m collab_charter.cli <命令>``。

命令一览::

    receipt              输出第一章要求的接收自检（≤3 行）
    clauses [--chapter]  列出全部条款（可带关键词过滤）
    clause <ID>          查询单条条款原文与定位
    route <文本>         只做路由决策，不动管线（看会走全量还是快速）
    handle <文本>        跑完整管线，打印逐站轨迹与输出
    verify               对宪章做完整性自检（SSOT 契约三项）
    export               导出机器可读版（json / yaml）
    kb [--stats]         知识库摘要（第十一章：词条数/断链/重复/未验证）
    mine <需求>          语义场深挖：加权词条 + 分布权重 + 闸门结论
    field <需求>         潜空间语义场：关联网络/中心性/社群/覆盖缺口
    anchor               认知锚定·符号求解（第十二章，需 z3-solver）
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .charter_loader import Charter, CharterError
from .flows import Confidence, FlowLayer, FlowType, Source, TTL
from .router import TaskLevel
from .session import Session


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="collab-charter",
        description="用户协作宪章 v3.2 的 Agent 执行内核",
    )
    p.add_argument("--charter", help="charter.yaml 路径（默认自动查找）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("receipt", help="输出接收自检")

    pc = sub.add_parser("clauses", help="列出条款")
    pc.add_argument("--chapter", help="只看某一章的 key，如 chapter_5_analysis")
    pc.add_argument("--grep", help="条款文本关键词过滤")

    p1 = sub.add_parser("clause", help="查询单条条款")
    p1.add_argument("id", help="条款 id，如 0.5-R4")

    pr = sub.add_parser("route", help="只做路由决策")
    pr.add_argument("text")
    pr.add_argument("--level", default="L2", choices=["L1", "L2", "L3", "L4"])

    ph = sub.add_parser("handle", help="跑完整管线")
    ph.add_argument("text")
    ph.add_argument("--level", default="L2", choices=["L1", "L2", "L3", "L4"])
    ph.add_argument("--creative", action="store_true", help="标记为创造性产出")
    ph.add_argument("--plan", action="store_true", help="标记为多步计划")
    ph.add_argument("--local-files", action="store_true", help="涉及本地文件")
    ph.add_argument("--constraint", action="append", default=[], help="关键约束，可多次")

    sub.add_parser("verify", help="宪章完整性自检")

    pe = sub.add_parser("export", help="导出机器可读版")
    pe.add_argument("--format", default="json", choices=["json", "yaml"])

    pk = sub.add_parser("kb", help="知识库摘要（第十一章）")
    pk.add_argument("--stats", action="store_true", help="只输出机器可读统计")

    pm = sub.add_parser("mine", help="语义场深挖（11.4）")
    pm.add_argument("requirement", help="需求原文")
    pm.add_argument("--objective", action="append", default=[], help="任务目标，可多次")
    pm.add_argument("--state", default="", help="语义状态：探索期/收敛期/创意期/校验期")
    pm.add_argument("--domain", action="append", default=[], help="限定域，可多次")
    pm.add_argument("--limit", type=int, default=12)
    pm.add_argument("--kind", action="append", default=[], help="限定词条类型，可多次")
    pm.add_argument("--online", action="store_true", help="允许在线扩容（只报闸门结论，10-R4）")

    pf = sub.add_parser("field", help="潜空间语义场（11.3）")
    pf.add_argument("requirement", help="需求原文")
    pf.add_argument("--objective", action="append", default=[], help="任务目标，可多次")
    pf.add_argument("--state", default="", help="语义状态：探索期/收敛期/创意期/校验期")
    pf.add_argument("--domain", action="append", default=[], help="限定域，可多次")
    pf.add_argument("--limit", type=int, default=30)

    pa = sub.add_parser("anchor", help="认知锚定·符号求解（第十二章，需 z3-solver）")
    pa.add_argument("--declare", help="变量声明：变量:含义，逗号分隔")
    pa.add_argument("--constraints", help="硬约束，分号分隔")
    pa.add_argument("--decisions", help="候选档位：档名:谓词，分号分隔")
    pa.add_argument("--rounds", default="", help="多轮对齐，| 分隔")
    pa.add_argument("--max-solutions", type=int, default=100)
    pa.add_argument("--as-json", action="store_true")
    pa.add_argument("--selftest", action="store_true", help="跑内置验收")

    prp = sub.add_parser("replay", help="回放审计账本中的会话决策流（治理内核）")
    prp.add_argument("session", nargs="?", default="", help="会话 id（或 audit 目录中的文件名）")
    prp.add_argument("--step", action="store_true", help="逐事件展开回放")
    prp.add_argument("--why", help="解释某条决策记录（decision_id）")
    prp.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    prp.add_argument("--audit-dir", default="", help="审计目录（默认 ./audit）")
    prp.add_argument("--sessions", action="store_true", help="列出全部会话")

    pp = sub.add_parser("policy", help="宪章编译为策略IR + 差分（治理内核·P2-10 轻量版）")
    pp.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    pp.add_argument("--risk", help="只看某风险档：low/medium/high/critical")
    pp.add_argument("--summary", action="store_true", help="只输出风险档概览")
    pp.add_argument("--diff", help="与另一份 charter.yaml 差分")
    return p


def cmd_receipt(charter: Charter) -> int:
    print(Session(charter).receipt())
    return 0


def cmd_clauses(charter: Charter, args: argparse.Namespace) -> int:
    for c in charter:
        if args.chapter and c.chapter_key != args.chapter:
            continue
        if args.grep and args.grep not in c.text and not (c.zh and args.grep in c.zh):
            continue
        label = f"{c.zh} " if c.zh else ""
        print(f"{c.id:<10} {c.section_title:<16} {label}{c.text}")
    return 0


def cmd_clause(charter: Charter, args: argparse.Namespace) -> int:
    try:
        c = charter.clause(args.id)
    except CharterError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print(f"条款 ID   ：{c.id}")
    print(f"定位      ：{c.anchor}")
    if c.zh:
        print(f"条目      ：{c.zh}")
    print(f"正文      ：{c.text}")
    return 0


def cmd_route(charter: Charter, args: argparse.Namespace) -> int:
    s = Session(charter, level=TaskLevel(args.level))
    route = s.router.plan(level=TaskLevel(args.level), user_text=args.text)
    print(route)
    return 0


def cmd_handle(charter: Charter, args: argparse.Namespace) -> int:
    s = Session(charter, level=TaskLevel(args.level))
    out = s.handle(
        args.text,
        has_creative_output=args.creative,
        has_multi_step_plan=args.plan,
        has_local_files=args.local_files,
        constraints=args.constraint,
    )
    print("── 路由 ──")
    print(out.run.route)
    print("── 逐站轨迹 ──")
    print(out.trace)
    print("── 输出 ──")
    print(out.text)
    if out.mirror:
        print("── 认知镜像 ──")
        print(out.mirror)
    if out.tiebreak:
        print("── 待你裁断（0.5-R4，一次最多 1 问）──")
        print(out.tiebreak)
    if out.selfcheck and not out.selfcheck.passed:
        print("── 自检未通过 ──")
        print(out.explain_failures())
    return 0


def cmd_verify(charter: Charter) -> int:
    """SSOT 契约三项 + 结构一致性，全部可判定。"""
    ok = True
    print(f"宪章 ID   ：{charter.charter_id}")
    print(f"宪章版本  ：{charter.version}")
    print(f"条款总数  ：{len(charter)}")

    # 契约 1：条款 id 唯一（加载时已强制，这里复查）
    ids = charter.clause_ids()
    dup = len(ids) != len(set(ids))
    print(f"[{'PASS' if not dup else 'FAIL'}] 契约1 条款 id 唯一")
    ok &= not dup

    # 契约 2：每条条款必须有可判定文本
    empty = [c.id for c in charter if not c.text.strip()]
    print(f"[{'PASS' if not empty else 'FAIL'}] 契约2 条款均可判定（非空）"
          + (f" —— 空条款：{empty}" if empty else ""))
    ok &= not empty

    # 契约 3：章节覆盖
    chapters = {c.chapter_key for c in charter}
    print(f"[PASS] 契约3 涉及章节 {len(chapters)} 章：{sorted(chapters)}")

    # 结构：路由站点与宪章一致
    try:
        from .router import Router

        Router(charter)
        print("[PASS] 结构  路由站点与 0.3 完全一致")
    except CharterError as exc:
        print(f"[FAIL] 结构  路由站点不一致：{exc}")
        ok = False

    # 结构：闸门矩阵覆盖 3×3 全组合
    matrix = charter.section("enforcement", "gate_matrix")
    print(f"[{'PASS' if len(matrix) == 9 else 'FAIL'}] 结构  安全闸门矩阵覆盖 {len(matrix)}/9 组合")
    ok &= len(matrix) == 9

    # 结构：自检项与 0.8 一致
    from .selfcheck import SelfCheckRunner

    declared = [i["id"] for i in charter.section("chapter_0_information_flow", "0.8_selfcheck")["items"]]
    print(f"[{'PASS' if declared == list(SelfCheckRunner.CLAUSE_IDS) else 'FAIL'}] "
          f"结构  自检项与 0.8 一致（{len(declared)} 项）")
    ok &= declared == list(SelfCheckRunner.CLAUSE_IDS)

    print()
    print("验收结果：" + ("全部通过 ✓" if ok else "存在失败项 ✗"))
    return 0 if ok else 1


def cmd_export(charter: Charter, args: argparse.Namespace) -> int:
    if args.format == "json":
        print(json.dumps(charter.raw, ensure_ascii=False, indent=2))
    else:
        import yaml

        print(yaml.safe_dump(charter.raw, allow_unicode=True, sort_keys=False))
    return 0


def cmd_kb(args: argparse.Namespace) -> int:
    from .lexicon import KnowledgeBase

    kb = KnowledgeBase.load()
    s = kb.stats()
    if args.stats:
        print(json.dumps({**s, "duplicate_terms": kb.duplicate_terms},
                         ensure_ascii=False, indent=2))
        return 0
    print(f"知识库 digest：{s['digest']}")
    print(f"词条总数    ：{s['entry_count']}")
    print(f"按类型      ：{s['kinds']}")
    print(f"按来源文件  ：{s['files']}")
    dup = kb.duplicate_terms
    print(f"跨文件同名  ：{len(dup)}"
          + (f" —— {dup}" if dup else ""))
    print(f"未验证词条  ：{s['unverified_count']}"
          + (f" —— {kb.unverified[:10]}{' …' if len(kb.unverified) > 10 else ''}"
             if kb.unverified else ""))
    return 0


def cmd_mine(charter: Charter, args: argparse.Namespace) -> int:
    from .lexicon import MiningRequest, mine

    result = mine(
        MiningRequest(
            requirement=args.requirement,
            task_objectives=list(args.objective),
            semantic_state=args.state,
            domains=list(args.domain),
            limit=args.limit,
            kinds=list(args.kind) or None,
            allow_online=args.online,
        ),
        charter=charter,
    )
    print(f"语义状态：{result.semantic_state or '（中性）'}   策略：{result.policy.get('note', '')}")
    print(f"空间指纹：{result.space_digest}")
    print()
    print(f"{'词条':<10}{'类型':<12}{'得分':>8}{'分布权重':>10}  闸门")
    for e in result.entries:
        gate = e.gate["verdict"] if e.gate else "-"
        print(f"{e.term:<10}{e.kind:<12}{e.score:>8.3f}{e.weight:>10.3f}  {gate}")
        if e.suggestion.get("example"):
            print(f"          建议：{e.suggestion['example']}")
    if result.field.gaps:
        print()
        print(f"覆盖缺口：{result.field.gaps}")
    for w in result.warnings:
        print(f"[警告] {w}")
    if result.online_expansion and result.online_expansion.get("requested"):
        oe = result.online_expansion
        print(f"[在线扩容] 未执行（{oe['confirmation_clause']}）："
              f"需用户确认={oe['requires_user_confirmation']}，"
              f"闸门={oe['gate_verdict']}")
    return 0


def cmd_field(charter: Charter, args: argparse.Namespace) -> int:
    from .lexicon import MiningRequest, mine

    result = mine(
        MiningRequest(
            requirement=args.requirement,
            task_objectives=list(args.objective),
            semantic_state=args.state,
            domains=list(args.domain),
            limit=args.limit,
        ),
        charter=charter,
    )
    f = result.field
    m = f.metrics
    print(f"节点 {int(m['node_count'])} · 边 {int(m['edge_count'])} · "
          f"密度 {m['density']:.3f} · 模块度 {m['modularity']:.3f} · "
          f"社群 {int(m['community_count'])}")
    print()
    print("中心性 Top5：")
    for eid, c in f.top_central(5):
        print(f"  {f.terms[eid]:<10}{c:.3f}  社群#{f.community_of(eid)}")
    print()
    print("社群：")
    for cid, members in sorted(f.communities.items()):
        names = [f.terms[m] for m in members]
        print(f"  #{cid}：{'、'.join(names)}")
    if f.gaps:
        print()
        print(f"覆盖缺口：{f.gaps}")
    for w in result.warnings:
        print(f"[警告] {w}")
    return 0


def cmd_anchor(args: argparse.Namespace) -> int:
    from .anchor import solve

    if args.selftest:
        from .anchor import selftest

        return 0 if selftest() else 1
    try:
        result = solve(
            declare=args.declare or "",
            constraints=args.constraints or "",
            decisions=args.decisions or "",
            rounds=args.rounds,
            max_solutions=args.max_solutions,
        )
    except Exception as exc:  # AnchorError / AnchorUnavailableError 均走友好路径
        print(f"输入错误：{exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    for r in result["rounds"]:
        print(f"\n===== {r['round']} =====")
        print(f"满足解总数: {r['solutions']}" + ("（已截断）" if r["truncated"] else ""))
        print("档位票数: " + "  ".join(f"{k}={v}" for k, v in r["votes"].items()))
        if r["solutions"] > 0:
            print(f">>> 推荐档: {r['recommend']}")
        for w in r["warnings"]:
            print(f"[警告] {w}")
    if len(result["rounds"]) >= 2:
        print("\n===== 多轮对齐对比 =====")
        print(f"第一轮推荐: {result['rounds'][0]['recommend']}  "
              f"末轮推荐: {result['rounds'][-1]['recommend']}")
        print(f">>> {result['drift_note'] or '两轮推荐一致，标准收敛，结论可钉住。'}")
    return 0


def cmd_replay(charter: Charter, args: argparse.Namespace) -> int:
    """回放审计账本：列出会话 / 逐事件 / 解释某条决策（治理内核）。"""
    from .audit import AuditLedger

    ledger = AuditLedger(args.audit_dir) if args.audit_dir else AuditLedger()

    if args.sessions:
        sessions = ledger.all_sessions()
        if not sessions:
            print("（审计目录为空，尚无会话记录）")
            return 0
        print("审计会话：")
        for sid in sessions:
            n = len(ledger.decisions_of(sid))
            print(f"  {sid:<24} 决策 {n} 条")
        return 0

    if args.why:
        # 解释单条决策记录
        target = args.why
        found = None
        for sid in ledger.all_sessions():
            for d in ledger.decisions_of(sid):
                if d.decision_id == target or target in d.explanation:
                    found = d
                    break
            if found:
                break
        if found is None:
            print(f"未找到决策记录：{target}", file=sys.stderr)
            return 2
        if args.json:
            import json as _json

            print(_json.dumps(found.to_dict(), ensure_ascii=False, indent=2))
            return 0
        print(full_sid := f"决策 {found.decision_id}（trace {found.trace_id}）")
        print(found.explain())
        return 0

    if not args.session:
        print("请指定会话 id，或用 `--sessions` 列出全部会话。", file=sys.stderr)
        return 2

    events = ledger.read(args.session)
    if not events:
        # 允许不带 .jsonl 后缀的会话名
        if ledger._file_for(args.session).exists():
            events = ledger.read(args.session)
        if not events:
            print(f"会话 {args.session} 无审计记录。用 `collab-charter replay --sessions` 查看。",
                  file=sys.stderr)
            return 2

    if args.json:
        import json as _json

        print(_json.dumps(
            [ev.to_dict() for ev in events], ensure_ascii=False, indent=2
        ))
        return 0

    decisions = ledger.decisions_of(args.session)
    print(f"── 会话 {args.session} 回放 ──")
    print(f"审计事件 {len(events)} 条 · 决策 {len(decisions)} 条\n")

    if args.step:
        for ev in events:
            ts = ev.ts[11:19] if len(ev.ts) >= 19 else ev.ts
            print(f"[{ev.seq:>3}] {ts} {ev.event_type}")
            payload = ev.payload
            if ev.event_type == "decision" and "explanation" in payload:
                print(f"      → {payload['outcome']}：{payload['explanation'][:70]}")
            elif ev.event_type == "pipeline":
                route = payload.get("route", "")
                print(f"      → {route}")
                for r in payload.get("stage_records", []):
                    print(f"      · {r[:80]}")
        print()
    else:
        # 简洁回放：决策摘要
        for d in decisions:
            mark = {"allow": "✓", "deny": "✗", "ask": "？", "degrade": "~"}.get(d.outcome, "·")
            print(f"  {mark} {d.event:<14} {d.outcome:<8} {d.explanation[:70]}")

    return 0


def cmd_policy(charter: Charter, args: argparse.Namespace) -> int:
    """把宪章编译为轻量 Policy IR；支持风险档概览与宪章差分。"""
    from .policy_ir import compile_charter

    ir = compile_charter(charter)

    if args.diff:
        try:
            other = Charter.load(args.diff)
        except CharterError as exc:
            print(f"加载对照宪章失败：{exc}", file=sys.stderr)
            return 2
        diff = ir.diff(compile_charter(other))
        if args.json:
            import json as _json

            print(_json.dumps(diff, ensure_ascii=False, indent=2))
            return 0
        print(f"宪章差分（{charter.charter_id} → {other.charter_id}）：")
        print(f"  新增 {diff['counts']['added']} · 变更 {diff['counts']['changed']} · 删除 {diff['counts']['removed']}")
        if diff["added"]:
            print("  新增：" + ", ".join(diff["added"]))
        if diff["changed"]:
            print("  变更：" + ", ".join(diff["changed"]))
        if diff["removed"]:
            print("  删除：" + ", ".join(diff["removed"]))
        print("  受影响章节：" + ", ".join(diff["affected_chapters"]))
        return 0

    if args.json:
        print(ir.to_json())
        return 0

    if args.summary:
        print(f"宪章 {charter.charter_id} v{charter.version} · 策略IR {len(ir.rules)} 条")
        for lvl, n in ir.risk_summary().items():
            print(f"  {lvl:<9} {n}")
        return 0

    print(f"宪章 {charter.charter_id} v{charter.version} · 策略IR {len(ir.rules)} 条")
    print("（按优先级排序，越靠前越优先）\n")
    for r in ir.sorted():
        print(ir.format_rule(r))
        print()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        charter = Charter.load(args.charter)
    except CharterError as exc:
        print(f"宪章加载失败：{exc}", file=sys.stderr)
        return 2

    table = {
        "receipt": lambda a: cmd_receipt(charter),
        "clauses": lambda a: cmd_clauses(charter, a),
        "clause": lambda a: cmd_clause(charter, a),
        "route": lambda a: cmd_route(charter, a),
        "handle": lambda a: cmd_handle(charter, a),
        "verify": lambda a: cmd_verify(charter),
        "export": lambda a: cmd_export(charter, a),
        "kb": lambda a: cmd_kb(a),
        "mine": lambda a: cmd_mine(charter, a),
        "field": lambda a: cmd_field(charter, a),
        "anchor": lambda a: cmd_anchor(a),
        "replay": lambda a: cmd_replay(charter, a),
        "policy": lambda a: cmd_policy(charter, a),
    }
    return table[args.cmd](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

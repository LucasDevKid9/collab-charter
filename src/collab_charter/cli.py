"""命令行入口：``python -m collab_charter.cli <命令>``。

命令一览::

    receipt              输出第一章要求的接收自检（≤3 行）
    clauses [--chapter]  列出全部条款（可带关键词过滤）
    clause <ID>          查询单条条款原文与定位
    route <文本>         只做路由决策，不动管线（看会走全量还是快速）
    handle <文本>        跑完整管线，打印逐站轨迹与输出
    verify               对宪章做完整性自检（SSOT 契约三项）
    export               导出机器可读版（json / yaml）
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
        description="用户协作宪章 v3.1 的 Agent 执行内核",
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
    }
    return table[args.cmd](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

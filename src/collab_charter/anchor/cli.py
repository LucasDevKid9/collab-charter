"""符号锚定 CLI：``python -m collab_charter.anchor <参数>``。

用法示例::

    python -m collab_charter.anchor \
      --declare "x:可行性,y:预算充足,z:时间允许,w:风险可控" \
      --constraints "x+y+z+w>=3; Implies(y==0,w==1); Implies(z==0,And(x==1,w==1))" \
      --decisions "做:x+y+z+w>=4; 观望:x+y+z+w==3; 不做:x+y+z+w<3" \
      --rounds "|y==0" \
      --max-solutions 100

与 cognitive-anchor v2.0 的 ``scripts/solve.py`` 参数完全兼容。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from .solver import __version__, selftest, solve


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m collab_charter.anchor",
        description="认知锚定·符号求解器（z3 全枚举）——宪章 12.1 符号锚定",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--declare", help="变量声明，逗号分隔，格式 变量:含义（全角冒号逗号也可）")
    ap.add_argument("--constraints", help="硬约束，分号分隔的 z3 表达式")
    ap.add_argument("--decisions", help="候选档位，分号分隔，格式 档名:谓词")
    ap.add_argument("--rounds", default="",
                    help="多轮对齐：用 | 分隔，段数=轮数；第 1 段通常留空（只用基础约束），"
                         "后续每段=该轮追加的约束")
    ap.add_argument("--max-solutions", type=int, default=100, help="枚举上限（默认 100）")
    ap.add_argument("--as-json", action="store_true", help="输出 JSON（供下游 skill 解析）")
    ap.add_argument("--selftest", action="store_true", help="跑内置验收示例并退出")
    ap.add_argument("--version", action="version",
                    version=f"collab-charter anchor {__version__}")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.selftest:
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
        # 复用 run_round 的终端渲染：这里只打印关键行
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
        if result["drift_note"]:
            print(f">>> {result['drift_note']}")
        else:
            print(">>> 两轮推荐一致，标准收敛，结论可钉住。")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

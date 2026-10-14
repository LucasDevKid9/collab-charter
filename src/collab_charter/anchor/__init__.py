"""认知锚定·符号求解器（cognitive-anchor v2.0 并入）。

把多条件权衡变成 0/1 符号问题交给 z3 硬算（宪章 12.1）。

公开 API::

    from collab_charter.anchor import solve, selftest_checks

    result = solve(declare="x:可行,y:预算", constraints="x+y>=1",
                   decisions="做:x+y==2; 不做:x+y<2")

z3-solver 为可选依赖：``pip install collab-charter[anchor]``。
未安装时 import 本包不会失败，调用 solve/run_round 等会抛
AnchorUnavailableError。
"""

from .solver import (
    JSON_SCHEMA_VERSION,
    AnchorError,
    AnchorUnavailableError,
    __version__,
    build_solver,
    enum_models,
    eval_decision,
    normalize_input,
    parse_constraints,
    parse_declare,
    parse_kv,
    run_round,
    selftest,
    selftest_checks,
    solve,
)

__all__ = [
    "solve",
    "run_round",
    "build_solver",
    "enum_models",
    "eval_decision",
    "normalize_input",
    "parse_declare",
    "parse_kv",
    "parse_constraints",
    "selftest",
    "selftest_checks",
    "AnchorError",
    "AnchorUnavailableError",
    "JSON_SCHEMA_VERSION",
    "__version__",
]

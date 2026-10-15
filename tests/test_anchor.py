"""符号锚定（宪章第十二章）：AST 白名单、枚举、投票、漂移、验收断言。

对应 cognitive-anchor v2.0 的 18 项内置断言——移植为 pytest 后，
原 selftest 与测试共用同一份 selftest_checks()，避免两套验收漂移。
"""

from __future__ import annotations

import pytest

from collab_charter.anchor import (
    JSON_SCHEMA_VERSION,
    AnchorError,
    AnchorUnavailableError,
    build_solver,
    enum_models,
    normalize_input,
    parse_constraints,
    parse_declare,
    parse_kv,
    run_round,
    selftest_checks,
    solve,
)

z3 = pytest.importorskip("z3", reason="anchor 可选依赖未安装")

DECLARE = "x:可行性,y:预算充足,z:时间允许,w:风险可控"
CONSTRAINTS = ["x+y+z+w>=3", "Implies(y==0,w==1)", "Implies(z==0,And(x==1,w==1))"]
DECISIONS = {"做": "x+y+z+w>=4", "观望": "x+y+z+w==3", "不做": "x+y+z+w<3"}


# -- 内置验收断言（cognitive-anchor v2.0 的 18 项） -----------------------
def test_内置验收断言全部通过() -> None:
    checks = selftest_checks()
    assert len(checks) == 18
    failed = [name for name, ok in checks if not ok]
    assert not failed, f"失败的断言：{failed}"


# -- 输入归一化 -------------------------------------------------------------
def test_全角标点归一化() -> None:
    assert normalize_input("x：可行，y：预算；z==1") == "x:可行,y:预算;z==1"
    assert normalize_input("") == ""


def test_变量声明拒绝非法名() -> None:
    with pytest.raises(AnchorError):
        parse_declare("1x:含义")
    with pytest.raises(AnchorError):
        parse_declare("缺少冒号")


def test_档位声明拒绝空谓词() -> None:
    with pytest.raises(AnchorError):
        parse_kv("做:")
    with pytest.raises(AnchorError):
        parse_kv("没有冒号")


# -- AST 白名单（12.1-A2）--------------------------------------------------
@pytest.mark.parametrize("expr", [
    "x.__class__",
    "x.__class__.__mro__",
    "(lambda: 1)()",
    "[i for i in range(3)]",
    "{1: 2}",
    "x if y else z",
    "open('/etc/passwd')",
    "__import__('os')",
    "x[0]",
    "getattr(x, 'real')",
])
def test_逃逸构造一律被拒(expr: str) -> None:
    with pytest.raises(AnchorError):
        run_round({"x": "t", "y": "t"}, [expr], DECISIONS, [], 10, "t", True)


def test_未声明变量被拒() -> None:
    with pytest.raises(AnchorError):
        run_round({"x": "t"}, ["q+1"], DECISIONS, [], 10, "t", True)


def test_非常量被拒() -> None:
    with pytest.raises(AnchorError):
        run_round({"x": "t"}, ["x==1.5"], DECISIONS, [], 10, "t", True)


def test_白名单函数可用() -> None:
    r = run_round(parse_declare("x:a,y:b"), ["x+y>=1"],
                  {"异": "Distinct(x,y)", "同": "Not(Distinct(x,y))"}, [], 10, "t", True)
    assert r["status"] == "sat"
    assert r["votes"].get("异", 0) + r["votes"].get("同", 0) == r["solutions"]


# -- 求解语义 --------------------------------------------------------------
def test_第一轮推荐观望() -> None:
    r = run_round(parse_declare(DECLARE), CONSTRAINTS, DECISIONS, [], 100, "t", True)
    assert r["status"] == "sat"
    assert r["recommend"] == "观望"
    assert r["truncated"] is False


def test_追加约束后收敛不漂移() -> None:
    r2 = run_round(parse_declare(DECLARE), CONSTRAINTS, DECISIONS, ["y==0"], 100, "t", True)
    assert r2["recommend"] == "观望"


def test_无解轮给出建议() -> None:
    r = run_round(parse_declare(DECLARE), ["x==1", "x==0"], DECISIONS, [], 100, "t", True)
    assert r["status"] == "unsat"
    assert any("放宽" in w for w in r["warnings"])


def test_枚举截断标志如实上报() -> None:
    s, z = build_solver({k: k for k in "abcde"}, ["a+b+c+d+e>=1"])
    models, truncated = enum_models(s, z, 3)
    assert len(models) == 3
    assert truncated is True


def test_档位未覆盖的解被计数() -> None:
    # 档位只覆盖 x+y==2，故意漏掉其余解
    r = run_round(parse_declare("x:a,y:b"), ["x+y>=1"],
                  {"恰二": "x+y==2"}, [], 10, "t", True)
    assert r["unvoted"] > 0
    assert any("未命中任何档位" in w for w in r["warnings"])


def test_变量频率() -> None:
    r = run_round(parse_declare("x:a,y:b"), ["x+y>=1"],
                  {"恰一": "x+y==1", "恰二": "x+y==2"}, [], 10, "t", True)
    assert r["freq"]["x"] + r["freq"]["y"] >= 1.0
    assert set(r["freq"]) == {"x", "y"}


# -- solve() 高层 API -------------------------------------------------------
def test_solve_返回标准_schema() -> None:
    out = solve(DECLARE, "x+y>=1", "做:x+y==2; 不做:x+y<2")
    assert out["schema_version"] == JSON_SCHEMA_VERSION
    assert out["origin"].startswith("cognitive-anchor")
    assert out["clauses"][0] == "12.1-A1"


def test_solve_检测漂移并提示标准未稳() -> None:
    out = solve(DECLARE, "x+y+z+w>=3", "做:x+y+z+w>=4; 观望:x+y+z+w==3; 不做:x+y+z+w<3",
                rounds="|y==0|z==0")
    assert len(out["rounds"]) == 3
    # 末轮在 y=0,z=0 下需 x+w>=3，而 x+w 最大 2 → 无解轮次
    assert out["drift_note"]
    assert out["drift"] is False or "标准未稳" in out["drift_note"]


def test_solve_拒绝空输入() -> None:
    with pytest.raises(AnchorError):
        solve("", "x>=1", "做:x==1")


def test_solve_拒绝非法枚举上限() -> None:
    with pytest.raises(AnchorError):
        solve(DECLARE, "x+y>=1", "做:x+y==2", max_solutions=0)


# -- 可选依赖缺失时的行为 ---------------------------------------------------
def test_z3_缺失时报错清晰(monkeypatch: pytest.MonkeyPatch) -> None:
    import collab_charter.anchor.solver as solver

    monkeypatch.setattr(solver, "z3", None)
    with pytest.raises(AnchorUnavailableError, match="z3-solver"):
        solver.solve(DECLARE, "x+y>=1", "做:x+y==2")


# -- 12.1-A2 纵深防御：彻底不依赖 eval/compile ------------------------------
def test_表达式求值_零eval_零compile() -> None:
    """12.1-A2 的纵深防御：表达式求值必须走纯 AST 解释器，
    绝不能退化为 eval/compile（白名单之外还有纵深防线）。"""
    import inspect
    import collab_charter.anchor.solver as solver

    src = inspect.getsource(solver)
    # _safe_eval 与 _ast_eval 的实现体：不得出现内置 eval 或 compile 调用
    safe_src = inspect.getsource(solver._safe_eval) + inspect.getsource(solver._ast_eval)
    assert "eval(compile(" not in safe_src
    assert " eval(" not in safe_src.replace("_safe_eval", "_x").replace("_ast_eval", "_x")
    # 允许出现的只有 AST 解析的 mode="eval" 与 z3 模型 m.eval，二者都不是 Python 求值
    assert "ast.parse" in inspect.getsource(solver._safe_eval)

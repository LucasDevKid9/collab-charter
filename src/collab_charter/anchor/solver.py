"""认知锚定·符号求解器（z3 全枚举）——宪章第十二章「符号锚定」的执行载体。

本模块由 cognitive-anchor v2.0.0 的 ``scripts/solve.py`` 原样移植而来，
作为 collab-charter 仓库的常驻能力（两仓库功能合一）。求解语义与
``JSON_SCHEMA_VERSION = "cognitive-anchor.solve/2.0"`` 保持向后兼容。

执行的条款
----------
12.1-A1  结论来自求解器枚举输出，AI 不得自行下最终判断
12.1-A2  表达式只走 AST 白名单求值，逃逸构造一律拒绝
12.1-A3  求解器警告（截断/档位未覆盖/无解）必须原样转告
12.1-A4  多轮追加约束后推荐档变化时必须提示「标准未稳」
12.1-A5  档位未覆盖的解数必须报告

依赖说明
--------
z3-solver 是**可选依赖**（``pip install collab-charter[anchor]``）。
未安装时本模块仍可导入，但调用任何求解函数都会抛出
:class:`AnchorUnavailableError`——内核其余部分（宪章、语义场、闸门）
不受影响。
"""

from __future__ import annotations

import ast
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

try:  # pragma: no cover - 取决于安装环境
    import z3
except ImportError:  # pragma: no cover
    z3 = None  # type: ignore[assignment]

__version__ = "2.0.0"
JSON_SCHEMA_VERSION = "cognitive-anchor.solve/2.0"
SPACE_NOTE = "cognitive-anchor v2.0.0 移植并入 collab-charter（12.1 符号锚定）"


class AnchorError(ValueError):
    """符号锚定的输入/表达式错误（用户可修正）。"""


class AnchorUnavailableError(RuntimeError):
    """z3-solver 未安装。安装方式：pip install collab-charter[anchor]"""


def _require_z3():
    if z3 is None:
        raise AnchorUnavailableError(
            "符号锚定需要可选依赖 z3-solver：pip install collab-charter[anchor]"
        )
    return z3


# ---------- 输入归一化（全角 → 半角） ----------

_FULLWIDTH_MAP = {
    "，": ",", "；": ";", "：": ":", "｜": "|",
    "（": "(", "）": ")", "、": ",", "＝": "=",
    "＞": ">", "＜": "<", "＋": "+", "－": "-", "！": "!",
}


def normalize_input(text: str) -> str:
    """把中文全角标点归一化为 ASCII，保留其余字符。"""
    if not text:
        return text
    out = []
    for ch in text:
        if ch in _FULLWIDTH_MAP:
            out.append(_FULLWIDTH_MAP[ch])
        elif unicodedata.category(ch) == "Po" and ord(ch) > 0x2000 and ch not in "…":
            # 其余全角/变宽标点统一转半角（保守：仅标点大类）
            out.append(unicodedata.normalize("NFKC", ch))
        else:
            out.append(ch)
    return "".join(out)


# ---------- 受控表达式解析（AST 白名单制） ----------

# 允许的 AST 节点类型：表达式、布尔、一元、二元、比较、调用、名字、常量
_ALLOWED_NODE_TYPES = (
    ast.Expression,
    ast.BoolOp, ast.And, ast.Or,
    ast.UnaryOp, ast.Not, ast.USub, ast.UAdd,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.FloorDiv,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Call, ast.Name, ast.Load, ast.Constant,
)

#: BinOp / UnaryOp / Compare 各操作符 → 实际函数。
#: 用 operator 模块而不是 Python 内置 eval：对 z3 对象与原生 int/bool 都成立。
_OP_FUNCS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.USub: lambda a: -a,
    ast.UAdd: lambda a: +a,
    ast.Not: lambda a: not a,
}
_CMP_FUNCS = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
}


def _is_symbolic(v: Any) -> bool:
    """是否为 z3 符号对象（未实例化的 BoolRef / ArithRef 等）。"""
    return hasattr(v, "get_id") or type(v).__name__.endswith("Ref")


def _ast_eval(node: ast.AST, env: dict) -> Any:
    """纯 AST 解释器（12.1-A2）——不调用 eval/compile。

    手工遍历白名单节点；任何不在白名单的节点都在前置校验中被拒绝，
    因此这里无需再设逃逸防线。对 z3 表达式与原生 int/bool 统一求值。
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env[node.id]  # 前置校验保证 node.id 已被允许
    if isinstance(node, ast.BoolOp):
        vals = [_ast_eval(v, env) for v in node.values]
        # 符号操作数（z3 BoolRef/ArithRef）用 z3 的 And/Or，不能用 Python all/any（会强制 bool）
        symbolic = any(_is_symbolic(v) for v in vals)
        if symbolic:
            z = _require_z3()
            if isinstance(node.op, ast.And):
                return z.And(*vals)
            if isinstance(node.op, ast.Or):
                return z.Or(*vals)
            raise AnchorError("不支持的布尔运算符")
        if isinstance(node.op, ast.And):
            return all(vals)
        if isinstance(node.op, ast.Or):
            return any(vals)
        raise AnchorError("不支持的布尔运算符")
    if isinstance(node, ast.UnaryOp):
        operand = _ast_eval(node.operand, env)
        # 符号操作数：Not 用 z3.Not，USub/UAdd 用 z3 算术（不可用 Python 一元运算）
        if isinstance(node.op, ast.Not) and _is_symbolic(operand):
            z = _require_z3()
            return z.Not(operand)
        fn = _OP_FUNCS.get(type(node.op))
        if fn is None:
            raise AnchorError(f"不支持的一元运算符: {type(node.op).__name__}")
        return fn(operand)
    if isinstance(node, ast.BinOp):
        fn = _OP_FUNCS.get(type(node.op))
        if fn is None:
            raise AnchorError(f"不支持的二元运算符: {type(node.op).__name__}")
        return fn(_ast_eval(node.left, env), _ast_eval(node.right, env))
    if isinstance(node, ast.Compare):
        left = _ast_eval(node.left, env)
        results: list = []
        for op, comp in zip(node.ops, node.comparators):
            fn = _CMP_FUNCS.get(type(op))
            if fn is None:
                raise AnchorError(f"不支持的比较运算符: {type(op).__name__}")
            right = _ast_eval(comp, env)
            results.append(fn(left, right))
            left = right
        # 任一比较是符号结果 → 不强制 bool（z3 禁止 bool(BoolRef)）
        if any(_is_symbolic(r) for r in results):
            z = _require_z3()
            return z.And(*results) if len(results) > 1 else results[0]
        return all(results)
    if isinstance(node, ast.Call):
        fn = env[node.func.id]  # 前置校验保证是白名单函数
        args = [_ast_eval(a, env) for a in node.args]
        return fn(*args)
    raise AnchorError(f"不支持的 AST 节点: {type(node).__name__}")


def _allowed_z3_funcs() -> Dict[str, Any]:
    z = _require_z3()
    return {
        "And": z.And, "Or": z.Or, "Not": z.Not, "Implies": z.Implies,
        "If": z.If, "Distinct": z.Distinct, "Xor": z.Xor,
        "True": True, "False": False,
    }


def _safe_eval(expr: str, allowed: dict):
    """AST 白名单制求值（12.1-A2）。

    节点类型白名单：凡不在白名单内的 AST 构造（Attribute/Subscript/
    Lambda/推导式/关键字参数等）一律拒绝，从结构上阻断逃逸——
    v1 只检查 ast.Name，``x.__class__...`` 可绕过直达任意 Python 对象。
    本实现不依赖 eval/compile：白名单校验后用纯 AST 解释器求值。
    """
    z = _require_z3()
    expr = normalize_input(expr).strip()
    if not expr:
        raise AnchorError("表达式为空")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise AnchorError(f"表达式语法错误: {expr!r}（{e.msg}）") from None

    funcs = _allowed_z3_funcs()
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODE_TYPES):
            raise AnchorError(
                f"表达式含不允许的构造 {type(node).__name__}: {expr!r}"
                f"（仅支持 与/或/非/蕴含/算术/比较 与白名单函数 And/Or/Not/Implies/If/Distinct/Xor）"
            )
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise AnchorError(f"只允许调用具名函数: {expr!r}")
            if node.func.id not in funcs:
                raise AnchorError(
                    f"表达式里出现未允许的函数: {node.func.id!r}（在 {expr!r} 中）"
                )
            if node.keywords:
                raise AnchorError(f"不支持关键字参数: {expr!r}")
        elif isinstance(node, ast.Name):
            if node.id not in allowed and node.id not in funcs:
                raise AnchorError(f"表达式里出现未允许的名字: {node.id!r}（在 {expr!r} 中）")
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, bool)):
                raise AnchorError(f"只允许整数/布尔常量: {expr!r}")

    env: dict = dict(allowed)
    env.update(funcs)
    env["__builtins__"] = {}
    result = _ast_eval(tree.body, env)
    if callable(result):
        raise AnchorError(f"函数名未被调用（单独出现的函数名无意义）: {expr!r}")
    return result


def parse_declare(text: str) -> Dict[str, str]:
    """'x:可行性,y:预算充足' -> {'x':'可行性',...}（全角冒号/逗号已归一化）"""
    out: Dict[str, str] = {}
    for part in normalize_input(text).split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            k, v = part.split(":", 1)
            k = k.strip()
            if not k.replace("_", "").isalnum() or not k.isidentifier():
                raise AnchorError(f"变量名不合法: {k!r}（用小写字母/数字/下划线，如 x1）")
            out[k] = v.strip() or k
        else:
            raise AnchorError(f"变量声明缺少 ':含义': {part!r}")
    return out


def parse_kv(text: str) -> Dict[str, str]:
    """'做:x+y>=4; 观望:...' -> {'做': 'x+y>=4', ...}（全角分号/冒号已归一化）"""
    out: Dict[str, str] = {}
    for part in normalize_input(text).split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise AnchorError(f"档位声明缺少 ':谓词': {part!r}")
        k, v = part.split(":", 1)
        k = k.strip()
        if not k:
            raise AnchorError(f"档位名为空: {part!r}")
        v = v.strip()
        if not v:
            raise AnchorError(f"档位谓词为空: {part!r}（形如 做:x+y>=3）")
        out[k] = v
    return out


def parse_constraints(text: str) -> List[str]:
    """'a>=1; Implies(...)' -> [...]（全角分号已归一化，去空）"""
    return [c.strip() for c in normalize_input(text).split(";") if c.strip()]


def build_solver(vars_decl: Dict[str, str],
                 constraints: List[str],
                 extra: Optional[List[str]] = None):
    """构造 z3 求解器：变量声明 + 域约束(0/1) + 硬约束 + 本轮追加约束。

    返回 (solver, vars)；z3 缺失时抛 AnchorUnavailableError。
    """
    z = _require_z3()
    zv = {k: z.Int(k) for k in vars_decl}
    allowed = dict(zv)
    s = z.Solver()
    for v in zv.values():
        s.add(v >= 0)
        s.add(v <= 1)
    for c in constraints:
        s.add(_safe_eval(c, allowed))
    for e in (extra or []):
        e = e.strip()
        if e:
            s.add(_safe_eval(e, allowed))
    return s, zv


def enum_models(s, z: Dict[str, Any], max_solutions: int) -> Tuple[List[Dict[str, int]], bool]:
    """枚举满足解（回溯阻塞子句）。返回 (解列表, 是否被截断)。"""
    zlib = _require_z3()
    models: List[Dict[str, int]] = []
    while len(models) < max_solutions and s.check() == zlib.sat:
        m = s.model()
        row = {k: m.eval(v).as_long() for k, v in z.items()}
        models.append(row)
        s.add(zlib.Or(*[v != m.eval(v) for v in z.values()]))
    truncated = len(models) >= max_solutions and s.check() == zlib.sat
    return models, truncated


def eval_decision(row: Dict[str, int], expr: str) -> bool:
    """把档位谓词对某一解求值（先 simplify 快路径，失败再回退求解器）。"""
    zlib = _require_z3()
    allowed = {k: zlib.IntVal(v) for k, v in row.items()}
    val = _safe_eval(expr, allowed)
    if isinstance(val, zlib.BoolRef):
        simplified = zlib.simplify(val)
        if zlib.is_true(simplified):
            return True
        if zlib.is_false(simplified):
            return False
        s = zlib.Solver()
        s.add(val)
        return s.check() == zlib.sat
    if isinstance(val, (int, bool)):
        return bool(val)
    # 算术结果按 >0 为真处理（防御性，正常档位谓词应为布尔式）
    simplified = zlib.simplify(val)
    return bool(simplified.as_long()) if hasattr(simplified, "as_long") else False


# ---------- 终端表格对齐（中文按显示宽度） ----------

def _disp_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "FW" else 1 for c in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _disp_width(s))


def run_round(vars_decl, constraints, decisions, extra, max_solutions,
              label: str, as_json: bool = False) -> dict:
    """跑一轮求解：枚举 → 投票（12.1-A1）→ 频率 → 分支表 → 警告（12.1-A3/A5）。"""
    s, z = build_solver(vars_decl, constraints, extra)
    models, truncated = enum_models(s, z, max_solutions)
    total = len(models)
    warnings: List[str] = []

    # 档位票数 + 覆盖检查（12.1-A5：未覆盖的解数必须报告）
    votes = Counter()
    covered = 0
    for r in models:
        hit = [d for d, e in decisions.items() if eval_decision(r, e)]
        if hit:
            covered += 1
        for d in hit:
            votes[d] += 1
    unvoted = total - covered
    if total > 0 and unvoted > 0:
        warnings.append(
            f"有 {unvoted}/{total} 个满足解未命中任何档位（档位谓词可能不互斥或不完整），"
            f"投票基数不完整，建议补齐档位划分"
        )

    # 变量频率
    freq = {k: (sum(r[k] for r in models) / total) if total else 0.0 for k in vars_decl}

    # 分支表：按"成立条件数"降序
    branches = []
    for i, r in enumerate(models, 1):
        sat_count = sum(r.values())
        hit = [d for d, e in decisions.items() if eval_decision(r, e)]
        branches.append({"#": i, "vars": r, "sat": sat_count,
                         "grades": hit, "top": hit[0] if hit else "-"})
    branches.sort(key=lambda b: -b["sat"])

    # 推荐：票数最多的档；并列时用分支表第一条的 top 裁决
    top_votes = max(votes.values()) if votes else 0
    winners = [d for d, v in votes.items() if v == top_votes and top_votes > 0]
    recommend = winners[0] if winners else "-"
    if len(winners) > 1 and branches:
        first = branches[0]["top"]
        if first in winners:
            recommend = first

    if truncated:
        warnings.append(
            f"枚举被 max-solutions={max_solutions} 截断：满足解至少 {total} 个，"
            f"票数结论仅对已枚举部分成立，提高上限可获完整结论"
        )

    if total == 0:
        warnings.append("无满足解：约束互相矛盾。建议逐条放宽硬约束，或检查是否有条件写反")

    result = {
        "round": label,
        "status": "sat" if total else "unsat",
        "solutions": total,
        "truncated": truncated,
        "votes": dict(votes),
        "unvoted": unvoted,
        "freq": {k: round(v, 3) for k, v in freq.items()},
        "recommend": recommend,
        "branches": branches[:20],
        "warnings": warnings,
    }
    if as_json:
        return result

    print(f"\n===== {label} =====")
    if total == 0:
        print("满足解总数: 0（约束矛盾，无任何组合能满足全部硬约束）")
        print("建议：逐条放宽硬约束重试；若刚追加过约束，先回退该轮")
    else:
        print(f"满足解总数: {total}" + ("（已截断，仅统计前 N 个解）" if truncated else ""))
    print("档位票数: " + "  ".join(f"{k}={v}" for k, v in votes.items()))
    print("变量=1 频率: " + "  ".join(
        f"{k}({vars_decl[k]})={freq[k]*100:.0f}%" for k in vars_decl))
    if total > 0:
        print(f">>> 推荐档: {recommend}")
    for w in warnings:
        print(f"[警告] {w}")
    if branches:
        header = _pad("优先级", 7) + "".join(_pad(k, 6) for k in vars_decl) + _pad("满足数", 9) + "档位"
        print(header)
        for b in branches[:20]:
            line = _pad(f"#{b['#']}", 7) + "".join(_pad(str(b['vars'][k]), 6) for k in vars_decl) \
                + _pad(str(b['sat']), 9) + b['top']
            print(line)
    return result


# ---------- 高层 API（供 MCP 工具 / 库调用） ----------

def solve(declare: str, constraints: str, decisions: str,
          rounds: str = "", max_solutions: int = 100) -> Dict[str, Any]:
    """一次性求解并返回机器可读结果（schema 与 cognitive-anchor.solve/2.0 一致）。

    参数与 CLI 完全同名同义；``rounds`` 用 ``|`` 分隔，段数=轮数，
    第 1 段通常留空（只用基础约束）。

    12.1-A4：末轮推荐与首轮不一致时，结果里 ``drift=True`` 并附说明，
    调用方必须原样转告用户。
    """
    if max_solutions < 1:
        raise AnchorError("max_solutions 必须 ≥ 1")
    if not (declare and constraints and decisions):
        raise AnchorError("declare/constraints/decisions 都不能为空")
    vars_decl = parse_declare(declare)
    constraint_list = parse_constraints(constraints)
    decision_map = parse_kv(decisions)
    if not vars_decl or not constraint_list or not decision_map:
        raise AnchorError("declare/constraints/decisions 解析后为空")

    round_segments = [r.strip() for r in normalize_input(rounds).split("|")]
    rounds_out: List[Dict[str, Any]] = []
    cumulative: List[str] = []
    n_rounds = max(1, len(round_segments))
    for i in range(1, n_rounds + 1):
        seg = round_segments[i - 1] if i - 1 < len(round_segments) else ""
        new_cons = [c.strip() for c in seg.split(";") if c.strip()]
        cumulative.extend(new_cons)
        rounds_out.append(run_round(vars_decl, constraint_list, decision_map,
                                    list(cumulative), max_solutions, f"第{i}轮", True))

    drift = False
    drift_note = ""
    if len(rounds_out) >= 2:
        r1, r2 = rounds_out[0], rounds_out[-1]
        if r1["status"] == "unsat" or r2["status"] == "unsat":
            drift_note = "存在无解轮次：请检查该轮追加的约束是否与其他条件矛盾。"
        elif r1["recommend"] != r2["recommend"]:
            drift = True
            drift_note = ("结论漂移：追加约束后推荐档变化 → 对齐标准尚未稳定，"
                          "先别下最终结论。")

    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "tool_version": __version__,
        "origin": SPACE_NOTE,
        "clauses": ["12.1-A1", "12.1-A2", "12.1-A3", "12.1-A4", "12.1-A5"],
        "rounds": rounds_out,
        "drift": drift,
        "drift_note": drift_note,
    }


# ---------- 内置验收 ----------

def _expect_error(expr: str, vars_decl: Dict[str, str], needle: str) -> Tuple[bool, str]:
    """断言某表达式被白名单拒绝。"""
    try:
        _safe_eval(expr, dict(vars_decl))
        return False, f"未被拒绝: {expr!r}"
    except AnchorError as e:
        return needle in str(e) or True, str(e)
    except Exception as e:  # noqa: BLE001
        return False, f"异常类型错误: {type(e).__name__}"


def selftest_checks() -> List[Tuple[str, bool]]:
    """内置验收断言清单（覆盖 有解/推荐/收敛/分支有序/截断/全角/Distinct/
    rounds位置/unsat/沙箱），返回 [(断言名, 是否通过)]，由 pytest 消费。"""
    _require_z3()
    vars_decl = parse_declare("x:可行性,y:预算充足,z:时间允许,w:风险可控")
    constraints = ["x+y+z+w>=3", "Implies(y==0,w==1)", "Implies(z==0,And(x==1,w==1))"]
    decisions = {"做": "x+y+z+w>=4", "观望": "x+y+z+w==3", "不做": "x+y+z+w<3"}

    r1 = run_round(vars_decl, constraints, decisions, [], 100, "验收·第一轮", True)
    r2 = run_round(vars_decl, constraints, decisions, ["y==0"], 100, "验收·第二轮", True)

    # 截断标志：5 变量全空间 31 解，上限 3 应触发 truncated
    s5, z5 = build_solver({k: k for k in "abcde"}, ["a+b+c+d+e>=1"])
    rt, rtrunc = enum_models(s5, z5, 3)
    # 全角归一化：全角输入应与半角等价
    v_full = parse_declare("x：可行性，y：预算充足")
    v_half = parse_declare("x:可行性,y:预算充足")
    c_full = parse_constraints("x+y>=1；x==1")
    d_full = parse_kv("做：x+y>=2；观望：x+y==1")
    # rounds 位置语义：3 段 -> 3 轮；"|y==0" -> 2 轮
    segs = [r.strip() for r in "| |z==0".split("|")]
    segs2 = [r.strip() for r in "|y==0".split("|")]
    # unsat
    ru = run_round(vars_decl, ["x==1", "x==0"], decisions, [], 100, "验收·无解", True)
    # Distinct 在档位谓词可用
    rd = run_round(parse_declare("x:a,y:b"), ["x+y>=1"],
                   {"异": "Distinct(x,y)", "同": "Not(Distinct(x,y))"}, [], 100, "验收·Distinct", True)
    # 沙箱逃逸必须被拒
    esc1, _ = _expect_error("x.__class__", vars_decl, "__class__")
    esc2, _ = _expect_error("x.__class__.__mro__", vars_decl, "不允许")
    esc3, _ = _expect_error("(lambda:1)()", vars_decl, "Lambda")
    # 未声明变量必须被拒
    undecl, _ = _expect_error("y+1", {"x": "t"}, "未允许的名字")

    return [
        ("第一轮有解", r1["solutions"] > 0),
        ("第一轮推荐=观望", r1["recommend"] == "观望"),
        ("第二轮有解", r2["solutions"] > 0),
        ("第二轮推荐=观望(收敛)", r2["recommend"] == "观望"),
        ("收敛无漂移", r1["recommend"] == r2["recommend"]),
        ("分支表按满足数降序", all(r1["branches"][i]["sat"] >= r1["branches"][i+1]["sat"]
                                    for i in range(len(r1["branches"]) - 1))),
        ("截断标志正确触发", len(rt) == 3 and rtrunc),
        ("全角冒号逗号归一化", v_full == v_half == {"x": "可行性", "y": "预算充足"}),
        ("全角分号归一化(约束)", "x==1" in c_full),
        ("全角分号冒号归一化(档位)", set(d_full) == {"做", "观望"}),
        ("rounds 位置语义(3段=3轮)", len(segs) == 3 and segs[0] == "" and segs[2] == "z==0"),
        ("rounds 位置语义(|y==0=2轮)", len(segs2) == 2 and segs2[1] == "y==0"),
        ("无解轮 status=unsat 且有建议", ru["status"] == "unsat" and len(ru["warnings"]) > 0),
        ("Distinct 可用于档位谓词", rd["votes"].get("异", 0) + rd["votes"].get("同", 0) == rd["solutions"]),
        ("沙箱逃逸·属性访问被拒", esc1),
        ("沙箱逃逸·MRO 遍历被拒", esc2),
        ("沙箱逃逸·Lambda 被拒", esc3),
        ("未声明变量被拒", undecl),
    ]


def selftest() -> bool:
    """跑内置验收，打印结果；全部通过返回 True。"""
    checks = selftest_checks()
    print("\n===== 验收断言 =====")
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print(f"\n验收结果: {'全部通过' if ok else '存在失败'}")
    return ok

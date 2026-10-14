"""条款追溯：宪章条款 ↔ 内核实现 ↔ 测试 的双向验证。

这是本项目最重要的一条设计护栏。被分析的四份材料共同的失败模式是
「规范写了一套，实现做的是另一套，且没人能及时发现」。本测试把这种漂移
变成**可机械检出的失败**：

  1. 每条被声明"已实现"的条款，必须真实存在于 charter.yaml；
  2. 每个执行条款的内核模块，必须真实存在于源码树；
  3. 每条关键条款，必须有指名它的测试。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from collab_charter import Charter

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# ① 条款 → 执行它的内核模块
# ---------------------------------------------------------------------------
CLAUSE_IMPLEMENTATION: dict[str, str] = {
    # 0.1 / 0.2 流的定义与元数据标签
    "0.1-V": "flows",
    "0.2-V": "flows",
    # 0.3 八站管线与三条不变量
    "0.3-I1": "router",
    "0.3-I2": "router",
    "0.3-I3": "gates",
    # 0.4 / 0.5 优先级与冲突裁决
    "0.4-R1": "arbiter",
    "0.5-R1": "arbiter",
    "0.5-R2": "arbiter",
    "0.5-R3": "arbiter",
    "0.5-R4": "arbiter",
    "0.5-R5": "arbiter",
    # 0.6 记忆流三操作
    "0.6-O1": "memory",
    "0.6-O2": "memory",
    "0.6-O3": "memory",
    # 0.7 输出过滤
    "0.7-R1": "router",
    "0.7-R2": "session",
    "0.7-R3": "router",
    # 0.8 回流前自检六项
    "0.8-C1": "selfcheck",
    "0.8-C2": "selfcheck",
    "0.8-C3": "selfcheck",
    "0.8-C4": "selfcheck",
    "0.8-C5": "selfcheck",
    "0.8-C6": "selfcheck",
    # 第一章 接收自检
    "1-C1": "session",
    "1-C2": "session",
    "1-C3": "session",
    "1-C4": "session",
    # 第九章 快捷词
    "9-W1": "session",
    "9-W2": "session",
    "9-W3": "session",
    "9-W4": "session",
    "9-W5": "session",
    "9-W6": "session",
    # 第十章 安全边界
    "10-R1": "gates",
    "10-R2": "gates",
    "10-R3": "gates",
    "10-R4": "gates",
    # 第十一章 知识库与语义场（v3.2；模块为包内子模块，用点号路径）
    "11.1-K1": "lexicon.kb",      # 加载与零代码扩容
    "11.1-K2": "lexicon.kb",      # 溯源与未验证名单
    "11.1-K3": "lexicon.kb",      # 摘要与 digest
    "11.2-V1": "lexicon.vectors",  # 向量征量空间与空间指纹
    "11.2-V2": "lexicon.mine",     # 分布权重
    "11.2-V3": "lexicon.vectors",  # 任务期临时建构、用后即弃
    "11.3-F1": "lexicon.field",    # 关联网络
    "11.3-F2": "lexicon.field",    # 覆盖缺口
    "11.3-F3": "lexicon.kb",       # 释义以来源为准
    "11.4-M1": "lexicon.mine",     # 闸门结论
    "11.4-M2": "lexicon.mine",     # 在线扩容只报不执行
    "11.4-M3": "lexicon.mine",     # 语义状态策略
    # 第十二章 符号锚定（v3.2；cognitive-anchor v2.0 并入）
    "12.1-A1": "anchor.solver",    # 结论来自求解器
    "12.1-A2": "anchor.solver",    # AST 白名单
    "12.1-A3": "anchor.solver",    # 警告原样转告
    "12.1-A4": "anchor.solver",    # 漂移必须提示
    "12.1-A5": "anchor.solver",    # 未覆盖解数必须报告
}

# ---------------------------------------------------------------------------
# ② 特征簇规范章节 → fcslint 规则码
# ---------------------------------------------------------------------------
SPEC_IMPLEMENTATION: dict[str, tuple[str, ...]] = {
    "2.1": ("FCS001", "FCS011"),   # 封闭集分类 / 排布顺序
    "3.1": ("FCS008",),            # 核心载体锚点
    "3.2": ("FCS006",),            # 风格域数量法则
    "3.4": ("FCS003", "FCS005"),   # 抽象词条权重与数量
    "3.5": ("FCS010",),            # 权重梯度
    "5.4": ("FCS007",),            # 冗余过滤
    "8.3": ("FCS004", "FCS009"),   # 冲突判定
    "9.1": ("FCS002",),            # 权重区间
}

# ---------------------------------------------------------------------------
# ③ 条款 → 指名它的测试函数（片段匹配）
# ---------------------------------------------------------------------------
TEST_COVERAGE: dict[str, str] = {
    "0.1-V": "test_分层与宪章一致",
    "0.2-V": "test_八个元数据标签齐备",
    "0.3-I1": "test_reflow_后自检通过",
    "0.3-I2": "test_全量路由包含认知镜像",
    "0.3-I3": "test_不过闸时管线终止",
    "0.4-R1": "test_真实高于用户目标",
    "0.5-R1": "test_事实优于推测",
    "0.5-R2": "test_新信息优于旧信息",
    "0.5-R3": "test_用户显式陈述优于模型推测",
    "0.5-R4": "test_同级同源并列呈现",
    "0.5-R5": "test_情感流不参与事实裁决",
    "0.6-O1": "test_沉淀生成记忆节点",
    "0.6-O2": "test_再激活还原为带元数据的流",
    "0.6-O3": "test_用户纠正刷新为高置信并记录来源",
    "0.7-R1": "test_内部流不进入输出",
    "0.7-R2": "test_简化快捷词压缩输出",
    "0.7-R3": "test_低置信流出前补待验证",
    "0.8-C1": "test_约束丢失被检出",
    "0.8-C2": "test_未回流时自检失败",
    "0.8-C3": "test_不可追溯的事实流被检出",
    "0.8-C4": "test_未回流时自检失败",
    "0.8-C5": "test_未回流时自检失败",
    "0.8-C6": "test_全部通过时报告为空",
    "1-C1": "test_receipt_不超过三行",
    "1-C2": "test_声明不可执行时附降级方案",
    "1-C4": "test_receipt_无寒暄",
    "9-W2": "test_简化快捷词压缩输出",
    "9-W6": "test_快捷词被识别",
    "10-R1": "test_每种组合都有裁决",
    "10-R3": "test_禁外发一律拦截",
    # 第十一章 / 第十二章（v3.2）
    "11.1-K1": "test_零代码扩容",
    "11.1-K2": "test_不可溯源条目进入名单",
    "11.1-K3": "test_digest_稳定且随内容变化",
    "11.2-V1": "test_空间指纹随上下文变化",
    "11.2-V2": "test_分布权重归一",
    "11.2-V3": "test_空间任务期临时建构用后即弃",
    "11.3-F1": "test_关联网络与社群",
    "11.3-F2": "test_覆盖缺口可操作",
    "11.3-F3": "test_检索工具返回可溯源字段",
    "11.4-M1": "test_高危条目闸门_block",
    "11.4-M2": "test_在线扩容只报不执行",
    "11.4-M3": "test_语义状态策略表齐全",
    "12.1-A1": "test_第一轮推荐观望",
    "12.1-A2": "test_逃逸构造一律被拒",
    "12.1-A3": "test_无解轮给出建议",
    "12.1-A4": "test_solve_检测漂移并提示标准未稳",
    "12.1-A5": "test_档位未覆盖的解被计数",
}


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cid", sorted(CLAUSE_IMPLEMENTATION))
def test_声明实现的条款真实存在(charter: Charter, cid: str) -> None:
    c = charter.clause(cid)
    assert c.id == cid


@pytest.mark.parametrize("cid,module", sorted(CLAUSE_IMPLEMENTATION.items()))
def test_执行条款的模块存在且可导入(cid: str, module: str) -> None:
    """模块可以是单文件（gates）或包内子模块（lexicon.kb / anchor.solver）。"""
    rel = Path(*module.split("."))
    assert (ROOT / "src" / "collab_charter" / f"{rel}.py").is_file(), f"{module}.py 不存在"
    importlib.import_module(f"collab_charter.{module}")


@pytest.mark.parametrize("section,codes", sorted(SPEC_IMPLEMENTATION.items()))
def test_规范章节有对应规则码(section: str, codes: tuple[str, ...]) -> None:
    from fcslint.rules import Linter

    source = (ROOT / "tools" / "fcslint" / "rules.py").read_text(encoding="utf-8")
    for code in codes:
        assert f'"{code}"' in source, f"规范 {section} 声明的规则 {code} 未在规则引擎中实现"
    assert Linter is not None


def test_规则码在报告层被渲染() -> None:
    report = (ROOT / "tools" / "fcslint" / "report.py").read_text(encoding="utf-8")
    assert "suggest" in report
    assert "clause" in report, "报告应带上依据条款，供「查来源」回溯"


def test_关键条款都有指名测试(charter: Charter, request: pytest.FixtureRequest) -> None:
    collected = {item.name.split("[")[0] for item in request.session.items}
    missing = []
    for cid, test_name in TEST_COVERAGE.items():
        charter.clause(cid)  # 条款必须真实存在
        if test_name not in collected:
            missing.append(f"{cid} → {test_name}")
    assert missing == [], "以下条款缺少指名测试：\n  " + "\n  ".join(missing)


def test_条款覆盖率达标(charter: Charter) -> None:
    """已实现条款占可执行条款的比例。

    可执行 = 带规则型类型的条款：R/I/C/O/V/W/P（前三版）+
    K/F/M/A（v3.2 新增：知识库/语义场/深挖/锚定，同为可机械检出的规则）。
    """
    executable = [
        c for c in charter
        if c.kind in {"R", "I", "C", "O", "V", "W", "P", "K", "F", "M", "A"}
    ]
    implemented = [c for c in executable if c.id in CLAUSE_IMPLEMENTATION]
    ratio = len(implemented) / max(1, len(executable))
    print(
        f"\n可执行条款 {len(executable)} 条，已声明实现 {len(implemented)} 条，"
        f"覆盖率 {ratio:.0%}"
    )
    # 关键条款（0/10 章 + 0.8）必须全覆盖
    critical = [
        c.id for c in executable
        if c.id.startswith(("0.", "10-"))
    ]
    not_impl = [c for c in critical if c not in CLAUSE_IMPLEMENTATION]
    assert not_impl == [], f"以下关键条款尚无实现声明：{not_impl}"


def test_实现声明不指向不存在的条款(charter: Charter) -> None:
    """反向检查：不能声明实现一个宪章里没有的条款（防止一厢情愿）。"""
    all_ids = set(charter.clause_ids())
    bogus = [cid for cid in CLAUSE_IMPLEMENTATION if cid not in all_ids]
    assert bogus == [], f"以下实现声明指向不存在的条款：{bogus}"


def test_ssot_契约在实际文件中被声明() -> None:
    """三条 SSOT 契约必须写进 charter.yaml 头部，而不是只活在文档里。"""
    text = (ROOT / "charter" / "charter.yaml").read_text(encoding="utf-8")
    assert "单一事实源" in text
    assert "id 一旦发布不得复用或改写含义" in text
    assert "可判定" in text

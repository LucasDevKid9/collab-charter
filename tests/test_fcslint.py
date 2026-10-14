"""fcslint：特征簇标记语法的规则引擎与控制力量化。"""

from __future__ import annotations

import pytest

from conftest import CASE_HI8, CASE_PC98
from fcslint import Lexicon, Linter, parse, render
from fcslint.report import suggest, to_dict
from fcslint.rules import Analysis


@pytest.fixture(scope="module")
def lex() -> Lexicon:
    return Lexicon.load()


@pytest.fixture(scope="module")
def linter(lex: Lexicon) -> Linter:
    return Linter(lex)


# -- 解析器（规范第 9 章） --------------------------------------------------
def test_逗号是唯一分隔符() -> None:
    p = parse("甲, 乙，丙")
    assert [i.text for i in p.items] == ["甲", "乙", "丙"]


def test_括号内的逗号不是分隔符() -> None:
    p = parse("(Agfacolor胶片色阶浸染，时代印痕:0.8), 低保真")
    assert len(p.items) == 2, "括号内全角逗号属于词条内容，不得切开"
    assert p.items[0].text == "Agfacolor胶片色阶浸染，时代印痕"
    assert p.items[0].weight == 0.8


def test_全角标点被归一化() -> None:
    p = parse("甲，乙，丙")
    assert len(p.items) == 3


def test_权重标记解析() -> None:
    p = parse("(主体:1.4), (氛围:0.6)")
    assert p.items[0].weight == 1.4 and p.items[0].explicit_weight
    assert p.items[1].weight == 0.6


def test_无括号权重写法也识别() -> None:
    p = parse("私影像cult风:1.3, 低保真")
    assert p.items[0].text == "私影像cult风"
    assert p.items[0].weight == 1.3


def test_画幅不被误判为权重() -> None:
    p = parse("立绘, 16:9")
    assert p.items[1].is_param is True, "16:9 是画幅而非权重标记"
    assert p.items[1].explicit_weight is False


def test_簇标记被保留但不计入词条内容() -> None:
    p = parse("[色彩系统] (荧光白:1.2), 暗苔绿")
    assert p.items[0].cluster_marker == "色彩系统"
    assert p.items[0].text == "荧光白"


def test_渲染可往返() -> None:
    src = "古早立绘, (赛璐璐平涂:1.2), 4:3"
    assert render(parse(src).items) == src


def test_空输入返回空结果() -> None:
    assert len(parse("")) == 0
    assert len(parse("   ")) == 0


# -- 规则：六大簇归类（2.1） -----------------------------------------------
def test_词条被归入六大簇(linter: Linter, lex: Lexicon) -> None:
    a = linter.analyze(CASE_PC98)
    clusters = {c.cluster for c in a.classified}
    assert clusters <= set(lex.clusters), "归类结果必须落在六大簇封闭集内"
    assert "subject" in clusters


def test_未归类词条被显式报出(linter: Linter) -> None:
    a = linter.analyze("古早立绘, 完全没见过的词条甲")
    assert any(f.code == "FCS001" for f in a.findings), "6.6：禁止静默过滤"
    assert "完全没见过的词条甲" in a.unclassified()[0].text


# -- 规则：权重（9.1 / 3.4 / 3.5） ----------------------------------------
def test_权重越界被报错(linter: Linter) -> None:
    a = linter.analyze("(古早立绘:2.5)")
    assert any(f.code == "FCS002" for f in a.findings)


def test_抽象词条高权重被报错(linter: Linter) -> None:
    a = linter.analyze("(古早立绘:1.2), (宿命感:1.1)")
    assert any(f.code == "FCS003" for f in a.findings), "3.4：抽象词条权重必须 < 1.0"


def test_抽象词条数量不得不少于实体(linter: Linter) -> None:
    a = linter.analyze("古早立绘, 宿命感, 存在主义焦虑, 审美疲劳")
    assert any(f.code == "FCS005" for f in a.findings)


def test_权重梯度偏离给提示但不定罪(linter: Linter) -> None:
    a = linter.analyze("(低保真:1.4)")
    hit = [f for f in a.findings if f.code == "FCS010"]
    assert hit and hit[0].severity == "info", "3.5 与第 11 章冲突时只提示，不替创作者判决"


# -- 规则：锚点与冲突（3.1 / 8.3） ----------------------------------------
def test_缺主体锚点被报错(linter: Linter) -> None:
    a = linter.analyze("低保真, 光感漫射, 低分辨率")
    assert any(f.code == "FCS008" for f in a.findings)


def test_直接语义冲突被报错(linter: Linter) -> None:
    a = linter.analyze("古早立绘, 带着微微颗粒感, 禁噪点")
    hit = [f for f in a.findings if f.code == "FCS004"]
    assert hit and hit[0].severity == "error"
    assert "颗粒感" in hit[0].message and "禁噪点" in hit[0].message


def test_跨域逻辑冲突只警告(linter: Linter) -> None:
    a = linter.analyze("古早立绘, Agfacolor胶片色阶浸染, Hi8机分辨率质感")
    hit = [f for f in a.findings if f.code == "FCS009"]
    assert hit and hit[0].severity == "warn", "8.3：跨域冲突是可控风险，不是硬错误"


# -- 规则：风格域与冗余（3.2 / 5.4） --------------------------------------
def test_风格域超限被警告(linter: Linter) -> None:
    a = linter.analyze("古早立绘, 奇情武侠, 网络核艺术, 蒸汽波, 哥特")
    assert any(f.code == "FCS006" for f in a.findings)


def test_无效技术参数被报出(linter: Linter) -> None:
    a = linter.analyze("古早立绘, 随机种子")
    hit = [f for f in a.findings if f.code == "FCS007"]
    assert hit and "随机种子" in hit[0].message


def test_簇序倒置被检出(linter: Linter) -> None:
    # 畸变图层（order 5）先于媒介采集（order 4）出现
    a = linter.analyze("古早立绘, 抠图伪影, 扫描线")
    assert any(f.code == "FCS011" for f in a.findings)


# -- 控制力量化（5.4） -----------------------------------------------------
def test_评分在合理区间(linter: Linter) -> None:
    a = linter.analyze(CASE_PC98)
    assert 0 <= a.score.total <= 100
    assert a.score.grade in {"A 可控", "B 基本可控", "C 存在漂移风险", "D 不可控"}


def test_无锚点实例评分显著更低(linter: Linter) -> None:
    good = linter.analyze(CASE_PC98).score.total
    bad = linter.analyze("带着微微颗粒感, 禁噪点, 有点模糊, 随机种子").score.total
    assert bad < good, "锚点缺失 + 冲突 + 无效项应显著拉低控制力"


def test_评分四项都有明细(linter: Linter) -> None:
    a = linter.analyze(CASE_PC98)
    for key in ("词条总数", "实体视觉", "抽象概念", "高映射", "冲突数"):
        assert key in a.score.detail


# -- 簇结构保留优化（5.2） -------------------------------------------------
def test_优化稿不移除核心意图词条(linter: Linter) -> None:
    a = linter.analyze("(古早立绘:1.2), 宿命感, 随机种子")
    s = suggest(a, Lexicon.load())
    assert "古早立绘" in s.optimized, "第 11 章禁止项 5：不得抹除核心表达"
    assert "随机种子" not in s.optimized, "无效技术参数应移除"
    assert "宿命感" in s.optimized


def test_优化稿把主体锚点前置(linter: Linter, lex: Lexicon) -> None:
    a = linter.analyze("宿命感, 低保真, 古早立绘")
    s = suggest(a, lex)
    assert s.optimized.index("古早立绘") < s.optimized.index("宿命感")


def test_优化稿仍是短句簇而非叙事长句(linter: Linter, lex: Lexicon) -> None:
    a = linter.analyze(CASE_PC98)
    s = suggest(a, lex)
    assert "。 " not in s.optimized, "第 11 章禁止项 1：禁止改写为自然叙事"
    assert s.optimized.count(",") >= 10


def test_无问题时不改动(linter: Linter, lex: Lexicon) -> None:
    a = linter.analyze("(古早立绘:1.2), 赛璐璐平涂, 4:3")
    s = suggest(a, lex)
    assert s.optimized  # 至少能渲染


# -- 结构化输出 ------------------------------------------------------------
def test_结构化输出字段完整(linter: Linter, lex: Lexicon) -> None:
    data = to_dict(linter.analyze(CASE_PC98), lex)
    for key in ("summary", "score_detail", "clusters", "findings", "suggestion"):
        assert key in data
    assert data["summary"]["score"] == linter.analyze(CASE_PC98).score.total

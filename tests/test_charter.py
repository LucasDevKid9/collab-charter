"""宪章加载与 SSOT 契约。

对应契约（charter.yaml 头部三条）：
  1. 条款 id 全局唯一
  2. 每条条款可判定（非空文本）
  3. 条款 id 一旦发布不得复用或改写含义（此处以快照式断言守住已知条款）
"""

from __future__ import annotations

import pytest

from collab_charter import Charter
from collab_charter.charter_loader import CLAUSE_ID_RE, CharterError


def test_条款_id_全局唯一(charter: Charter) -> None:
    ids = charter.clause_ids()
    assert len(ids) == len(set(ids)), "SSOT 契约 1 被破坏：存在重复条款 id"


def test_条款均可判定(charter: Charter) -> None:
    empty = [c.id for c in charter if not c.text.strip()]
    assert empty == [], f"SSOT 契约 2 被破坏：以下条款无判定文本 {empty}"


def test_条款_id_格式合法(charter: Charter) -> None:
    bad = [c.id for c in charter if not CLAUSE_ID_RE.match(c.id)]
    assert bad == [], f"条款 id 不符合 章节-类型序号 格式：{bad}"


def test_十一个章节都被索引(charter: Charter) -> None:
    chapters = {c.chapter_key for c in charter}
    expected = {
        "chapter_0_information_flow",
        "chapter_1_receipt",
        "chapter_2_user_profile",
        "chapter_3_communication",
        "chapter_4_minimal_context",
        "chapter_5_analysis",
        "chapter_6_local_files",
        "chapter_7_cognition_memory",
        "chapter_8_output_format",
        "chapter_9_shortcuts",
        "chapter_10_safety",
    }
    assert expected <= chapters, f"缺少章节：{expected - chapters}"


@pytest.mark.parametrize(
    "cid",
    [
        "0.1-V", "0.2-V",
        "0.3-I1", "0.3-I2", "0.3-I3",
        "0.4-R1",
        "0.5-R1", "0.5-R2", "0.5-R3", "0.5-R4", "0.5-R5",
        "0.6-O1", "0.6-O2", "0.6-O3",
        "0.7-R1", "0.7-R2", "0.7-R3",
        "0.8-C1", "0.8-C2", "0.8-C3", "0.8-C4", "0.8-C5", "0.8-C6",
        "1-C1", "2-P1", "3-R1", "4-V1", "5-R1", "6-R1",
        "7-R1", "8-R1", "9-W1", "10-R1",
    ],
)
def test_关键条款存在且可寻址(charter: Charter, cid: str) -> None:
    c = charter.clause(cid)
    assert c.id == cid
    assert c.text
    assert "/" in c.anchor  # 定位串形如 章节/小节/条款id


def test_查询不存在的条款必须报错(charter: Charter) -> None:
    with pytest.raises(CharterError):
        charter.clause("99-X9")


def test_章节访问不存在的小节必须报错(charter: Charter) -> None:
    with pytest.raises(CharterError):
        charter.section("chapter_0_information_flow", "no_such_section")
    with pytest.raises(CharterError):
        charter.section("no_such_chapter", "x")


def test_关键词检索(charter: Charter) -> None:
    hits = charter.find("并列呈现")
    assert any(c.id == "0.5-R4" for c in hits)


def test_单据加载不存在的文件必须报错() -> None:
    with pytest.raises(CharterError):
        Charter.load("/nonexistent/path/charter.yaml")

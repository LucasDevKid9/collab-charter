"""知识库与潜空间语义场（宪章第十一章）：加载校验 / 向量征量空间 /
语义场建构 / 深挖引擎。

覆盖条款：11.1-K1..K3（加载/溯源/摘要）、11.2-V1..V3（稀疏向量/分布
权重/空间指纹）、11.3-F1..F3（关联/中心性/覆盖）、11.4-M1..M3（闸门/
在线扩容/语义状态策略）。
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from collab_charter.lexicon import (
    KnowledgeBase,
    KnowledgeBaseError,
    MiningRequest,
    StatePolicy,
    build_field,
    lexicon_search,
    mine,
)
from collab_charter.lexicon.vectors import (
    CONTEXT_BOOST,
    SPACE_VERSION,
    W_GLOSS,
    W_META,
    W_UNIGRAM,
    MeasureSpace,
    cosine,
    entry_features,
    tokenize,
    tokenize_query,
)


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return KnowledgeBase.load()


ROOT = Path(__file__).resolve().parents[1]
KB_DIR = ROOT / "knowledge"


# ===========================================================================
# 11.1 知识库加载与校验
# ===========================================================================
class Test知识库加载:
    def test_三文件合并(self, kb: KnowledgeBase) -> None:
        assert set(kb.files) == {"lexicon.yaml", "styles.yaml", "subcultures.yaml"}
        assert len(kb) == sum(kb.stats()["files"].values())

    def test_零代码扩容(self, kb: KnowledgeBase) -> None:
        """新 yaml 文件无需改代码即进入库（11.1-K1）。"""
        ids = {e.id for e in kb}
        assert "style_lofi" in ids          # styles.yaml
        assert "sub_yyds" in ids            # subcultures.yaml

    def test_digest_稳定且随内容变化(self, kb: KnowledgeBase, tmp_path) -> None:
        d1 = kb.digest()
        assert d1 == kb.digest()
        # 追加一个文件后 digest 必须变
        import shutil
        for name in kb.files:
            shutil.copy(KB_DIR / name, tmp_path / name)
        (tmp_path / "extra.yaml").write_text(
            "version: 1\nentries:\n  - {id: x1, term: 测试词, kind: entity}\n",
            encoding="utf-8")
        kb2 = KnowledgeBase.load(tmp_path)
        assert kb2.digest() != d1

    def test_断链即错(self, tmp_path) -> None:
        (tmp_path / "broken.yaml").write_text(
            "version: 1\nentries:\n"
            "  - {id: a1, term: 甲, kind: entity, related: [不存在的id]}\n",
            encoding="utf-8")
        with pytest.raises(KnowledgeBaseError, match="不存在"):
            KnowledgeBase.load(tmp_path)

    def test_空目录报错(self, tmp_path) -> None:
        with pytest.raises(KnowledgeBaseError, match="没有任何知识文件"):
            KnowledgeBase.load(tmp_path)

    def test_跨文件同名词被检出(self, kb: KnowledgeBase) -> None:
        assert kb.duplicate_terms, "styles 与 lexicon 的重复词条应被检出"
        for term, ids in kb.duplicate_terms.items():
            assert len(ids) >= 2

    def test_检索与定位(self, kb: KnowledgeBase) -> None:
        hits = kb.search("谷圈")
        assert any(e.term == "谷圈" for e in hits)
        e = kb.get("sub_kaihe")
        assert e.term == "开盒"
        assert e.sensitivity == "高危"
        assert e.permission == "禁外发"

    def test_按类型过滤(self, kb: KnowledgeBase) -> None:
        styles = kb.by_kind("style")
        assert styles and all(e.kind == "style" for e in styles)

    def test_簇名与权重梯度(self, kb: KnowledgeBase) -> None:
        assert kb.cluster_zh("subject") == "主体实体"
        band = kb.weight_gradient("subject")
        assert band and band["min"] <= band["max"]

    def test_不可溯源条目进入名单(self, tmp_path) -> None:
        (tmp_path / "unv.yaml").write_text(
            "version: 1\nentries:\n  - {id: u1, term: 无来源词, kind: entity}\n",
            encoding="utf-8")
        kb2 = KnowledgeBase.load(tmp_path)
        assert "u1" in kb2.unverified
        assert kb2.stats()["unverified_count"] == 1


# ===========================================================================
# 11.2 向量征量空间
# ===========================================================================
class Test向量征量空间:
    def test_分词含_n_gram(self) -> None:
        toks = tokenize("赛璐莉平涂")
        assert "赛璐" in toks and "璐" in toks and "平涂" in toks
        assert "赛璐莉" not in toks, "CJK 只取单字 + 相邻二元组（召回取向）"

    def test_查询侧词表最大匹配(self, kb: KnowledgeBase) -> None:
        """查询「谷圈社群」应按词表切出整词，不产生跨边界二元组。"""
        space = MeasureSpace.build(kb)
        toks = tokenize_query("谷圈社群", space.vocab)
        assert "谷圈" in toks
        assert "圈社" not in toks

    def test_条目特征权重分级(self) -> None:
        from collab_charter.lexicon.kb import Entry

        e = Entry(id="t1", term="立绘", kind="entity", source_file="test",
                  cluster="subject", domain=["复古"], era="2000s",
                  tags=["测试"], gloss="人物站立图画")
        feats = entry_features(e)
        # 整词 = term 1.0 + 自身二元组 1.0；单字 0.35
        assert feats["t:立绘"] == pytest.approx(2.0)
        assert feats["t:立"] == pytest.approx(W_UNIGRAM)
        assert feats["c:subject"] == pytest.approx(W_META)
        assert feats["k:entity"] == pytest.approx(W_META)
        assert feats["d:复古"] == pytest.approx(W_META)
        assert feats["e:2000s"] == pytest.approx(W_META)
        assert feats["g:测试"] == pytest.approx(W_META)
        assert feats["s:图画"] == pytest.approx(W_GLOSS)

    def test_余弦基本性质(self) -> None:
        assert cosine({"a": 1.0}, {"a": 1.0}) == pytest.approx(1.0)
        assert cosine({"a": 1.0}, {"b": 1.0}) == pytest.approx(0.0)
        assert cosine({}, {"a": 1.0}) == 0.0

    def test_向量_l2_归一(self, kb: KnowledgeBase) -> None:
        space = MeasureSpace.build(kb)
        for vec in list(space.entry_vectors.values())[:20]:
            norm = math.sqrt(sum(v * v for v in vec.values()))
            assert norm == pytest.approx(1.0, abs=1e-9)

    def test_空间指纹随上下文变化(self, kb: KnowledgeBase) -> None:
        s1 = MeasureSpace.build(kb, context=["探索期"])
        s2 = MeasureSpace.build(kb, context=["收敛期"])
        assert s1.digest != s2.digest
        assert MeasureSpace.build(kb, context=["探索期"]).digest == s1.digest
        assert s1.dimension == s2.dimension

    def test_上下文增益作用于条目侧(self, kb: KnowledgeBase) -> None:
        """上下文中出现的特征应在条目侧提权（11.4-M3 的空间侧机制）。"""
        base = MeasureSpace.build(kb)
        boosted = MeasureSpace.build(kb, context=["晒谷 吃谷"])
        eid = next(e.id for e in kb if e.term == "晒谷")
        v0 = base.vector_of(eid)
        v1 = boosted.vector_of(eid)
        q = base.query_vector(["晒谷"])
        assert cosine(v1, q) > cosine(v0, q)
        assert CONTEXT_BOOST > 1.0


# ===========================================================================
# 11.3 潜空间语义场
# ===========================================================================
class Test语义场:
    def test_关联网络与社群(self, kb: KnowledgeBase) -> None:
        space = MeasureSpace.build(kb, context=["整理徽章收藏圈的术语"])
        qf = space.query_features(["谷圈 痛包 吧唧 吃谷 晒谷"])
        ids = [e.id for e in kb.search("谷圈")] + [
            e.id for e in kb if e.term in {"痛包", "吧唧", "吃谷", "晒谷"}]
        field = build_field(space, ids, qf)
        assert field.metrics["node_count"] >= 3
        assert field.metrics["edge_count"] >= 1
        assert field.metrics["modularity"] >= 0.0
        assert field.communities

    def test_中心性确定性(self, kb: KnowledgeBase) -> None:
        space = MeasureSpace.build(kb)
        qf = space.query_features(["谷圈 痛包 晒谷"])
        ids = [e.id for e in kb if e.term in {"谷圈", "痛包", "晒谷"}]
        f1 = build_field(space, ids, qf)
        f2 = build_field(space, list(reversed(ids)), qf)
        # 幂迭代均匀初始化：节点顺序只影响浮点求和次序，数值应一致
        assert set(f1.centrality) == set(f2.centrality)
        for eid in f1.centrality:
            assert f1.centrality[eid] == pytest.approx(f2.centrality[eid], abs=1e-9)
        for c in f1.centrality.values():
            assert 0.0 <= c <= 1.0

    def test_冲突断边(self, kb: KnowledgeBase) -> None:
        space = MeasureSpace.build(kb)
        qf = space.query_features(["胶片 数码"])
        # 找一对显式冲突
        pair = None
        for e in kb:
            for cid in e.conflicts:
                if cid in kb.entries and kb.entries[cid].term != e.term:
                    pair = (e.id, cid)
                    break
            if pair:
                break
        assert pair, "知识库中应存在显式冲突对"
        field = build_field(space, list(pair), qf)
        assert not any(
            {edge.a, edge.b} == set(pair) for edge in field.edges
        ), "互斥词条之间不得有边"

    def test_覆盖缺口可操作(self, kb: KnowledgeBase) -> None:
        space = MeasureSpace.build(kb, context=["整理术语"])
        qf = space.query_features(["谷圈 痛包 晒谷"])
        ids = [e.id for e in kb if e.term in {"谷圈", "痛包", "晒谷"}]
        field = build_field(space, ids, qf)
        assert isinstance(field.gaps, list)
        for g in field.gaps:
            assert g.startswith("t:"), "缺口应指向具体特征而非边界二元组"

    def test_to_dict_可_json_化(self, kb: KnowledgeBase) -> None:
        import json

        space = MeasureSpace.build(kb)
        qf = space.query_features(["谷圈"])
        field = build_field(space, [e.id for e in kb.search("谷圈")], qf)
        json.dumps(field.to_dict(), ensure_ascii=False)


# ===========================================================================
# 11.4 深挖引擎
# ===========================================================================
class Test深挖引擎:
    def test_语义状态策略表齐全(self) -> None:
        from collab_charter.lexicon.mine import STATE_POLICIES

        assert set(STATE_POLICIES) == {
            "探索期", "发散期", "收敛期", "聚焦期", "创意期", "校验期"}
        for p in STATE_POLICIES.values():
            assert isinstance(p, StatePolicy)

    def test_未知语义状态告警并回落中性(self, kb) -> None:
        from collab_charter.lexicon.mine import NEUTRAL_POLICY, _resolve_policy

        warnings: list[str] = []
        policy = _resolve_policy("顿悟期", warnings)
        assert policy == NEUTRAL_POLICY
        assert any("未识别的语义状态" in w for w in warnings)

    def test_分布权重归一(self, kb) -> None:
        r = mine(MiningRequest(requirement="谷圈 痛包 晒谷", limit=8), kb=kb)
        assert r.entries
        assert sum(e.weight for e in r.entries) == pytest.approx(1.0, abs=1e-6)

    def test_同词条跨文件去重(self, kb) -> None:
        # 「超现实主义」在 lexicon 与 styles 各有一份（duplicate_terms 已检出）
        assert "超现实主义" in kb.duplicate_terms
        r = mine(MiningRequest(requirement="超现实主义 梦境 绘画", limit=10), kb=kb)
        terms = [e.term for e in r.entries]
        assert len(terms) == len(set(terms)), "同一词条不得入选两次"
        assert any("去重" in w for w in r.warnings)

    def test_invalid_条目被剔除(self, kb) -> None:
        r = mine(MiningRequest(requirement="随机种子 立绘", limit=10), kb=kb)
        assert "随机种子" not in [e.term for e in r.entries]
        assert any("随机种子" in w for w in r.warnings)

    def test_高危条目闸门_block(self, kb) -> None:
        r = mine(MiningRequest(requirement="开盒 人肉搜索", limit=8), kb=kb)
        for e in r.entries:
            if e.term in {"开盒", "人肉搜索"}:
                assert e.gate and e.gate["verdict"] == "block"
                assert e.gate["clause"] == "10-R3"

    def test_在线扩容只报不执行(self, kb) -> None:
        r = mine(MiningRequest(requirement="谷圈", allow_online=True, limit=5), kb=kb)
        oe = r.online_expansion
        assert oe and oe["requested"] is True
        assert oe["executed"] is False
        assert oe["requires_user_confirmation"] is True
        assert oe["confirmation_clause"] == "10-R4"

    def test_特征簇建议含簇位与权重(self, kb) -> None:
        r = mine(MiningRequest(requirement="谷圈 痛包", limit=5), kb=kb)
        for e in r.entries:
            assert "example" in e.suggestion
            assert "cluster" in e.suggestion

    def test_min_score_可覆盖策略阈值(self, kb) -> None:
        base = mine(MiningRequest(requirement="谷圈", semantic_state="收敛期", limit=10), kb=kb)
        tuned = mine(MiningRequest(requirement="谷圈", semantic_state="收敛期",
                                   limit=10, min_score=0.05), kb=kb)
        assert len(tuned.entries) >= len(base.entries)

    def test_检索工具返回可溯源字段(self, kb) -> None:
        out = lexicon_search("谷圈", limit=3, kb=kb)
        assert out and all({"id", "term", "kind", "source"} <= set(i) for i in out)

    def test_空间指纹可复现(self, kb) -> None:
        req = dict(requirement="谷圈 痛包", task_objectives=["整理术语"],
                   semantic_state="收敛期", limit=5)
        r1 = mine(MiningRequest(**req), kb=kb)
        r2 = mine(MiningRequest(**req), kb=kb)
        assert r1.space_digest == r2.space_digest
        assert len(r1.space_digest) == 64

    def test_空间任务期临时建构用后即弃(self, kb) -> None:
        """11.2-V3：空间按任务临时建构，不缓存、不跨任务复用。"""
        s1 = MeasureSpace.build(kb, context=["探索期"])
        s2 = MeasureSpace.build(kb, context=["探索期"])
        assert s1 is not s2, "不得返回缓存的空间实例"
        assert s1.digest == s2.digest, "同输入必须同指纹（可复现）"

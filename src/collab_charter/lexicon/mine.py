"""深挖引擎（宪章 11.4）：按需求、目标与语义状态，从知识库里挖词条。

输入四要素（缺一不可，缺了按宪章 4-V 系列用默认值并在结果里注明）
--------------------------------------------------------------
1. ``requirement``     用户需求原文
2. ``task_objectives`` 当前上下文/目标任务（可多条）
3. ``semantic_state``  语义状态（探索期/收敛期/创意期/校验期……）——
                       必须显式传入（11.4-M3），引擎不暗自假设；
                       未声明时按中性处理并在 warnings 里注明。
4. ``domains``         语义域偏好（可选）

输出
----
* 加权候选词条（相关性 × 先验 × 上下文增益，MMR 去重保多样）
* **分布权重**：每个入选词条的得分占总质量的比例（11.2-V2），
  并附特征级归因（是需求的哪些特征把它选上的）
* 潜空间语义场结构（社群/中心性/覆盖缺口）
* 闸门结论：非「公开/可输出」条目附第十章 3×3 裁决（11.4-M1）
* 特征簇标记建议：词条进提示词时的簇位与权重区间

边界
----
引擎只在**本地知识库**内检索（11.4-M2）。``allow_online=True`` 不构成
联网授权，只是把「用户请求了在线扩容」这一事实连同闸门结论报回去，
由调用方（平台/用户）决定是否真的外发。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from ..flows import (
    Confidence,
    Direction,
    Flow,
    FlowLayer,
    FlowType,
    Permission,
    Sensitivity,
    Source,
    TTL,
)
from ..gates import SafetyGate
from ..charter_loader import Charter
from .kb import Entry, KnowledgeBase
from .field import SemanticField, build_field
from .vectors import MeasureSpace, cosine

# ---------------------------------------------------------------------------
# 语义状态策略表（11.4-M3：状态是显式输入，不是暗自假设）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StatePolicy:
    """语义状态 → 评分策略。"""

    coverage_lambda: float   # 探索期奖励「覆盖更多需求特征」
    kind_boost: dict[str, float]  # 类型增益
    mmr_lambda: float        # MMR 多样性权重（越大越偏相关，越小越偏多样）
    min_score: float


STATE_POLICIES: dict[str, StatePolicy] = {
    "探索期": StatePolicy(coverage_lambda=0.35, kind_boost={"abstract": 1.15, "style": 1.15},
                        mmr_lambda=0.5, min_score=0.02),
    "发散期": StatePolicy(coverage_lambda=0.35, kind_boost={"abstract": 1.15, "style": 1.15},
                        mmr_lambda=0.5, min_score=0.02),
    "收敛期": StatePolicy(coverage_lambda=0.0, kind_boost={"entity": 1.15, "tech": 1.15},
                        mmr_lambda=0.8, min_score=0.06),
    "聚焦期": StatePolicy(coverage_lambda=0.0, kind_boost={"entity": 1.15, "tech": 1.15},
                        mmr_lambda=0.8, min_score=0.06),
    "创意期": StatePolicy(coverage_lambda=0.2, kind_boost={"style": 1.3, "abstract": 1.2, "meme": 1.15},
                        mmr_lambda=0.55, min_score=0.03),
    "校验期": StatePolicy(coverage_lambda=0.0, kind_boost={"entity": 1.25, "tech": 1.25},
                        mmr_lambda=0.85, min_score=0.08),
}

NEUTRAL_POLICY = StatePolicy(coverage_lambda=0.1, kind_boost={}, mmr_lambda=0.65, min_score=0.03)

#: 语义域命中增益
DOMAIN_BOOST = 1.25


@dataclass
class MiningRequest:
    """一次深挖请求。"""

    requirement: str = ""
    task_objectives: list[str] = field(default_factory=list)
    semantic_state: str = ""
    domains: list[str] = field(default_factory=list)
    limit: int = 12
    mmr_lambda: float | None = None
    min_score: float | None = None
    kinds: list[str] | None = None
    allow_online: bool = False


@dataclass
class MinedEntry:
    """一个入选词条及其分布权重与归因。"""

    id: str
    term: str
    kind: str
    cluster: str | None
    cluster_zh: str | None
    score: float
    weight: float                      # 分布权重（Σ=1）
    attribution: list[tuple[str, float]]  # 特征级归因（11.2-V2）
    gate: dict[str, Any] | None        # 闸门结论（11.4-M1）
    suggestion: dict[str, Any]         # 特征簇标记建议
    confidence: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "term": self.term,
            "kind": self.kind,
            "cluster": self.cluster,
            "cluster_zh": self.cluster_zh,
            "score": round(self.score, 4),
            "weight": round(self.weight, 4),
            "attribution": [
                {"feature": f, "share": round(s, 4)} for f, s in self.attribution
            ],
            "gate": self.gate,
            "suggestion": self.suggestion,
            "confidence": self.confidence,
            "source": self.source,
        }


@dataclass
class MiningResult:
    """一次深挖的完整结果（JSON 可序列化，供 MCP 传输）。"""

    kb_digest: str
    space_digest: str
    semantic_state: str
    policy: dict[str, Any]
    entries: list[MinedEntry]
    field: SemanticField
    warnings: list[str]
    online_expansion: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kb_digest": self.kb_digest,
            "space_digest": self.space_digest,
            "semantic_state": self.semantic_state,
            "policy": self.policy,
            "entries": [e.to_dict() for e in self.entries],
            "field": self.field.to_dict(),
            "warnings": self.warnings,
            "online_expansion": self.online_expansion,
        }


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------
def mine(
    request: MiningRequest,
    kb: KnowledgeBase | None = None,
    charter: Charter | None = None,
) -> MiningResult:
    """执行一次深挖。"""
    kb = kb or KnowledgeBase.load()
    charter = charter or Charter.load()
    warnings: list[str] = []

    policy = _resolve_policy(request.semantic_state, warnings)
    # 调用方显式传入 min_score 时覆盖策略默认值（与 mmr_lambda 同一约定）
    if request.min_score is not None:
        policy = replace(policy, min_score=request.min_score)
    context = [*request.task_objectives, request.semantic_state, *request.domains]
    space = MeasureSpace.build(kb, context=context)

    query_texts = [request.requirement, *request.task_objectives, request.semantic_state]
    query_vec = space.query_vector(query_texts)
    query_features = space.query_features(query_texts)

    # -- 1. 候选评分 --------------------------------------------------------
    scored: list[tuple[Entry, float]] = []
    excluded_invalid: list[Entry] = []
    for entry in kb:
        if request.kinds and entry.kind not in request.kinds:
            continue
        if entry.invalid:
            excluded_invalid.append(entry)   # 规范显式禁止的词条不进候选
            continue
        if not query_vec:
            continue
        sim = space.similarity(entry.id, query_vec)
        if sim <= 0.0:
            continue
        prior = entry.weight_prior
        domain_boost = DOMAIN_BOOST if (
            request.domains and set(entry.domain) & set(request.domains)
        ) else 1.0
        kind_boost = policy.kind_boost.get(entry.kind, 1.0)
        score = sim * prior * domain_boost * kind_boost
        if policy.coverage_lambda > 0.0:
            score += policy.coverage_lambda * _coverage_term(
                space, entry.id, query_features
            )
        if score >= policy.min_score:
            scored.append((entry, score))

    if not scored:
        warnings.append(
            "没有条目达到入选阈值：需求特征与知识库相距过远，"
            "或语义状态过于收束。建议补充知识库或放宽 min_score。"
        )

    # -- 1.5 同词条去重 ------------------------------------------------------
    # 跨文件同名词（如 lexicon 与 styles 各有一份「赛博朋克」）只保留
    # 得分最高的一个——同一结论出现两次会污染分布权重（11.2-V2）。
    deduped: dict[str, tuple[Entry, float]] = {}
    dropped_dupes: list[str] = []
    for entry, score in scored:
        key = entry.term
        if key in deduped:
            if score > deduped[key][1]:
                dropped_dupes.append(deduped[key][0].id)
                deduped[key] = (entry, score)
            else:
                dropped_dupes.append(entry.id)
        else:
            deduped[key] = (entry, score)
    scored = list(deduped.values())
    if dropped_dupes:
        warnings.append(
            f"{len(dropped_dupes)} 个跨文件同名词条已去重（保留最高分者）；"
            f"全部同名单见 KnowledgeBase.duplicate_terms。"
        )

    # -- 2. MMR 选择（相关性与多样性权衡）----------------------------------
    mmr_lambda = request.mmr_lambda if request.mmr_lambda is not None else policy.mmr_lambda
    selected = _mmr_select(scored, space, request.limit, mmr_lambda)

    # -- 3. 分布权重（11.2-V2）---------------------------------------------
    total = sum(s for _, s in selected) or 1.0
    weights = {e.id: s / total for e, s in selected}

    # -- 4. 语义场 ----------------------------------------------------------
    node_ids = [e.id for e, _ in selected]
    semantic_field = build_field(space, node_ids, query_features)

    # -- 5. 归因 / 闸门 / 建议 ----------------------------------------------
    mined: list[MinedEntry] = []
    gate = SafetyGate(charter)
    for entry, score in selected:
        attribution = _attribution(space, entry.id, query_features)
        gate_result = _gate_for(gate, entry)
        mined.append(MinedEntry(
            id=entry.id,
            term=entry.term,
            kind=entry.kind,
            cluster=entry.cluster,
            cluster_zh=kb.cluster_zh(entry.cluster) if entry.cluster else None,
            score=score,
            weight=weights[entry.id],
            attribution=attribution,
            gate=gate_result,
            suggestion=_fcs_suggestion(kb, entry),
            confidence=entry.confidence,
            source=entry.source,
        ))

    # -- 6. 汇总警告 ---------------------------------------------------------
    for entry, _ in selected:
        if entry.is_unverified:
            warnings.append(
                f"条目「{entry.term}」来源未标注或置信度为低（11.1-K2）："
                f"引用前请先补知识库来源。"
            )
    for entry in excluded_invalid:
        warnings.append(
            f"条目「{entry.term}」被规范显式禁止（invalid 标记），已从候选剔除；"
            f"如需求确实需要它，先改知识库再改需求。"
        )
    if not request.semantic_state.strip():
        warnings.append(
            "未声明语义状态，按中性策略处理（11.4-M3：语义状态须显式传入）。"
        )
    if semantic_field.gaps:
        warnings.append(
            f"{len(semantic_field.gaps)} 个需求特征无词条覆盖（11.3-F2）："
            + "、".join(semantic_field.gaps[:8])
            + ("……" if len(semantic_field.gaps) > 8 else "")
        )

    online = _online_report(request.allow_online, charter, gate)

    return MiningResult(
        kb_digest=kb.digest(),
        space_digest=space.digest,
        semantic_state=request.semantic_state,
        policy={
            "coverage_lambda": policy.coverage_lambda,
            "kind_boost": policy.kind_boost,
            "mmr_lambda": mmr_lambda,
            "min_score": policy.min_score,
        },
        entries=mined,
        field=semantic_field,
        warnings=warnings,
        online_expansion=online,
    )


# ---------------------------------------------------------------------------
# 内部
# ---------------------------------------------------------------------------
def _resolve_policy(state: str, warnings: list[str]) -> StatePolicy:
    key = (state or "").strip()
    if not key:
        return NEUTRAL_POLICY
    if key in STATE_POLICIES:
        return STATE_POLICIES[key]
    warnings.append(
        f"未识别的语义状态「{key}」，按中性策略处理；"
        f"已知状态：{'、'.join(STATE_POLICIES)}。"
    )
    return NEUTRAL_POLICY


def _coverage_term(
    space: MeasureSpace, entry_id: str, query_features: dict[str, float]
) -> float:
    """探索期加分项：条目接住的需求特征质量（IDF 加权的覆盖和）。"""
    fw = space.feature_weights(entry_id)
    acc = 0.0
    for feature, q_weight in query_features.items():
        hit = fw.get(feature, 0.0)
        if hit > 0.0:
            acc += q_weight * min(hit, 1.0)
    n = len(query_features) or 1
    return acc / n


def _mmr_select(
    scored: list[tuple[Entry, float]],
    space: MeasureSpace,
    limit: int,
    mmr_lambda: float,
) -> list[tuple[Entry, float]]:
    """最大边际相关性选择：λ=1 纯相关，λ=0 纯多样。"""
    if not scored:
        return []
    remaining = sorted(scored, key=lambda kv: (-kv[1], kv[0].id))
    chosen: list[tuple[Entry, float]] = []
    chosen_vecs: list[dict[int, float]] = []
    while remaining and len(chosen) < limit:
        best_idx, best_val = 0, -math.inf
        for i, (entry, score) in enumerate(remaining):
            if not chosen_vecs:
                val = mmr_lambda * score
            else:
                redundancy = max(
                    cosine(space.vector_of(entry.id), v) for v in chosen_vecs
                )
                val = mmr_lambda * score - (1.0 - mmr_lambda) * redundancy
            if val > best_val:
                best_idx, best_val = i, val
        entry, score = remaining.pop(best_idx)
        chosen.append((entry, score))
        chosen_vecs.append(space.vector_of(entry.id))
    return chosen


def _attribution(
    space: MeasureSpace, entry_id: str, query_features: dict[str, float]
) -> list[tuple[str, float]]:
    """把条目得分分解到需求特征维度（11.2-V2），取前 5。"""
    fw = space.feature_weights(entry_id)
    contributions: dict[str, float] = {}
    for feature, q_weight in query_features.items():
        hit = fw.get(feature, 0.0)
        if hit > 0.0:
            contributions[feature] = q_weight * hit
    total = sum(contributions.values())
    if total <= 0.0:
        return []
    ranked = sorted(contributions.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(f, c / total) for f, c in ranked[:5]]


def _gate_for(gate: SafetyGate, entry: Entry) -> dict[str, Any] | None:
    """非公开/可输出条目 → 第十章 3×3 闸门结论（11.4-M1）。"""
    if entry.sensitivity == "公开" and entry.permission == "可输出":
        return None
    flow = Flow(
        text=f"(知识条目:{entry.term})",
        layer=FlowLayer.OUTPUT,
        type=FlowType.KNOWLEDGE,
        source=Source.RETRIEVED,
        direction=Direction.OUTBOUND,
        ttl=TTL.SESSION,
        confidence=Confidence.HIGH,
        sensitivity=Sensitivity(entry.sensitivity),
        permission=Permission(entry.permission),
    )
    d = gate.inspect(flow)
    return {
        "sensitivity": entry.sensitivity,
        "permission": entry.permission,
        "verdict": d.verdict.value,
        "verdict_zh": d.verdict_zh,
        "passed": d.passed,
        "clause": d.clause,
        "explain": d.explain(),
    }


def _fcs_suggestion(kb: KnowledgeBase, entry: Entry) -> dict[str, Any]:
    """词条进特征簇提示词时的标记建议（簇位 + 权重区间）。"""
    kind_def = kb.kinds.get(entry.kind, {})
    fcs = entry.fcs or {}
    cluster = entry.cluster or fcs.get("cluster") or kind_def.get("fcs_cluster")
    fcs_kind = fcs.get("kind") or kind_def.get("fcs_kind") or entry.kind
    weight = fcs.get("weight") or {}
    if not weight:
        gradient = (kb.files.get("lexicon.yaml") or {}).get("weight_gradient") or {}
        g = gradient.get(cluster) if cluster else None
        weight = {"min": g["min"], "max": g["max"]} if g else {}
    lo, hi = weight.get("min"), weight.get("max")
    suggestion: dict[str, Any] = {
        "cluster": cluster,
        "cluster_zh": kb.cluster_zh(cluster) if cluster else None,
        "kind": fcs_kind,
        "weight_range": [lo, hi] if lo is not None and hi is not None else None,
        "note": (
            "建议写入簇尾并以显式权重标记，如 (词条:数值)；"
            "具体权重按 3.5 梯度与 9.1 区间取值。"
        ),
    }
    if cluster and lo is not None and hi is not None:
        mid = (float(lo) + float(hi)) / 2
        suggestion["example"] = f"[{kb.cluster_zh(cluster) or cluster}] ({entry.term}:{mid:g})"
    return suggestion


def _online_report(
    allow_online: bool, charter: Charter, gate: SafetyGate
) -> dict[str, Any] | None:
    """在线扩容请求的门诊报告（11.4-M2：报结论，不代为执行）。"""
    if not allow_online:
        return None
    # 把「联网检索」建模成一条公开可输出流：矩阵裁决内容本身可外发；
    # 但对外发送属于 10-R4 的重大不可逆动作，须用户明确确认。
    flow = Flow(
        text="(在线语料扩容检索请求)",
        layer=FlowLayer.OUTPUT,
        type=FlowType.KNOWLEDGE,
        source=Source.RETRIEVED,
        direction=Direction.OUTBOUND,
        ttl=TTL.SESSION,
        confidence=Confidence.HIGH,
        sensitivity=Sensitivity.PUBLIC,
        permission=Permission.OUTPUTTABLE,
    )
    d = gate.inspect(flow)
    return {
        "requested": True,
        "executed": False,
        "gate_verdict": d.verdict.value,
        "gate_clause": d.clause,
        "requires_user_confirmation": True,
        "confirmation_clause": "10-R4",
        "note": (
            "引擎不在本地知识库外执行任何检索。调用方须先取得用户对"
            "「对外发送」的明确确认（10-R4），再行联网扩容。"
        ),
    }


def lexicon_search(
    query: str,
    *,
    kinds: list[str] | None = None,
    limit: int = 20,
    kb: KnowledgeBase | None = None,
) -> list[dict[str, Any]]:
    """知识库检索（MCP 工具 lexicon_search 的后端）。"""
    kb = kb or KnowledgeBase.load()
    out = []
    for entry in kb.search(query, kinds=tuple(kinds) if kinds else None, limit=limit):
        out.append({
            "id": entry.id,
            "term": entry.term,
            "kind": entry.kind,
            "cluster": entry.cluster,
            "domain": list(entry.domain),
            "era": entry.era,
            "gloss": entry.gloss,
            "confidence": entry.confidence,
            "source": entry.source,
        })
    return out

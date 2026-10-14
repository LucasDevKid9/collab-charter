"""潜空间语义场（宪章 11.3）：在向量征量空间上建构关联网络并做结构分析。

语义场不是「相似度排行榜」——那是平面。语义场要回答结构性问题：

1. **关联网络**：候选词条之间谁连着谁（向量相似 + 显式 related，
   显式 conflicts 断边）。边权可查。
2. **中心性**：哪些词条是这个场地的枢纽（幂迭代特征向量中心性，
   确定性初始化，无随机）。
3. **社群**：词条分成几撮（标签传播，确定性顺序，无随机初始化——
   11.3-F1 的可判定版本）。
4. **覆盖缺口**：需求特征里哪些根本没有词条接住（11.3-F2：
   缺口必须显式列出，不许静默略过）。
5. **场度量**：密度、模块度、社群内聚——供「这个场子稳不稳」的判断。

边界（诚实声明，见 docs/SEMANTIC-FIELD.md）
--------------------------------------------
这是**词汇级**语义场：关联来自词元共现与人工标注的 related/conflicts，
不是神经嵌入的分布语义。它能发现「谷圈-痛包-吧唧」这样的紧邻社群，
不能发现需要世界知识的远距离关联（「内卷」与「躺平」只能靠显式
related 连接，不能靠向量）。 related 断链即报错，正是为了逼着
知识库把该连的连上。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

from .kb import Entry
from .vectors import MeasureSpace, cosine

#: 建边相似度阈值。低于此不连边——语义场要的是结构，不是全连接图。
SIM_THRESHOLD = 0.10

#: 显式 related 边的权重大于隐式相似边（人工标注比向量近似可信）
RELATED_EDGE_WEIGHT = 0.5

#: 中心性幂迭代参数
POWER_ITERATIONS = 60
POWER_TOLERANCE = 1e-9

#: 标签传播参数
LPA_MAX_ITERATIONS = 50

#: 覆盖判定阈值：条目在某需求特征上的权重 ≥ 此值算「接住」
COVER_MIN = 0.05


@dataclass(frozen=True)
class Edge:
    a: str
    b: str
    weight: float
    kind: str  # "sim" | "related"


@dataclass
class SemanticField:
    """一次语义场建构的完整结果（可 JSON 化，供 MCP 传输）。"""

    node_ids: list[str]
    terms: dict[str, str]
    edges: list[Edge]
    communities: dict[int, list[str]]
    centrality: dict[str, float]
    metrics: dict[str, float]
    coverage: dict[str, dict[str, Any]]
    gaps: list[str]

    # -- 视图 ---------------------------------------------------------------
    def community_of(self, entry_id: str) -> int | None:
        for cid, members in self.communities.items():
            if entry_id in members:
                return cid
        return None

    def top_central(self, k: int = 5) -> list[tuple[str, float]]:
        ranked = sorted(self.centrality.items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[:k]

    def neighbors(self, entry_id: str) -> list[tuple[str, float, str]]:
        out = []
        for e in self.edges:
            if e.a == entry_id:
                out.append((e.b, e.weight, e.kind))
            elif e.b == entry_id:
                out.append((e.a, e.weight, e.kind))
        return sorted(out, key=lambda x: -x[1])

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [{"id": n, "term": self.terms[n]} for n in self.node_ids],
            "edges": [
                {"a": e.a, "b": e.b, "weight": round(e.weight, 4), "kind": e.kind}
                for e in self.edges
            ],
            "communities": {
                str(cid): [
                    {"id": m, "term": self.terms[m]} for m in members
                ]
                for cid, members in sorted(self.communities.items())
            },
            "centrality": {
                n: round(c, 4) for n, c in sorted(
                    self.centrality.items(), key=lambda kv: (-kv[1], kv[0])
                )
            },
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
            "coverage": self.coverage,
            "gaps": self.gaps,
        }


# ---------------------------------------------------------------------------
# 建构
# ---------------------------------------------------------------------------
def build_field(
    space: MeasureSpace,
    node_ids: Iterable[str],
    query_features: dict[str, float],
    *,
    sim_threshold: float = SIM_THRESHOLD,
    cover_min: float = COVER_MIN,
) -> SemanticField:
    """在空间上建构语义场。

    ``node_ids``：入场的条目（通常是挖掘引擎的候选集）。
    ``query_features``：需求侧的加权特征表，用于覆盖缺口分析。
    """
    nodes = [n for n in node_ids if n in space.entry_vectors]
    terms = {n: space.entries[n].term for n in nodes}

    # -- 1. 关联网络 --------------------------------------------------------
    edges: list[Edge] = []
    seen: set[frozenset[str]] = set()
    conflicts = {
        n: {c for c in space.entries[n].conflicts if c in set(nodes)}
        for n in nodes
    }
    related = {
        n: {r for r in space.entries[n].related if r in set(nodes)}
        for n in nodes
    }
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            pair = frozenset((a, b))
            if pair in seen:
                continue
            seen.add(pair)
            if b in conflicts[a] or a in conflicts[b]:
                continue  # 显式冲突：断边（语义场不连互斥的词）
            sim = cosine(space.entry_vectors[a], space.entry_vectors[b])
            if b in related[a] or a in related[b]:
                edges.append(Edge(a=a, b=b, weight=RELATED_EDGE_WEIGHT, kind="related"))
            elif sim >= sim_threshold:
                edges.append(Edge(a=a, b=b, weight=sim, kind="sim"))

    # -- 2. 中心性（幂迭代，确定性初始化）-----------------------------------
    centrality = _power_centrality(nodes, edges)

    # -- 3. 社群（标签传播，确定性顺序）-------------------------------------
    communities = _label_propagation(nodes, edges, centrality)

    # -- 4. 覆盖与缺口 ------------------------------------------------------
    coverage, gaps = _coverage(space, nodes, query_features, cover_min)

    # -- 5. 场度量 ----------------------------------------------------------
    metrics = _metrics(nodes, edges, communities)

    return SemanticField(
        node_ids=nodes,
        terms=terms,
        edges=edges,
        communities=communities,
        centrality=centrality,
        metrics=metrics,
        coverage=coverage,
        gaps=gaps,
    )


# ---------------------------------------------------------------------------
# 内部算法（全部确定性：固定顺序、固定初始化、无随机源）
# ---------------------------------------------------------------------------
def _power_centrality(nodes: list[str], edges: list[Edge]) -> dict[str, float]:
    """特征向量中心性：c ← normalize(A·c)，c₀ = 均匀向量。"""
    n = len(nodes)
    if n == 0:
        return {}
    index = {node: i for i, node in enumerate(nodes)}
    adj = [[0.0] * n for _ in range(n)]
    for e in edges:
        i, j = index[e.a], index[e.b]
        adj[i][j] += e.weight
        adj[j][i] += e.weight
    vec = [1.0 / math.sqrt(n)] * n
    for _ in range(POWER_ITERATIONS):
        nxt = [0.0] * n
        for i in range(n):
            row = adj[i]
            acc = 0.0
            for j in range(n):
                w = row[j]
                if w:
                    acc += w * vec[j]
            nxt[i] = acc
        norm = math.sqrt(sum(v * v for v in nxt))
        if norm == 0.0:
            break
        nxt = [v / norm for v in nxt]
        delta = max(abs(a - b) for a, b in zip(nxt, vec))
        vec = nxt
        if delta < POWER_TOLERANCE:
            break
    return {node: vec[index[node]] for node in nodes}


def _label_propagation(
    nodes: list[str], edges: list[Edge], centrality: dict[str, float]
) -> dict[int, list[str]]:
    """标签传播社群发现。

    确定性保证：更新顺序固定为「中心性降序 → id 升序」；异步更新；
    新标签取邻居标签的加权众数（并列时取编号最小）。无随机初始化，
    初始标签即节点自身。
    """
    if not nodes:
        return {}
    order = sorted(nodes, key=lambda n: (-centrality.get(n, 0.0), n))
    labels = {node: i for i, node in enumerate(nodes)}
    adjacency: dict[str, list[tuple[str, float]]] = {n: [] for n in nodes}
    for e in edges:
        adjacency[e.a].append((e.b, e.weight))
        adjacency[e.b].append((e.a, e.weight))

    for _ in range(LPA_MAX_ITERATIONS):
        changed = False
        for node in order:
            if not adjacency[node]:
                continue
            weights: dict[int, float] = {}
            for nbr, w in adjacency[node]:
                lbl = labels[nbr]
                weights[lbl] = weights.get(lbl, 0.0) + w
            best = min(
                weights.items(), key=lambda kv: (-kv[1], kv[0])
            )[0]
            if best != labels[node]:
                labels[node] = best
                changed = True
        if not changed:
            break

    communities: dict[int, list[str]] = {}
    for node in nodes:
        communities.setdefault(labels[node], []).append(node)
    # 社群编号按成员的中心性和重排，输出稳定
    ranked = sorted(
        communities.items(),
        key=lambda kv: (-sum(centrality.get(m, 0.0) for m in kv[1]), kv[0]),
    )
    return {i: members for i, (_, members) in enumerate(ranked)}


def _coverage(
    space: MeasureSpace,
    nodes: list[str],
    query_features: dict[str, float],
    cover_min: float,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """需求特征 → 最佳承接条目。未接住的特征进 gaps（11.3-F2）。

    缺口只报告「有语义重量的特征」：CJK 单字（如 t:人、t:的）在任何
    文本里都大量出现，把它们列成缺口只会制造噪声；二元组与英文词才
    对应一个可寻址的概念。
    """
    coverage: dict[str, dict[str, Any]] = {}
    gaps: list[str] = []
    # 只检查查询侧权重最高的特征，避免把 CJK 单字碎特征全列成缺口
    ranked = sorted(query_features.items(), key=lambda kv: (-kv[1], kv[0]))
    for feature, q_weight in ranked[:40]:
        best_id, best_score = "", 0.0
        for node in nodes:
            fw = space.feature_weights(node)
            score = fw.get(feature, 0.0)
            if score > best_score:
                best_id, best_score = node, score
        if best_id and best_score >= cover_min:
            coverage[feature] = {
                "best_entry": best_id,
                "best_term": space.entries[best_id].term,
                "score": round(best_score, 4),
                "covered": True,
            }
        else:
            coverage[feature] = {
                "best_entry": best_id or None,
                "best_term": space.entries[best_id].term if best_id else None,
                "score": round(best_score, 4),
                "covered": False,
            }
            if _has_semantic_weight(feature):
                gaps.append(feature)
    return coverage, gaps


def _has_semantic_weight(feature: str) -> bool:
    """特征是否对应可寻址概念：英文词/无停用字的二元组/元特征算，CJK 单字不算。

    停用字过滤专门处理跨词边界的噪声二元组：「质感的人」切出的
    「的人」「感的」不是概念，不该进缺口清单。
    """
    token = feature.split(":", 1)[-1]
    if feature.startswith(("t:", "s:")):
        if len(token) < 2:
            return False
        return not any(ch in _STOP_CHARS for ch in token)
    return True  # c:/k:/d:/e:/g: 元特征都有语义重量


#: CJK 功能字：出现在二元组里多半是跨词边界噪声
_STOP_CHARS = frozenset("的了是在有和与及或着过把被让向从对该此其之于为以所而则且啊吗呢吧呀哦嗯么是我你他她它们这那哪些怎么怎样")


def _metrics(
    nodes: list[str], edges: list[Edge], communities: dict[int, list[str]]
) -> dict[str, float]:
    """场结构度量：密度 + 模块度（Q）。"""
    n = len(nodes)
    if n < 2:
        return {"node_count": float(n), "edge_count": float(len(edges)),
                "density": 0.0, "modularity": 0.0, "community_count": float(len(communities))}
    density = 2.0 * len(edges) / (n * (n - 1))

    community_of: dict[str, int] = {}
    for cid, members in communities.items():
        for m in members:
            community_of[m] = cid
    total_w = sum(e.weight for e in edges)
    intra: dict[int, float] = {}
    degree: dict[int, float] = {cid: 0.0 for cid in communities}
    for e in edges:
        ca, cb = community_of.get(e.a), community_of.get(e.b)
        if ca is not None:
            degree[ca] += e.weight
        if cb is not None:
            degree[cb] += e.weight
        if ca is not None and ca == cb:
            intra[ca] = intra.get(ca, 0.0) + e.weight
    modularity = 0.0
    if total_w > 0:
        for cid in communities:
            l_c = intra.get(cid, 0.0)
            d_c = degree.get(cid, 0.0)
            modularity += l_c / total_w - (d_c / (2.0 * total_w)) ** 2
    return {
        "node_count": float(n),
        "edge_count": float(len(edges)),
        "density": density,
        "modularity": modularity,
        "community_count": float(len(communities)),
    }

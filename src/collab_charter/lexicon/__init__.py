"""collab_charter.lexicon —— 知识库与潜空间语义场（宪章第十一章）。

四件套：

* :mod:`kb`     知识库加载/校验/摘要（11.1）
* :mod:`vectors` 向量征量空间：确定性哈希嵌入 + IDF + 上下文增益（11.2）
* :mod:`field`   潜空间语义场：关联网络/中心性/社群/覆盖缺口（11.3）
* :mod:`mine`    深挖引擎：需求+目标+语义状态 → 加权词条+分布权重（11.4）

快速开始::

    from collab_charter.lexicon import KnowledgeBase, MiningRequest, mine

    result = mine(MiningRequest(
        requirement="千禧年复古质感的人物立绘",
        task_objectives=["复刻 2000 年代视觉小说质感"],
        semantic_state="探索期",
    ))
    for e in result.entries:
        print(e.term, e.weight, e.suggestion["example"])
"""

from .kb import Entry, KnowledgeBase, KnowledgeBaseError
from .vectors import MeasureSpace, cosine, tokenize
from .field import Edge, SemanticField, build_field
from .mine import (
    MiningRequest,
    MiningResult,
    MinedEntry,
    STATE_POLICIES,
    StatePolicy,
    lexicon_search,
    mine,
)

__all__ = [
    "Entry",
    "KnowledgeBase",
    "KnowledgeBaseError",
    "MeasureSpace",
    "cosine",
    "tokenize",
    "Edge",
    "SemanticField",
    "build_field",
    "MiningRequest",
    "MiningResult",
    "MinedEntry",
    "STATE_POLICIES",
    "StatePolicy",
    "mine",
    "lexicon_search",
]

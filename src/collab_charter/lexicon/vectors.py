"""向量征量空间（宪章 11.2）：把知识库变成一个可计算、可复现的度量空间。

设计约束（全部来自宪章，写成断言由测试保证）
--------------------------------------------
* **11.2-V1 确定性**：同一知识库 digest + 同一上下文 → 同一向量、同一排序。
  本实现不含任何随机源；向量即「特征 → 权重」的稀疏字典，
  跨进程逐字节一致（早期版本用 blake2b hashing trick 压成定维向量，
  实测在三百级词条规模下碰撞噪声已可观测——「赛璐璐」混进「谷圈」社群
  就是这个噪声——故改为精确稀疏特征向量，宁慢不错）。
* **11.2-V2 可分解**：任何得分都能分解到需求特征维度
  （见 ``mine.py`` 的 attribution）——因为向量本身就是特征表。
* **11.2-V3 暂时性**：``MeasureSpace`` 是任务期临时建构——按当次的
  需求/目标/语义状态构建，用后即弃；本模块不提供任何全局缓存，
  也不把空间持久化。

特征体系
--------
每条知识的特征分四层，权重不同：

==============  ==========================================  ======
特征            内容                                        权重
==============  ==========================================  ======
``t:``          词条与别名的中英词元（CJK 单字+二元组）        1.0
``c:/k:``       功能簇 / 条目类型                             0.6
``d:/e:/g:``    语义域 / 时代 / 标签                          0.6
``s:``          释义文本词元                                  0.35
==============  ==========================================  ======

再加 IDF 逆文档频率调整：在越多条目里出现的特征越没有区分度
（「光影」出现几百次，「谷圈」只出现几次），查询侧同等命中的情况下，
后者应该赢。上下文特征（任务目标/语义状态里出现的）在条目侧提权——
这是「语义状态影响分布权重」（11.4-M3）在空间侧的机制。
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Iterable

from .kb import Entry, KnowledgeBase

#: 特征层权重
W_TERM = 1.0
W_UNIGRAM = 0.35   # CJK 单字：弱证据（「网」命中「丝网印刷」不算命中）
W_META = 0.6      # cluster / kind / domain / era / tags
W_GLOSS = 0.35    # 释义词元

#: 上下文特征增益：任务目标/语义状态里出现的特征，条目侧同特征提权
CONTEXT_BOOST = 1.6

#: 空间的「维度」= 实时特征词表大小（随知识库增长，不是固定超参）
SPACE_VERSION = "measure-space/2.0-sparse"

_ASCII_WORD = re.compile(r"[A-Za-z0-9]+")
_CJK = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def tokenize(text: str) -> list[str]:
    """条目侧全量词元化：英文/数字按词，CJK 取单字 + 相邻二元组。

    例：「赛博朋克 cyberpunk 影像」→ [赛, 博, 博朋, 朋克, cyberpunk, 影像]
    二元组让「朋克」能同时命中「蒸汽朋克」与「赛博朋克」——
    这是词汇语义场的最低限度近似：没有神经嵌入，也不假装有。
    条目侧要的是**召回**：宁可多切，不可漏切。
    """
    tokens: list[str] = []
    buf: list[str] = []
    cjk_buf: list[str] = []

    def flush_ascii() -> None:
        if buf:
            tokens.append("".join(buf).lower())
            buf.clear()

    def flush_cjk() -> None:
        if cjk_buf:
            for ch in cjk_buf:
                tokens.append(ch)
            for i in range(len(cjk_buf) - 1):
                tokens.append(cjk_buf[i] + cjk_buf[i + 1])
            cjk_buf.clear()

    for ch in str(text or ""):
        if _CJK.match(ch):
            flush_ascii()
            cjk_buf.append(ch)
        elif ch.isascii() and ch.isalnum():
            flush_cjk()
            buf.append(ch)
        else:
            flush_ascii()
            flush_cjk()
    flush_ascii()
    flush_cjk()
    return [t for t in tokens if t]


def build_vocabulary(kb: KnowledgeBase) -> dict[str, int]:
    """知识库词表：term/别名 → 长度（供查询侧前向最大匹配）。

    只收长度 ≥2 且含 CJK 的词——英文与数字走 ``_ASCII_WORD`` 通道，
    单字不成词。
    """
    vocab: dict[str, int] = {}
    for entry in kb:
        for word in (entry.term, *entry.aliases):
            w = str(word).strip()
            if len(w) >= 2 and _CJK.search(w):
                vocab[w] = len(w)
    return vocab


def tokenize_query(text: str, vocab: dict[str, int]) -> list[str]:
    """查询侧词元化：对 CJK 段做**前向最大匹配**（拿知识库词表当日词典）。

    与条目侧的分工：查询侧要的是**精准**——
    命中的词表词整体成一个词元；未命中段只取单字（不再产二元组，
    跨词边界的二元组如「古质」「代视」是缺口报告的主要噪声源）。
    """
    tokens: list[str] = []
    buf: list[str] = []
    cjk_buf: list[str] = []

    def flush_ascii() -> None:
        if buf:
            tokens.append("".join(buf).lower())
            buf.clear()

    def flush_cjk() -> None:
        if not cjk_buf:
            return
        run = "".join(cjk_buf)
        i = 0
        while i < len(run):
            matched = ""
            # 前向最大匹配：从最长可能词开始试（词表最长词封顶 12）
            for length in range(min(12, len(run) - i), 1, -1):
                candidate = run[i:i + length]
                if candidate in vocab:
                    matched = candidate
                    break
            if matched:
                tokens.append(matched)
                i += len(matched)
            else:
                tokens.append(run[i])
                i += 1
        cjk_buf.clear()

    for ch in str(text or ""):
        if _CJK.match(ch):
            flush_ascii()
            cjk_buf.append(ch)
        elif ch.isascii() and ch.isalnum():
            flush_cjk()
            buf.append(ch)
        else:
            flush_ascii()
            flush_cjk()
    flush_ascii()
    flush_cjk()
    return [t for t in tokens if t]


def normalize(vec: dict[str, float]) -> dict[str, float]:
    """L2 归一化；零向量原样返回。"""
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm == 0.0:
        return dict(vec)
    return {k: v / norm for k, v in vec.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """稀疏向量余弦（精确特征空间，无哈希碰撞）。"""
    if not a or not b:
        return 0.0
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    return sum(v * big.get(k, 0.0) for k, v in small.items())


def entry_features(entry: Entry) -> dict[str, float]:
    """条目 → 加权特征表（未乘 IDF）。条目侧保召回：全量 n-gram。"""
    feats: dict[str, float] = {}

    def add(feature: str, weight: float) -> None:
        if feature and weight > 0:
            feats[feature] = feats.get(feature, 0.0) + weight

    # 整词本身也是一个特征（权重最高），保证整词命中优先于部分命中
    if len(entry.term) >= 2:
        add(f"t:{entry.term}", W_TERM)
    for token in tokenize(entry.term):
        add(f"t:{token}", W_UNIGRAM if len(token) == 1 else W_TERM)
    for alias in entry.aliases:
        if len(alias) >= 2:
            add(f"t:{alias}", W_TERM * 0.9)
        for token in tokenize(alias):
            add(f"t:{token}", (W_UNIGRAM if len(token) == 1 else W_TERM) * 0.9)
    if entry.cluster:
        add(f"c:{entry.cluster}", W_META)
    add(f"k:{entry.kind}", W_META)
    for d in entry.domain:
        add(f"d:{d}", W_META)
    if entry.era:
        add(f"e:{entry.era}", W_META)
    for t in entry.tags:
        add(f"g:{t}", W_META)
    for token in tokenize(entry.gloss):
        add(f"s:{token}", W_GLOSS)
    return feats


def _text_features(text: str, vocab: dict[str, int] | None = None) -> dict[str, float]:
    """自由文本 → 加权特征表（查询侧：有词表则走最大匹配分词）。"""
    feats: dict[str, float] = {}
    tokens = tokenize_query(text, vocab) if vocab else tokenize(text)
    for token in tokens:
        w = W_UNIGRAM if len(token) == 1 else W_TERM
        feats[f"t:{token}"] = feats.get(f"t:{token}", 0.0) + w
    return feats


@dataclass
class MeasureSpace:
    """任务期临时建构的向量征量空间（11.2-V3：用后即弃，不缓存不持久化）。"""

    entries: dict[str, Entry]
    idf: dict[str, float]
    entry_vectors: dict[str, dict[str, float]]   # 精确稀疏特征向量
    context_features: frozenset[str]
    vocab: dict[str, int]                        # 查询侧日词典（前向最大匹配）
    kb_digest: str = ""
    context_digest: str = ""
    _space_version: str = SPACE_VERSION

    # -- 建构 ---------------------------------------------------------------
    @classmethod
    def build(
        cls,
        kb: KnowledgeBase,
        *,
        context: Iterable[str] = (),
    ) -> "MeasureSpace":
        """从知识库建构空间。``context`` 是任务目标/语义状态等上下文文本。"""
        vocab = build_vocabulary(kb)
        entry_feats = {e.id: entry_features(e) for e in kb}
        n = max(1, len(entry_feats))
        df: dict[str, int] = {}
        for feats in entry_feats.values():
            for f in feats:
                df[f] = df.get(f, 0) + 1
        idf = {f: math.log((n + 1) / (d + 1)) + 1.0 for f, d in df.items()}

        ctx_text = "\n".join(str(c) for c in context if str(c).strip())
        ctx_features = frozenset(_text_features(ctx_text, vocab))
        # 上下文特征在条目侧提权（语义状态影响分布权重，11.4-M3 的空间侧机制）
        entry_vectors = {
            eid: _apply_idf(feats, idf, n, ctx_features)
            for eid, feats in entry_feats.items()
        }
        return cls(
            entries={e.id: e for e in kb},
            idf=idf,
            entry_vectors=entry_vectors,
            context_features=ctx_features,
            vocab=vocab,
            kb_digest=kb.digest(),
            context_digest=_text_digest(ctx_text),
        )

    # -- 查询 ---------------------------------------------------------------
    def query_vector(self, texts: Iterable[str]) -> dict[str, float]:
        """把需求/目标/语义状态查询文本嵌成空间向量（词表最大匹配分词）。"""
        feats = _text_features(
            "\n".join(str(t) for t in texts if str(t).strip()), self.vocab
        )
        return _apply_idf(feats, self.idf, max(1, len(self.entry_vectors)), frozenset())

    def query_features(self, texts: Iterable[str]) -> dict[str, float]:
        """查询的原始特征表（未乘 IDF，供覆盖缺口分析复用）。"""
        return _text_features(
            "\n".join(str(t) for t in texts if str(t).strip()), self.vocab
        )

    def vector_of(self, entry_id: str) -> dict[str, float]:
        return self.entry_vectors[entry_id]

    def similarity(self, entry_id: str, query_vec: dict[str, float]) -> float:
        return cosine(self.entry_vectors[entry_id], query_vec)

    # -- 摘要 ---------------------------------------------------------------
    @property
    def digest(self) -> str:
        """空间指纹：版本 + 知识库 + 上下文（11.2-V1 的复现锚点）。"""
        payload = "|".join([
            self._space_version, self.kb_digest, self.context_digest,
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def dimension(self) -> int:
        """空间维度 = 实时特征词表大小（随知识库增长）。"""
        return len(self.idf)

    def feature_weights(self, entry_id: str) -> dict[str, float]:
        """条目的「特征 → 权重」表（attribution 分解用，11.2-V2）。"""
        return self.entry_vectors[entry_id]


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _apply_idf(
    feats: dict[str, float],
    idf: dict[str, float],
    n: int,
    context_features: frozenset[str],
) -> dict[str, float]:
    """乘 IDF + 上下文增益 + L2 归一化。"""
    rare_idf = math.log(n + 1) + 1.0
    weighted = {
        f: w * idf.get(f, rare_idf) * (CONTEXT_BOOST if f in context_features else 1.0)
        for f, w in feats.items()
    }
    return normalize(weighted)


def _text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

"""记忆流：0.6 的三个操作——沉淀、再激活、衰减与刷新（第 7 章「长期记忆网络化」）。

存储后端刻意做成可替换的：默认是内存 + JSON 落盘，任何实现了
``deposit/recall/correct`` 三法的对象都能顶替（本地文件、知识库、向量库）。
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

from .flows import (
    Confidence,
    Destination,
    Direction,
    Flow,
    FlowLayer,
    FlowType,
    Sensitivity,
    Source,
    TTL,
)

#: 各时效档的半衰期（秒）。``None`` 表示不衰减。
HALF_LIFE: dict[TTL, float | None] = {
    TTL.REALTIME: 3600.0,          # 1 小时
    TTL.SESSION: 7 * 86400.0,      # 7 天
    TTL.STABLE: None,              # 长期稳定，不衰减
}

#: 置信度阶梯，衰减时逐级下降
_CONF_LADDER = [Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW]

_CJK = None  # 惰性初始化


def _semantic_tokens(text: str) -> set[str]:
    """记忆语义检索的词元化：英文按词，CJK 取单字 + 相邻二元组。

    复用 lexicon.vectors 的确定性词元策略（无随机、无外部状态），
    使记忆检索对同义改写（如「记下重构方案」vs「重构」）更鲁棒。
    """
    global _CJK
    if _CJK is None:
        import re

        _CJK = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
    out: set[str] = set()
    buf: list[str] = []
    cjk_buf: list[str] = []

    def flush_ascii() -> None:
        if buf:
            out.add("".join(buf).lower())
            buf.clear()

    def flush_cjk() -> None:
        if cjk_buf:
            for ch in cjk_buf:
                out.add(ch)
            for i in range(len(cjk_buf) - 1):
                out.add(cjk_buf[i] + cjk_buf[i + 1])
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
    return out


@dataclass
class Provenance:
    """记忆来源凭证（最终优化·第二梯队·P1-6）。

    对齐「记忆不是真相，记忆只是证据」原则：每条记忆必须能回答
    来源类型、来源 id、何时观察、谁确认、推断置信度。没有 provenance
    的记忆不能进入长期召回。
    """

    source_type: str = "user_explicit"   # user_explicit/user_implicit/agent_inference/tool_result/document/policy/other_agent/hallucination_suspect
    source_id: str = ""                  # msg-123 / episode-456 / tool:web_fetch 等
    observed_at: float = field(default_factory=time.time)
    confirmed_by: str = ""               # user / tool / agent / charter
    inference_confidence: float = 1.0   # 0–1，推断类来源的置信度

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "observed_at": self.observed_at,
            "confirmed_by": self.confirmed_by,
            "inference_confidence": self.inference_confidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Provenance":
        d = d or {}
        return cls(
            source_type=d.get("source_type", "user_explicit"),
            source_id=d.get("source_id", ""),
            observed_at=float(d.get("observed_at", time.time())),
            confirmed_by=d.get("confirmed_by", ""),
            inference_confidence=float(d.get("inference_confidence", 1.0)),
        )


def _source_type_from_flow(flow: Flow) -> str:
    """从流的 Source 推导来源类型。"""
    from .flows import Source as S

    if flow.source is S.USER_STATED:
        return "user_explicit"
    if flow.source is S.FILE_EVIDENCE:
        return "document"
    if flow.source is S.RETRIEVED:
        return "tool_result"
    if flow.source is S.MODEL_PRIOR:
        return "agent_inference"
    if flow.source is S.MODEL_GUESS:
        return "agent_inference"
    return "other_agent"


def _confirmed_by(flow: Flow) -> str:
    from .flows import Source as S

    if flow.source is S.USER_STATED:
        return "user"
    if flow.source is S.RETRIEVED or flow.source is S.FILE_EVIDENCE:
        return "tool"
    return "agent"


def _inference_confidence(flow: Flow) -> float:
    from .flows import Confidence as C

    return {"高": 1.0, "中": 0.7, "低": 0.35}.get(flow.confidence.value, 1.0)


@dataclass
class MemoryNode:
    """一条沉淀下来的记忆。"""

    key: str
    text: str
    tags: list[str] = field(default_factory=list)
    confidence: Confidence = Confidence.MEDIUM
    ttl: TTL = TTL.STABLE
    sensitivity: Sensitivity = Sensitivity.PUBLIC
    source: Source = Source.USER_STATED
    private: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    corrections: list[dict[str, Any]] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)

    # -- 序列化 -----------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("confidence", "ttl", "sensitivity", "source"):
            d[k] = getattr(self, k).value
        d["provenance"] = self.provenance.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryNode":
        d = dict(d)
        d["confidence"] = Confidence(d.get("confidence", Confidence.MEDIUM.value))
        d["ttl"] = TTL(d.get("ttl", TTL.STABLE.value))
        d["sensitivity"] = Sensitivity(d.get("sensitivity", Sensitivity.PUBLIC.value))
        d["source"] = Source(d.get("source", Source.USER_STATED.value))
        d["provenance"] = Provenance.from_dict(d.get("provenance"))
        return cls(**d)

    def to_flow(self, *, origin: str = "recall") -> Flow:
        """0.6-O2 再激活：还原为**带元数据**的流进入管线，而非原文照搬。"""
        note = f"记忆节点 {self.key} 于 {time.strftime('%Y-%m-%d %H:%M', time.localtime(self.updated_at))} 更新"
        return Flow(
            text=self.text,
            layer=FlowLayer.MEMORY,
            type=FlowType.KNOWLEDGE,
            source=self.source,
            direction=Direction.INTERNAL,
            ttl=self.ttl,
            confidence=self.confidence,
            sensitivity=self.sensitivity,
            destination=Destination.REPLY,
            notes=[note, f"recall:{origin}"],
            payload={"memory_key": self.key, "tags": list(self.tags)},
        )

    def decayed_confidence(self, now: float | None = None) -> Confidence:
        """按半衰期推算当前置信度（不写回，纯计算）。"""
        half_life = HALF_LIFE.get(self.ttl)
        if half_life is None:
            return self.confidence
        now = time.time() if now is None else now
        elapsed = max(0.0, now - self.updated_at)
        steps = int(elapsed // half_life)
        if steps <= 0:
            return self.confidence
        idx = _CONF_LADDER.index(self.confidence)
        return _CONF_LADDER[min(len(_CONF_LADDER) - 1, idx + steps)]

    def provenance_summary(self) -> str:
        """人可读的来源凭证摘要（供 why / replay / 诊断）。"""
        src_zh = {
            "user_explicit": "用户明说",
            "user_implicit": "用户行为推断",
            "agent_inference": "模型推断",
            "tool_result": "工具结果",
            "document": "文档",
            "policy": "宪章",
            "other_agent": "其他Agent",
            "hallucination_suspect": "可疑幻觉",
        }.get(self.provenance.source_type, self.provenance.source_type)
        conf = f"{self.provenance.inference_confidence:.2f}" if self.provenance.inference_confidence < 1.0 else "1.00"
        sid = f"#{self.provenance.source_id}" if self.provenance.source_id else ""
        return f"{src_zh}{sid}·确认方={self.provenance.confirmed_by or '—'}·推断置信={conf}"


class MemoryBackend(Protocol):
    """可替换的记忆后端契约。"""

    def upsert(self, node: MemoryNode) -> MemoryNode: ...
    def get(self, key: str) -> MemoryNode | None: ...
    def all(self) -> list[MemoryNode]: ...


class _InMemoryBackend:
    def __init__(self) -> None:
        self._data: dict[str, MemoryNode] = {}

    def upsert(self, node: MemoryNode) -> MemoryNode:
        self._data[node.key] = node
        return node

    def get(self, key: str) -> MemoryNode | None:
        return self._data.get(key)

    def all(self) -> list[MemoryNode]:
        return list(self._data.values())


class MemoryStore:
    """记忆流管理器。默认内存后端；``path`` 给定时自动 JSON 落盘。"""

    def __init__(self, path: str | Path | None = None, backend: MemoryBackend | None = None) -> None:
        self.path = Path(path) if path else None
        self._backend: MemoryBackend = backend or _InMemoryBackend()
        self.last_deposit_at: float | None = None
        if self.path and self.path.is_file():
            self.load()

    # -- 0.6-O1 沉淀 ------------------------------------------------------
    def deposit(
        self,
        flow: Flow,
        key: str | None = None,
        *,
        tags: Iterable[str] = (),
        private: bool | None = None,
    ) -> MemoryNode:
        """把一条流沉淀为记忆节点。"""
        if flow.destination is not Destination.MEMORY and key is None:
            # 未显式要求沉淀时，不静默沉淀——避免记忆被无意义内容稀释
            key = f"{flow.layer.value}:{flow.id}"
        key = key or f"{flow.layer.value}:{flow.id}"
        existing = self._backend.get(key)
        # 记忆 Provenance：从流推导来源类型/确认方/推断置信度
        prov = Provenance(
            source_type=_source_type_from_flow(flow),
            source_id=str(flow.payload.get("source_id", "") or flow.id),
            observed_at=time.time(),
            confirmed_by=_confirmed_by(flow),
            inference_confidence=_inference_confidence(flow),
        )
        node = MemoryNode(
            key=key,
            text=flow.text,
            tags=list(dict.fromkeys(list(tags) or list(flow.payload.get("tags", [])))),
            confidence=flow.confidence,
            ttl=flow.ttl,
            sensitivity=flow.sensitivity,
            source=flow.source,
            private=bool(private) if private is not None else flow.sensitivity is not Sensitivity.PUBLIC,
            created_at=existing.created_at if existing else time.time(),
            updated_at=time.time(),
            corrections=existing.corrections if existing else [],
            provenance=existing.provenance if existing else prov,
        )
        self._backend.upsert(node)
        self.last_deposit_at = node.updated_at
        self.save()
        return node

    # -- 0.6-O2 再激活 ----------------------------------------------------
    def recall(
        self,
        query: str = "",
        *,
        limit: int = 5,
        tags: Iterable[str] = (),
        semantic: bool = False,
    ) -> list[Flow]:
        """按关键词/标签检索记忆，还原为流。空的 ``query`` 返回最近更新的若干条。

        ``semantic=True`` 时启用词元重叠语义检索（复用 lexicon 向量词元化，
        对同义改写更鲁棒）：对 query 与各记忆节点的 text/tags 做 CJK 二元组
        与英文词元重叠打分，子串命中仍给额外权重。确定性：同输入 → 同排序。
        """
        tag_set = {t for t in tags}
        query_tokens = _semantic_tokens(query) if (semantic and query) else None
        scored: list[tuple[float, MemoryNode]] = []
        for node in self._backend.all():
            score = 0.0
            if query and query in node.text:
                score += 3.0
            if query and any(query in t for t in node.tags):
                score += 2.0
            if tag_set:
                score += 1.5 * len(tag_set & set(node.tags))
                if not (tag_set & set(node.tags)) and not query:
                    continue
            if query_tokens is not None:
                # 语义分量：query 词元与节点文本词元的交集比例
                node_tokens = _semantic_tokens(node.text)
                if node_tokens:
                    inter = len(query_tokens & node_tokens)
                    if inter:
                        score += inter * 1.2 / max(1.0, len(query_tokens))
            if not query and not tag_set:
                score = 0.1
            if score > 0:
                # 越新越靠前
                score += node.updated_at / 1e12
                scored.append((score, node))
        scored.sort(key=lambda x: (-x[0], -x[1].updated_at))
        return [n.to_flow() for _, n in scored[:limit]]

    # -- 0.6-O3 衰减与刷新 ------------------------------------------------
    def decay(self, now: float | None = None) -> list[MemoryNode]:
        """按半衰期刷新全部记忆节点的置信度，返回被下调的节点。"""
        now = time.time() if now is None else now
        changed: list[MemoryNode] = []
        for node in self._backend.all():
            new_conf = node.decayed_confidence(now)
            if new_conf is not node.confidence:
                node.confidence = new_conf
                node.updated_at = now
                node.corrections.append(
                    {"at": now, "kind": "decay", "to": new_conf.value, "clause": "0.6-O3"}
                )
                self._backend.upsert(node)
                changed.append(node)
        if changed:
            self.save()
        return changed

    def correct(self, key: str, new_text: str, *, by: str = "用户纠正") -> MemoryNode:
        """用户纠正的记忆必须更新，并记录纠正来源（0.6-O3）。"""
        node = self._backend.get(key)
        if node is None:
            raise KeyError(f"记忆节点不存在：{key}")
        node.corrections.append(
            {
                "at": time.time(),
                "kind": "correction",
                "by": by,
                "from": node.text,
            }
        )
        node.text = new_text
        node.confidence = Confidence.HIGH  # 用户纠正视为高置信
        node.source = Source.USER_STATED
        node.provenance.source_type = "user_explicit"
        node.provenance.confirmed_by = "user"
        node.provenance.source_id = f"correction:{time.time():.0f}"
        node.provenance.inference_confidence = 1.0
        node.updated_at = time.time()
        self._backend.upsert(node)
        self.save()
        return node

    # -- 记忆冲突解决器（P1-6，最终优化·第二梯队） -----------------------
    def conflict_resolve(
        self,
        key: str,
        new_text: str,
        *,
        new_confidence: Confidence = Confidence.HIGH,
        by: str = "用户",
        scope: str = "task",          # task=单次任务覆盖 / preference=长期偏好变化
    ) -> dict[str, Any]:
        """新旧记忆冲突时，不简单覆盖，而是记录冲突类型并决策保留方式。

        对齐蓝图「记忆冲突解决器」：
          - 判断是长期偏好变化还是单次任务覆盖
          - 长期偏好变化 → 覆盖旧记忆（记录 supersede）
          - 单次任务覆盖 → 保留旧记忆，仅本次任务用新值（apply_current_task_override）
        返回结构化冲突决策，供调用方决定是否真正落盘。
        """
        node = self._backend.get(key)
        if node is None:
            # 无旧记忆，直接新建（无冲突）
            flow = Flow(
                text=new_text,
                layer=FlowLayer.INPUT,
                type=FlowType.FACT,
                source=Source.USER_STATED,
                direction=Direction.INBOUND,
                ttl=TTL.STABLE,
                confidence=new_confidence,
            )
            self.deposit(flow, key=key)
            return {
                "conflict_type": "none",
                "decision": "create",
                "reason": "无既有记忆，直接新建",
                "action": "created",
            }

        # 判断冲突：新旧文本是否实质冲突（置信度或内容分歧）
        if node.text.strip() == new_text.strip():
            return {"conflict_type": "none", "decision": "keep_same", "reason": "内容一致", "action": "noop"}

        is_longterm = scope == "preference"
        if is_longterm:
            node.corrections.append({
                "at": time.time(), "kind": "supersede", "by": by,
                "from": node.text, "to": new_text, "scope": "preference",
            })
            node.text = new_text
            node.confidence = new_confidence
            node.source = Source.USER_STATED
            node.provenance.source_type = "user_explicit"
            node.provenance.confirmed_by = "user"
            node.updated_at = time.time()
            self._backend.upsert(node)
            self.save()
            return {
                "conflict_type": "scope_mismatch",
                "decision": "supersede",
                "reason": "用户确认为长期偏好变化，旧记忆被新偏好覆盖",
                "action": "overwritten",
            }

        # 单次任务覆盖：保留旧记忆，返回本次任务覆盖指令
        return {
            "conflict_type": "scope_mismatch",
            "decision": "keep_both",
            "reason": f"长期记忆为「{node.text}」，本次任务要求「{new_text}」",
            "action": "apply_current_task_override",
        }

    # -- 持久化 -----------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {"nodes": [n.to_dict() for n in self._backend.all()]}

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load(self) -> None:
        if not self.path or not self.path.is_file():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        for d in data.get("nodes", []):
            self._backend.upsert(MemoryNode.from_dict(d))

    # -- 诊断 -------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._backend.all())

    @property
    def private_nodes(self) -> list[MemoryNode]:
        """隐私字段（第 7 章 / 0.6-O1 的 private 标记）。"""
        return [n for n in self._backend.all() if n.private]

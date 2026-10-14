"""知识库：把 knowledge/*.yaml 读成可寻址、可校验、可摘要的知识层。

宪章依据
--------
* **11.1-K1**：字典、语料、词条、风格、亚文化知识只存于 ``knowledge/*.yaml``；
  本模块是唯一的读取入口，代码与测试不得内联词条数据。
* **11.1-K2**：每条知识必须带来源与置信度。条目级缺失时回退到文件级
  ``meta.source/meta.confidence``；两者都缺的条目进入 ``unverified`` 名单，
  置信度强制降为「低」——不可溯源的知识不得当作事实流引用。
* **11.1-K3**：``digest()`` 对全部知识文件做内容哈希，随挖掘结果输出，
  使任何一次调用可复现、可审计。

扩容方式：往 ``knowledge/`` 目录丢一个新的 ``*.yaml``（含 ``kinds`` 与
``entries`` 两个块）即被自动加载，无需改代码。条目 id 全局唯一，
重复即抛 ``KnowledgeBaseError``——宁可加载失败，不要静默合并。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml

#: 知识文件默认搜索路径（与 charter_loader 同哲学：源码树 → 安装包 → cwd）
DEFAULT_SEARCH_PATHS = (
    Path(__file__).resolve().parents[3] / "knowledge",   # 源码树仓库根
    Path(__file__).resolve().parents[1] / "knowledge",   # 打包后随包分发
    Path.cwd() / "knowledge",                            # 运行时 cwd
)

#: 条目缺省安全元数据（11.4-M1 的判定基准）
DEFAULT_SENSITIVITY = "公开"
DEFAULT_PERMISSION = "可输出"

_SENSITIVITIES = {"公开", "隐私", "高危"}
_PERMISSIONS = {"可输出", "仅内部", "禁外发"}
_CONFIDENCES = {"高", "中", "低"}

#: mapping → 先验权重（高映射词条更可能成为画面主干）
_MAPPING_PRIOR = {"high": 1.0, "mid": 0.7, "low": 0.4}
_DEFAULT_PRIOR = 0.6


class KnowledgeBaseError(RuntimeError):
    """知识库加载或校验失败。"""


@dataclass(frozen=True)
class Entry:
    """一条知识。所有字段除 id/term/kind 外均有缺省值。"""

    id: str
    term: str
    kind: str
    source_file: str
    aliases: tuple[str, ...] = ()
    cluster: str | None = None
    mapping: str = "mid"
    domain: tuple[str, ...] = ()
    era: str = ""
    tags: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    weight_prior: float = _DEFAULT_PRIOR
    sensitivity: str = DEFAULT_SENSITIVITY
    permission: str = DEFAULT_PERMISSION
    source: str = ""
    confidence: str = "低"
    gloss: str = ""
    invalid: bool = False
    fcs: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_unverified(self) -> bool:
        return not self.source or self.confidence == "低"

    def searchable(self) -> str:
        """参与子串检索的文本。"""
        return " ".join([self.term, *self.aliases, self.gloss])


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def _slug(text: str) -> str:
    """从 term 生成稳定 id：保留中英数字，其余转下划线。"""
    s = re.sub(r"\s+", "_", str(text).strip().lower())
    s = re.sub(r"[^\w一-鿿]+", "_", s)
    return s.strip("_") or "entry"


@dataclass
class KnowledgeBase:
    """已加载的知识库（多文件合并视图）。"""

    files: dict[str, dict[str, Any]]           # 文件名 → 原始 yaml
    entries: dict[str, Entry]                  # id → 条目
    by_term: dict[str, Entry]                  # term/alias → 条目（长词优先）
    kinds: dict[str, dict[str, Any]]           # 各文件 kinds 块的合并视图
    unverified: list[str]                      # 不可溯源条目 id（11.1-K2）
    duplicate_terms: dict[str, list[str]]      # 跨文件同名词条 → id 列表

    # -- 加载 -------------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path | None = None) -> "KnowledgeBase":
        directory = cls._resolve(path)
        files: dict[str, dict[str, Any]] = {}
        for p in sorted(directory.glob("*.yaml")):
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                raise KnowledgeBaseError(f"知识文件 YAML 解析失败：{p}（{exc}）") from exc
            if not isinstance(data, dict):
                raise KnowledgeBaseError(f"知识文件根节点必须是映射：{p}")
            files[p.name] = data
        if not files:
            raise KnowledgeBaseError(f"{directory} 下没有任何知识文件")
        return cls._build(files, directory)

    @staticmethod
    def _resolve(path: str | Path | None) -> Path:
        if path is not None:
            p = Path(path)
            if not p.is_dir():
                raise KnowledgeBaseError(f"知识库目录不存在：{p}")
            return p
        for candidate in DEFAULT_SEARCH_PATHS:
            if candidate.is_dir():
                return candidate
        raise KnowledgeBaseError(
            "未找到 knowledge/ 目录。请显式传入路径，或把项目根目录作为 cwd 运行。"
        )

    @classmethod
    def _build(cls, files: dict[str, dict[str, Any]], directory: Path) -> "KnowledgeBase":
        entries: dict[str, Entry] = {}
        by_term: dict[str, Entry] = {}
        kinds: dict[str, dict[str, Any]] = {}
        unverified: list[str] = []

        for name, data in files.items():
            file_meta = data.get("meta") or {}
            file_source = str(file_meta.get("source", "")).strip()
            file_conf = str(file_meta.get("confidence", "")).strip()
            file_kinds = data.get("kinds") or {}
            # 文件级缺省 kind：kinds 块只有一个键时，条目可不写 kind
            default_kind = next(iter(file_kinds)) if len(file_kinds) == 1 else None
            for kind_name, kind_def in file_kinds.items():
                merged = dict(kind_def) if isinstance(kind_def, dict) else {}
                merged.setdefault("_files", [])
                merged["_files"] = sorted({*merged["_files"], name})
                kinds[kind_name] = merged

            for raw in data.get("entries") or []:
                if not isinstance(raw, dict) or not raw.get("term"):
                    raise KnowledgeBaseError(f"{name} 含缺少 term 的条目：{raw!r}")
                entry = cls._entry_from_raw(
                    raw, name, file_source, file_conf, default_kind
                )
                if entry.id in entries:
                    raise KnowledgeBaseError(
                        f"条目 id 重复：{entry.id}（{entries[entry.id].source_file} 与 {name}，"
                        f"违反 SSOT 契约第 2 条）"
                    )
                entries[entry.id] = entry
                if entry.is_unverified:
                    unverified.append(entry.id)
                # term/alias 索引：长词优先，避免「特写」吃掉「极度特写」
                for key in (entry.term, *entry.aliases):
                    by_term.setdefault(str(key), entry)

        by_term = dict(
            sorted(by_term.items(), key=lambda kv: -len(str(kv[0])))
        )
        kb = cls(files=files, entries=entries, by_term=by_term,
                 kinds=kinds, unverified=sorted(unverified),
                 duplicate_terms=cls._find_duplicate_terms(entries))
        kb._validate_links()
        return kb

    @staticmethod
    def _find_duplicate_terms(entries: dict[str, Entry]) -> dict[str, list[str]]:
        """跨文件同名词条。允许存在（不同文件可以各自描述同一词），
        但挖掘侧必须去重——同一结论出现两次会污染分布权重。"""
        seen: dict[str, list[str]] = {}
        for e in entries.values():
            seen.setdefault(e.term, []).append(e.id)
        return {t: ids for t, ids in seen.items() if len(ids) > 1}

    @staticmethod
    def _entry_from_raw(
        raw: dict[str, Any], name: str, file_source: str, file_conf: str,
        default_kind: str | None = None,
    ) -> Entry:
        term = str(raw["term"]).strip()
        eid = str(raw.get("id") or _slug(term))
        kind = str(raw.get("kind") or default_kind or "").strip()
        if not kind:
            raise KnowledgeBaseError(
                f"{name}/{eid} 缺少 kind，且文件 kinds 块无法推断唯一缺省值"
            )
        source = str(raw.get("source") or file_source).strip()
        confidence = str(raw.get("confidence") or file_conf or "低").strip()
        if confidence not in _CONFIDENCES:
            raise KnowledgeBaseError(f"{name}/{eid} confidence 非法：{confidence!r}")
        sensitivity = str(raw.get("sensitivity") or DEFAULT_SENSITIVITY)
        permission = str(raw.get("permission") or DEFAULT_PERMISSION)
        if sensitivity not in _SENSITIVITIES:
            raise KnowledgeBaseError(f"{name}/{eid} sensitivity 非法：{sensitivity!r}")
        if permission not in _PERMISSIONS:
            raise KnowledgeBaseError(f"{name}/{eid} permission 非法：{permission!r}")

        fcs = raw.get("fcs_hint") or raw.get("fcs")
        prior = raw.get("weight_prior")
        if prior is None:
            prior = _MAPPING_PRIOR.get(str(raw.get("mapping", "mid")), _DEFAULT_PRIOR)
        return Entry(
            id=eid,
            term=term,
            kind=kind,
            source_file=name,
            aliases=_as_tuple(raw.get("aliases")),
            cluster=(str(raw["cluster"]) if raw.get("cluster") else None),
            mapping=str(raw.get("mapping", "mid")),
            domain=_as_tuple(raw.get("domain")),
            era=str(raw.get("era") or ""),
            tags=_as_tuple(raw.get("tags")),
            related=_as_tuple(raw.get("related")),
            conflicts=_as_tuple(raw.get("conflicts")),
            weight_prior=float(prior),
            sensitivity=sensitivity,
            permission=permission,
            source=source,
            confidence=confidence,
            gloss=str(raw.get("gloss") or raw.get("desc") or ""),
            invalid=bool(raw.get("invalid", False)),
            fcs=dict(fcs) if isinstance(fcs, dict) else None,
            raw=raw,
        )

    def _validate_links(self) -> None:
        """related/conflicts 指向的 id 必须存在（断链即错，不静默）。"""
        broken: list[str] = []
        for e in self.entries.values():
            for rid in (*e.related, *e.conflicts):
                if rid not in self.entries:
                    broken.append(f"{e.id} → {rid}")
        if broken:
            raise KnowledgeBaseError(
                "以下关联/冲突指向不存在的条目：\n  " + "\n  ".join(broken)
            )

    # -- 查询 -------------------------------------------------------------
    def search(self, query: str, kinds: tuple[str, ...] | None = None,
               limit: int = 20) -> list[Entry]:
        """按 term/别名/释义做子串检索，长词优先。"""
        q = (query or "").strip()
        if not q:
            return []
        hits = [
            e for e in self.by_term.values()
            if (q in e.searchable()) and (not kinds or e.kind in kinds)
        ]
        return hits[:limit]

    def get(self, entry_id: str) -> Entry:
        try:
            return self.entries[entry_id]
        except KeyError as exc:
            raise KnowledgeBaseError(f"知识库中不存在条目：{entry_id!r}") from exc

    def by_kind(self, kind: str) -> list[Entry]:
        return [e for e in self.entries.values() if e.kind == kind]

    def cluster_zh(self, cluster: str | None) -> str | None:
        """六大功能簇的中文名（读 lexicon.yaml 的 clusters 块）。"""
        if not cluster:
            return None
        lex = self.files.get("lexicon.yaml") or {}
        node = (lex.get("clusters") or {}).get(cluster)
        if isinstance(node, dict):
            return str(node.get("zh", cluster))
        return cluster

    def weight_gradient(self, cluster: str | None) -> dict[str, float] | None:
        """某簇的推荐权重梯度（3.5 / 9.1，读 lexicon.yaml）。"""
        if not cluster:
            return None
        gradient = (self.files.get("lexicon.yaml") or {}).get("weight_gradient") or {}
        node = gradient.get(cluster)
        if isinstance(node, dict):
            return {"min": float(node["min"]), "max": float(node["max"])}
        return None

    def __iter__(self) -> Iterator[Entry]:
        return iter(self.entries.values())

    def __len__(self) -> int:
        return len(self.entries)

    # -- 摘要与哈希 ---------------------------------------------------------
    def digest(self) -> str:
        """全库内容哈希（11.1-K3）：同一知识 → 同一 digest。"""
        canonical = {
            name: json.dumps(data, ensure_ascii=False, sort_keys=True)
            for name, data in sorted(self.files.items())
        }
        blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def stats(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        by_file: dict[str, int] = {}
        for e in self.entries.values():
            by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
            by_file[e.source_file] = by_file.get(e.source_file, 0) + 1
        return {
            "digest": self.digest(),
            "entry_count": len(self.entries),
            "files": by_file,
            "kinds": by_kind,
            "unverified_count": len(self.unverified),
        }

"""宪章加载器：把 charter.yaml 读成可查询的条款索引。

设计要点
--------
* **单一事实源**：所有条款只在本模块读入一次，其余模块不得硬编码条款文本。
* **条款可寻址**：每条条款持有形如 ``0.4-R1`` / ``10-R4`` 的全局唯一 id，
  测试可以 ``charter.clause("0.5-R4")`` 直接取回原文与其所在章节路径，
  由此建立「条款 ↔ 测试」的双向追溯。
* **零隐式回退**：找不到条款、id 重复、yaml 不可读，一律抛 ``CharterError``，
  绝不静默降级——静默降级会让追溯矩阵失真。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

try:  # pragma: no cover - 依赖缺失时给出明确指引
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover
    raise ModuleNotFoundError(
        "collab-charter 需要 PyYAML 来读取 charter.yaml：pip install pyyaml"
    ) from exc

# 条款 id 形如 0.4-R1 / 0.8-C1 / 10-R4 / 2-P1 / 0.2-V（允许无序号后缀）
CLAUSE_ID_RE = re.compile(r"^(?P<section>\d+(?:\.\d+)?)-(?P<kind>[A-Z])(?P<n>\d*)$")

DEFAULT_SEARCH_PATHS = (
    Path(__file__).resolve().parents[2] / "charter" / "charter.yaml",  # 源码树
    Path(__file__).resolve().parent / "charter.yaml",                 # 打包后
    Path.cwd() / "charter" / "charter.yaml",                          # 运行时 cwd
)


class CharterError(RuntimeError):
    """宪章加载或查询失败。"""


@dataclass(frozen=True)
class Clause:
    """一条可判定、可引用的宪章条款。"""

    id: str
    text: str
    chapter_key: str
    chapter_title: str
    section_key: str
    section_title: str
    kind: str
    zh: str | None = None

    @property
    def anchor(self) -> str:
        """人类可读的定位串，例如 ``〇/0.5 冲突裁决规则/0.5-R4``。"""
        return f"{self.chapter_title}/{self.section_title}/{self.id}"

    def __str__(self) -> str:  # pragma: no cover - 展示用
        return f"[{self.id}] {self.text}"


@dataclass
class Charter:
    """已加载的宪章。"""

    raw: dict[str, Any]
    clauses: dict[str, Clause] = field(default_factory=dict)
    source: Path | None = None

    # -- 只读投影 ---------------------------------------------------------
    @property
    def version(self) -> str:
        return str(self.raw.get("meta", {}).get("version", "unknown"))

    @property
    def charter_id(self) -> str:
        return str(self.raw.get("meta", {}).get("charter_id", "unknown"))

    @property
    def title(self) -> str:
        return str(self.raw.get("meta", {}).get("charter_id", "用户协作宪章"))

    # -- 加载 -------------------------------------------------------------
    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Charter":
        """加载宪章。``path`` 为空时按默认搜索路径查找。"""
        target = cls._resolve(path)
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise CharterError(f"无法读取宪章文件：{target}（{exc}）") from exc
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise CharterError(f"宪章 YAML 解析失败：{target}（{exc}）") from exc
        if not isinstance(raw, dict):
            raise CharterError(f"宪章根节点必须是映射：{target}")

        charter = cls(raw=raw, source=target)
        charter._index_clauses()
        if not charter.clauses:
            raise CharterError(f"未能从 {target} 索引到任何条款，请检查文件结构。")
        return charter

    @staticmethod
    def _resolve(path: str | os.PathLike[str] | None) -> Path:
        if path is not None:
            p = Path(path)
            if not p.is_file():
                raise CharterError(f"指定的宪章文件不存在：{p}")
            return p
        for candidate in DEFAULT_SEARCH_PATHS:
            if candidate.is_file():
                return candidate
        raise CharterError(
            "未找到 charter.yaml。请显式传入路径，或把项目根目录作为 cwd 运行。"
        )

    # -- 条款索引 ---------------------------------------------------------
    def _index_clauses(self) -> None:
        for chapter_key, chapter in self.raw.items():
            if chapter_key == "meta" or not isinstance(chapter, dict):
                continue
            chapter_title = str(chapter.get("title", chapter_key))
            self._walk(chapter, chapter_key, chapter_title, chapter_title, chapter_title)

    def _walk(
        self,
        node: Any,
        chapter_key: str,
        chapter_title: str,
        section_key: str,
        section_title: str,
    ) -> None:
        if isinstance(node, dict):
            cid = node.get("id")
            if isinstance(cid, str) and CLAUSE_ID_RE.match(cid):
                text = (
                    node.get("statement")
                    or node.get("desc")
                    or node.get("effect")
                    or node.get("zh")
                    or ""
                )
                if cid in self.clauses:
                    raise CharterError(f"条款 id 重复：{cid}（违反 SSOT 契约第 2 条）")
                self.clauses[cid] = Clause(
                    id=cid,
                    text=str(text),
                    chapter_key=chapter_key,
                    chapter_title=chapter_title,
                    section_key=section_key,
                    section_title=section_title,
                    kind=str(node.get("kind", CLAUSE_ID_RE.match(cid).group("kind"))),
                    zh=node.get("zh"),
                )
            for key, value in node.items():
                if key in {"id", "statement", "desc", "effect", "zh", "title"}:
                    continue
                label = str(node.get("title", key))
                self._walk(value, chapter_key, chapter_title, key, label)
        elif isinstance(node, list):
            for item in node:
                self._walk(item, chapter_key, chapter_title, section_key, section_title)

    # -- 查询 -------------------------------------------------------------
    def clause(self, clause_id: str) -> Clause:
        """按 id 取回条款；不存在则抛 ``CharterError``。"""
        try:
            return self.clauses[clause_id]
        except KeyError as exc:
            raise CharterError(
                f"宪章中不存在条款 {clause_id!r}；已索引 {len(self.clauses)} 条。"
            ) from exc

    def clause_ids(self) -> list[str]:
        """全部条款 id，按「章节序 → 条款序」稳定排序。"""
        def sort_key(cid: str) -> tuple:
            m = CLAUSE_ID_RE.match(cid)
            assert m is not None
            head = float(m.group("section"))
            n = m.group("n")
            return (head, m.group("kind"), int(n) if n else 0)

        return sorted(self.clauses, key=sort_key)

    def __iter__(self) -> Iterator[Clause]:
        for cid in self.clause_ids():
            yield self.clauses[cid]

    def __len__(self) -> int:
        return len(self.clauses)

    def section(self, chapter_key: str, section_key: str) -> Any:
        """取回原始 yaml 的某一节，供内核模块读取结构性数据。

        返回值可能是映射（如 ``0.3_pipeline``）也可能是序列（如
        ``enforcement.gate_matrix``）——调用方按自己的契约断言类型。
        """
        if chapter_key not in self.raw:
            raise CharterError(f"宪章中不存在章节：{chapter_key}")
        chapter = self.raw[chapter_key]
        if not isinstance(chapter, dict):
            raise CharterError(f"章节 {chapter_key} 不是映射，无法按小节访问。")
        if section_key not in chapter:
            raise CharterError(f"章节 {chapter_key} 中不存在小节：{section_key}")
        return chapter[section_key]

    def find(self, needle: str) -> list[Clause]:
        """条款文本子串检索，用于「查来源」类回溯。"""
        return [c for c in self if needle in c.text or (c.zh and needle in c.zh)]


@lru_cache(maxsize=4)
def load_charter(path: str | None = None) -> Charter:
    """带缓存的加载入口，适合在 CLI/服务进程里反复取用。"""
    return Charter.load(path)

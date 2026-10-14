"""规则引擎：把《模块化特征簇标记语法》的判定标准变成可执行检查。

覆盖的条款
----------
2.1 封闭集分类 · 2.3 词条类型学 · 3.1 底层锚点 · 3.2 风格域数量法则
3.4 抽象词条规则 · 3.5 权重梯度 · 5.4 冗余过滤与控制力量化
8.3 冲突判定 · 9.1 权重区间 · 11 硬性约束

每条规则都挂 clause 字段，指向它所执行的规定条文——由此形成
「规则 ↔ 条款」的可审计映射，属于本项目「条款追溯」设计的一部分。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from .parser import CLUSTERS, Item, ParsedPrompt, parse

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent


def _default_lexicon_path() -> Path:
    """词库 SSOT 位于 knowledge/lexicon.yaml（见 11.1）。

    解析顺序：仓库根 knowledge/ → 工具目录内就地词库（旧版布局的兼容回退）。
    新装布局只应命中第一条，回退仅为不破坏历史安装。
    """
    ssot = _REPO_ROOT / "knowledge" / "lexicon.yaml"
    if ssot.is_file():
        return ssot
    legacy = _HERE / "lexicon.yaml"
    if legacy.is_file():
        return legacy
    return ssot  # 保持可预测的报错路径


DEFAULT_LEXICON = _default_lexicon_path()


# ---------------------------------------------------------------------------
# 模型
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Classification:
    """一个词条的归类结果。"""

    item_index: int
    text: str
    cluster: str          # subject/render/color/medium/distortion/light
    cluster_zh: str
    kind: str             # entity/abstract/tech
    mapping: str          # high/mid/low
    term: str             # 命中的词典条目
    invalid: bool = False

    @property
    def is_abstract(self) -> bool:
        return self.kind == "abstract"

    @property
    def is_entity(self) -> bool:
        return self.kind == "entity"


@dataclass(frozen=True)
class Finding:
    """一条诊断结论。"""

    code: str
    severity: str          # error / warn / info
    clause: str
    message: str
    items: tuple[int, ...] = ()

    def __str__(self) -> str:  # pragma: no cover
        mark = {"error": "✗", "warn": "!", "info": "i"}[self.severity]
        return f"{mark} [{self.code}] {self.message}（依据 {self.clause}）"


@dataclass
class ControlScore:
    """5.4 控制力量化：四项加权 + 风格域附加扣分。"""

    anchor_strength: float
    conflict_score: float
    abstract_score: float
    mapping_score: float
    style_penalty: float
    total: float
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def grade(self) -> str:
        if self.total >= 85:
            return "A 可控"
        if self.total >= 70:
            return "B 基本可控"
        if self.total >= 55:
            return "C 存在漂移风险"
        return "D 不可控"


@dataclass
class Analysis:
    """一次完整分析。"""

    parsed: ParsedPrompt
    classified: list[Classification]
    findings: list[Finding]
    score: ControlScore

    @property
    def by_cluster(self) -> dict[str, list[Classification]]:
        out: dict[str, list[Classification]] = {}
        for c in self.classified:
            out.setdefault(c.cluster, []).append(c)
        return out

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warn"]

    def unclassified(self) -> list[Item]:
        idx = {c.item_index for c in self.classified}
        return [i for i in self.parsed.items if i.index not in idx and not i.is_param]

    def cluster_order_violations(self, cluster_order: dict[str, int]) -> list[str]:
        """检查簇排布是否符合 2.1 的隐性权重梯度（主体在前、氛围在后）。

        判定依据是**各功能簇首次出现的位置**，而不是逐词条比对——同一簇的
        词条可以分散出现（如主体词条穿插在别处），只有「簇的先后次序」才
        构成 2.1 意义上的排布问题。
        """
        first_seen: dict[str, int] = {}
        for c in self.classified:
            first_seen.setdefault(c.cluster, c.item_index)
        seq = sorted(first_seen.items(), key=lambda kv: kv[1])

        problems: list[str] = []
        max_order = -1
        for cluster, _pos in seq:
            order = cluster_order.get(cluster, 99)
            if order < max_order:
                zh = next((c.cluster_zh for c in self.classified if c.cluster == cluster), cluster)
                problems.append(f"{zh} 的首次出现位置晚于更高层级的簇")
            max_order = max(max_order, order)
        return problems


# ---------------------------------------------------------------------------
# 词典
# ---------------------------------------------------------------------------
class Lexicon:
    """词条知识库。"""

    def __init__(self, data: dict[str, Any]) -> None:
        self.raw = data
        self.clusters: dict[str, dict[str, Any]] = data["clusters"]
        self.kinds: dict[str, dict[str, Any]] = data["kinds"]
        # 按 term 长度降序，保证长词优先命中
        self.entries: list[dict[str, Any]] = sorted(
            data["entries"], key=lambda e: -len(str(e["term"]))
        )
        self.direct_conflicts = data.get("direct_conflicts", [])
        self.cross_conflicts = data.get("cross_domain_conflicts", [])
        self.weight_gradient: dict[str, dict[str, float]] = data.get("weight_gradient", {})
        self.global_range: dict[str, float] = data.get("global_weight_range", {"min": 0.5, "max": 1.4})
        self.style_terms: list[str] = data.get("style_domain_terms", [])
        self.scoring: dict[str, float] = data.get("scoring", {})
        self.chain_stages: dict[str, dict[str, str]] = data.get("chain_stages", {})

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Lexicon":
        p = Path(path) if path else DEFAULT_LEXICON
        return cls(yaml.safe_load(p.read_text(encoding="utf-8")))

    # -- 归类 -------------------------------------------------------------
    def classify_text(self, text: str) -> dict[str, Any] | None:
        for e in self.entries:
            if str(e["term"]) in text:
                return e
        return None

    def cluster_order(self) -> dict[str, int]:
        return {k: int(v["order"]) for k, v in self.clusters.items()}

    def detect_style_domains(self, texts: Iterable[str]) -> list[str]:
        joined = "\n".join(texts)
        return [t for t in self.style_terms if t in joined]


# ---------------------------------------------------------------------------
# 规则引擎
# ---------------------------------------------------------------------------
class Linter:
    """对一段提示词执行完整诊断。"""

    def __init__(self, lexicon: Lexicon | None = None) -> None:
        self.lex = lexicon or Lexicon.load()

    # -- 主入口 -----------------------------------------------------------
    def analyze(self, prompt: str) -> Analysis:
        parsed = parse(prompt)
        classified: list[Classification] = []
        findings: list[Finding] = []

        for item in parsed.items:
            if item.is_param or not item.text:
                continue
            hit = self.lex.classify_text(item.text)
            if hit is None:
                continue
            cluster = str(hit["cluster"])
            classified.append(
                Classification(
                    item_index=item.index,
                    text=item.text,
                    cluster=cluster,
                    cluster_zh=self.lex.clusters[cluster]["zh"],
                    kind=str(hit["kind"]),
                    mapping=str(hit["mapping"]),
                    term=str(hit["term"]),
                    invalid=bool(hit.get("invalid", False)),
                )
            )

        findings += self._check_coverage(parsed, classified)
        findings += self._check_weights(parsed, classified)
        findings += self._check_abstract_rule(parsed, classified)
        findings += self._check_anchor(classified)
        findings += self._check_conflicts(parsed)
        findings += self._check_style_domains(parsed)
        findings += self._check_invalid(parsed, classified)
        findings += self._check_gradient(parsed, classified)

        findings.sort(key=lambda f: ({"error": 0, "warn": 1, "info": 2}[f.severity], f.code))
        score = self._score(parsed, classified, findings)
        analysis = Analysis(parsed=parsed, classified=classified, findings=findings, score=score)
        # 2.1 簇序检查依赖 Analysis 的首次出现统计，故在其后追加
        for msg in analysis.cluster_order_violations(self.lex.cluster_order()):
            analysis.findings.append(
                Finding(code="FCS011", severity="info", clause="2.1", message=msg)
            )
        analysis.findings.sort(
            key=lambda f: ({"error": 0, "warn": 1, "info": 2}[f.severity], f.code)
        )
        return analysis

    # -- 2.1 封闭集分类 ---------------------------------------------------
    def _check_coverage(self, parsed: ParsedPrompt, classified: list[Classification]) -> list[Finding]:
        known = {c.item_index for c in classified}
        orphans = [
            i for i in parsed.items
            if not i.is_param and i.text and i.index not in known and not i.cluster_marker
        ]
        if not orphans:
            return []
        return [
            Finding(
                code="FCS001",
                severity="warn",
                clause="2.1",
                message=f"以下词条未能归入六大功能簇，需人工判定或补入词库：{[i.text for i in orphans]}",
                items=tuple(i.index for i in orphans),
            )
        ]

    # -- 9.1 权重区间 -----------------------------------------------------
    def _check_weights(self, parsed: ParsedPrompt, classified: list[Classification]) -> list[Finding]:
        lo, hi = self.lex.global_range["min"], self.lex.global_range["max"]
        out: list[Finding] = []
        over = [i for i in parsed.items if i.explicit_weight and (i.effective_weight < lo or i.effective_weight > hi)]
        if over:
            out.append(
                Finding(
                    code="FCS002",
                    severity="error",
                    clause="9.1",
                    message=f"权重超出推荐区间 [{lo}, {hi}]："
                            + "、".join(f"{i.text}={i.effective_weight:g}" for i in over),
                    items=tuple(i.index for i in over),
                )
            )
        return out

    # -- 3.4 抽象词条权重与数量 -------------------------------------------
    def _check_abstract_rule(self, parsed: ParsedPrompt, classified: list[Classification]) -> list[Finding]:
        out: list[Finding] = []
        idx2item = {i.index: i for i in parsed.items}
        heavy = [
            c for c in classified
            if c.is_abstract and idx2item[c.item_index].effective_weight >= 1.0
            and idx2item[c.item_index].explicit_weight
        ]
        if heavy:
            out.append(
                Finding(
                    code="FCS003",
                    severity="error",
                    clause="3.4",
                    message="抽象概念词条权重不得 ≥ 1.0（必须低于实体视觉词条，统一降权）："
                            + "、".join(f"{c.text}" for c in heavy),
                    items=tuple(c.item_index for c in heavy),
                )
            )
        n_entity = sum(1 for c in classified if c.is_entity)
        n_abstract = sum(1 for c in classified if c.is_abstract)
        if n_abstract and n_entity and n_abstract >= n_entity:
            out.append(
                Finding(
                    code="FCS005",
                    severity="error",
                    clause="3.4",
                    message=f"抽象概念词条数（{n_abstract}）不少于实体视觉词条数（{n_entity}），"
                            "会挤占实体特征的向量权重，造成画面空洞",
                )
            )
        return out

    # -- 3.1 底层锚点 -----------------------------------------------------
    def _check_anchor(self, classified: list[Classification]) -> list[Finding]:
        if any(c.cluster == "subject" for c in classified):
            return []
        return [
            Finding(
                code="FCS008",
                severity="error",
                clause="3.1",
                message="缺少第一层「核心载体锚点」：没有可识别的主体实体词条，"
                        "后续风格、质感、氛围词条都会发生向量漂移",
            )
        ]

    # -- 8.3 冲突判定 -----------------------------------------------------
    def _check_conflicts(self, parsed: ParsedPrompt) -> list[Finding]:
        out: list[Finding] = []
        joined = " | ".join(i.text for i in parsed.items)
        for pair in self.lex.direct_conflicts:
            a, b = str(pair["a"]), str(pair["b"])
            if a in joined and b in joined:
                out.append(
                    Finding(
                        code="FCS004",
                        severity="error",
                        clause=str(pair.get("clause", "8.3")),
                        message=f"直接语义冲突：「{a}」与「{b}」字面互斥，必须删除其一或权重隔离"
                                + (f"——{pair['note']}" if pair.get("note") else ""),
                    )
                )
        for pair in self.lex.cross_conflicts:
            a, b = str(pair["a"]), str(pair["b"])
            if a in joined and b in joined:
                out.append(
                    Finding(
                        code="FCS009",
                        severity="warn",
                        clause=str(pair.get("clause", "8.3")),
                        message=f"跨域逻辑冲突：「{a}」与「{b}」来自两套独立影像体系，"
                                "属可控风险叠加，须以权重制衡与簇隔离管理"
                                + (f"——{pair['note']}" if pair.get("note") else ""),
                    )
                )
        return out

    # -- 3.2 风格域数量法则 -----------------------------------------------
    def _check_style_domains(self, parsed: ParsedPrompt) -> list[Finding]:
        domains = self.lex.detect_style_domains([i.text for i in parsed.items])
        if len(domains) > 3:
            return [
                Finding(
                    code="FCS006",
                    severity="warn",
                    clause="3.2",
                    message=f"检测到 {len(domains)} 个风格域（{domains}），超过「主风格域最多两个 + "
                            "次要风格域最多一个」的数量法则，构成高风险风格撕裂",
                )
            ]
        return []

    # -- 5.4 冗余过滤 -----------------------------------------------------
    def _check_invalid(self, parsed: ParsedPrompt, classified: list[Classification]) -> list[Finding]:
        bad = [c for c in classified if c.invalid]
        if not bad:
            return []
        return [
            Finding(
                code="FCS007",
                severity="warn",
                clause="5.4",
                message=f"无效技术参数，应予移除：{', '.join(c.text for c in bad)}",
                items=tuple(c.item_index for c in bad),
            )
        ]

    # -- 3.5 权重梯度 -----------------------------------------------------
    def _check_gradient(self, parsed: ParsedPrompt, classified: list[Classification]) -> list[Finding]:
        out: list[Finding] = []
        idx2item = {i.index: i for i in parsed.items}
        for c in classified:
            item = idx2item[c.item_index]
            if not item.explicit_weight:
                continue
            band = self.lex.weight_gradient.get(c.cluster)
            if not band:
                continue
            w = item.effective_weight
            if w < band["min"] or w > band["max"]:
                out.append(
                    Finding(
                        code="FCS010",
                        severity="info",
                        clause="3.5",
                        message=f"「{c.text}」权重 {w:g} 偏离 {c.cluster_zh} 推荐区间 "
                                f"[{band['min']:g}, {band['max']:g}]，与顺序形成的隐性权重可能不一致",
                        items=(c.item_index,),
                    )
                )
        return out

    # -- 5.4 控制力量化 ---------------------------------------------------
    def _score(
        self,
        parsed: ParsedPrompt,
        classified: list[Classification],
        findings: list[Finding],
    ) -> ControlScore:
        n_total = max(1, len(classified))
        n_entity = sum(1 for c in classified if c.is_entity)
        n_abstract = sum(1 for c in classified if c.is_abstract)
        n_high = sum(1 for c in classified if c.mapping == "high")

        # 主体锚定强度：有主体簇 + 主体词条带权重或靠前
        anchor = 0.0
        if any(c.cluster == "subject" for c in classified):
            anchor = 0.7
            first_subject = min((c.item_index for c in classified if c.cluster == "subject"), default=999)
            if first_subject <= 2:
                anchor += 0.3
        anchor = min(1.0, anchor)

        n_conflict = sum(1 for f in findings if f.code in {"FCS004", "FCS009"})
        conflict_score = max(0.0, 1.0 - n_conflict / max(1, n_total) * 2)

        abstract_score = 1.0 - (n_abstract / n_total)
        mapping_score = n_high / n_total

        domains = self.lex.detect_style_domains([i.text for i in parsed.items])
        style_penalty = max(0.0, (len(domains) - 3) * 4.0)

        w = self.lex.scoring
        total = (
            anchor * w.get("anchor_strength", 0.35)
            + conflict_score * w.get("conflict_penalty", 0.25)
            + abstract_score * w.get("abstract_ratio", 0.20)
            + mapping_score * w.get("high_mapping_ratio", 0.20)
        ) * 100.0
        total = max(0.0, min(100.0, total - style_penalty))

        return ControlScore(
            anchor_strength=round(anchor, 3),
            conflict_score=round(conflict_score, 3),
            abstract_score=round(abstract_score, 3),
            mapping_score=round(mapping_score, 3),
            style_penalty=style_penalty,
            total=round(total, 1),
            detail={
                "词条总数": n_total,
                "实体视觉": n_entity,
                "抽象概念": n_abstract,
                "高映射": n_high,
                "冲突数": n_conflict,
                "风格域": domains,
            },
        )

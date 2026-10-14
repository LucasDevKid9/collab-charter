"""报告渲染与簇结构保留优化建议。

对应规范 5.1「诊断解构分支」与 5.2「簇结构保留优化分支」——两个分支必须
并行交付。本模块把 ``Analysis`` 渲染成人读报告，并给出**同范式**的优化稿：
只做重排、降权、删除无效项、补锚点，绝不改写为自然叙事长句（第 11 章禁止项）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .parser import Item, ParsedPrompt, render
from .rules import Analysis, Classification, Lexicon

_SEV_MARK = {"error": "✗", "warn": "!", "info": "i"}


# ---------------------------------------------------------------------------
# 优化建议（5.2 簇结构保留优化分支）
# ---------------------------------------------------------------------------
@dataclass
class Suggestion:
    changes: list[str] = field(default_factory=list)
    optimized: str = ""
    items: list[Item] = field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        return not self.changes


def suggest(analysis: Analysis, lexicon: Lexicon) -> Suggestion:
    """生成同范式优化稿。"""
    rules = {c.item_index: c for c in analysis.classified}
    changes: list[str] = []
    kept: list[Item] = []

    # 1) 删除无效技术参数（5.4 冗余过滤）
    for item in analysis.parsed.items:
        cls = rules.get(item.index)
        if cls and cls.invalid:
            changes.append(f"移除无效技术参数「{item.text}」（5.4）")
            continue
        kept.append(_copy(item))

    # 2) 抽象词条降权（3.4）
    for item in kept:
        cls = rules.get(item.index)
        if cls and cls.is_abstract:
            if item.explicit_weight and item.effective_weight >= 0.8:
                changes.append(f"抽象词条「{item.text}」降权 {item.weight:g} → 0.6（3.4）")
                item.weight = 0.6
            elif not item.explicit_weight:
                changes.append(f"抽象词条「{item.text}」补低权重 0.6（3.4）")
                item.weight = 0.6
                item.explicit_weight = True

    # 3) 补主体锚点权重（3.1 / 3.5）
    body = [i for i in kept if i.index in rules and rules[i.index].cluster == "subject"]
    for item in body:
        if not item.explicit_weight:
            changes.append(f"主体锚点「{item.text}」补权重 1.2（3.5）")
            item.weight = 1.2
            item.explicit_weight = True
            break

    # 4) 按四层设计模型重排簇顺序（5.2 第一步）
    order = lexicon.cluster_order()
    def sort_key(i: Item) -> tuple[int, int]:
        cls = rules.get(i.index)
        if cls is not None:
            return (order.get(cls.cluster, 99), i.index)
        # 技术参数保持在手写内容之后；未归类词条排在已归类之后、参数之前
        return (98 if i.is_param else 90, i.index)

    reordered = sorted(kept, key=sort_key)
    if [i.index for i in reordered] != [i.index for i in kept]:
        changes.append("按四层设计模型重排簇顺序：主体锚点前置、抽象氛围置末（5.2 第一步）")

    return Suggestion(changes=changes, optimized=render(reordered), items=reordered)


def _copy(item: Item) -> Item:
    import copy

    return copy.deepcopy(item)


# ---------------------------------------------------------------------------
# 人读报告
# ---------------------------------------------------------------------------
def to_dict(analysis: Analysis, lexicon: Lexicon | None = None) -> dict[str, Any]:
    """结构化输出，供 MCP / HTTP 接口直接返回。"""
    out: dict[str, Any] = {
        "summary": {
            "items": len(analysis.parsed.items),
            "classified": len(analysis.classified),
            "errors": len(analysis.errors),
            "warnings": len(analysis.warnings),
            "score": analysis.score.total,
            "grade": analysis.score.grade,
        },
        "score_detail": analysis.score.detail,
        "clusters": {
            lexicon.clusters[k]["zh"] if lexicon and k in lexicon.clusters else k: [
                {"text": c.text, "kind": c.kind, "mapping": c.mapping, "weight": None}
                for c in v
            ]
            for k, v in analysis.by_cluster.items()
        },
        "findings": [
            {
                "code": f.code,
                "severity": f.severity,
                "clause": f.clause,
                "message": f.message,
                "items": list(f.items),
            }
            for f in analysis.findings
        ],
        "unclassified": [i.text for i in analysis.unclassified()],
    }
    if lexicon:
        sug = suggest(analysis, lexicon)
        out["suggestion"] = {"changes": sug.changes, "optimized": sug.optimized}
        out["cluster_order_violations"] = analysis.cluster_order_violations(lexicon.cluster_order())
    return out


def render_text(analysis: Analysis, lexicon: Lexicon) -> str:
    s = analysis.score
    lines: list[str] = []
    lines.append("═══ 诊断解构分支（5.1，不改原文）═══")
    lines.append(
        f"词条 {len(analysis.parsed.items)} 条 | 已归类 {len(analysis.classified)} 条 | "
        f"错误 {len(analysis.errors)} | 警告 {len(analysis.warnings)}"
    )
    lines.append(f"控制力量化：{s.total}/100 —— {s.grade}（5.4）")
    lines.append("")

    lines.append("── 六大功能簇分布 ──")
    for key, zh in [(k, v["zh"]) for k, v in sorted(lexicon.clusters.items(), key=lambda x: x[1]["order"])]:
        group = analysis.by_cluster.get(key, [])
        if not group:
            continue
        lines.append(f"[{zh}] " + "、".join(f"{c.text}" for c in group))
    if analysis.unclassified():
        lines.append("[未归类] " + "、".join(i.text for i in analysis.unclassified()))
    lines.append("")

    viol = analysis.cluster_order_violations(lexicon.cluster_order())
    if viol:
        lines.append("── 簇序检查（2.1 隐性权重梯度）──")
        lines += [f"  ! {v}" for v in viol]
        lines.append("")

    if analysis.findings:
        lines.append("── 诊断清单 ──")
        for f in analysis.findings:
            lines.append(f"  {_SEV_MARK[f.severity]} [{f.code}] {f.message}（依据 {f.clause}）")
        lines.append("")

    lines.append("── 控制力量化明细（5.4）──")
    for k, v in s.detail.items():
        lines.append(f"  {k}: {v}")
    lines.append(
        f"  主体锚定 {s.anchor_strength} | 冲突消解 {s.conflict_score} | "
        f"抽象占比 {s.abstract_score} | 高映射占比 {s.mapping_score}"
        + (f" | 风格域扣分 {s.style_penalty:g}" if s.style_penalty else "")
    )
    lines.append("")

    sug = suggest(analysis, lexicon)
    lines.append("═══ 簇结构保留优化分支（5.2，禁止改写为自然叙事长句）═══")
    if sug.is_noop:
        lines.append("未发现需要调整的项——原稿已符合四层模型与权重梯度。")
    else:
        for ch in sug.changes:
            lines.append(f"  · {ch}")
        lines.append("")
        lines.append("── 优化后全文（同范式）──")
        lines.append(sug.optimized)
    return "\n".join(lines)


def render_markdown(analysis: Analysis, lexicon: Lexicon) -> str:
    s = analysis.score
    md: list[str] = []
    md.append("## 诊断解构分支（5.1）\n")
    md.append(f"- 词条总数：**{len(analysis.parsed.items)}**")
    md.append(f"- 已归类：**{len(analysis.classified)}**")
    md.append(f"- 错误 **{len(analysis.errors)}** / 警告 **{len(analysis.warnings)}**")
    md.append(f"- 控制力：**{s.total}/100（{s.grade}）**\n")

    md.append("| 功能簇 | 词条 |")
    md.append("|---|---|")
    for key, v in sorted(lexicon.clusters.items(), key=lambda x: x[1]["order"]):
        group = analysis.by_cluster.get(key, [])
        if group:
            md.append(f"| {v['zh']} | {'、'.join(c.text for c in group)} |")
    md.append("")

    if analysis.findings:
        md.append("| 级别 | 编号 | 结论 | 依据 |")
        md.append("|---|---|---|---|")
        for f in analysis.findings:
            md.append(f"| {f.severity} | `{f.code}` | {f.message} | {f.clause} |")
        md.append("")

    sug = suggest(analysis, lexicon)
    md.append("## 簇结构保留优化分支（5.2）\n")
    if sug.is_noop:
        md.append("无需调整。\n")
    else:
        md.extend(f"- {c}" for c in sug.changes)
        md.append("\n```text\n" + sug.optimized + "\n```")
    return "\n".join(md)


def dumps(analysis: Analysis, lexicon: Lexicon | None = None, *, indent: int = 2) -> str:
    return json.dumps(to_dict(analysis, lexicon), ensure_ascii=False, indent=indent)

"""fcslint · 《模块化特征簇标记语法》的可执行实现。

用法::

    from fcslint import analyze

    report = analyze("PC-98 era visual novel sprite, 古早立绘, (赛璐璐平涂:1.2), 4:3")
    print(report["summary"]["score"], report["summary"]["grade"])

命令行::

    python -m fcslint "<提示词>"          # 人类可读报告
    python -m fcslint --json "<提示词>"   # 结构化输出
"""

from .parser import CLUSTERS, Item, ParsedPrompt, normalize_structure, parse, render
from .report import Suggestion, dumps, render_markdown, render_text, suggest, to_dict
from .rules import Analysis, Classification, ControlScore, Finding, Lexicon, Linter

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "CLUSTERS",
    "Item",
    "ParsedPrompt",
    "parse",
    "render",
    "normalize_structure",
    "Analysis",
    "Classification",
    "ControlScore",
    "Finding",
    "Lexicon",
    "Linter",
    "Suggestion",
    "suggest",
    "to_dict",
    "dumps",
    "render_text",
    "render_markdown",
    "analyze",
]


def analyze(prompt: str, *, lexicon: Lexicon | None = None) -> dict:
    """一站式入口：解析 → 诊断 → 评分 → 优化建议，返回结构化字典。"""
    lex = lexicon or Lexicon.load()
    analysis = Linter(lex).analyze(prompt)
    return to_dict(analysis, lex)

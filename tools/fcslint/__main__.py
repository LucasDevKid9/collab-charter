"""fcslint 命令行。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .report import dumps, render_markdown, render_text
from .rules import Lexicon, Linter


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fcslint",
        description="《模块化特征簇标记语法》诊断与簇结构保留优化",
    )
    p.add_argument("prompt", nargs="?", help="提示词文本；省略时从 stdin 读取")
    p.add_argument("-f", "--file", help="从文件读取提示词")
    p.add_argument("--json", action="store_true", help="输出 JSON（供 Agent 调用）")
    p.add_argument("--md", action="store_true", help="输出 Markdown")
    p.add_argument("--lexicon", help="自定义 lexicon.yaml 路径")
    p.add_argument("--fail-on-error", action="store_true", help="存在 error 级问题时以非零码退出")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.file:
        prompt = Path(args.file).read_text(encoding="utf-8")
    elif args.prompt:
        prompt = args.prompt
    else:
        prompt = sys.stdin.read()

    if not prompt.strip():
        print("错误：没有输入提示词。", file=sys.stderr)
        return 2

    lex = Lexicon.load(args.lexicon)
    analysis = Linter(lex).analyze(prompt)

    if args.json:
        print(dumps(analysis, lex))
    elif args.md:
        print(render_markdown(analysis, lex))
    else:
        print(render_text(analysis, lex))

    if args.fail_on_error and analysis.errors:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

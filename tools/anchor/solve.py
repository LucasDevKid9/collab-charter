#!/usr/bin/env python3
"""collab-charter 内置 cognitive-anchor 兼容入口（v2.0 语义不变）。

本文件是兼容 shim：cognitive-anchor 独立仓库时代的调用方式
``python3 scripts/solve.py ...`` 在 collab-charter 仓库里对应
``python3 tools/anchor/solve.py ...``。

真正的实现位于 ``src/collab_charter/anchor/solver.py``（宪章 12.1
符号锚定的执行载体）。本 shim 只做转发，不承载任何逻辑，
避免两处实现漂移。
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from collab_charter.anchor.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

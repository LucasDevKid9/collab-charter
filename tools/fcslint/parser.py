"""特征簇标记语法解析器。

把一段提示词解析为「词条序列 + 权重 + 簇标记」，为规则引擎与评分器提供
结构化输入。解析器的三条硬约束（来自《模块化特征簇标记语法》第 9 章）：

1. **逗号是唯一分隔符**，且只有**括号深度为 0** 的逗号才是分隔符——
   案例中的 ``(Agfacolor胶片色阶浸染，时代印痕:0.8)`` 内部的全角逗号
   属于词条内容，不得切开。
2. **权重标记**形如 ``(词条:数值)``，推荐区间 0.5–1.4。
3. **簇标记**形如 ``[簇名称]``，仅是分析元标记，图像模型不识别；
   解析器需要保留它，但不得把它当成词条计入画面内容。

同时兼容中文全角标点（``（）：，［］`` 与半角等价），因为创作者的输入
往往直接从中文输入法来。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: 结构字符的全角 → 半角映射。只映射**结构性**字符，不动中文标点内容。
#: 刻意不含全角逗号「，」——逗号既是分隔符也可能是词条内容（如
#: `(Agfacolor胶片色阶浸染，时代印痕:0.8)`），归一化会破坏内容。
#: 分隔符的兼容在 `_split_top_level` 里按「任一写法都算分隔符」处理。
_STRUCT_MAP = str.maketrans(
    {
        "（": "(",
        "）": ")",
        "：": ":",
        "［": "[",
        "］": "]",
        "【": "[",
        "】": "]",
        "＝": "=",
    }
)

#: 逗号分隔符的两种写法（半角 / 全角）
_SEPARATORS = ",，"

#: 权重语法：括号内 last 冒号后是数字
_WEIGHT_RE = re.compile(r"^(?P<body>.*?)[:：]\s*(?P<w>-?\d+(?:\.\d+)?)\s*$", re.S)
#: 行首簇标记 [簇名称]（允许后面还跟着词条内容）
_CLUSTER_RE = re.compile(r"^\[(?P<name>[^\]]+)\]\s*")
#: 技术参数类尾注，如 4:3 / 16:9 / 240p / --ar 3:4
PARAM_RE = re.compile(r"^(--ar\s+\d+:\d+|\d+:\d+|\d+p|--\w+(?:\s+\S+)?)$", re.I)

#: 六大功能簇（封闭集，来自规范 2.1）
CLUSTERS = (
    "主体实体",
    "原生绘制",
    "色彩系统",
    "媒介采集",
    "畸变图层",
    "光影氛围",
)


@dataclass
class Item:
    """一个词条。"""

    index: int
    text: str
    weight: float | None = None
    explicit_weight: bool = False
    cluster_marker: str | None = None
    is_param: bool = False
    raw: str = ""

    @property
    def effective_weight(self) -> float:
        """未显式标注权重时返回 1.0（规范 11 条禁止默认权重均等的误判，
        因此这里显式暴露「是否显式标注」）。"""
        return 1.0 if self.weight is None else self.weight

    def __str__(self) -> str:  # pragma: no cover
        w = f":{self.weight}" if self.explicit_weight else ""
        m = f"[{self.cluster_marker}] " if self.cluster_marker else ""
        return f"{self.index}. {m}{self.text}{w}"


@dataclass
class ParsedPrompt:
    """一次解析的完整结果。"""

    raw: str
    items: list[Item] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)

    @property
    def terms(self) -> list[str]:
        return [i.text for i in self.items if not i.is_param and i.text]

    @property
    def params(self) -> list[str]:
        return [i.text for i in self.items if i.is_param]

    @property
    def markers(self) -> list[str]:
        return [i.cluster_marker for i in self.items if i.cluster_marker]

    def with_marker(self, name: str) -> list[Item]:
        return [i for i in self.items if i.cluster_marker == name]

    def has_explicit_weights(self) -> bool:
        return any(i.explicit_weight for i in self.items)

    def __len__(self) -> int:
        return len(self.items)


def normalize_structure(text: str) -> str:
    """把结构性全角标点归一为半角，内容标点原样保留。"""
    return text.translate(_STRUCT_MAP)


def _split_top_level(text: str, separators: str = _SEPARATORS) -> list[str]:
    """按括号深度 0 的分隔符切分。括号内的分隔符不切。

    分隔符同时接受半角 ``,`` 与全角 ``，``——创作者从中文输入法来的文本
    两种混用极常见，而两者在深度 >0 时都属于词条内容。
    """
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch in separators and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def parse_item(segment: str, index: int) -> Item:
    """解析单个词条段。"""
    raw = segment
    seg = segment.strip()
    item = Item(index=index, text=seg, raw=raw)

    # 1) 剥离行首簇标记 [簇名称]（标记后面可能直接跟着词条）
    m = _CLUSTER_RE.match(seg.strip())
    if m:
        item.cluster_marker = m.group("name").strip()
        seg = seg.strip()[m.end():].strip()
        if not seg:
            item.text = ""
            return item

    # 2) 技术参数（画幅/比例等）
    if PARAM_RE.match(seg):
        item.text = seg
        item.is_param = True
        return item

    # 3) 权重标记 (词条:1.2)
    if seg.startswith("(") and seg.endswith(")"):
        inner = seg[1:-1].strip()
        m = _WEIGHT_RE.match(inner)
        if m:
            item.text = m.group("body").strip()
            item.weight = float(m.group("w"))
            item.explicit_weight = True
            return item

    # 3.5) 无括号的权重写法「词条:1.3」——创作者输入法下的常见形式。
    #      技术参数已在第 2 步拦下，故 16:9 之类不会走到这里。
    m = _WEIGHT_RE.match(seg)
    if m and m.group("body").strip():
        item.text = m.group("body").strip()
        item.weight = float(m.group("w"))
        item.explicit_weight = True
        item.raw = raw
        return item

    item.text = seg
    return item


def parse(prompt: str) -> ParsedPrompt:
    """解析一段提示词。"""
    result = ParsedPrompt(raw=prompt)
    if not prompt or not prompt.strip():
        return result
    normalized = normalize_structure(prompt)
    segments = _split_top_level(normalized)
    for i, seg in enumerate(segments):
        try:
            result.items.append(parse_item(seg, i))
        except Exception:  # pragma: no cover - 解析器不得让整段失败
            result.unparsed.append(seg)
    return result


def render(items: list[Item]) -> str:
    """把词条序列还原为提示词文本（簇结构保留优化的输出用）。"""
    chunks: list[str] = []
    for it in items:
        prefix = f"[{it.cluster_marker}]" if it.cluster_marker else ""
        if it.explicit_weight:
            chunks.append(f"{prefix}({it.text}:{it.weight:g})")
        else:
            chunks.append(f"{prefix}{it.text}")
    return ", ".join(chunks)

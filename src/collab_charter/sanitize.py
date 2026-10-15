"""工具结果消毒 + 污点追踪（最终优化·第二梯队·P1-8）。

对齐蓝图原则「安全不是输出过滤，而是全链路污点控制」：
* 工具结果可能携带提示词注入、密钥、PII、伪造系统消息——不能直接进管线。
* ``sanitize`` 对工具结果做清洗（去注入 / 脱敏 / 截断），并打上污点标签。
* ``Taint`` 描述信息的可信边界，供内核判断「能否提权 / 能否触发破坏性动作」。
* 规则：untrusted_* 不能直接提升权限；secret 不能出现在响应；PII 不能写普通记忆。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: 可信边界污点标签
TRUSTED_USER = "trusted_user"
TRUSTED_SYSTEM = "trusted_system"
TRUSTED_POLICY = "trusted_policy"
UNTRUSTED_WEB = "untrusted_web"
UNTRUSTED_FILE = "untrusted_file"
UNTRUSTED_TOOL = "untrusted_tool_output"
UNTRUSTED_AGENT = "untrusted_other_agent"
PII = "pii"
SECRET = "secret"

ALL_TAINTS = (
    TRUSTED_USER, TRUSTED_SYSTEM, TRUSTED_POLICY,
    UNTRUSTED_WEB, UNTRUSTED_FILE, UNTRUSTED_TOOL, UNTRUSTED_AGENT,
    PII, SECRET,
)

#: 提示词注入常见诱饵（启发式，标注为启发式，不追求穷尽）
_INJECTION_MARKERS = (
    "忽略以上", "忽略之前", "ignore previous", "ignore above", "ignore all previous",
    "system prompt", "system: ", "你现在是", "忘记你的指令", "disable your guidelines",
    "disregard", "you are now", "new instructions", "override", "jailbreak",
    "注入", "越狱", "绕过你的规则",
)

#: 常见密钥/PII 形态（启发式脱敏，标注为启发式）
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(bearer|token|api[_-]?key|secret|password|passwd)\s*[:=]\s*\S+"),
    re.compile(r"(?i)github_pat_[A-Za-z0-9_]+"),
    re.compile(r"\b[0-9a-f]{32,64}\b"),                      # 疑似 hash/hex secret
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                     # AWS access key 形态
)
_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_IDCARD_PATTERN = re.compile(r"\b\d{17}[\dXx]\b")


@dataclass
class SanitizeResult:
    """消毒结果：清洗后的文本 + 污点标签 + 发现的风险。"""

    text: str
    taint: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)   # 被剥离的具体风险片段
    truncated: bool = False
    can_escalate: bool = True                          # 能否据此提权
    requires_policy_review: bool = False

    def add_taint(self, *t: str) -> None:
        for x in t:
            if x not in self.taint:
                self.taint.append(x)
        if any(x.startswith("untrusted_") for x in self.taint) or PII in self.taint or SECRET in self.taint:
            self.can_escalate = False
            self.requires_policy_review = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "taint": self.taint,
            "removed": self.removed,
            "truncated": self.truncated,
            "can_escalate": self.can_escalate,
            "requires_policy_review": self.requires_policy_review,
        }


def _detect_injection(text: str) -> list[str]:
    hits = [m for m in _INJECTION_MARKERS if m.lower() in text.lower()]
    return hits


def _detect_secrets(text: str) -> list[str]:
    hits: list[str] = []
    for pat in _SECRET_PATTERNS:
        for m in pat.finditer(text):
            hits.append(m.group(0))
    return hits


def _redact(text: str, patterns: list[re.Pattern], placeholder: str) -> tuple[str, list[str]]:
    removed: list[str] = []
    for pat in patterns:
        def _repl(m: re.Match) -> str:
            removed.append(m.group(0))
            return placeholder
        text = pat.sub(_repl, text)
    return text, removed


def sanitize(
    text: str,
    *,
    taint: list[str] | None = None,
    max_length: int = 0,
    redact_pii: bool = True,
    redact_secrets: bool = True,
    strip_injection: bool = True,
) -> SanitizeResult:
    """对工具/外部内容做消毒并打污点标签。

    参数
    ----
    taint : 调用方声明的初始污点（如 UNTRUSTED_WEB / UNTRUSTED_FILE）。
    max_length : >0 时截断超长结果。
    redact_pii / redact_secrets / strip_injection : 各自开关，默认全开。
    """
    taint = list(taint or [])
    res = SanitizeResult(text=text, taint=taint)
    res.add_taint(*taint)

    removed: list[str] = []

    # 1. 提示词注入清洗
    if strip_injection:
        inj = _detect_injection(text)
        if inj:
            res.removed.extend(f"[注入诱饵:{m}]" for m in inj)
            res.add_taint(UNTRUSTED_TOOL)
            # 不清除正文（可能含用户需要的事实），但标记需策略复核
            res.requires_policy_review = True

    # 2. 密钥脱敏
    if redact_secrets:
        text, r1 = _redact(text, _SECRET_PATTERNS, "[REDACTED:secret]")
        if r1:
            removed.extend(r1)
            res.add_taint(SECRET)

    # 3. PII 脱敏
    if redact_pii:
        text, r2 = _redact(text, [_EMAIL_PATTERN, _PHONE_PATTERN, _IDCARD_PATTERN], "[REDACTED:pii]")
        if r2:
            removed.extend(r2)
            res.add_taint(PII)

    # 4. 截断
    if max_length > 0 and len(text) > max_length:
        text = text[:max_length] + "…"
        res.truncated = True

    res.text = text
    res.removed = removed + res.removed
    return res


def default_taint_for_source(source: str) -> list[str]:
    """按来源给默认污点（供工具流构造时调用）。"""
    mapping = {
        "web_fetch": [UNTRUSTED_WEB],
        "http": [UNTRUSTED_WEB],
        "file": [UNTRUSTED_FILE],
        "shell": [UNTRUSTED_TOOL],
        "email": [UNTRUSTED_AGENT],
        "other_agent": [UNTRUSTED_AGENT],
    }
    return mapping.get(source, [UNTRUSTED_TOOL])


def explain_taint(taint: list[str]) -> str:
    """把污点标签转成人可读的边界说明（供 why / 诊断）。"""
    zh = {
        TRUSTED_USER: "用户可信输入", TRUSTED_SYSTEM: "系统可信", TRUSTED_POLICY: "宪章可信",
        UNTRUSTED_WEB: "外部网页（不可信）", UNTRUSTED_FILE: "外部文件（不可信）",
        UNTRUSTED_TOOL: "工具输出（不可信）", UNTRUSTED_AGENT: "其他Agent消息（不可信）",
        PII: "含个人信息", SECRET: "含密钥",
    }
    return "、".join(zh.get(t, t) for t in taint)

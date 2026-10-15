"""审计账本：append-only JSONL 治理记录（P0-4）。

设计
----
* 每次关键事件（决策 / 管线执行 / 记忆写入 / 闸门拦截）都追加一条 JSON 记录。
* 记录只增不改（append-only），带 ``ts`` 与 ``seq``，天然可按 session 回放。
* 存储：纯本地 JSONL 文件，默认 ``audit/`` 目录，零依赖。
* 与 ``governance.DecisionRecord`` 打通：审计事件可以直接承载决策记录，供
  Replay / ``why`` 命令读取。

不变量
------
* 写入使用追加 + flush，崩溃不丢已落盘记录。
* 每条记录带 ``event_id``（可幂等去重）与 ``seq``（全局递增序号）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .governance import DecisionRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AuditEvent:
    """一条审计事件。"""

    event_type: str          # decision / pipeline / memory_write / gate_block
    session_id: str
    seq: int = 0
    event_id: str = field(default_factory=lambda: uuid4().hex[:16])
    ts: str = field(default_factory=_now_iso)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "seq": self.seq,
            "ts": self.ts,
            "session_id": self.session_id,
            "event_type": self.event_type,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AuditEvent":
        return cls(
            event_id=d.get("event_id", uuid4().hex[:16]),
            seq=int(d.get("seq", 0)),
            ts=d.get("ts", _now_iso()),
            session_id=d.get("session_id", ""),
            event_type=d.get("event_type", ""),
            payload=d.get("payload", {}),
        )


class AuditLedger:
    """append-only 审计账本（JSONL）。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else Path("audit")
        self.path.mkdir(parents=True, exist_ok=True)
        # 目录模式：每会话一个文件 <audit>/<session_id>.jsonl
        self._next_seq = 0
        self._load_seq()

    def _file_for(self, session_id: str) -> Path:
        safe = session_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        return self.path / f"{safe}.jsonl"

    def _load_seq(self) -> None:
        """从已存在文件恢复 seq 计数（进程重启后不重号）。"""
        max_seq = 0
        for f in self.path.glob("*.jsonl"):
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    d = json.loads(line)
                    if "seq" in d and isinstance(d["seq"], int):
                        max_seq = max(max_seq, d["seq"])
            except (json.JSONDecodeError, OSError):
                continue
        self._next_seq = max_seq + 1

    def append(self, event: AuditEvent) -> AuditEvent:
        """追加一条事件并落盘。返回带真实 seq 的事件。"""
        if event.seq == 0:
            event.seq = self._next_seq
            self._next_seq += 1
        with open(self._file_for(event.session_id), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            fh.flush()
        return event

    def record_decision(self, session_id: str, decision: DecisionRecord) -> AuditEvent:
        """把一条决策记录写入账本。"""
        return self.append(AuditEvent(
            event_type="decision",
            session_id=session_id,
            payload=decision.to_dict(),
        ))

    def record_pipeline(
        self,
        session_id: str,
        *,
        route: str = "",
        records: Iterable[str] = (),
        decisions: Iterable[DecisionRecord] = (),
        terminated: bool = False,
    ) -> AuditEvent:
        """把一次管线执行的整体信息写入账本（含逐条决策）。"""
        return self.append(AuditEvent(
            event_type="pipeline",
            session_id=session_id,
            payload={
                "route": route,
                "stage_records": list(records),
                "decisions": [d.to_dict() for d in decisions],
                "terminated": terminated,
            },
        ))

    # -- 查询 -------------------------------------------------------------
    def read(self, session_id: str) -> list[AuditEvent]:
        """读取某 session 的完整事件流（按 seq 排序）。"""
        f = self._file_for(session_id)
        if not f.exists():
            return []
        events: list[AuditEvent] = []
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(AuditEvent.from_dict(json.loads(line)))
            except json.JSONDecodeError:
                continue
        events.sort(key=lambda e: e.seq)
        return events

    def decisions_of(self, session_id: str) -> list[DecisionRecord]:
        """取某 session 的全部决策记录（跨 pipeline/decision 事件去重）。"""
        seen: dict[str, DecisionRecord] = {}
        for ev in self.read(session_id):
            if ev.event_type == "decision" and "decision_id" in ev.payload:
                seen[ev.payload["decision_id"]] = DecisionRecord.from_dict(ev.payload)
            elif ev.event_type == "pipeline":
                for d in ev.payload.get("decisions", []):
                    if "decision_id" in d:
                        seen[d["decision_id"]] = DecisionRecord.from_dict(d)
        return list(seen.values())

    def all_sessions(self) -> list[str]:
        return sorted({f.stem for f in self.path.glob("*.jsonl")})

    def __len__(self) -> int:
        return sum(len(self.read(s)) for s in self.all_sessions())


# 便捷：默认账本（供 CLI 使用）
_default_ledger: AuditLedger | None = None


def default_ledger(path: str | Path | None = None) -> AuditLedger:
    global _default_ledger
    if path is not None:
        return AuditLedger(path)
    if _default_ledger is None:
        _default_ledger = AuditLedger()
    return _default_ledger

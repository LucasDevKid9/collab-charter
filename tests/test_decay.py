"""条款折旧（Charter Decay）测试。

覆盖三层：
1. 登记表加载与内容约束（12 条样例、断链校验、永不退休对照项）
2. 校验失败路径（未知 id / 重复 / 非法状态 / 空条件 / 文件缺失）
3. 报告与 CLI（计数、覆盖率、文本三列、JSON、按状态过滤、坏表退出码）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from collab_charter import Charter
from collab_charter.decay import (
    STATUSES,
    DecayError,
    ExpiryEntry,
    load_expiry,
)


# ---------------------------------------------------------------------------
# 1. 登记表加载
# ---------------------------------------------------------------------------

class Test登记表加载:
    def test_默认登记表可加载_71条样例(self, charter: Charter) -> None:
        report = load_expiry(charter=charter)
        assert len(report.entries) == 71
        assert report.clause_total == len(charter.clauses) == 90

    def test_全部id都存在于宪章_无断链(self, charter: Charter) -> None:
        report = load_expiry(charter=charter)
        known = set(charter.clauses)
        assert all(e.id in known for e in report.entries)

    def test_登记id不重复(self, charter: Charter) -> None:
        ids = [e.id for e in load_expiry(charter=charter).entries]
        assert len(ids) == len(set(ids))

    def test_四种状态都有样例(self, charter: Charter) -> None:
        counts = load_expiry(charter=charter).counts()
        assert set(counts) == set(STATUSES)
        # active 必然存在；candidate / permanent 是本表的对照设计
        assert counts["active"] >= 1
        assert counts["candidate"] >= 1
        assert counts["permanent"] >= 1

    def test_存在永不退休的对照项(self, charter: Charter) -> None:
        """机制必须能说「永不」——否则它只是无脑删除。"""
        report = load_expiry(charter=charter)
        permanent = report.by_status("permanent")
        assert permanent, "登记表应至少保留一条 permanent 对照项"
        assert all(e.note for e in permanent), "对照项必须写明为什么不设退休条件"

    def test_第〇章全部条款已登记(self, charter: Charter) -> None:
        """M2 第一批交付的硬指标：第〇章 23 条无一遗漏。"""
        report = load_expiry(charter=charter)
        registered = {e.id for e in report.entries}
        zero_chapter = {cid for cid in charter.clauses if cid.startswith("0.")}
        assert len(zero_chapter) == 23
        assert zero_chapter <= registered, zero_chapter - registered

    def test_评审状态结构稳定(self, charter: Charter) -> None:
        counts = load_expiry(charter=charter).review_counts()
        assert list(counts) == ["draft", "approved", "rejected"]
        assert counts["draft"] == 30
        assert counts["approved"] == 41

    def test_第〇章全部已批准(self, charter: Charter) -> None:
        report = load_expiry(charter=charter)
        zero_chapter = [e for e in report.entries if e.id.startswith("0.")]
        assert len(zero_chapter) == 23
        assert all(e.review == "approved" for e in zero_chapter)

    def test_第二批四章全部已登记(self, charter: Charter) -> None:
        """第一/二/三/五章共 23 条，第二批交付后应无遗漏。"""
        report = load_expiry(charter=charter)
        registered = {e.id for e in report.entries}
        batch2 = {
            cid for cid in charter.clauses
            if cid.split("-")[0].split(".")[0] in {"1", "2", "3", "5"}
        }
        assert len(batch2) == 23
        assert batch2 <= registered, batch2 - registered

    def test_第三批五章全部已登记(self, charter: Charter) -> None:
        """第四/六/七/八/九章共 23 条，第三批（上）交付后应无遗漏。"""
        report = load_expiry(charter=charter)
        registered = {e.id for e in report.entries}
        batch3 = {
            cid for cid in charter.clauses
            if cid.split("-")[0].split(".")[0] in {"4", "6", "7", "8", "9"}
        }
        assert len(batch3) == 23
        assert batch3 <= registered, batch3 - registered

    def test_第二批条目已全部批准(self, charter: Charter) -> None:
        approved = {e.id for e in load_expiry(charter=charter).entries
                    if e.review == "approved"}
        assert len(approved) == 41
        for cid in ("1-C2", "2-P1", "3-R1", "5-R6"):
            assert cid in approved

    def test_每条都有合法评审状态(self, charter: Charter) -> None:
        for e in load_expiry(charter=charter).entries:
            assert e.review in ("draft", "approved", "rejected")

    def test_每条退休条件都非空且可证伪(self, charter: Charter) -> None:
        """退休条件必须可观测：数值阈值，或「零 / 全部 / 所有 / 永不」类全称判定。"""
        markers = ("≥", "≤", "零", "全部", "所有", "永不退休")
        for e in load_expiry(charter=charter).entries:
            assert len(e.expiry_test.strip()) >= 10
            assert any(m in e.expiry_test for m in markers), (
                f"{e.id} 的退休条件缺少可证伪的判定词：{e.expiry_test}"
            )


# ---------------------------------------------------------------------------
# 2. 校验失败路径
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "expiry.yaml"
    p.write_text(
        yaml.safe_dump({"meta": {"version": "test"}, "entries": rows}, allow_unicode=True),
        encoding="utf-8",
    )
    return p


class Test校验:
    def test_未知条款id_断链即错(self, tmp_path: Path, charter: Charter) -> None:
        p = _write(tmp_path, [
            {"id": "99.9-Z1", "expiry_test": "某个条件 ≥90%", "status": "active"},
        ])
        with pytest.raises(DecayError, match="断链"):
            load_expiry(p, charter)

    def test_重复id报错(self, tmp_path: Path, charter: Charter) -> None:
        row = {"id": "1-C1", "expiry_test": "某个条件 ≥90%", "status": "active"}
        p = _write(tmp_path, [row, dict(row)])
        with pytest.raises(DecayError, match="重复"):
            load_expiry(p, charter)

    def test_非法状态报错(self, tmp_path: Path, charter: Charter) -> None:
        p = _write(tmp_path, [
            {"id": "1-C1", "expiry_test": "某个条件 ≥90%", "status": "deleted"},
        ])
        with pytest.raises(DecayError, match="状态非法"):
            load_expiry(p, charter)

    def test_非法评审状态报错(self, tmp_path: Path, charter: Charter) -> None:
        p = _write(tmp_path, [
            {"id": "1-C1", "expiry_test": "某个条件 ≥90%", "status": "active",
             "review": "pending"},
        ])
        with pytest.raises(DecayError, match="评审状态非法"):
            load_expiry(p, charter)

    def test_空退休条件报错(self, tmp_path: Path, charter: Charter) -> None:
        p = _write(tmp_path, [{"id": "1-C1", "expiry_test": "  ", "status": "active"}])
        with pytest.raises(DecayError, match="退休条件为空"):
            load_expiry(p, charter)

    def test_缺少entries报错(self, tmp_path: Path, charter: Charter) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text("meta: {}\n", encoding="utf-8")
        with pytest.raises(DecayError, match="entries"):
            load_expiry(p, charter)

    def test_文件不存在报错(self, tmp_path: Path, charter: Charter) -> None:
        with pytest.raises(DecayError, match="不存在"):
            load_expiry(tmp_path / "nope.yaml", charter)


# ---------------------------------------------------------------------------
# 3. 报告与 CLI
# ---------------------------------------------------------------------------

class Test报告:
    def test_状态计数稳定含零(self, charter: Charter) -> None:
        counts = load_expiry(charter=charter).counts()
        assert list(counts) == list(STATUSES)
        assert sum(counts.values()) == 71

    def test_覆盖率按全部条款计算(self, charter: Charter) -> None:
        report = load_expiry(charter=charter)
        assert report.coverage == pytest.approx(71 / 90)

    def test_文本报告含三列要素(self, charter: Charter) -> None:
        text = load_expiry(charter=charter).render()
        assert "条款总数 90" in text
        assert "覆盖率" in text
        for e in load_expiry(charter=charter).entries[:3]:
            assert e.id in text

    def test_json可序列化且字段齐全(self, charter: Charter) -> None:
        data = load_expiry(charter=charter).to_dict()
        assert data["clause_total"] == 90
        assert data["registered"] == 71
        assert data["entries"][0]["expiry_test"]
        json.dumps(data, ensure_ascii=False)  # 不抛异常即通过

    def test_按状态过滤(self, charter: Charter) -> None:
        report = load_expiry(charter=charter)
        candidates = report.by_status("candidate")
        assert candidates and all(e.status == "candidate" for e in candidates)

    def test_条目可独立构造用于排序与导出(self) -> None:
        e = ExpiryEntry(id="1-C1", expiry_test="条件 ≥95%", status="active", note=None)
        assert e.label == "服役"
        assert e.to_dict()["status"] == "active"


class TestCLI:
    def test_cli_decay_默认输出(self, capsys: pytest.CaptureFixture[str]) -> None:
        from collab_charter.cli import main

        assert main(["decay"]) == 0
        out = capsys.readouterr().out
        assert "折旧登记表" in out
        assert "1-C1" in out

    def test_cli_decay_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        from collab_charter.cli import main

        assert main(["decay", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["registered"] == 71

    def test_cli_decay_按状态过滤(self, capsys: pytest.CaptureFixture[str]) -> None:
        from collab_charter.cli import main

        assert main(["decay", "--status", "permanent"]) == 0
        out = capsys.readouterr().out
        assert "10-R2" in out

    def test_cli_decay_按评审状态过滤(self, capsys: pytest.CaptureFixture[str]) -> None:
        from collab_charter.cli import main

        assert main(["decay", "--review", "draft"]) == 0
        out = capsys.readouterr().out
        assert "待批准 30" in out

    def test_cli_decay_坏登记表返回2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from collab_charter.cli import main

        p = _write(tmp_path, [{"id": "99.9-Z1", "expiry_test": "x", "status": "active"}])
        assert main(["decay", "--expiry", str(p)]) == 2
        assert "无效" in capsys.readouterr().err

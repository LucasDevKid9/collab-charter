"""MCP 接口层：协议握手、工具列举与调用。"""

from __future__ import annotations

import json

import pytest

import mcp_server
from mcp_server import PROTOCOL_VERSION, SERVER_NAME, ToolRegistry, dispatch


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


# -- 协议 ------------------------------------------------------------------
def _call(registry: ToolRegistry, method: str, params: dict | None = None, req_id: int = 1):
    resp = dispatch({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}, registry)
    assert resp is not None
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == req_id
    return resp


def test_initialize_握手(registry: ToolRegistry) -> None:
    resp = _call(registry, "initialize")
    result = resp["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == SERVER_NAME
    assert "tools" in result["capabilities"]


def test_初始化通知不回复(registry: ToolRegistry) -> None:
    assert dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}, registry) is None


def test_ping(registry: ToolRegistry) -> None:
    assert _call(registry, "ping")["result"] == {}


def test_未知方法返回_32601(registry: ToolRegistry) -> None:
    resp = _call(registry, "no/such/method")
    assert resp["error"]["code"] == -32601


# -- 工具列表 --------------------------------------------------------------
def test_十四个工具都已注册(registry: ToolRegistry) -> None:
    tools = _call(registry, "tools/list")["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {
        "charter_clause", "charter_clauses", "charter_receipt", "charter_route",
        "charter_handle", "charter_arbitrate", "charter_gate", "fcslint_analyze",
        "memory_deposit", "memory_recall",
        # v3.2 新增：符号锚定（12.1）+ 知识库与语义场（11）
        "anchor_solve", "lexicon_search", "lexicon_mine", "semantic_field",
    }


def test_server_版本与内核一致(registry: ToolRegistry) -> None:
    assert mcp_server.SERVER_VERSION == "3.2.0"
    resp = _call(registry, "initialize")
    assert resp["result"]["serverInfo"]["version"] == "3.2.0"


def test_每个工具都有描述与输入_schema(registry: ToolRegistry) -> None:
    tools = _call(registry, "tools/list")["result"]["tools"]
    for t in tools:
        assert t["description"], f"{t['name']} 缺少描述"
        assert t["description"].endswith("。"), f"{t['name']} 描述应当说明何时使用"
        assert t["inputSchema"]["type"] == "object"
        assert "properties" in t["inputSchema"]


def test_带必填参数的工具都声明了_required(registry: ToolRegistry) -> None:
    tools = {t["name"]: t for t in _call(registry, "tools/list")["result"]["tools"]}
    assert tools["charter_clause"]["inputSchema"]["required"] == ["clause_id"]
    assert tools["charter_handle"]["inputSchema"]["required"] == ["text"]
    assert tools["fcslint_analyze"]["inputSchema"]["required"] == ["prompt"]


# -- 工具调用 --------------------------------------------------------------
def _payload(resp) -> dict:
    assert resp["result"]["isError"] is False, resp["result"]["content"][0]["text"]
    return json.loads(resp["result"]["content"][0]["text"])


def test_调用_charter_clause(registry: ToolRegistry) -> None:
    data = _payload(_call(registry, "tools/call", {"name": "charter_clause", "arguments": {"clause_id": "0.5-R4"}}))
    assert data["id"] == "0.5-R4"
    assert "并列呈现" in data["text"]


def test_调用_charter_gate_高危禁外发被拦截(registry: ToolRegistry) -> None:
    data = _payload(_call(registry, "tools/call", {"name": "charter_gate", "arguments": {
        "sensitivity": "高危", "permission": "禁外发"}}))
    assert data["verdict"] == "block"
    assert data["terminates_pipeline"] is True
    assert data["explain"]


def test_调用_charter_route(registry: ToolRegistry) -> None:
    data = _payload(_call(registry, "tools/call", {"name": "charter_route", "arguments": {
        "text": "快速告诉我 z3 是什么"}}))
    assert data["fast_path"] is True
    assert len(data["stages"]) == 3


def test_调用_charter_handle_返回轨迹(registry: ToolRegistry) -> None:
    data = _payload(_call(registry, "tools/call", {"name": "charter_handle", "arguments": {
        "text": "帮我分析这个方案"}}))
    assert data["trace"]
    assert data["mirror"]
    assert isinstance(data["selfcheck_passed"], bool)


def test_调用_charter_arbitrate(registry: ToolRegistry) -> None:
    data = _payload(_call(registry, "tools/call", {"name": "charter_arbitrate", "arguments": {
        "left": "这是事实", "right": "这可能是对的"}}))
    assert data["clause"] == "0.5-R1"


def test_调用_fcslint_analyze(registry: ToolRegistry) -> None:
    data = _payload(_call(registry, "tools/call", {"name": "fcslint_analyze", "arguments": {
        "prompt": "古早立绘, 赛璐璐平涂, 随机种子, 4:3"}}))
    assert "summary" in data
    assert data["summary"]["grade"]


def test_调用_anchor_solve_结论来自求解器(registry: ToolRegistry) -> None:
    data = _payload(_call(registry, "tools/call", {"name": "anchor_solve", "arguments": {
        "declare": "x:可行性,y:预算充足",
        "constraints": "x+y>=1",
        "decisions": "做:x+y==2; 不做:x+y<2",
        "rounds": "|y==0",
    }}))
    assert data["schema_version"] == "cognitive-anchor.solve/2.0"
    assert len(data["rounds"]) == 2
    assert data["rounds"][0]["recommend"] == "不做"
    assert data["drift"] is False
    assert data["clauses"] == ["12.1-A1", "12.1-A2", "12.1-A3", "12.1-A4", "12.1-A5"]


def test_调用_lexicon_search(registry: ToolRegistry) -> None:
    data = _payload(_call(registry, "tools/call", {"name": "lexicon_search", "arguments": {
        "query": "谷圈", "limit": 5}}))
    assert data["count"] >= 1
    assert data["kb_digest"]
    assert any(i["term"] == "谷圈" for i in data["items"])


def test_调用_lexicon_mine_返回分布权重与闸门(registry: ToolRegistry) -> None:
    data = _payload(_call(registry, "tools/call", {"name": "lexicon_mine", "arguments": {
        "requirement": "谷圈 痛包 晒谷",
        "task_objectives": ["整理术语"],
        "semantic_state": "收敛期",
        "limit": 6,
    }}))
    assert data["entries"]
    total_w = sum(e["weight"] for e in data["entries"])
    assert abs(total_w - 1.0) < 1e-6, "分布权重必须归一（11.2-V2）"
    assert data["space_digest"]
    assert "field" in data


def test_调用_lexicon_mine_高危条目被闸门拦截(registry: ToolRegistry) -> None:
    data = _payload(_call(registry, "tools/call", {"name": "lexicon_mine", "arguments": {
        "requirement": "开盒 人肉搜索",
        "limit": 8,
    }}))
    blocked = [e for e in data["entries"] if e["gate"] and e["gate"]["verdict"] == "block"]
    assert blocked, "高危敏感词条必须带 block 闸门结论（11.4-M1）"


def test_调用_semantic_field_返回社群与缺口(registry: ToolRegistry) -> None:
    data = _payload(_call(registry, "tools/call", {"name": "semantic_field", "arguments": {
        "requirement": "谷圈 痛包 吧唧 吃谷 晒谷",
        "task_objectives": ["整理徽章收藏圈的术语"],
        "semantic_state": "收敛期",
        "limit": 10,
    }}))
    f = data["field"]
    assert f["metrics"]["node_count"] >= 3
    assert f["metrics"]["modularity"] >= 0.0
    assert "gaps" in f
    assert "centrality" in f


def test_记忆沉淀与检索闭环(registry: ToolRegistry) -> None:
    _payload(_call(registry, "tools/call", {"name": "memory_deposit", "arguments": {
        "text": "关键结论甲", "key": "k.mcp", "tags": ["t"]}}))
    data = _payload(_call(registry, "tools/call", {"name": "memory_recall", "arguments": {
        "query": "关键结论"}}))
    assert data["count"] == 1
    assert data["items"][0]["meta"]["layer"] == "memory"


# -- 错误处理 --------------------------------------------------------------
def test_未知工具报错但不崩(registry: ToolRegistry) -> None:
    resp = _call(registry, "tools/call", {"name": "not_a_tool", "arguments": {}})
    assert resp["result"]["isError"] is True
    assert "未知工具" in resp["result"]["content"][0]["text"]


def test_参数错误被捕获(registry: ToolRegistry) -> None:
    resp = _call(registry, "tools/call", {"name": "charter_clause", "arguments": {"wrong": "x"}})
    assert resp["result"]["isError"] is True
    assert "参数错误" in resp["result"]["content"][0]["text"]


def test_条款不存在时返回错误文本(registry: ToolRegistry) -> None:
    resp = _call(registry, "tools/call", {"name": "charter_clause", "arguments": {"clause_id": "99-X1"}})
    assert resp["result"]["isError"] is True
    assert "不存在条款" in resp["result"]["content"][0]["text"]


def test_批量请求逐条回复(registry: ToolRegistry) -> None:
    for i, method in enumerate(["ping", "tools/list"], start=1):
        assert _call(registry, method, req_id=i)["id"] == i

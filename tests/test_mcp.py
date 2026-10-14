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
def test_十个工具都已注册(registry: ToolRegistry) -> None:
    tools = _call(registry, "tools/list")["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {
        "charter_clause", "charter_clauses", "charter_receipt", "charter_route",
        "charter_handle", "charter_arbitrate", "charter_gate", "fcslint_analyze",
        "memory_deposit", "memory_recall",
    }


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

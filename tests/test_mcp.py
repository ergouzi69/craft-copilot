"""MCP 层测试：JSON-RPC 握手 / 工具列表 / 工具调用 / 错误处理

验证点（对应 s19 MCP + craft R18）：
- initialize 握手（协议版本 + 能力）
- notifications 无响应
- tools/list 返回 3 个工具（query_order/refund_order/list_sources）
- tools/call 调 query_order（真实查库返回订单）
- 未知工具 → -32602 错误
- 缺必填参数 → -32602 错误
- 非法 JSON → -32700 解析错误
- 未知方法 → -32601 方法不存在
"""

import pytest

from app.tools.mcp import MiniMcpServer
import app.store.db as db


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "m.db")
    db.init_db()
    db.seed_orders([
        {"order_id": "T1001", "source": "taobao", "product": "无线鼠标", "amount": 89.0,
         "status": "in_transit", "carrier": "顺丰速运", "tracking_no": "SF123", "eta": "明天 18:00 前"},
    ])
    yield


def _send(server, method, params=None, msg_id=1):
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return server.handle_line(__import__("json").dumps(msg))[0]


def test_initialize_handshake():
    server = MiniMcpServer()
    resp = _send(server, "initialize", {"protocolVersion": "2024-11-05"})
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert resp["result"]["serverInfo"]["name"] == "craft-copilot-mcp"
    assert resp["id"] == 1


def test_initialized_notification_no_response():
    server = MiniMcpServer()
    assert server.handle_line(
        '{"jsonrpc":"2.0","method":"notifications/initialized"}') == []


def test_tools_list_has_three():
    server = MiniMcpServer()
    resp = _send(server, "tools/list")
    tools = {t["name"] for t in resp["result"]["tools"]}
    assert tools == {"query_order", "refund_order", "list_sources"}
    # 每个工具有 inputSchema（JSON Schema）
    q = next(t for t in resp["result"]["tools"] if t["name"] == "query_order")
    assert "inputSchema" in q and "properties" in q["inputSchema"]


def test_tools_call_query_order():
    server = MiniMcpServer()
    resp = _send(server, "tools/call", {"name": "query_order", "arguments": {"order_id": "T1001"}})
    assert resp["result"]["isError"] is False
    text = resp["result"]["content"][0]["text"]
    assert "淘宝" in text and "T1001" in text


def test_tools_call_unknown_tool():
    server = MiniMcpServer()
    resp = _send(server, "tools/call", {"name": "nope", "arguments": {}})
    assert resp["error"]["code"] == -32602
    assert "Unknown tool" in resp["error"]["message"]


def test_tools_call_missing_required():
    server = MiniMcpServer()
    resp = _send(server, "tools/call", {"name": "query_order", "arguments": {}})
    assert resp["error"]["code"] == -32602
    assert "缺少必填参数" in resp["error"]["message"]


def test_parse_error():
    server = MiniMcpServer()
    resp = server.handle_line("{这不是JSON")[0]
    assert resp["error"]["code"] == -32700


def test_unknown_method():
    server = MiniMcpServer()
    resp = _send(server, "resources/list")
    assert resp["error"]["code"] == -32601

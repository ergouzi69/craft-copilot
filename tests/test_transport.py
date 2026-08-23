"""传输层测试：RPC 信封路由（mock 服务层，不依赖 LLM/DB 实际数据）

验证点（对应 craft R12"统一 RPC 抽象"）：
- chat.reply 请求 → chat.reply.result 响应（req_id 对应）
- action.confirm → action.confirm.result
- session.list → session.list.result
- 缺字段/未知 type → error 响应（不静默）
- 路由只做包装，不写业务（注入 mock 验证调用）
"""

import pytest

from app.transport import handle_message
from app.protocol import REQ_CHAT_REPLY, REQ_ACTION_CONFIRM, REQ_SESSION_LIST
import app.store.db as db


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    """独立临时库（避免测试间 DB 污染）"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    yield


def fake_reply(buyer, buyer_message):
    return {"session_id": 1, "suggestion": "OK", "tool_results": [], "pending_actions": [], "calls": 1}


def fake_confirm(action_id, approve):
    return {"ok": True, "result": "已执行"}


def fake_list():
    return [{"id": 1, "buyer": "张三"}]


def test_chat_reply_routing():
    req = {"type": REQ_CHAT_REPLY, "req_id": "1", "payload": {"buyer": "张三", "buyer_message": "T1001 到哪了"}}
    resps = handle_message(req, reply_fn=fake_reply)
    assert len(resps) == 1
    assert resps[0]["type"] == "chat.reply.result"
    assert resps[0]["req_id"] == "1"                      # req_id 对应
    assert resps[0]["payload"]["suggestion"] == "OK"


def test_confirm_routing():
    req = {"type": REQ_ACTION_CONFIRM, "req_id": "2", "payload": {"action_id": 1, "approve": True}}
    resps = handle_message(req, confirm_fn=fake_confirm)
    assert resps[0]["type"] == "action.confirm.result"
    assert resps[0]["payload"]["ok"] is True


def test_session_list_routing():
    req = {"type": REQ_SESSION_LIST, "req_id": "3", "payload": {}}
    resps = handle_message(req)
    assert resps[0]["type"] == "session.list.result"
    assert isinstance(resps[0]["payload"]["sessions"], list)


def test_missing_req_id_errors():
    resps = handle_message({"type": REQ_CHAT_REPLY, "payload": {}})
    assert resps[0]["type"] == "error"
    assert "req_id" in resps[0]["payload"]["message"]


def test_unknown_type_errors():
    req = {"type": "nope", "req_id": "9", "payload": {}}
    resps = handle_message(req)
    assert resps[0]["type"] == "error"
    assert "未知 type" in resps[0]["payload"]["message"]


def test_missing_buyer_errors():
    req = {"type": REQ_CHAT_REPLY, "req_id": "1", "payload": {"buyer_message": "hi"}}
    resps = handle_message(req, reply_fn=fake_reply)
    assert resps[0]["type"] == "error"


def test_ws_endpoint_roundtrip():
    """端到端：ws 连接 → 发信封 → 收响应（TestClient，mock 服务层）"""
    from fastapi.testclient import TestClient
    from app.server import app
    import app.transport as transport
    transport.reply_fn = fake_reply      # 注入（测试用）

    client = TestClient(app)
    with client.websocket_connect("/ws/copilot") as ws:
        ws.send_json({"type": REQ_CHAT_REPLY, "req_id": "7", "payload": {"buyer": "张三", "buyer_message": "hi"}})
        d = ws.receive_json()
        assert d["type"] == "chat.reply.result"
        assert d["req_id"] == "7"

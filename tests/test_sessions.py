"""服务层测试：会话落库 + 操作确认状态机（不依赖真实 LLM/API）

验证点（对应 30 题第 5-7/16 题）：
- reply 落库：user/assistant 消息进库，会话可查
- 多轮：同一 buyer 复用会话（历史上下文）
- risky 操作落 pending：reply 返回带 id 的 pending_actions
- confirm approve：状态 → approved，且真执行工具
- confirm reject：状态 → rejected
- confirm 已处理的操作：拒绝重复
"""

import pytest

import app.store.db as db
from app.services.sessions import reply, confirm
from app.agent.loop import run_agent_turn


# 假 agent：固定返回（可注入特定结果）
def make_fake_agent(suggestion="好的，已为您查询。", pending=None):
    def fake(buyer_message, registry, history=None):
        return {
            "suggestion": suggestion,
            "tool_results": ["[淘宝] 订单 T1001 已发货"],
            "pending_actions": pending or [],
            "calls": 2,
        }
    return fake


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    """每个测试用独立临时库，互不污染"""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    yield


def test_reply_persists_messages():
    r = reply("买家A", "T1001 到哪了？", agent=make_fake_agent())
    msgs = db.get_messages(r["session_id"])
    assert msgs[0]["role"] == "user" and "T1001" in msgs[0]["content"]
    assert msgs[-1]["role"] == "assistant"


def test_same_buyer_reuses_session():
    r1 = reply("买家B", "第一条", agent=make_fake_agent())
    r2 = reply("买家B", "第二条", agent=make_fake_agent())
    assert r1["session_id"] == r2["session_id"]      # 同一 buyer → 同一会话
    assert len(db.get_messages(r1["session_id"])) == 4   # 2 user + 2 assistant


def test_risky_action_goes_to_pending():
    r = reply("买家C", "退款 T1001",
              agent=make_fake_agent(pending=[{"tool": "refund_order", "args": {"order_id": "T1001", "amount": "89"}}]))
    assert len(r["pending_actions"]) == 1
    assert "id" in r["pending_actions"][0]
    pendings = db.get_pending_actions(r["session_id"])
    assert len(pendings) == 1 and pendings[0]["status"] == "pending"


def test_confirm_approve_executes():
    r = reply("买家D", "退款 T1001",
              agent=make_fake_agent(pending=[{"tool": "refund_order", "args": {"order_id": "T1001", "amount": "89"}}]))
    aid = r["pending_actions"][0]["id"]
    res = confirm(aid, approve=True)
    assert res["ok"] is True
    assert "退款" in res["result"]                    # 工具真执行了（返回模拟结果）
    assert db.get_actions(r["session_id"])[0]["status"] == "approved"


def test_confirm_reject():
    r = reply("买家E", "退款 T1001",
              agent=make_fake_agent(pending=[{"tool": "refund_order", "args": {"order_id": "T1001", "amount": "89"}}]))
    aid = r["pending_actions"][0]["id"]
    res = confirm(aid, approve=False)
    assert res["ok"] is False
    assert db.get_actions(r["session_id"])[0]["status"] == "rejected"


def test_confirm_twice_rejected():
    r = reply("买家F", "退款 T1001",
              agent=make_fake_agent(pending=[{"tool": "refund_order", "args": {"order_id": "T1001", "amount": "89"}}]))
    aid = r["pending_actions"][0]["id"]
    confirm(aid, approve=True)
    res = confirm(aid, approve=True)                  # 已处理，拒绝重复
    assert res["ok"] is False and "不存在或已处理" in res["result"]

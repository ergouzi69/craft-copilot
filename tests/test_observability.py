"""可观测与评测测试：usage 埋点落库 / stats 计算 / 采纳率

验证点（对应好项目标准 5 + 30 题第 21 题）：
- reply 后 usage 表有记录（token/耗时/模型）
- 流式 reply 同样落 usage
- session_stats / global_stats 计算正确
- adoption_stats：采纳率 = approved / total
- 成本估算存在（标注为估算，不吹精确）
"""

import pytest

import app.store.db as db
from app.services.sessions import reply, reply_stream
from app.agent.loop import run_agent_turn


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "o.db")
    db.init_db()
    yield


def fake_agent(buyer_message, registry, history=None, system=None):
    """返回带 usage 的假 agent（模拟真实埋点数据）"""
    return {
        "suggestion": "OK", "tool_results": [], "pending_actions": [],
        "tools_used": [], "calls": 2,
        "usage": [
            {"model": "mock-model", "prompt_tokens": 100, "completion_tokens": 50,
             "total_tokens": 150, "duration_ms": 300},
            {"model": "mock-model", "prompt_tokens": 120, "completion_tokens": 60,
             "total_tokens": 180, "duration_ms": 400},
        ],
    }


def fake_agent_stream(buyer_message, registry, history=None, system=None):
    yield {"type": "status", "text": "识别中"}
    yield {"type": "delta", "text": "你"}
    yield {"type": "done", "suggestion": "你好", "tool_results": [], "pending_actions": [],
           "tools_used": [], "calls": 1,
           "usage": [{"model": "mock-model", "prompt_tokens": 10, "completion_tokens": 5,
                      "total_tokens": 15, "duration_ms": 200}]}


def test_reply_writes_usage():
    r = reply("观测买家", "T1001 到哪了", agent=fake_agent)
    rows = db.get_conn().execute("SELECT * FROM usage").fetchall()
    assert len(rows) == 2                    # 两次调用都落库
    assert rows[0]["total_tokens"] == 150
    assert rows[0]["duration_ms"] == 300
    assert rows[0]["session_id"] == r["session_id"]


def test_reply_stream_writes_usage():
    list(reply_stream("观测买家2", "hi", agent=fake_agent_stream))
    rows = db.get_conn().execute("SELECT * FROM usage").fetchall()
    assert len(rows) == 1
    assert rows[0]["total_tokens"] == 15


def test_session_stats():
    reply("观测买家3", "hi", agent=fake_agent)
    s = db.session_stats(1)
    assert s["calls"] == 2
    assert s["total_tokens"] == 330          # 150 + 180
    assert s["total_duration_ms"] == 700


def test_global_stats():
    reply("观测买家4", "hi", agent=fake_agent)
    g = db.global_stats()
    assert g["calls"] == 2
    assert g["total_tokens"] == 330
    assert g["sessions"] == 1
    assert g["est_cost_cny"] > 0             # 成本估算存在
    assert "估算" in g["note"]               # 诚实标注


def test_adoption_stats():
    reply("观测买家5", "hi", agent=fake_agent)
    assert db.adoption_stats()["total_actions"] == 0   # 无操作时

    # 模拟一次确认流程
    from app.services.sessions import confirm
    r = reply("观测买家6", "退款 T1001",
              agent=lambda msg, reg, history=None, system=None: {
                  "suggestion": "OK", "tool_results": [], "calls": 1,
                  "tools_used": ["refund_order"], "usage": [],
                  "pending_actions": [{"tool": "refund_order", "args": {"order_id": "T1001", "amount": "89"}}]})
    aid = r["pending_actions"][0]["id"]
    assert db.adoption_stats()["pending"] == 1

    confirm(aid, approve=True)
    stats = db.adoption_stats()
    assert stats["approved"] == 1
    assert stats["adoption_rate"] == 1.0     # 1/1 采纳


def test_api_stats_endpoint():
    from fastapi.testclient import TestClient
    from app.server import app
    client = TestClient(app)
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert "usage" in r.json() and "adoption" in r.json()

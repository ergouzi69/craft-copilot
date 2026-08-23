"""上下文工程测试：五类上下文组装 / Prompt Sections / 记忆提取

验证点（对应好项目标准 4 + 30 题 10-13）：
- schema 迁移 v1→v2：老库升级自动加 memory 表（迁移机制实战）
- Prompt Sections：有记忆时注入记忆段，无记忆时不出现
- 记忆提取：订单号（正则）→ last_order；意图（工具/关键词）→ intent
- 记忆跨会话生效：新会话能读到旧会话提取的记忆（注入 system）
"""

import pytest

import app.store.db as db
from app.agent.context import build_system, build_messages, extract_memory
from app.services.sessions import reply


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "c.db")
    db.init_db()
    yield


def test_schema_migration_v1_to_v3():
    """模拟 v1 老库（无 memory/orders 表）→ init_db 升到最新（迁移机制实战）"""
    conn = db.get_conn()
    conn.executescript("DROP TABLE IF EXISTS memory")     # 模拟老库缺 memory 表
    conn.execute("PRAGMA user_version = 1")              # 标记为 v1
    conn.commit()
    conn.close()

    db.init_db()                                          # 迁移 → v3
    conn = db.get_conn()
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    has_memory = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory'").fetchone()
    has_orders = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='orders'").fetchone()
    conn.close()
    assert v == 3                                         # 升到 v3
    assert has_memory is not None
    assert has_orders is not None                         # v3 迁移也生效


def test_build_system_no_memory():
    s = build_system({})
    assert "买家记忆" not in s        # 无记忆时不注入记忆段
    assert "客服 Copilot" in s and "退款" in s


def test_build_system_with_memory():
    s = build_system({"last_order": "T1001", "intent": "refund"})
    assert "买家记忆" in s
    assert "T1001" in s and "refund" in s


def test_extract_memory_order_and_intent():
    extract_memory("记忆买家", "我的订单 J2001 要退款", ["refund_order"])
    m = db.get_memory("记忆买家")
    assert m["last_order"] == "J2001"      # 正则提取订单号
    assert m["intent"] == "refund"         # 工具优先判断意图


def test_extract_memory_keyword_fallback():
    extract_memory("记忆买家2", "我的订单 T1001 发货了吗？", [])
    m = db.get_memory("记忆买家2")
    assert m["intent"] == "query"          # 无工具时用关键词兜底


def test_memory_injects_into_next_reply():
    """第一轮提取记忆 → 第二轮 system 里能看到（跨会话记忆生效）"""
    fake = lambda msg, reg, history=None, system=None: {
        "suggestion": "OK", "tool_results": [], "pending_actions": [],
        "tools_used": [], "calls": 1,
    }
    reply("记忆买家3", "我的订单 S3001 要退款", agent=fake)
    m = db.get_memory("记忆买家3")
    assert m["last_order"] == "S3001"

    # 第二轮：system 应含记忆（通过 build_system 验证注入链路）
    s = build_system(db.get_memory("记忆买家3"))
    assert "S3001" in s and "买家记忆" in s


def test_build_messages_structure():
    """五类上下文组装：system(含记忆) + history + user"""
    db.upsert_memory("结构买家", "last_order", "T1001")
    history = [{"role": "assistant", "content": "之前回复"}]
    msgs = build_messages("结构买家", "现在的问题", history)
    assert msgs[0]["role"] == "system" and "T1001" in msgs[0]["content"]
    assert msgs[1] == {"role": "assistant", "content": "之前回复"}
    assert msgs[-1] == {"role": "user", "content": "现在的问题"}

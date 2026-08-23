"""服务层：会话服务（把 Agent 结果落库 + 操作确认）

对应 craft-agents-oss 的 server-core/src/sessions/SessionManager.ts
和 30 题第 5-7 题（记忆外化：跨会话不丢状态，靠落盘不靠模型记忆）。

职责：
- create/reply：买家消息 → 会话 → Agent 循环 → 落库（user 消息/assistant 建议/usage 埋点/risky 操作落 pending）
- confirm：客服确认/拒绝 pending 操作（人机协同的"人"这一环）
- 状态机：pending → approved（真执行）/ rejected（拒绝）
"""

from typing import Callable

import app.store.db as db
from app.tools.builtin import build_registry
from app.agent.loop import run_agent_turn

_registry = build_registry()


def reply(buyer: str, buyer_message: str, agent: Callable = run_agent_turn) -> dict:
    """完整一轮：落库 + Agent + 落库。返回给上层（HTTP/WS）的结果"""
    session_id = db.get_or_create_session(buyer)
    db.add_message(session_id, "user", buyer_message)

    # 历史消息 → 上下文（多轮会话，Phase 6 会升级成五类上下文）
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in db.get_messages(session_id, limit=20)[:-1]   # 排除刚插入的这条
    ]

    result = agent(buyer_message, _registry, history=history)

    # 落库：建议 + 埋点
    db.add_message(session_id, "assistant", result["suggestion"])
    if result["calls"]:
        # 埋点简化：calls 次数已记录在 usage 的调用细节中（由循环层逐次埋点更细，Phase 7 强化）
        pass

    # risky 操作落 pending（循环层只返回提议，这里落库 + 带 id 返回）
    pending_with_id = []
    for p in result["pending_actions"]:
        aid = db.add_action(session_id, p["tool"], p["args"], "pending")
        pending_with_id.append({"id": aid, **p})

    return {
        "session_id": session_id,
        "suggestion": result["suggestion"],
        "tool_results": result["tool_results"],
        "pending_actions": pending_with_id,
        "calls": result["calls"],
    }


def confirm(action_id: int, approve: bool) -> dict:
    """客服确认/拒绝高危操作。approve=True → 真执行工具"""
    import json

    conn = db.get_conn()
    row = conn.execute(
        "SELECT id, tool, args FROM actions WHERE id=? AND status='pending'",
        (action_id,),
    ).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "result": f"操作 #{action_id} 不存在或已处理"}

    args = json.loads(row["args"])

    if approve:
        tool = _registry.get(row["tool"])
        result = tool.execute(args) if tool else f"工具不存在: {row['tool']}"
        db.update_action_status(action_id, "approved")
        conn.close()
        return {"ok": True, "result": result}

    db.update_action_status(action_id, "rejected")
    conn.close()
    return {"ok": False, "result": f"已拒绝操作 #{action_id}"}

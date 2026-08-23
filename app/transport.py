"""传输层：WebSocket 消息路由（信封 → 服务层 → 信封）

对应 craft-agents-oss 的 transport（RPC server/handlers）。

职责：
- 接收客户端请求信封
- 按 type 路由到服务层（chat.reply → services.reply；action.confirm → services.confirm）
- 把服务层结果包装成响应信封
- 未知 type / 协议错误 → error 响应（不静默）

流式：chat.reply 带 payload.stream=true → 走 reply_stream，返回多条帧（status/delta/done）。
handle_message 返回迭代器（可能是生成器），ws 端点 for 循环逐帧发送。

本层不写业务逻辑——只有"路由 + 包装"（对齐 craft 的 handlers 层）
"""

from typing import Callable, Iterable

from app.protocol import (
    parse_request, response, error_response,
    REQ_CHAT_REPLY, REQ_ACTION_CONFIRM, REQ_SESSION_LIST, REQ_SESSION_HISTORY,
    RES_CHAT_RESULT, RES_ACTION_RESULT, RES_SESSION_LIST, RES_SESSION_HISTORY,
    RPCError,
)
import app.services.sessions as sessions
import app.store.db as db


def handle_message(raw: dict, reply_fn: Callable = sessions.reply,
                   confirm_fn: Callable = sessions.confirm,
                   reply_stream_fn: Callable = sessions.reply_stream) -> Iterable[dict]:
    """处理一条请求消息，返回 0..N 条响应（迭代器；流式请求返回生成器）。
    reply_fn/confirm_fn 可注入（测试用 mock）。"""
    try:
        rtype, req_id, payload = parse_request(raw)
    except RPCError as e:
        return [error_response(str(raw.get("req_id", "")), str(e))]

    if rtype == REQ_CHAT_REPLY:
        buyer = payload.get("buyer", "")
        message = payload.get("buyer_message", "")
        if not buyer or not message:
            return [error_response(req_id, "payload 需要 buyer 和 buyer_message")]
        if payload.get("stream"):
            # 流式：生成器逐帧发（status/delta/done）
            return _stream_frames(reply_stream_fn, buyer, message, req_id)
        result = reply_fn(buyer, message)
        return [response(RES_CHAT_RESULT, req_id, result)]

    if rtype == REQ_ACTION_CONFIRM:
        action_id = payload.get("action_id")
        approve = payload.get("approve")
        if action_id is None or approve is None:
            return [error_response(req_id, "payload 需要 action_id 和 approve")]
        result = confirm_fn(int(action_id), bool(approve))
        return [response(RES_ACTION_RESULT, req_id, result)]

    if rtype == REQ_SESSION_LIST:
        return [response(RES_SESSION_LIST, req_id, {"sessions": db.list_sessions()})]

    if rtype == REQ_SESSION_HISTORY:
        buyer = payload.get("buyer", "")
        if not buyer:
            return [error_response(req_id, "payload 需要 buyer")]
        sid = db.get_session_by_buyer(buyer)
        if sid is None:
            return [response(RES_SESSION_HISTORY, req_id, {"buyer": buyer, "messages": []})]
        return [response(RES_SESSION_HISTORY, req_id, {"buyer": buyer, "messages": db.get_messages(sid)})]

    return [error_response(req_id, f"未知 type: {rtype}")]


def _stream_frames(reply_stream_fn, buyer: str, message: str, req_id: str):
    """把 reply_stream 的事件帧包装成 RPC 响应（req_id 带回去，客户端能对应）"""
    for ev in reply_stream_fn(buyer, message):
        if ev["type"] == "status":
            yield response("chat.status", req_id, {"text": ev["text"]})
        elif ev["type"] == "delta":
            yield response("chat.delta", req_id, {"text": ev["text"]})
        elif ev["type"] == "done":
            yield response("chat.done", req_id, {
                "suggestion": ev.get("suggestion", ""),
                "tool_results": ev.get("tool_results", []),
                "pending_actions": ev.get("pending_actions", []),
                "session_id": ev.get("session_id"),
            })

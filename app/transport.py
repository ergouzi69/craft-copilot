"""传输层：WebSocket 消息路由（信封 → 服务层 → 信封）

对应 craft-agents-oss 的 transport（RPC server/handlers）。

职责：
- 接收客户端请求信封
- 按 type 路由到服务层（chat.reply → services.reply；action.confirm → services.confirm）
- 把服务层结果包装成响应信封
- 未知 type / 协议错误 → error 响应（不静默）

本层不写业务逻辑——只有"路由 + 包装"（对齐 craft 的 handlers 层）
"""

from typing import Callable

from app.protocol import (
    parse_request, response, error_response,
    REQ_CHAT_REPLY, REQ_ACTION_CONFIRM, REQ_SESSION_LIST,
    RES_CHAT_RESULT, RES_ACTION_RESULT, RES_SESSION_LIST,
    RPCError,
)
import app.services.sessions as sessions
import app.store.db as db


def handle_message(raw: dict, reply_fn: Callable = sessions.reply,
                   confirm_fn: Callable = sessions.confirm) -> list[dict]:
    """处理一条请求消息，返回 0..N 条响应（当前同步版：恰好 1 条）。
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

    return [error_response(req_id, f"未知 type: {rtype}")]

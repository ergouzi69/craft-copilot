"""传输层协议：RPC 信封（type / req_id / channel / payload）

对应 craft-agents-oss 的 shared/src/protocol（RPC channel + DTO + 路由规则）。

为什么需要信封（面试可讲，对齐 craft R12"统一 RPC 抽象"）：
1. req_id：响应能对应到请求——一个连接可并发多个请求，不会乱
2. type：一个连接处理所有业务（chat/action/session）——统一 channel，多端复用
3. payload：业务数据与信封分离——DTO 清晰，传输层不知道业务

消息形态：
  请求   {type:"chat.reply", req_id:"1", payload:{buyer, buyer_message}}
  响应   {type:"chat.reply.result", req_id:"1", payload:{...}}
  流式   {type:"chat.delta", req_id:"1", payload:{text}}   ← 打字机中间帧
  完成   {type:"chat.done", req_id:"1", payload:{...}}     ← 终帧
"""

# ---- type 常量（请求） ----
REQ_CHAT_REPLY = "chat.reply"            # 买家消息 → Agent 回复
REQ_ACTION_CONFIRM = "action.confirm"    # 客服确认/拒绝操作
REQ_SESSION_LIST = "session.list"        # 会话列表

# ---- type 常量（响应/推送） ----
RES_CHAT_RESULT = "chat.reply.result"
RES_ACTION_RESULT = "action.confirm.result"
RES_SESSION_LIST = "session.list.result"
RES_ERROR = "error"                      # 通用错误


class RPCError(Exception):
    """协议层错误（缺字段/未知类型）"""


def parse_request(raw: dict) -> tuple[str, str, dict]:
    """校验并拆解请求信封 → (type, req_id, payload)。
    不符合协议直接抛 RPCError（传输层转成 error 响应）。"""
    if not isinstance(raw, dict):
        raise RPCError("消息必须是 JSON 对象")
    rtype = raw.get("type")
    req_id = raw.get("req_id")
    payload = raw.get("payload")
    if not isinstance(rtype, str):
        raise RPCError("缺少 type")
    if not isinstance(req_id, str):
        raise RPCError("缺少 req_id（字符串）")
    if not isinstance(payload, dict):
        raise RPCError("缺少 payload（对象）")
    return rtype, req_id, payload


def response(rtype: str, req_id: str, payload: dict) -> dict:
    """构造响应信封（type 由请求决定 + 约定后缀）"""
    return {"type": rtype, "req_id": req_id, "payload": payload}


def error_response(req_id: str, message: str) -> dict:
    return {"type": RES_ERROR, "req_id": req_id, "payload": {"message": message}}


def delta_frame(req_id: str, text: str) -> dict:
    """流式中间帧（打字机用；Phase 5 客户端配套）"""
    return {"type": "chat.delta", "req_id": req_id, "payload": {"text": text}}


def done_frame(req_id: str, suggestion: str) -> dict:
    """流式终帧"""
    return {"type": "chat.done", "req_id": req_id, "payload": {"suggestion": suggestion}}

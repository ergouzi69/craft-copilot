"""上下文工程：五类上下文的显式区分与组装

对应好项目标准 4"上下文工程"和 learn cc s10（Prompt Sections）、30 题 10-13。
这是 customer-copilot 没做的重点——这里把它做透。

五类上下文（好项目文档原文）：
1. 当前任务上下文：本轮目标、约束、输入数据
2. 会话上下文：当前对话中的关键结论（历史消息）
3. 用户记忆：用户偏好、历史选择、长期信息（memory 表）
4. 工具上下文：工具返回结果、执行状态、错误信息（循环内维护，不进这里）
5. 全局知识：业务规则、政策（PROMPT_POLICY）

Prompt Sections（s10/MiniCode R04 落地）：
SYSTEM = 人设 + 工具规则 + [买家记忆] + 政策——分段拼装，按需注入
（记忆段只在有记忆时出现，避免空段浪费 token）
"""

import re

import app.store.db as db

# ---- Prompt Sections（每段独立，可单独讲解） ----

PROMPT_PERSONA = """你是电商客服 Copilot，帮助客服人员高效处理买家消息。
你的输出是给客服的回复建议（可直接复制发送给买家），并说明关键操作。"""

PROMPT_TOOLS = """规则：
1. 查订单/物流 → 调 query_order；退款 → 调 refund_order；不知道平台 → 调 list_sources
2. 工具结果必须如实采用，不要编造订单信息
3. 退款是高危操作：买家明确要求退款时，无论订单状态如何，【必须】调用 refund_order 提交申请，
   由客服最终确认执行——不要用文字回复代替调工具
4. 收到工具结果后，基于结果给客服一段可直接使用的回复建议
5. 如果工具查不到信息，诚实说明，不要编造"""

PROMPT_POLICY = """业务政策：
1. 退款必须走客服确认流程（Human-in-the-loop），AI 只提交申请
2. 订单号前缀 T=淘宝 / J=京东 / S=Shopify，识别错误会导致查不到单
3. 配送中的订单退款需提醒客服谨慎处理，但买家确认后仍要提交申请"""


def build_system(memory: dict[str, str]) -> str:
    """组装 SYSTEM（Prompt Sections 按需拼装：记忆段只在有时注入）"""
    sections = [PROMPT_PERSONA, PROMPT_TOOLS]
    if memory:
        lines = "\n".join(f"- {k}: {v}" for k, v in memory.items())
        sections.append(f"买家记忆（来自历史会话，请参考）：\n{lines}")
    sections.append(PROMPT_POLICY)
    return "\n\n".join(sections)


def build_messages(buyer: str, buyer_message: str, history: list[dict]) -> list[dict]:
    """组装完整 messages（五类上下文中：任务+会话+用户记忆+全局；工具在循环内）"""
    memory = db.get_memory(buyer)              # ③ 用户记忆
    system = build_system(memory)              # ⑤ 全局知识 + ③
    messages: list[dict] = [{"role": "system", "content": system}]
    messages.extend(history)                   # ② 会话上下文
    messages.append({"role": "user", "content": buyer_message})   # ① 当前任务
    return messages


# ---- 记忆提取（规则版：从消息里提取订单号等关键事实） ----

ORDER_RE = re.compile(r"[TJS]\d{3,4}")         # T1001 / J2001 / S3001

INTENT_KEYWORDS = {
    "refund": ["退款", "退钱", "退货", "取消订单"],
    "query": ["到哪", "发货", "物流", "查", "在哪"],
}


def extract_memory(buyer: str, message: str, tool_names: list[str] | None = None) -> None:
    """从买家消息提取关键事实存入记忆：
    - 订单号（正则）→ last_order
    - 意图（关键词/tool）→ intent
    """
    order = ORDER_RE.search(message)
    if order:
        db.upsert_memory(buyer, "last_order", order.group())

    # 意图：优先用工具判断（真实执行了查单/退款），其次关键词
    intent = ""
    if tool_names:
        if "refund_order" in tool_names:
            intent = "refund"
        elif "query_order" in tool_names:
            intent = "query"
    if not intent:
        for name, kws in INTENT_KEYWORDS.items():
            if any(k in message for k in kws):
                intent = name
                break
    if intent:
        db.upsert_memory(buyer, "intent", intent)

"""Agent 层：runAgentTurn 主循环（对应 craft 的 base-agent / 30 题第 1-2 题）

核心循环（Observe-Reason-Act）：
  messages → LLM → 有 tool_calls? → 执行/拦截 → 回填 → 再来
                  └─ 无 tool_calls → 最终建议，终止

可靠性机制（30 题第 2 题"怎么让 Agent 可靠"的落地）：
1. 终止检查：LLM 不再调工具才算完成（防"说过早完成"）
2. 最大轮数：MAX_TURNS 防死循环（s05 踩过的坑）
3. risky 工具拦截：LLM 只能提议，不执行（人机协同）——pending 通过返回值交给上层
4. 工具结果强制回填：LLM 必须看到工具真实结果再继续（不能自己编）
5. 错误兜底：LLM 调用失败 → 返回可读错误（不静默）

本层不落库、不感知 HTTP——纯净的 Agent 逻辑，可单测（注入 mock LLM）。
"""

import json
from typing import Callable

from app.tools.registry import ToolRegistry
from app.llm import call_chat, LLMError

MAX_TURNS = 8   # 最多 8 轮（防死循环；真实场景 2-4 轮足够）

# SYSTEM prompt：Agent 的"人设 + 规则"（Phase 6 会升级为 Prompt Sections）
SYSTEM = """你是电商客服 Copilot，帮助客服人员高效处理买家消息。
规则：
1. 查订单/物流 → 调 query_order；退款 → 调 refund_order；不知道平台 → 调 list_sources
2. 工具结果必须如实采用，不要编造订单信息
3. 退款是高危操作：买家明确要求退款时，无论订单状态如何，【必须】调用 refund_order 提交申请，
   由客服最终确认执行——不要用文字回复代替调工具
4. 收到工具结果后，基于结果给客服一段可直接使用的回复建议
5. 如果工具查不到信息，诚实说明，不要编造
"""


def _parse_tool_call(call: dict) -> tuple[str, dict]:
    """解析 LLM 返回的 tool_call（函数名 + 参数 JSON）"""
    fn = call.get("function", {})
    name = fn.get("name", "")
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {}
    return name, args


def run_agent_turn(
    buyer_message: str,
    registry: ToolRegistry,
    llm: Callable = call_chat,
    system: str = SYSTEM,
    history: list[dict] | None = None,
) -> dict:
    """执行一个完整的 Agent 轮次，返回:
    {
      "suggestion": str,           # 最终建议（LLM 纯文本收尾）
      "tool_results": list[str],   # 已执行工具的结果
      "pending_actions": list[dict], # 待确认的高危操作（risky 拦截）
      "calls": int,                # LLM 调用次数（可观测）
    }
    """
    messages: list[dict] = [{"role": "system", "content": system}]
    if history:                      # 会话上下文（多轮）
        messages.extend(history)
    messages.append({"role": "user", "content": buyer_message})

    tool_results: list[str] = []
    pending_actions: list[dict] = []
    suggestion = ""
    calls = 0

    for _ in range(MAX_TURNS):
        try:
            resp, _meta = llm(messages, tools=registry.schemas())
        except LLMError as e:
            return {
                "suggestion": f"⚠️ LLM 调用失败: {e}",
                "tool_results": tool_results,
                "pending_actions": pending_actions,
                "calls": calls,
            }
        calls += 1
        msg = resp["choices"][0]["message"]

        # 终止检查：没有 tool_calls = LLM 收尾，给最终建议
        if not msg.get("tool_calls"):
            suggestion = (msg.get("content") or "").strip()
            break

        for call in msg["tool_calls"]:
            name, args = _parse_tool_call(call)
            tool = registry.get(name)
            if not tool:
                tool_text = f"工具不存在: {name}"
            elif tool.risky:
                # 权限关卡：高危工具不执行 → 交给上层（服务层）落 pending
                pending_actions.append({"tool": name, "args": args})
                tool_text = f"退款申请已提交（待客服确认 #{len(pending_actions)}）"
            else:
                tool_text = registry.execute(name, args)
                tool_results.append(tool_text)

            # 回填：LLM 必须看到工具真实结果
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [call],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": tool_text,
            })

    # 超轮数兜底（正常不该到这）
    if not suggestion:
        suggestion = "⚠️ 处理轮数过多已停止，请尝试更具体的描述。"

    return {
        "suggestion": suggestion,
        "tool_results": tool_results,
        "pending_actions": pending_actions,
        "calls": calls,
    }

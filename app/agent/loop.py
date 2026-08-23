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

上下文组装（Prompt Sections）在 agent/context.py——本层只负责循环，
system 默认用 build_system({})（无记忆时），有记忆由服务层注入。
"""

import json
from typing import Callable

from app.tools.registry import ToolRegistry
from app.llm import call_chat, call_chat_stream, LLMError
from app.agent.context import build_system

MAX_TURNS = 8   # 最多 8 轮（防死循环；真实场景 2-4 轮足够）


def _parse_tool_call(call: dict) -> tuple[str, dict]:
    """解析 LLM 返回的 tool_call（函数名 + 参数 JSON）"""
    fn = call.get("function", {})
    name = fn.get("name", "")
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {}
    return name, args


def _tool_loop(
    messages: list[dict],
    registry: ToolRegistry,
    llm: Callable,
) -> tuple[list[dict], list[str], list[dict], list[str], int, str]:
    """工具调用阶段：循环到 LLM 不再调工具（Observe-Reason-Act 前半）。
    返回 (messages, tool_results, pending_actions, tools_used, calls, suggestion_or_error)
    suggestion 非空 = 已收尾（无需再流式）；空 = 还需要生成建议。
    """
    tool_results: list[str] = []
    pending_actions: list[dict] = []
    tools_used: list[str] = []
    calls = 0

    for _ in range(MAX_TURNS):
        try:
            resp, _meta = llm(messages, tools=registry.schemas())
        except LLMError as e:
            return messages, tool_results, pending_actions, tools_used, calls, f"⚠️ LLM 调用失败: {e}"
        calls += 1
        msg = resp["choices"][0]["message"]

        # 终止检查：没有 tool_calls = LLM 收尾，给最终建议
        if not msg.get("tool_calls"):
            return messages, tool_results, pending_actions, tools_used, calls, (msg.get("content") or "").strip()

        for call in msg["tool_calls"]:
            name, args = _parse_tool_call(call)
            tool = registry.get(name)
            tools_used.append(name)
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
            messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": tool_text})

    # 超轮数兜底（正常不该到这）
    return messages, tool_results, pending_actions, tools_used, calls, "⚠️ 处理轮数过多已停止，请尝试更具体的描述。"


def run_agent_turn(
    buyer_message: str,
    registry: ToolRegistry,
    llm: Callable = call_chat,
    system: str | None = None,
    history: list[dict] | None = None,
) -> dict:
    """执行一个完整的 Agent 轮次，返回:
    {
      "suggestion": str,           # 最终建议（LLM 纯文本收尾）
      "tool_results": list[str],   # 已执行工具的结果
      "pending_actions": list[dict], # 待确认的高危操作（risky 拦截）
      "tools_used": list[str],     # 实际调用的工具名（记忆提取用）
      "calls": int,                # LLM 调用次数（可观测）
    }
    """
    if system is None:
        system = build_system({})    # 默认无记忆版（服务层注入有记忆版）

    messages: list[dict] = [{"role": "system", "content": system}]
    if history:                      # 会话上下文（多轮）
        messages.extend(history)
    messages.append({"role": "user", "content": buyer_message})

    messages, tool_results, pending_actions, tools_used, calls, suggestion = _tool_loop(
        messages, registry, llm)

    return {
        "suggestion": suggestion,
        "tool_results": tool_results,
        "pending_actions": pending_actions,
        "tools_used": tools_used,
        "calls": calls,
    }


def run_agent_turn_stream(
    buyer_message: str,
    registry: ToolRegistry,
    llm: Callable = call_chat,
    stream_fn: Callable = call_chat_stream,
    system: str | None = None,
    history: list[dict] | None = None,
):
    """流式版：工具阶段同步（快）→ 建议阶段流式（打字机）。
    yield 事件字典：{"type":"status",...} / {"type":"delta",...} / {"type":"done",...}
    """
    if system is None:
        system = build_system({})

    messages: list[dict] = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": buyer_message})

    messages, tool_results, pending_actions, tools_used, calls, suggestion = _tool_loop(
        messages, registry, llm)

    # LLM 失败或超轮数：已经给建议（带警告），不流式
    if suggestion.startswith("⚠️"):
        yield {"type": "done", "suggestion": suggestion, "tool_results": tool_results,
               "pending_actions": pending_actions, "tools_used": tools_used, "calls": calls}
        return

    # 建议阶段：无论工具阶段是否已收尾，都用流式重新生成建议
    # （工具结果已回填 messages；统一走 stream 保证打字机有 delta 素材）
    try:
        parts = []
        for delta in stream_fn(messages):
            parts.append(delta)
            yield {"type": "delta", "text": delta}
        full = "".join(parts) or suggestion   # 流式为空则用工具阶段收尾文本兜底
    except LLMError as e:
        full = f"⚠️ 流式生成失败: {e}"

    yield {"type": "done", "suggestion": full, "tool_results": tool_results,
           "pending_actions": pending_actions, "tools_used": tools_used, "calls": calls}

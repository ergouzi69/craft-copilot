"""Agent 循环测试：mock LLM 验证循环行为（不依赖真实 API）

验证点（对应 30 题第 1/2/18 题）：
- 纯文本收尾：LLM 不调工具 → 直接给建议
- 工具调用：LLM 调 query_order → 执行 → 回填 → 再收尾
- 权限拦截：risky 工具（refund）→ 不执行 → 进 pending
- 多轮：连续调工具（如先查单再退款）
- 防死循环：LLM 一直调工具 → MAX_TURNS 后兜底
- LLM 失败：抛 LLMError → 返回可读错误
"""

import pytest

from app.tools.builtin import build_registry
from app.agent.loop import run_agent_turn, MAX_TURNS
from app.llm import LLMError


def make_llm(script):
    """根据 script 依次返回预设响应的假 LLM。
    script: list of dict, 每个元素是 {text: "..."} 或 {tool_calls: [...]}
    """
    calls = {"n": 0}

    def fake_llm(messages, tools=None):
        idx = calls["n"]
        calls["n"] += 1
        step = script[min(idx, len(script) - 1)]
        if "tool_calls" in step:
            return {"choices": [{"message": {"content": None, "tool_calls": step["tool_calls"]}}]}, {}
        return {"choices": [{"message": {"content": step.get("text", ""), "tool_calls": None}}]}, {}

    return fake_llm


def tc(name, args, call_id="call_1"):
    """构造一个 tool_call 字典（模拟 LLM 返回格式）"""
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": __import__("json").dumps(args)}}


def test_plain_text_finish():
    llm = make_llm([{"text": "您好，请问有什么可以帮您？"}])
    r = run_agent_turn("你好", build_registry(), llm=llm)
    assert r["suggestion"] == "您好，请问有什么可以帮您？"
    assert r["calls"] == 1
    assert r["pending_actions"] == []


def test_query_order_executes():
    llm = make_llm([
        {"tool_calls": [tc("query_order", {"order_id": "T1001"})]},
        {"text": "订单已发货，顺丰明天到。"},
    ])
    r = run_agent_turn("T1001 到哪了？", build_registry(), llm=llm)
    assert "淘宝" in r["tool_results"][0]     # 工具真的执行了
    assert r["suggestion"].startswith("订单已发货")
    assert r["calls"] == 2


def test_refund_goes_to_pending():
    llm = make_llm([
        {"tool_calls": [tc("refund_order", {"order_id": "T1001", "amount": "89"})]},
        {"text": "已提交退款申请，等待确认。"},
    ])
    r = run_agent_turn("退款 T1001", build_registry(), llm=llm)
    assert r["pending_actions"] == [{"tool": "refund_order", "args": {"order_id": "T1001", "amount": "89"}}]
    assert r["tool_results"] == []             # risky 没执行，没进 tool_results
    assert r["calls"] == 2


def test_multi_tool_plan():
    """LLM 先查单再退款（多步规划，R2 的核心场景）"""
    llm = make_llm([
        {"tool_calls": [tc("query_order", {"order_id": "T1001"})]},
        {"tool_calls": [tc("refund_order", {"order_id": "T1001", "amount": "89"})]},
        {"text": "查询完毕，退款申请已提交。"},
    ])
    r = run_agent_turn("查一下 T1001 然后退款", build_registry(), llm=llm)
    assert len(r["tool_results"]) == 1         # query 执行了
    assert len(r["pending_actions"]) == 1      # refund 被拦
    assert r["calls"] == 3


def test_loop_terminates_on_infinite_tools():
    """LLM 每次都调工具（永不收尾）→ MAX_TURNS 后兜底，不死循环"""
    always = make_llm([{"tool_calls": [tc("query_order", {"order_id": "T1001"})]}])
    r = run_agent_turn("测试", build_registry(), llm=always)
    assert r["calls"] == MAX_TURNS
    assert "过多" in r["suggestion"]


def test_llm_error_returns_readable():
    def failing(messages, tools=None):
        raise LLMError("HTTP 429: rate limited")

    r = run_agent_turn("测试", build_registry(), llm=failing)
    assert "429" in r["suggestion"]
    assert r["calls"] == 0

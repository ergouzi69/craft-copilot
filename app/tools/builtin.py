"""内置工具：把 Sources 包成 Agent 可调用的 ToolDefinition 并注册

对应 craft-agents-oss 的 Source→Tool 转换（api-tools.ts 动态生成工具）
和 learn cc 的 s07 工具契约。核心：工具层 = Sources + 注册表 的组合。

- query_order：安全工具（直接执行）
- refund_order：高危工具（risky=True → LLM 只能提议，人确认才执行）
- list_sources：可发现性（告诉 LLM 有哪些平台）
"""

from app.tools.registry import ToolDefinition, ToolRegistry
from app.tools.sources import SourceRouter, DEFAULT_SOURCES

router = SourceRouter(DEFAULT_SOURCES)


def _query_order(order_id: str, source: str = "") -> str:
    return router.query(order_id, source or None)


def _refund_order(order_id: str, amount: str, source: str = "") -> str:
    return router.refund(order_id, amount, source or None)


def _list_sources() -> str:
    return f"可用数据源: {', '.join(router.source_names())}"


def build_registry() -> ToolRegistry:
    """构建工具注册表（动态注入：Source 变化 → 工具自动跟随）"""
    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="query_order",
        description="查询订单状态/物流信息。订单号前缀决定平台：T=淘宝 J=京东 S=Shopify。",
        parameters={
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号，如 T1001"},
                "source": {"type": "string", "description": "平台（可选，自动识别）"},
            },
            "required": ["order_id"],
        },
        handler=_query_order,
    ))
    reg.register(ToolDefinition(
        name="refund_order",
        description="发起退款申请。高风险操作，需要客服确认后才执行。",
        parameters={
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号"},
                "amount": {"type": "string", "description": "退款金额"},
                "source": {"type": "string", "description": "平台（可选）"},
            },
            "required": ["order_id", "amount"],
        },
        handler=_refund_order,
        risky=True,
    ))
    reg.register(ToolDefinition(
        name="list_sources",
        description="列出当前可用的数据源（平台）列表",
        parameters={"type": "object", "properties": {}},
        handler=_list_sources,
    ))
    return reg

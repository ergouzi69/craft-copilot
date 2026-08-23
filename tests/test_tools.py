"""工具层测试：注册表 / Source 路由 / 权限标记 / 参数校验

验证点（对应 30 题第 30 题"外部工具怎么接"）：
- 工具注册后可查、可执行、schema 可喂 LLM
- 前缀路由：T/J/S 自动识别平台，未知来源可提示
- 参数校验：缺必填参数返回错误，不炸
- risky 标记：refund_order 是 risky（权限关卡靠这个）
- Source 从 orders 表查单（v3 数据源）
"""

import pytest

from app.tools.registry import ToolRegistry, ToolDefinition
from app.tools.sources import SourceRouter, DEFAULT_SOURCES
from app.tools.builtin import build_registry
import app.store.db as db


@pytest.fixture(autouse=True)
def clean_db_with_orders(tmp_path, monkeypatch):
    """临时库 + seed 三平台各一单（Source 查库依赖）"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    db.seed_orders([
        {"order_id": "T1001", "source": "taobao", "product": "无线鼠标", "amount": 89.0,
         "status": "in_transit", "carrier": "顺丰速运", "tracking_no": "SF123", "eta": "明天 18:00 前"},
        {"order_id": "J2001", "source": "jd", "product": "显示器支架", "amount": 150.0,
         "status": "in_transit", "carrier": "京东物流", "tracking_no": "JD001", "eta": "今天 20:00 前"},
        {"order_id": "S3001", "source": "shopify", "product": "机械键盘", "amount": 499.0,
         "status": "shipped", "carrier": "UPS", "tracking_no": "UP001", "eta": "3 天内送达"},
    ])
    yield


def test_registry_register_and_get():
    reg = ToolRegistry()
    t = ToolDefinition("ping", "测试", {"type": "object", "properties": {}}, lambda: "pong")
    reg.register(t)
    assert reg.get("ping") is not None
    assert reg.execute("ping", {}) == "pong"


def test_registry_execute_unknown_tool():
    reg = ToolRegistry()
    assert "不存在" in reg.execute("nope", {})


def test_registry_validate_missing_required():
    reg = ToolRegistry()
    t = ToolDefinition(
        "need_arg", "测试", {"type": "object", "properties": {}, "required": ["x"]},
        lambda x: x,
    )
    reg.register(t)
    assert "缺少必填参数" in reg.execute("need_arg", {})


def test_builtin_registry_has_three_tools():
    reg = build_registry()
    names = [t.name for t in reg.list_tools()]
    assert set(names) == {"query_order", "refund_order", "list_sources"}


def test_refund_is_risky():
    reg = build_registry()
    assert reg.get("refund_order").risky is True
    assert reg.get("query_order").risky is False


def test_query_order_by_prefix():
    reg = build_registry()
    assert "淘宝" in reg.execute("query_order", {"order_id": "T1001"})
    assert "京东" in reg.execute("query_order", {"order_id": "J2001"})
    assert "Shopify" in reg.execute("query_order", {"order_id": "S3001"})


def test_query_unknown_source():
    reg = build_registry()
    out = reg.execute("query_order", {"order_id": "X9000"})
    assert "未知来源" in out and "可用" in out


def test_list_sources():
    reg = build_registry()
    out = reg.execute("list_sources", {})
    assert "taobao" in out and "jd" in out and "shopify" in out

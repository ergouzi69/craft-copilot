"""Sources 动态工厂（数据源适配层）

对应 craft-agents-oss 的 shared/src/sources/（storage、server-builder、api-tools）
和 learn cc 的 s19 Source 概念。核心：

- BaseSource：一个订单平台（淘宝/京东/Shopify）的统一接口
  query(order_id) / refund(order_id, amount) —— 平台差异藏在内部
- 订单号前缀路由：T→taobao, J→jd, S→shopify —— 系统自动识别平台（可发现性）
- 加新平台 = 注册一个 Source，业务代码不动（变更隔离）

数据来源（v3 升级）：从 orders 表查真实感数据（generate_data.py 生成 100+ 单），
不再写死——面试官随便报订单号都能查到，且换真实订单 API 只改 Source 内部实现。

"查不到就诚实说"（30 题防编造）：未找到订单返回明确文案，不让模型编。
"""

from typing import Optional

import app.store.db as db

# 状态 → 中文
STATUS_TEXT = {
    "pending": "待付款",
    "shipped": "已发货",
    "in_transit": "配送中",
    "delivered": "已签收",
}


def _fmt_order(order: dict, platform_cn: str) -> str:
    status = STATUS_TEXT.get(order["status"], order["status"])
    carrier = order.get("carrier", "") or ""
    tracking = order.get("tracking_no", "") or ""
    eta = order.get("eta", "") or ""
    parts = f"[{platform_cn}] 订单 {order['order_id']}（{order['product']}）{status}"
    if carrier:
        parts += f"，{carrier} {tracking}"
    if eta:
        parts += f"，预计 {eta}"
    if order["status"] == "pending":
        parts += f"，金额 ¥{order['amount']:.2f}（待付款）"
    return parts


class BaseSource:
    """数据源基类：平台差异统一在这里（接口固定，数据来自 orders 表/真实 API）"""

    name = "base"
    prefix = "?"
    platform_cn = "未知"

    def query(self, order_id: str) -> str:
        row = db.get_order(order_id)
        if not row:
            return f"[{self.platform_cn}] 未找到订单 {order_id}"
        return _fmt_order(row, self.platform_cn)

    def refund(self, order_id: str, amount: str) -> str:
        return f"[{self.platform_cn}] 订单 {order_id} 退款 ¥{amount} 已提交（模拟）"


class TaobaoSource(BaseSource):
    name = "taobao"
    prefix = "T"
    platform_cn = "淘宝"


class JDSource(BaseSource):
    name = "jd"
    prefix = "J"
    platform_cn = "京东"


class ShopifySource(BaseSource):
    name = "shopify"
    prefix = "S"
    platform_cn = "Shopify"


class SourceRouter:
    """按订单号前缀路由到对应 Source（订单号前缀 = 平台标记）"""

    def __init__(self, sources: list[BaseSource]):
        self._by_prefix = {s.prefix: s for s in sources}
        self._by_name = {s.name: s for s in sources}

    def resolve(self, order_id: str) -> Optional[BaseSource]:
        """根据订单号前缀找 Source；找不到返回 None（可提示可用列表）"""
        prefix = order_id[0].upper() if order_id else ""
        return self._by_prefix.get(prefix)

    def source_names(self) -> list[str]:
        return list(self._by_name.keys())

    def query(self, order_id: str, source: Optional[str] = None) -> str:
        """统一查单入口：指定 source 或按前缀自动路由"""
        src = self._by_name.get(source) if source else self.resolve(order_id)
        if not src:
            return f"未知来源（可用: {', '.join(self.source_names())}）"
        return src.query(order_id)

    def refund(self, order_id: str, amount: str, source: Optional[str] = None) -> str:
        src = self._by_name.get(source) if source else self.resolve(order_id)
        if not src:
            return f"未知来源（可用: {', '.join(self.source_names())}）"
        return src.refund(order_id, amount)


# 默认注册表（加新平台 = 在这里加一个 Source）
DEFAULT_SOURCES = [TaobaoSource(), JDSource(), ShopifySource()]

"""Sources 动态工厂（数据源适配层）

对应 craft-agents-oss 的 shared/src/sources/（storage、server-builder、api-tools）
和 learn cc 的 s19 Source 概念。核心：

- BaseSource：一个订单平台（淘宝/京东/Shopify）的统一接口
  query(order_id) / refund(order_id, amount) —— 平台差异藏在内部
- 订单号前缀路由：T→taobao, J→jd, S→shopify —— 系统自动识别平台（可发现性）
- 加新平台 = 注册一个 Source，业务代码不动（变更隔离）

这是"外部能力统一接入"的落地：Agent 层不认识任何平台，只认 BaseSource。
"""

from typing import Optional


class BaseSource:
    """数据源基类：平台差异统一在这里（接口固定，内部可换真实 API）"""

    name = "base"
    prefix = "?"

    def query(self, order_id: str) -> str:
        raise NotImplementedError

    def refund(self, order_id: str, amount: str) -> str:
        raise NotImplementedError


class TaobaoSource(BaseSource):
    name = "taobao"
    prefix = "T"

    def query(self, order_id: str) -> str:
        if order_id == "T1001":
            return "[淘宝] 订单 T1001（无线鼠标）已发货，顺丰 SF1234567890，预计明天 18:00 前送达"
        return f"[淘宝] 未找到订单 {order_id}"

    def refund(self, order_id: str, amount: str) -> str:
        return f"[淘宝] 订单 {order_id} 退款 ¥{amount} 已提交（模拟）"


class JDSource(BaseSource):
    name = "jd"
    prefix = "J"

    def query(self, order_id: str) -> str:
        if order_id == "J2001":
            return "[京东] 订单 J2001（显示器支架）配送中，京东物流 JD8899001，预计今天 20:00 前送达"
        return f"[京东] 未找到订单 {order_id}"

    def refund(self, order_id: str, amount: str) -> str:
        return f"[京东] 订单 {order_id} 退款 ¥{amount} 已提交（模拟）"


class ShopifySource(BaseSource):
    name = "shopify"
    prefix = "S"

    def query(self, order_id: str) -> str:
        if order_id == "S3001":
            return "[Shopify] 订单 S3001（机械键盘）已发货，UPS 1Z999AA1，预计 3 天内送达"
        return f"[Shopify] 未找到订单 {order_id}"

    def refund(self, order_id: str, amount: str) -> str:
        return f"[Shopify] 订单 {order_id} 退款 ¥{amount} 已提交（模拟）"


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

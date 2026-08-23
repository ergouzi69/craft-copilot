"""数据生成脚本：生成 100+ 真实感订单入库（解决"数据哪来的"短板）

用法：craft-copilot/.venv/Scripts/python.exe -m app.tools.generate_data

设计：
- 三平台商品池（淘宝/京东/Shopify 各自风格的商品名）
- 状态分布真实：待付款 20% / 已发货 20% / 配送中 40% / 已签收 20%
- 金额合理（几十到几千），物流按平台（顺丰/京东物流/UPS 等）
- 确定性随机（seed 固定）→ 每次生成结果一致，可复现（对齐 harness"环境可重现"）
- INSERT OR IGNORE：重复跑不重复插入
"""

import random

import app.store.db as db

random.seed(42)   # 固定种子：可复现

PRODUCTS = {
    "taobao": ["无线鼠标", "机械键盘", "手机壳", "蓝牙耳机", "保温杯", "数据线", "桌面收纳盒", "USB 小风扇"],
    "jd": ["27寸显示器", "激光打印机", "路由器", "人体工学椅", "固态硬盘", "机械键盘", "台灯", "空气净化器"],
    "shopify": ["机械键盘", "USB-C 扩展坞", "便携显示器", "手写板", "电容笔", "降噪耳机", "桌面支架", "人体工学鼠标"],
}

CARRIERS = {
    "taobao": ("顺丰速运", "中通快递"),
    "jd": ("京东物流", "顺丰速运"),
    "shopify": ("UPS", "DHL"),
}

STATUS_WEIGHTS = [("pending", 20), ("shipped", 20), ("in_transit", 40), ("delivered", 20)]


def _pick_status() -> str:
    pool: list[str] = []
    for st, w in STATUS_WEIGHTS:
        pool += [st] * w
    return random.choice(pool)


def _pick_eta(status: str) -> str:
    if status == "in_transit":
        return random.choice(["今天 18:00 前", "今天 20:00 前", "明天上午", "明天 18:00 前", "后天前"])
    if status == "shipped":
        return f"{random.randint(2, 4)} 天内送达"
    return ""


def generate(per_platform: int = 40) -> int:
    """生成三平台各 40 单（共 120），入库。返回实际插入数"""
    orders = []
    for source, prefix in (("taobao", "T"), ("jd", "J"), ("shopify", "S")):
        for i in range(1, per_platform + 1):
            status = _pick_status()
            order_id = f"{prefix}{1000 + i}"     # T1001, T1002, ... J1001, S1001...
            carrier, tracking = "", ""
            if status in ("shipped", "in_transit", "delivered"):
                carrier = random.choice(CARRIERS[source])
                tracking = carrier[:2].upper() + str(random.randint(10**9, 10**10 - 1))
            orders.append({
                "order_id": order_id,
                "source": source,
                "product": random.choice(PRODUCTS[source]),
                "amount": round(random.uniform(29, 3999), 2),
                "status": status,
                "carrier": carrier,
                "tracking_no": tracking,
                "eta": _pick_eta(status),
            })
    inserted = db.seed_orders(orders)
    print(f"生成 {len(orders)} 单，新插入 {inserted} 单；库内共 {db.count_orders()} 单")
    return inserted


if __name__ == "__main__":
    db.init_db()
    generate()
    # 抽查三条
    for oid in ("T1001", "J1050", "S1100"):
        row = db.get_order(oid)
        if row:
            from app.tools.sources import SourceRouter, DEFAULT_SOURCES
            print(SourceRouter(DEFAULT_SOURCES).query(oid))
        else:
            print(f"{oid} 未生成（序号超出范围）")

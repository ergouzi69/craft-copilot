"""买家人格画像生成脚本：用 LLM 生成 15 个不同人格的买家（配合记忆/会话演示）

用法：craft-copilot/.venv/Scripts/python.exe -m app.tools.generate_profiles

为什么用 LLM（用户建议的合理部分）：
- 拟人人格（暴躁/理性/老年/学生）是 LLM 强项，脚本编不出真实感
- 生成的是"非结构化"画像 + 历史对话，正好是 LLM 的用武之地
- 每次调用生成 5 个（3 批共 15 个），控制输出长度防截断

每个画像入库三处（记忆演示闭环）：
- buyer_profiles 表：画像描述（人格/偏好）
- messages 表：seed 历史消息（会话回放有内容）
- memory 表：last_order/intent（跨会话记忆立即生效）
"""

import json
import re

import app.store.db as db
from app.llm import call_chat, LLMError

BATCH = 5
TOTAL = 15

PROFILE_PROMPT = """你是电商平台的数据运营。请生成 {n} 个真实感的买家画像，只输出 JSON 数组，不要任何其他文字。
每个买家包含 6 个字段：
- buyer: 买家昵称（2-3 字中文，不要重复，不要用"张三李四"这种）
- personality: 人格标签（如：急躁型/价格敏感型/老年用户/学生党/大促囤货型/差评威胁型/理性型/佛系型）
- profile: 画像描述（40-70 字：年龄段/购物习惯/情绪特点/常见诉求）
- seed_history: 与该买家的历史对话摘要（40-70 字：曾咨询什么/对什么不满/上次结果）
- last_order: 该买家最近订单号（格式：T 或 J 或 S 开头 + 4 位数字，如 T1023）
- intent: 最近一次诉求（query=查物流 / refund=退款退货 / other=其他）
要求：人格尽量多样（至少 4 种不同人格），场景真实（查物流/催发货/要退款/改地址/开发票），订单号不要重复。"""


def _extract_json(text: str) -> list[dict]:
    """解析 LLM 输出（容错：剥离 markdown 代码块/前后文字）"""
    text = re.sub(r"```(?:json)?", "", text).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"输出中没有 JSON 数组: {text[:200]}")
    return json.loads(text[start:end + 1])


PREFIX_MAP = {"T": "taobao", "J": "jd", "S": "shopify"}


def _fix_order_id(last_order: str) -> str:
    """把 LLM 编的订单号替换为库内真实订单（同前缀）——防"查不到"穿帮。
    真实教训：LLM 生成的订单号与 generate_data 的编号规则不一致（J7890 不在库内）。"""
    prefix = last_order[0].upper() if last_order else "T"
    source = PREFIX_MAP.get(prefix, "taobao")
    ids = db.list_order_ids(source)
    if not ids:
        return last_order
    return ids[hash(last_order) % len(ids)]


def _seed_buyer(p: dict) -> None:
    """画像入库 + 会话 seed 消息 + 记忆预置（订单号修正为库内真实订单）"""
    buyer = p["buyer"]
    db.upsert_profile(buyer, p["personality"], p["profile"], p["seed_history"])

    # 会话 + seed 历史消息（回放有内容）
    sid = db.get_or_create_session(buyer)
    db.add_message(sid, "user", p["seed_history"].split("。")[0] + "。")
    db.add_message(sid, "assistant", f"（历史对话摘要）{p['seed_history']}")

    # 记忆预置（跨会话记忆立即生效）——订单号必须真实存在
    if p.get("last_order"):
        db.upsert_memory(buyer, "last_order", _fix_order_id(p["last_order"]))
    if p.get("intent"):
        db.upsert_memory(buyer, "intent", p["intent"])


def _ask_batch(n: int, retries: int = 3) -> list[dict]:
    """调用 LLM 生成一批画像；失败重试（LLM 不稳定是常态，脚本要容错）"""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp, _meta = call_chat([
                {"role": "user", "content": PROFILE_PROMPT.format(n=n)},
            ], max_tokens=1500)
            text = resp["choices"][0]["message"]["content"]
            if not text or not text.strip():
                raise ValueError("LLM 返回空内容")
            return _extract_json(text)
        except (LLMError, ValueError, json.JSONDecodeError, KeyError) as e:
            last_err = e
            print(f"    ↻ 第 {attempt} 次失败（{e}），重试...")
    raise last_err


def generate() -> int:
    created = 0
    seen: set[str] = set()
    for batch_start in range(0, TOTAL, BATCH):
        n = min(BATCH, TOTAL - batch_start)
        print(f"—— 生成第 {batch_start // BATCH + 1} 批（{n} 个）——")
        try:
            profiles = _ask_batch(n)
            for p in profiles:
                # 程序兜底：LLM 不保证"名字不重复"（真实教训），这里强制去重
                if p["buyer"] in seen:
                    print(f"  ⚠️ {p['buyer']} 已存在，跳过（LLM 重复了，程序兜底）")
                    continue
                seen.add(p["buyer"])
                _seed_buyer(p)
                created += 1
                print(f"  ✅ {p['buyer']}（{p['personality']}）last_order={p.get('last_order')}")
        except Exception as e:
            print(f"  ❌ 本批最终失败: {e}")
    print(f"共生成 {created} 个独特买家人格画像")
    return created


def fix_existing() -> int:
    """修复已生成画像的 last_order（改为库内真实订单）——不重跑 LLM"""
    n = 0
    conn = db.get_conn()
    rows = conn.execute("SELECT buyer FROM buyer_profiles").fetchall()
    conn.close()
    for r in rows:
        buyer = r["buyer"]
        m = db.get_memory(buyer)
        if m.get("last_order"):
            fixed = _fix_order_id(m["last_order"])
            if fixed != m["last_order"]:
                db.upsert_memory(buyer, "last_order", fixed)
                n += 1
    print(f"修正 {n} 个买家的 last_order 为库内真实订单")
    return n


if __name__ == "__main__":
    db.init_db()
    if input("修正现有画像的订单号？(y/n): ").strip().lower() == "y":
        fix_existing()
    generate()

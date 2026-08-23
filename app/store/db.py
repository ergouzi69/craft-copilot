"""存储层：SQLite 持久化（sessions/messages/actions/usage 四表）

对应 craft-agents-oss 的 shared/src/sessions/storage.ts（craft 用 JSONL，
这里是服务场景，SQLite 更合适：多用户并发 + 结构化查询 + 事务）

表职责（对齐好项目标准 2"数据库设计"）：
- sessions: 会话（买家维度）——记忆外化的"会话文件"
- messages: 消息流（user/assistant）——会话内上下文
- actions: 操作审计（pending/approved/rejected 状态机）——人机协同的落点
- usage: 每次 LLM 调用的 token/耗时——可观测埋点（30 题第 21 题）

迁移机制：PRAGMA user_version 记录 schema 版本，启动时增量迁移（老库升级不崩）
"""

import json
import os
import sqlite3
import time
from pathlib import Path

# db.py 位于 app/store/ 下，项目根 = 上三级（app/store → app → craft-copilot）
DB_PATH = Path(os.environ.get("DB_PATH", str(Path(__file__).resolve().parent.parent.parent / "craft.db")))

SCHEMA_VERSION = 2

MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        buyer TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        role TEXT NOT NULL,           -- user / assistant / tool
        content TEXT NOT NULL,
        ts REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        tool TEXT NOT NULL,
        args TEXT NOT NULL,           -- JSON 字符串
        status TEXT NOT NULL,         -- pending / approved / rejected
        ts REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        model TEXT NOT NULL,
        prompt_tokens INTEGER NOT NULL,
        completion_tokens INTEGER NOT NULL,
        total_tokens INTEGER NOT NULL,
        duration_ms INTEGER NOT NULL,
        ts REAL NOT NULL
    );
    """,
    # v2：买家记忆表（上下文工程的"用户记忆"类——买家画像/偏好/关键事实）
    2: """
    CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        buyer TEXT NOT NULL,
        key TEXT NOT NULL,            -- 如 last_order / intent / vip
        value TEXT NOT NULL,
        updated_at REAL NOT NULL,
        UNIQUE(buyer, key)
    );
    """,
}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """启动时执行迁移：把数据库升到 SCHEMA_VERSION"""
    conn = get_conn()
    cur = conn.execute("PRAGMA user_version").fetchone()[0]
    for target in range(cur + 1, SCHEMA_VERSION + 1):
        sql = MIGRATIONS.get(target)
        if sql:
            conn.executescript(sql)
        conn.execute(f"PRAGMA user_version = {target}")
        conn.commit()
    conn.close()


# ========== sessions（会话 = 买家工单） ==========

def get_or_create_session(buyer: str) -> int:
    conn = get_conn()
    row = conn.execute("SELECT id FROM sessions WHERE buyer=?", (buyer,)).fetchone()
    if row:
        conn.close()
        return row["id"]
    cur = conn.execute("INSERT INTO sessions (buyer, created_at) VALUES (?, ?)",
                       (buyer, time.time()))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def get_session_by_buyer(buyer: str) -> int | None:
    """只查不建（会话历史接口用；查不到返回 None 而不是创建）"""
    conn = get_conn()
    row = conn.execute("SELECT id FROM sessions WHERE buyer=?", (buyer,)).fetchone()
    conn.close()
    return row["id"] if row else None


def list_sessions() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT s.id, s.buyer, s.created_at, COUNT(m.id) AS msg_count "
        "FROM sessions s LEFT JOIN messages m ON m.session_id=s.id "
        "GROUP BY s.id ORDER BY s.created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ========== messages（消息流） ==========

def add_message(session_id: int, role: str, content: str) -> None:
    conn = get_conn()
    conn.execute("INSERT INTO messages (session_id, role, content, ts) VALUES (?,?,?,?)",
                 (session_id, role, content, time.time()))
    conn.commit()
    conn.close()


def get_messages(session_id: int, limit: int = 50) -> list[dict]:
    """取最近 limit 条消息（正序返回）——上下文组装用"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id=? ORDER BY ts DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


# ========== actions（操作审计，人机协同落点） ==========

def add_action(session_id: int, tool: str, args: dict, status: str = "pending") -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO actions (session_id, tool, args, status, ts) VALUES (?,?,?,?,?)",
        (session_id, tool, json.dumps(args, ensure_ascii=False), status, time.time()),
    )
    conn.commit()
    aid = cur.lastrowid
    conn.close()
    return aid


def update_action_status(action_id: int, status: str) -> None:
    conn = get_conn()
    conn.execute("UPDATE actions SET status=? WHERE id=?", (status, action_id))
    conn.commit()
    conn.close()


def get_pending_actions(session_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, tool, args, status FROM actions WHERE session_id=? AND status='pending' ORDER BY ts",
        (session_id,),
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "tool": r["tool"], "args": json.loads(r["args"]), "status": r["status"]}
            for r in rows]


def get_actions(session_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, tool, args, status, ts FROM actions WHERE session_id=? ORDER BY ts",
        (session_id,),
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "tool": r["tool"], "args": json.loads(r["args"]),
             "status": r["status"], "ts": r["ts"]} for r in rows]


# ========== memory（买家记忆：画像/偏好/关键事实，注入系统提示词） ==========

def upsert_memory(buyer: str, key: str, value: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO memory (buyer, key, value, updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(buyer, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (buyer, key, value, time.time()),
    )
    conn.commit()
    conn.close()


def get_memory(buyer: str) -> dict[str, str]:
    """返回该买家的全部记忆（key→value），用于注入系统提示词"""
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM memory WHERE buyer=?", (buyer,)).fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


# ========== usage（可观测埋点） ==========

def add_usage(session_id: int, meta: dict) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO usage (session_id, model, prompt_tokens, completion_tokens, total_tokens, duration_ms, ts) "
        "VALUES (?,?,?,?,?,?,?)",
        (session_id, meta.get("model", ""), meta.get("prompt_tokens", 0),
         meta.get("completion_tokens", 0), meta.get("total_tokens", 0),
         meta.get("duration_ms", 0), time.time()),
    )
    conn.commit()
    conn.close()


def session_stats(session_id: int) -> dict:
    """会话级 token/耗时统计（30 题第 21 题"Agent 跑崩了怎么查"的数据源）"""
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS calls, SUM(total_tokens) AS tokens, "
        "SUM(duration_ms) AS total_ms, AVG(duration_ms) AS avg_ms "
        "FROM usage WHERE session_id=?",
        (session_id,),
    ).fetchone()
    conn.close()
    return {
        "calls": row["calls"] or 0,
        "total_tokens": row["tokens"] or 0,
        "total_duration_ms": row["total_ms"] or 0,
        "avg_duration_ms": round(row["avg_ms"] or 0),
    }


def global_stats() -> dict:
    """全局统计 + 成本估算（好项目标准 5：可观测 + 量化收益）"""
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS calls, SUM(total_tokens) AS tokens, "
        "SUM(duration_ms) AS total_ms, AVG(duration_ms) AS avg_ms "
        "FROM usage",
    ).fetchone()
    sessions_n = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
    conn.close()

    total_tokens = row["tokens"] or 0
    # 成本估算：DeepSeek 近似价（输入 ¥2/百万 token，输出 ¥8/百万）——标注为估算
    est_cost = total_tokens / 1_000_000 * 4   # 粗略混合单价
    return {
        "calls": row["calls"] or 0,
        "total_tokens": total_tokens,
        "total_duration_ms": row["total_ms"] or 0,
        "avg_duration_ms": round(row["avg_ms"] or 0),
        "sessions": sessions_n,
        "est_cost_cny": round(est_cost, 4),   # 估算成本（元）
        "note": "成本为估算（混合单价 ¥4/百万 token）",
    }


def adoption_stats() -> dict:
    """评测：建议采纳率（Human-in-the-loop 的效果指标）
    采纳率 = 客服确认执行的操作数 / 全部待确认操作数（拒绝/待处理不计）
    """
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) AS n FROM actions").fetchone()["n"]
    approved = conn.execute("SELECT COUNT(*) AS n FROM actions WHERE status='approved'").fetchone()["n"]
    rejected = conn.execute("SELECT COUNT(*) AS n FROM actions WHERE status='rejected'").fetchone()["n"]
    conn.close()
    rate = approved / total if total else 0
    return {
        "total_actions": total,
        "approved": approved,
        "rejected": rejected,
        "pending": total - approved - rejected,
        "adoption_rate": round(rate, 4),
    }

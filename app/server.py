"""服务层入口（bootstrap）：FastAPI app

对应 craft-agents-oss 的 packages/server + server-core（headless 服务入口）。

职责：
- 启动时 init_db（迁移）
- /ws/copilot：WebSocket 传输端点（信封路由）
- /api/sessions：HTTP 会话列表（可选，ws 也能查）
- /：客户端工作台（Phase 5 填充）

注意：--reload 启动时 init_db 会跑两次（reloader + worker），幂等（CREATE IF NOT EXISTS）
"""

from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.store import db
from app.transport import handle_message

app = FastAPI(title="craft-copilot")

STATIC_DIR = Path(__file__).resolve().parent / "static"

# 启动迁移（幂等）
db.init_db()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/sessions")
def api_sessions():
    return {"sessions": db.list_sessions()}


@app.websocket("/ws/copilot")
async def ws_copilot(ws: WebSocket):
    """传输端点：接收信封 → 路由 → 回信封"""
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_json()
            for resp in handle_message(raw):
                await ws.send_json(resp)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        # 兜底：不让连接死掉，把错误发回去（不静默）
        try:
            await ws.send_json({"type": "error", "req_id": "", "payload": {"message": str(e)}})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass

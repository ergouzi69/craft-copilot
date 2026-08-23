"""简化 MCP server：把 Source 工具暴露为 MCP 协议工具

对应 craft-agents-oss 的 shared/src/sources/server-builder.ts（Source → MCP server）
和 learn cc 的 s19 MCP。这是 R6（Source 适配）的生产化扩展：
- 之前：Source 是内部函数直调（轻量抽象）
- 现在：Source 包装成 MCP 工具（JSON-RPC + tools/list + tools/call），
  外部 Agent（Claude Code 等）能通过标准 MCP 协议调用这些工具

MCP 协议要点（简化版，生产要加：能力协商/资源/采样/进度通知）：
- 传输：stdio（一行一个 JSON-RPC 消息）
- initialize：握手，返回协议版本 + 能力
- tools/list：列出工具（name/description/inputSchema）
- tools/call：调用工具（参数校验 → 执行 → 文本结果）
- 错误码：-32700 解析错误 / -32601 方法不存在 / -32602 参数错误
"""

import json

from app.tools.registry import ToolRegistry
from app.tools.builtin import build_registry

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "craft-copilot-mcp"
SERVER_VERSION = "0.1.0"


class MiniMcpServer:
    """简化 MCP server：处理 JSON-RPC 消息（stdio 逐行协议）"""

    def __init__(self, registry: ToolRegistry | None = None):
        self.registry = registry or build_registry()

    # ---- 对外入口：一行消息 → 0..N 条响应 ----

    def handle_line(self, line: str) -> list[dict]:
        """处理一行 JSON-RPC 消息，返回响应列表（notifications 返回空）"""
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return [self._rpc_error(None, -32700, "Parse error: 非法 JSON")]

        if not isinstance(msg, dict) or "method" not in msg:
            return [self._rpc_error(msg.get("id") if isinstance(msg, dict) else None,
                                    -32600, "Invalid Request: 缺少 method")]

        method = msg["method"]
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            return [self._rpc_result(msg_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            })]
        if method == "notifications/initialized":
            return []                       # 通知无响应
        if method == "tools/list":
            return [self._rpc_result(msg_id, {"tools": self._tool_list()})]
        if method == "tools/call":
            return [self._tool_call(msg_id, params)]
        return [self._rpc_error(msg_id, -32601, f"Method not found: {method}")]

    # ---- 内部 ----

    def _tool_list(self) -> list[dict]:
        """Source 工具 → MCP 工具格式（name/description/inputSchema）"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.parameters,   # 已是 JSON Schema
            }
            for t in self.registry.list_tools()
        ]

    def _tool_call(self, msg_id, params: dict) -> dict:
        """调用工具：参数校验 → 执行 → 文本结果（MCP content 格式）"""
        name = params.get("name", "")
        args = params.get("arguments") or {}
        tool = self.registry.get(name)
        if not tool:
            return self._rpc_error(msg_id, -32602, f"Unknown tool: {name}")

        err = tool.validate(args)
        if err:
            return self._rpc_error(msg_id, -32602, err)

        try:
            result = tool.execute(args)
            return self._rpc_result(msg_id, {
                "content": [{"type": "text", "text": result}],
                "isError": False,
            })
        except Exception as e:
            return self._rpc_result(msg_id, {
                "content": [{"type": "text", "text": f"工具执行失败: {e}"}],
                "isError": True,
            })

    @staticmethod
    def _rpc_result(msg_id, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _rpc_error(msg_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": code, "message": message}}


if __name__ == "__main__":
    """stdio 模式：从 stdin 逐行读 JSON-RPC，输出到 stdout（MCP 客户端标准接入）"""
    import sys
    from app.store import db
    db.init_db()
    server = MiniMcpServer()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        for resp in server.handle_line(line):
            print(json.dumps(resp, ensure_ascii=False), flush=True)

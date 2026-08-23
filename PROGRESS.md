# PROGRESS.md — craft-copilot 进度

> 每次收工前更新；每次开工先读。用"预期 vs 实际"记录每阶段。

## Phase 0 · 项目骨架（2026-08-23 ✅）
- [x] 目录结构（app/ 五层 + tests/）
- [x] AGENTS.md / PROGRESS.md / check.sh（指令/状态/反馈子系统）
- [x] .env.example / .gitignore / requirements.txt / venv
- [x] app/config.py（.env 加载）
- 验证：check.sh ✅

## Phase 1 · 工具层（2026-08-23 ✅）
- [x] registry.py：ToolDefinition（name/desc/schema/handler/risky）+ ToolRegistry（注册/校验/执行）
- [x] sources.py：BaseSource + 淘宝/京东/Shopify + SourceRouter（前缀路由）
- [x] builtin.py：query_order / refund_order(risky) / list_sources
- [x] tests/test_tools.py：8 测试

## Phase 2 · Agent 层（2026-08-23 ✅）
- [x] app/llm.py：模型层（call_chat / call_chat_stream / LLMError）
- [x] app/agent/loop.py：runAgentTurn 循环（终止检查/权限拦截/多步规划/防死循环/错误兜底）
- [x] tests/test_agent_loop.py：6 测试（mock LLM）
- [x] **真实 LLM 验证**：
  - 查单 ✅（意图→query_order→建议）
  - 退款 ⚠️→✅（初测 LLM 用文字打发退款请求，pending=[]；**强化 SYSTEM prompt 后**正确触发 refund_order → pending）
  - 教训：mock 全绿 ≠ 真实可用——真实模型行为不可控，prompt 约束要显式强
- git：81ce2a4（Phase 0-2）+ check.sh 修复

## 下一步
- Phase 3 · 服务层：会话管理 + SQLite 持久化（sessions/messages/actions/usage）
- Phase 4 · 传输层：WebSocket RPC 信封（type/req_id/channel）
- Phase 5 · 客户端层：Web UI
- Phase 6 · 上下文工程：五类上下文（当前/会话/用户/工具/全局）
- Phase 7 · 可观测 + 评测
- Phase 8 · 后台任务 + 定时（催单）
- 多 Agent：单链路跑通后按场景判断（暂定不做）

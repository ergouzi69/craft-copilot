# craft-copilot

电商客服 Agent 小助手（Python 版 craft-agents-oss 分层结构 + harness 五层架构）。

## 这个项目解决什么问题

- **谁的问题**：电商客服人员。买家消息（查单/物流/退款）每天几十条，重复回答。
- **原来怎么解决**：人工逐条回复，查单要开 ERP，退款要走流程，平均 2-5 分钟/条。
- **Agent 介入后**：自动识别意图 → 查订单 → 生成回复建议，高风险操作（退款）必须客服确认。目标是单条 3 秒内出建议。

## 架构（五层，对齐 craft-agents-oss）

```
客户端层  app/static/        Web UI（会话/消息/建议/确认按钮）
传输层    app/transport.py   WebSocket RPC（type/req_id/channel 信封 + DTO）
服务层    app/server.py      FastAPI：bootstrap/路由/会话生命周期
Agent 层  app/agent/loop.py  手写 runAgentTurn（模型-工具-回填-终止）
工具层    app/tools/         ToolDefinition 注册表 + Sources 动态工厂
持久化    app/store/db.py     SQLite（sessions/messages/actions/usage/memory）
```

## 技术栈

Python 3.12 / FastAPI / SQLite / 火山方舟 DeepSeek（OpenAI 兼容 function calling）/ WebSocket / pytest / Docker（后加）

## 硬约束（写死，改前先问）

- **不用第三方 Agent 框架**（LangChain/CrewAI/Claude SDK）——Agent 循环手写，这是学习项目，要能讲清每一环
- **key 只走环境变量 / .env**（.env 不进 git）
- **所有改动必须有测试**（`pytest` 全绿才能算完成）
- **高风险工具（退款）必须人确认**——LLM 提议，客服 confirm 才执行

## 验证命令（反馈子系统）

```bash
cd craft-copilot
python -m pytest -q          # 所有测试
python -m py_compile app/*.py app/agent/*.py app/tools/*.py app/services/*.py app/store/*.py
```

## 进度

见 `PROGRESS.md`。每次收工前更新，每次开工先读。

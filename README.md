# Craft Copilot — 电商客服 Copilot

面向电商客服场景的单用户 Agent 助手：买家消息进来，手写执行循环处理（查单/退款建议），高风险操作必须客服确认执行，全程会话/记忆/调用可观测可审计。

> 从 customer-copilot（概念验证版）重构而来：对齐五层架构 + 上下文工程 + 流式打字机 + 可观测评测。
> 多用户升级版见 [enterprise-workbench](../enterprise-workbench)。

## 特性

- **手写 Agent 执行循环**：runAgentTurn（Observe-Reason-Act），终止检查（8 轮防死循环）+ LLMError 兜底
- **权限关卡（HITL）**：risky 工具拦截 + pending/confirm 状态机——退款/改价 100% 客服确认，查单自主执行
- **五类上下文工程**：任务/会话/记忆/工具/全局知识 + Prompt Sections 分段拼装，记忆段按需注入
- **流式打字机**：工具阶段同步 + 建议阶段流式，done 帧延迟收尾（修复 done 时序 bug）
- **多源统一接入**：Source 适配层（淘宝/京东/Shopify 前缀路由）+ 简化 MCP server（JSON-RPC）
- **可观测评测**：每次调用埋点（token/耗时/成本估算/采纳率），实测一轮 2 次调用 1680 tokens / 2.2 秒
- **工程体系**：AGENTS.md / PROGRESS.md / check.sh + 54 个 mock LLM 测试 + SQLite 版本门控迁移

## 技术栈

Python · FastAPI · WebSocket（RPC 信封）· SQLite · 火山方舟 DeepSeek（OpenAI 兼容 function calling）· MCP（JSON-RPC）· pytest · **零第三方 Agent 框架**

## 快速开始

```bash
# 1. 克隆
git clone <repo-url> && cd craft-copilot

# 2. 虚拟环境 + 依赖
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. 配置（复制并填写密钥）
cp .env.example .env             # DEEPSEEK_API_KEY 必填

# 4. 生成演示数据（120 单订单 + 买家人格画像）
python -m app.tools.generate_data
python -m app.tools.generate_profiles

# 5. 启动
python -m uvicorn app.server:app --port 8010
# 打开 http://localhost:8010

# 6. 测试
bash check.sh                    # 结构自检 + 54 个测试
```

## 架构

```
客户端（工作台 UI + 打字机渲染）
  └─ 传输层：WS RPC 信封（type/req_id/payload + status/delta/done 流式帧）
      └─ 服务层：会话管理 + 权限状态机（pending/confirm）+ 记忆 + 统计
          └─ Agent 层：手写 runAgentTurn + 五类上下文
              └─ 工具层：Source 多源 / 简化 MCP / 内置工具注册
                  └─ 存储：SQLite（messages/usage/memory + v1→v3 迁移）
```

## 测试

54 个 pytest（mock LLM，0.5 秒跑完）：循环 / 上下文 / 流式时序 / 权限状态机 / 可观测 / MCP 链路。

## 协议

MIT License

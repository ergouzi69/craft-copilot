# PROGRESS.md — craft-copilot 进度

> 每次收工前更新；每次开工先读。用"预期 vs 实际"记录每阶段。

## Phase 0 · 项目骨架（2026-08-23 ✅）
- [x] 目录结构（app/ 五层 + tests/）
- [x] AGENTS.md（指令子系统）
- [x] PROGRESS.md（状态子系统，本文件）
- [x] check.sh（反馈子系统）
- [x] .env.example / .gitignore / requirements.txt
- [x] app/config.py（.env 加载，复用 customer-copilot 验证过的思路）
- [x] venv + 依赖安装
- 验证：check.sh ✅ 通过（语法/进度；测试 Phase 1 起）

## Phase 1 · 工具层（2026-08-23 进行中）
- [x] app/tools/registry.py：ToolDefinition（name/desc/schema/handler/risky）+ ToolRegistry（注册/校验/执行）
- [x] app/tools/sources.py：BaseSource + 淘宝/京东/Shopify + SourceRouter（前缀路由）
- [x] app/tools/builtin.py：query_order / refund_order(risky) / list_sources 注册
- [x] tests/test_tools.py：8 个测试（注册/校验/路由/risky/未知来源）
- [ ] 测试全绿验证（venv 装好后跑）

## 下一步
- Phase 2 · Agent 层：runAgentTurn 循环（模型-工具-回填-终止）+ 意图识别

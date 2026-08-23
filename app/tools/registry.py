"""工具注册表（Tool Registry）

对应 craft-agents-oss 的 session-tools-core（tool-defs + handlers + runtime）
和 learn cc 的 s07 工具契约。核心概念：

- ToolDefinition：一个工具的描述（name/description/parameters schema）+ 执行函数
  ——这是给 LLM 看的"工具说明书"，parameters 是 JSON Schema（对齐 Anthropic/OpenAI 工具格式）
- ToolRegistry：注册/查找/执行。执行前校验参数（validate），区分 safe/risky（权限属性）
- 权限属性 risky=True 的工具：LLM 只能提议，必须人确认才真正执行（对应 harness 安全/人机协同）

为什么这样设计（面试可讲）：
1. 工具定义和实现分离 → 加工具 = 注册一行，业务逻辑不动（变更隔离）
2. schema 化参数 → 执行前校验，LLM 传错参数不炸
3. risky 标记 → 权限关卡在注册表层面就显式声明，不是散落在循环里
"""

import json
from typing import Any, Callable, Optional


class ToolDefinition:
    """一个工具的完整定义（名称/描述/参数 schema/执行函数/权限）"""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable[..., Any],
        risky: bool = False,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters        # JSON Schema（LLM 填参数用）
        self.handler = handler              # 真正的执行函数
        self.risky = risky                  # True = 高危，必须人确认

    def to_schema(self) -> dict:
        """转成 OpenAI/Anthropic 工具格式（给 LLM 看的部分）"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def validate(self, args: dict) -> Optional[str]:
        """参数校验：必填项缺失 → 返回错误信息；OK → None"""
        required = self.parameters.get("required", [])
        for key in required:
            if key not in args or args[key] in (None, ""):
                return f"缺少必填参数: {key}"
        return None

    def execute(self, args: dict) -> str:
        """执行工具（跳过 risky 检查——权限判断在循环层做）"""
        return self.handler(**args)


class ToolRegistry:
    """工具注册表：注册/查找/列举"""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def schemas(self) -> list[dict]:
        """全部工具的 LLM 格式（喂给模型的 tools 参数）"""
        return [t.to_schema() for t in self._tools.values()]

    def execute(self, name: str, args: dict) -> str:
        """执行工具并返回字符串结果（Agent 循环调用入口）"""
        tool = self.get(name)
        if not tool:
            return f"工具不存在: {name}"
        err = tool.validate(args)
        if err:
            return f"参数错误: {err}"
        try:
            return tool.execute(args)
        except Exception as e:
            return f"工具执行失败: {e}"

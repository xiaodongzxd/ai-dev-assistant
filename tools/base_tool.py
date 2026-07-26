"""
MCP 风格工具基类：定义工具权限、注册和调用接口。
为未来完整 MCP 协议实现预留扩展点。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Callable, Awaitable, Optional

from loguru import logger


class ToolPermission(Enum):
    """工具权限级别，用于安全控制"""
    READ = "read"  # 只读，无风险
    WRITE = "write"  # 写入，需审核
    EXEC = "exec"  # 执行，高风险


@dataclass
class ToolDefinition:
    """单个工具的定义"""
    name: str
    description: str
    handler: Callable[..., Awaitable[Any]]  # 异步处理函数
    permission: ToolPermission
    parameters_schema: Optional[Dict[str, Any]] = None


class MCPBaseServer:
    """
    MCP 服务器基类。
    子类应实现 _register_all_tools() 并调用 register_tool() 注册具体工具。
    """

    def __init__(self, name: str):
        self.name = name
        self._tools: Dict[str, ToolDefinition] = {}

    def register_tool(self, tool_def: ToolDefinition) -> None:
        """注册一个工具到服务器"""
        self._tools[tool_def.name] = tool_def
        logger.info(f"Tool registered: {tool_def.name} (permission: {tool_def.permission.value})")

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """按名称获取工具定义"""
        return self._tools.get(name)

    def list_tools(self) -> list:
        """列出所有已注册工具（用于动态发现）"""
        return [
            {"name": name, "description": tool.description, "permission": tool.permission.value}
            for name, tool in self._tools.items()
        ]

    async def call_tool(self, name: str, **kwargs) -> Any:
        """异步调用工具"""
        tool = self.get_tool(name)
        if not tool:
            raise ValueError(f"Tool not found: {name}")
        logger.info(f"Calling tool: {name}")
        return await tool.handler(**kwargs)

    # 为了方便同步调用，可以提供一个同步包装（子类可选实现）
    def call_tool_sync(self, name: str, **kwargs) -> Any:
        import asyncio
        return asyncio.run(self.call_tool(name, **kwargs))

from __future__ import annotations

from typing import Any

from services.agents.types import AgentTool


class ToolRegistry:
    def __init__(self, tools: list[AgentTool]):
        self._tools = {tool.name: tool for tool in tools}

    @property
    def tools(self) -> list[AgentTool]:
        return list(self._tools.values())

    def get(self, name: str) -> AgentTool | None:
        return self._tools.get(name)

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self.get(name)
        if tool is None:
            raise ValueError(f"Unknown agent tool: {name}")
        return await tool.handler(arguments)


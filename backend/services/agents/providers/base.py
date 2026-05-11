from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from services.agents.types import AgentLLMEvent, AgentMessage, AgentTool


class NativeAgentClient(ABC):
    @abstractmethod
    async def stream_with_tools(
        self,
        *,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        context: str,
    ) -> AsyncIterator[AgentLLMEvent]:
        pass


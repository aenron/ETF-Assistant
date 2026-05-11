from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal


AgentToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: AgentToolHandler


@dataclass
class AgentMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass(frozen=True)
class AgentToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentLLMEvent:
    type: Literal["content", "tool_call", "done"]
    content: str = ""
    tool_call: AgentToolCall | None = None


@dataclass(frozen=True)
class AgentRunEvent:
    type: Literal["role_start", "role_chunk", "tool_call_start", "tool_call_done", "role_done", "role_error"]
    payload: dict[str, Any]


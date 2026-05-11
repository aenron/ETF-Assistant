from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from google.genai import types

from services.agents.providers.base import NativeAgentClient
from services.agents.types import AgentLLMEvent, AgentMessage, AgentTool, AgentToolCall
from services.llm.gemini_client import GeminiClient


class GeminiNativeAgentClient(NativeAgentClient):
    def __init__(self, llm: GeminiClient):
        self.llm = llm

    def _sanitize_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        unsupported_keys = {"additionalProperties", "$schema", "$defs", "oneOf", "anyOf", "allOf"}
        clean: dict[str, Any] = {}
        for key, value in schema.items():
            if key in unsupported_keys:
                continue
            if isinstance(value, dict):
                clean[key] = self._sanitize_schema(value)
            elif isinstance(value, list):
                clean[key] = [self._sanitize_schema(item) if isinstance(item, dict) else item for item in value]
            else:
                clean[key] = value
        return clean

    def _build_tools(self, tools: list[AgentTool]) -> list[Any]:
        gemini_tools: list[Any] = []
        if self.llm.enable_grounding:
            return [types.Tool(google_search=types.GoogleSearch())]

        declarations = []
        for tool in tools:
            declarations.append(
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters=self._sanitize_schema(tool.parameters),
                )
            )
        if declarations:
            gemini_tools.append(types.Tool(function_declarations=declarations))
        return gemini_tools

    def _tool_config(self, tools: list[AgentTool]) -> Any | None:
        return None

    def _contents(self, messages: list[AgentMessage]) -> list[Any]:
        contents = []
        for message in messages:
            if message.role == "system":
                continue
            role = "model" if message.role == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part(text=message.content)]))
        return contents

    def _system_instruction(self, messages: list[AgentMessage]) -> str | None:
        sections = [message.content for message in messages if message.role == "system" and message.content]
        return "\n\n".join(sections) or None

    def _extract_tool_calls(self, response: Any) -> list[AgentToolCall]:
        calls: list[AgentToolCall] = []
        function_calls = getattr(response, "function_calls", None) or []
        for index, call in enumerate(function_calls):
            name = getattr(call, "name", "")
            if not name:
                continue
            args = getattr(call, "args", None) or {}
            calls.append(AgentToolCall(id=f"gemini-call-{index}-{name}", name=name, arguments=dict(args)))
        if calls:
            return calls

        for candidate in getattr(response, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                call = getattr(part, "function_call", None)
                name = getattr(call, "name", "") if call else ""
                if not name:
                    continue
                args = getattr(call, "args", None) or {}
                calls.append(AgentToolCall(id=f"gemini-call-{len(calls)}-{name}", name=name, arguments=dict(args)))
        return calls

    def _extract_text(self, response: Any) -> str:
        texts: list[str] = []
        for candidate in getattr(response, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                text = getattr(part, "text", None)
                if isinstance(text, str) and text:
                    texts.append(text)
        return "".join(texts)

    async def stream_with_tools(
        self,
        *,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        context: str,
    ) -> AsyncIterator[AgentLLMEvent]:
        config = {
            "temperature": 0.0,
            "max_output_tokens": 8192,
            "tools": self._build_tools(tools) or None,
            "tool_config": self._tool_config(tools),
            "system_instruction": self._system_instruction(messages),
        }
        response = await asyncio.to_thread(
            self.llm.client.models.generate_content,
            model=self.llm.model_name,
            contents=self._contents(messages),
            config=config,
        )
        for call in self._extract_tool_calls(response):
            yield AgentLLMEvent(type="tool_call", tool_call=call)
        text = self._extract_text(response)
        if text:
            yield AgentLLMEvent(type="content", content=text)
        yield AgentLLMEvent(type="done")

    @staticmethod
    def tool_result_message(call: AgentToolCall, result: Any) -> AgentMessage:
        return AgentMessage(
            role="user",
            content=(
                f"工具 {call.name} 调用结果如下。请把它作为 Observation 使用，"
                "如果仍需更多数据可以继续调用工具，否则输出最终 JSON。\n"
                f"{json.dumps(result, ensure_ascii=False, default=str)}"
            ),
        )

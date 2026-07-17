from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from services.agents.providers.base import NativeAgentClient
from services.agents.types import AgentLLMEvent, AgentMessage, AgentTool
from services.llm.openai_client import OpenAIClient


class OpenAINativeAgentClient(NativeAgentClient):
    def __init__(self, llm: OpenAIClient):
        self.llm = llm

    @staticmethod
    def _split_messages(messages: list[AgentMessage]) -> tuple[str, str]:
        system_parts = [message.content for message in messages if message.role == "system" and message.content]
        input_parts = []
        for message in messages:
            if message.role == "system":
                continue
            role_label = "用户" if message.role == "user" else "助手" if message.role == "assistant" else "工具"
            input_parts.append(f"## {role_label}\n{message.content}")
        return "\n\n".join(system_parts), "\n\n".join(input_parts)

    @staticmethod
    def _ensure_object_schema(schema: dict[str, Any]) -> dict[str, Any]:
        clean = dict(schema or {})
        clean.setdefault("type", "object")
        clean.setdefault("properties", {})
        return clean

    def _build_tools(self, tools: list[AgentTool]) -> list[Any]:
        try:
            from agents import FunctionTool
        except ImportError as exc:
            raise RuntimeError("OpenAI Agents SDK 未安装，请安装 openai-agents") from exc

        sdk_tools: list[Any] = []
        for tool in tools:
            async def invoke(_ctx: Any, input_json: str, *, current_tool: AgentTool = tool) -> str:
                try:
                    args = json.loads(input_json or "{}")
                    if not isinstance(args, dict):
                        args = {}
                except json.JSONDecodeError:
                    args = {}
                result = await current_tool.handler(args)
                return json.dumps(result, ensure_ascii=False, default=str)

            sdk_tools.append(
                FunctionTool(
                    name=tool.name,
                    description=tool.description,
                    params_json_schema=self._ensure_object_schema(tool.parameters),
                    on_invoke_tool=invoke,
                    strict_json_schema=False,
                )
            )
        return sdk_tools

    async def stream_with_tools(
        self,
        *,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        context: str,
    ) -> AsyncIterator[AgentLLMEvent]:
        try:
            from agents import Agent, Runner, set_default_openai_api, set_default_openai_client, set_tracing_disabled
        except ImportError as exc:
            raise RuntimeError("OpenAI Agents SDK 未安装，请安装 openai-agents") from exc

        instructions, input_text = self._split_messages(messages)
        set_default_openai_client(self.llm.client, use_for_tracing=False)
        set_default_openai_api("responses")
        set_tracing_disabled(True)

        print(f"[OpenAIAgentSDK] context={context} tools={len(tools)} model={self.llm.model}", flush=True)

        agent = Agent(
            name=f"ETF Assistant Role Agent {context}",
            instructions=instructions,
            model=self.llm.model,
            tools=self._build_tools(tools),
        )
        result = Runner.run_streamed(agent, input=input_text)
        final_chunks: list[str] = []
        async for event in result.stream_events():
            if getattr(event, "type", "") != "raw_response_event":
                continue
            data = getattr(event, "data", None)
            if getattr(data, "type", "") != "response.output_text.delta":
                continue
            delta = getattr(data, "delta", "")
            if isinstance(delta, str) and delta:
                final_chunks.append(delta)
                yield AgentLLMEvent(type="content", content=delta)

        if not final_chunks:
            final_output = getattr(result, "final_output", "")
            if isinstance(final_output, str) and final_output:
                yield AgentLLMEvent(type="content", content=final_output)
        yield AgentLLMEvent(type="done")

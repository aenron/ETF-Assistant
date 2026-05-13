from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from schemas.multi_agent import MultiAgentContextSummary, MultiAgentRoleOpinion, MultiAgentScene
from services.agents.providers.gemini_agent_client import GeminiNativeAgentClient
from services.agents.tool_registry import ToolRegistry
from services.agents.types import AgentMessage, AgentRunEvent, AgentTool
from utils.timezone import now_in_shanghai


class RoleAgentExecutor:
    def __init__(
        self,
        *,
        scene: MultiAgentScene,
        role_id: str,
        role_name: str,
        role_focus: str,
        round_index: int,
        question: str | None,
        context_summary: MultiAgentContextSummary,
        tools: list[AgentTool],
        client: GeminiNativeAgentClient,
        previous_opinion: MultiAgentRoleOpinion | None = None,
        opposing_points: Sequence[str] = (),
        disagreement_summary: str = "",
        max_steps: int = 5,
    ):
        self.scene = scene
        self.role_id = role_id
        self.role_name = role_name
        self.role_focus = role_focus
        self.round_index = round_index
        self.question = question
        self.context_summary = context_summary
        self.registry = ToolRegistry(tools)
        self.client = client
        self.previous_opinion = previous_opinion
        self.opposing_points = list(opposing_points)
        self.disagreement_summary = disagreement_summary
        self.max_steps = max_steps

    def _messages(self) -> list[AgentMessage]:
        now = now_in_shanghai()
        current_time = now.strftime("%Y-%m-%d %H:%M:%S %Z")
        current_date = now.strftime("%Y-%m-%d")
        system_lines = [
            f"你是多智能体投资辩论系统中的【{self.role_name}】。",
            f"场景：{self.scene.value}。",
            f"当前时间：{current_time}。",
            f"角色职责：{self.role_focus}",
            "你必须像 ReAct agent 一样工作：先判断需要哪些数据，必要时调用可用工具获取 Observation，再输出最终 JSON。",
            "外部新闻、政策和最新市场信息必须通过可用搜索工具获取 Observation，不要编造最新事件。",
            f"调用搜索工具时，query 必须面向当前时间检索最新信息，并包含完整当前日期“{current_date}”，可同时包含“最新”“近期”“今日”等时间约束；不要只写年份，不要使用过去年份作为检索时间，除非用户问题明确要求历史日期。",
            "最终回答只能输出 JSON，字段必须包含：stance, action, summary, evidence, risk_notes, confidence, rebuttals。",
            "stance 只能是 bullish / neutral / bearish / mixed；confidence 为 0-100 数字。",
            "evidence 必须引用你实际获得的工具结果或上下文证据，不能编造数据来源。",
            "不要输出 markdown 代码块。",
        ]
        if self.role_id == "policy_event":
            system_lines.extend(
                [
                    "政策事件角色必须优先调用 search_policy_events 或 search_latest_news 获取最新新闻、政策、公告、监管或行业事件。",
                    f"政策事件角色的搜索 query 必须围绕当前日期检索最新政策/新闻，例如包含“最新 政策 新闻 公告 {current_date}”，不得只写年份或自行使用 2024、2025 等旧年份，除非用户明确问历史事件。",
                    "summary 必须先说明最新事件对方向和节奏的影响，不能只基于账户、现金、持仓结构给结论。",
                    "evidence 至少 2 条；每条必须包含新闻/政策/公告事件名称、发布日期或时间线、来源标题或URL，以及它如何影响判断。",
                    "如果没有找到足够最新新闻/政策证据，evidence 和 risk_notes 必须明确写“未找到足够最新政策/新闻证据”，不得用账户数据冒充政策事件证据。",
                ]
            )
        if self.role_id == "technical":
            system_lines.extend(
                [
                    "技术面角色必须给出明确技术面结论，summary 需要先说结论再说依据。",
                    "evidence 至少 2 条，且至少 1 条必须直接引用 K 线、均线、RSI、MACD、关键支撑/压力或最近涨跌变化。",
                ]
            )
        system = "\n".join(system_lines)
        user_sections: list[str] = [
            f"轮次：第{self.round_index}轮{'初评' if self.round_index == 1 else '辩论'}",
            "## 用户问题",
            self.question.strip() if self.question and self.question.strip() else "未提供明确问题，请基于场景和上下文判断。",
            "## 结构化上下文",
            json.dumps(self.context_summary.model_dump(mode="python"), ensure_ascii=False, indent=2, default=str),
        ]
        if self.previous_opinion is not None:
            user_sections.extend(
                [
                    "## 本角色上一轮观点",
                    json.dumps(self.previous_opinion.model_dump(mode="python"), ensure_ascii=False, indent=2, default=str),
                ]
            )
        if self.opposing_points:
            user_sections.extend(["## 最强反对点", "\n".join(f"- {item}" for item in self.opposing_points)])
        if self.disagreement_summary:
            user_sections.extend(["## 当前分歧摘要", self.disagreement_summary])
        return [
            AgentMessage(role="system", content=system),
            AgentMessage(role="user", content="\n\n".join(user_sections)),
        ]

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        clean = text.strip()
        if clean.startswith("```"):
            lines = clean.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            clean = "\n".join(lines).strip()
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(clean[start:end])
        raise ValueError("Agent final response did not contain JSON")

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return " ".join(str(value or "").split())

    @classmethod
    def _string_list(cls, value: Any, *, limit: int, default: list[str] | None = None) -> list[str]:
        default_list = default or []
        if isinstance(value, list):
            items = [cls._normalize_text(item) for item in value]
            return [item for item in items if item][:limit]
        if isinstance(value, tuple):
            items = [cls._normalize_text(item) for item in value]
            return [item for item in items if item][:limit]
        if isinstance(value, str):
            text = cls._normalize_text(value)
            return [text] if text else default_list
        return list(default_list)[:limit]

    def _normalize(self, raw: dict[str, Any]) -> MultiAgentRoleOpinion:
        stance = raw.get("stance")
        if stance not in {"bullish", "neutral", "bearish", "mixed"}:
            stance = "neutral"
        return MultiAgentRoleOpinion(
            round_index=self.round_index,
            role_id=self.role_id,
            role_name=self.role_name,
            stance=stance,
            action=self._normalize_text(raw.get("action") or ""),
            summary=self._normalize_text(raw.get("summary") or raw.get("conclusion") or "角色未给出明确结论。"),
            evidence=self._string_list(raw.get("evidence"), limit=8, default=["角色未给出可验证证据。"]),
            risk_notes=self._string_list(raw.get("risk_notes"), limit=8, default=["角色未给出风险依据。"]),
            confidence=max(0.0, min(100.0, float(raw.get("confidence") or 0.0))),
            rebuttals=self._string_list(raw.get("rebuttals"), limit=6),
        )

    async def run(self) -> MultiAgentRoleOpinion:
        final_text = ""
        async for event in self.stream():
            if event.type == "role_done":
                opinion = event.payload.get("opinion")
                if isinstance(opinion, MultiAgentRoleOpinion):
                    return opinion
            if event.type == "role_chunk":
                final_text += str(event.payload.get("content") or "")
        return self._normalize(self._extract_json(final_text))

    async def stream(self) -> AsyncIterator[AgentRunEvent]:
        message_id = f"role-{self.round_index}-{self.role_id}"
        yield AgentRunEvent(
            type="role_start",
            payload={
                "message_id": message_id,
                "round_index": self.round_index,
                "role_id": self.role_id,
                "role_name": self.role_name,
                "agent_mode": "react_native_sdk",
            },
        )
        messages = self._messages()
        final_text = ""
        try:
            for _ in range(self.max_steps):
                saw_tool_call = False
                async for event in self.client.stream_with_tools(
                    messages=messages,
                    tools=self.registry.tools,
                    context=f"multi_agent:{self.scene.value}:{self.role_id}:r{self.round_index}",
                ):
                    if event.type == "tool_call" and event.tool_call is not None:
                        saw_tool_call = True
                        call = event.tool_call
                        yield AgentRunEvent(
                            type="tool_call_start",
                            payload={
                                "message_id": message_id,
                                "round_index": self.round_index,
                                "role_id": self.role_id,
                                "role_name": self.role_name,
                                "tool_call_id": call.id,
                                "tool_name": call.name,
                                "arguments": call.arguments,
                            },
                        )
                        result = await self.registry.call(call.name, call.arguments)
                        messages.append(self.client.tool_result_message(call, result))
                        yield AgentRunEvent(
                            type="tool_call_done",
                            payload={
                                "message_id": message_id,
                                "round_index": self.round_index,
                                "role_id": self.role_id,
                                "role_name": self.role_name,
                                "tool_call_id": call.id,
                                "tool_name": call.name,
                                "result": result,
                            },
                        )
                    elif event.type == "content" and event.content:
                        final_text += event.content
                        yield AgentRunEvent(
                            type="role_chunk",
                            payload={
                                "message_id": message_id,
                                "round_index": self.round_index,
                                "role_id": self.role_id,
                                "role_name": self.role_name,
                                "content": event.content,
                            },
                        )
                if not saw_tool_call:
                    break
            opinion = self._normalize(self._extract_json(final_text))
        except Exception as exc:
            opinion = MultiAgentRoleOpinion(
                round_index=self.round_index,
                role_id=self.role_id,
                role_name=self.role_name,
                stance="neutral",
                action="继续观望",
                summary=f"{self.role_name} 执行 ReAct agent 失败，暂时给出保守观点。",
                evidence=[],
                risk_notes=[str(exc)],
                confidence=0.0,
                rebuttals=[],
            )
            yield AgentRunEvent(type="role_error", payload={"message_id": message_id, "message": str(exc)})
        yield AgentRunEvent(type="role_done", payload={"message_id": message_id, "opinion": opinion})

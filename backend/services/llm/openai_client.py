import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from services.llm.base import BaseLLMClient


class OpenAIClient(BaseLLMClient):
    """OpenAI API client based on the official SDK.

    Chat uses the Responses API so native OpenAI tools such as web_search can be
    enabled without changing the rest of the application LLM interface.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        enable_web_search: bool = False,
        timeout_seconds: float = 600.0,
        reasoning_effort: str = "",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.enable_web_search = enable_web_search
        self.reasoning_effort = reasoning_effort.strip().lower()
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=timeout_seconds,
        )

    def _response_tools(self) -> list[dict[str, str]]:
        return [{"type": "web_search"}] if self.enable_web_search else []

    def _response_options(self) -> dict[str, object]:
        options: dict[str, object] = {}
        if self.reasoning_effort:
            options["reasoning"] = {"effort": self.reasoning_effort}
        return options

    def _reset_openai_search_usage(self) -> None:
        self.reset_search_usage(
            provider="openai",
            enabled=self.enable_web_search,
            source="openai_web_search" if self.enable_web_search else "none",
        )

    @staticmethod
    def _annotation_value(annotation: Any, name: str) -> Any:
        if isinstance(annotation, dict):
            return annotation.get(name)
        return getattr(annotation, name, None)

    @classmethod
    def _extract_url_citations(cls, response: Any) -> list[dict[str, str]]:
        citations: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                for annotation in getattr(content, "annotations", []) or []:
                    annotation_type = cls._annotation_value(annotation, "type")
                    if annotation_type != "url_citation":
                        continue
                    url = cls._annotation_value(annotation, "url")
                    if not isinstance(url, str) or not url or url in seen:
                        continue
                    title = cls._annotation_value(annotation, "title")
                    citations.append({"url": url, "title": title if isinstance(title, str) and title else url})
                    seen.add(url)
        return citations

    @staticmethod
    def _format_citations(citations: list[dict[str, str]]) -> str:
        if not citations:
            return ""
        lines = ["", "", "**引用材料**"]
        for index, citation in enumerate(citations, 1):
            title = citation["title"].replace("[", "\\[").replace("]", "\\]")
            lines.append(f"{index}. [{title}]({citation['url']})")
        return "\n".join(lines)

    @staticmethod
    def _extract_output_text(response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text:
            return output_text

        chunks: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)

    def _update_search_usage_from_response(self, response: Any) -> None:
        if not self.enable_web_search:
            return

        used = False
        queries: list[str] = []
        for item in getattr(response, "output", []) or []:
            item_type = getattr(item, "type", None)
            if item_type and "web_search" in str(item_type):
                used = True
                query = getattr(item, "query", None) or getattr(item, "search_query", None)
                if isinstance(query, str) and query:
                    queries.append(query)

        citations = self._extract_url_citations(response)
        self.update_search_usage(used=used or bool(citations), queries=queries, result_count=len(citations) or None)

    async def chat(self, prompt: str) -> str:
        self._reset_openai_search_usage()
        response = await self.client.responses.create(
            model=self.model,
            input=prompt,
            temperature=0.7,
            tools=self._response_tools(),
            **self._response_options(),
        )
        self._update_search_usage_from_response(response)
        text = self._extract_output_text(response)
        return f"{text}{self._format_citations(self._extract_url_citations(response))}"

    async def chat_stream(self, prompt: str) -> AsyncIterator[str]:
        async for event in self.chat_stream_events(prompt):
            if event.get("type") == "text":
                content = event.get("content")
                if isinstance(content, str) and content:
                    yield content

    async def chat_stream_events(self, prompt: str) -> AsyncIterator[dict[str, object]]:
        self._reset_openai_search_usage()
        final_response = None
        search_phase_sent = False
        async with self.client.responses.stream(
            model=self.model,
            input=prompt,
            temperature=0.7,
            tools=self._response_tools(),
            **self._response_options(),
        ) as stream:
            async for event in stream:
                event_type = str(getattr(event, "type", ""))
                normalized_type = event_type.lower()
                if self.enable_web_search and not search_phase_sent and ("web_search" in normalized_type or "search" in normalized_type):
                    search_phase_sent = True
                    yield {"type": "phase", "phase": "searching", "detail": event_type}
                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", None)
                    if isinstance(delta, str) and delta:
                        yield {"type": "text", "content": delta}
            final_response = await stream.get_final_response()

        if final_response is not None:
            self._update_search_usage_from_response(final_response)
            citations_text = self._format_citations(self._extract_url_citations(final_response))
            if citations_text:
                yield {"type": "text", "content": citations_text}

    async def chat_json(self, prompt: str) -> dict:
        response = await self.chat(prompt)
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(response[start:end])
            return {"error": "No JSON found", "raw": response}
        except json.JSONDecodeError:
            return {"error": "JSON decode failed", "raw": response}

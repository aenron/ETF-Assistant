"""Tavily search tool integration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

from config import settings


TavilyTopic = Literal["general", "news", "finance"]
TavilyTimeRange = Literal["day", "week", "month", "year", "d", "w", "m", "y"]


@dataclass
class TavilySearchResult:
    title: str
    url: str
    content: str
    score: float | None = None
    published_date: str | None = None


@dataclass
class TavilySearchResponse:
    query: str
    answer: str | None
    results: list[TavilySearchResult]
    error: str | None = None


class TavilySearchService:
    """Small wrapper around Tavily Search API used as an LLM tool."""

    ENDPOINT = "https://api.tavily.com/search"
    VALID_SEARCH_DEPTHS = {"advanced", "basic", "fast", "ultra-fast"}
    VALID_TOPICS = {"general", "news", "finance"}
    VALID_TIME_RANGES = {"day", "week", "month", "year", "d", "w", "m", "y"}

    @classmethod
    def is_enabled(cls) -> bool:
        return bool(settings.tavily_enabled and settings.tavily_api_key.strip())

    @classmethod
    def normalize_topic(cls, value: str | None) -> TavilyTopic:
        topic = (value or settings.tavily_topic or "news").strip().lower()
        return topic if topic in cls.VALID_TOPICS else "news"  # type: ignore[return-value]

    @classmethod
    def normalize_time_range(cls, value: str | None) -> TavilyTimeRange:
        time_range = (value or settings.tavily_time_range or "week").strip().lower()
        return time_range if time_range in cls.VALID_TIME_RANGES else "week"  # type: ignore[return-value]

    @classmethod
    def normalize_max_results(cls, value: Any = None) -> int:
        try:
            parsed = int(value if value is not None else settings.tavily_max_results)
        except (TypeError, ValueError):
            parsed = settings.tavily_max_results
        return max(1, min(parsed, 10))

    @classmethod
    def normalize_search_depth(cls) -> str:
        """search_depth only comes from environment config and cannot be overridden by callers."""
        value = (settings.tavily_search_depth or "basic").strip().lower()
        return value if value in cls.VALID_SEARCH_DEPTHS else "basic"

    @classmethod
    async def search(
        cls,
        query: str,
        *,
        topic: str | None = None,
        time_range: str | None = None,
        max_results: int | None = None,
    ) -> TavilySearchResponse:
        clean_query = " ".join((query or "").split())
        if not clean_query:
            return TavilySearchResponse(query=query, answer=None, results=[], error="empty query")

        if not cls.is_enabled():
            return TavilySearchResponse(query=clean_query, answer=None, results=[], error="Tavily is not configured")

        body: dict[str, Any] = {
            "query": clean_query,
            "topic": cls.normalize_topic(topic),
            "search_depth": cls.normalize_search_depth(),
            "max_results": cls.normalize_max_results(max_results),
            "include_answer": "basic",
            "include_raw_content": False,
            "include_images": False,
            "include_favicon": False,
        }
        normalized_time_range = cls.normalize_time_range(time_range)
        if body["topic"] == "news":
            body["days"] = 7 if normalized_time_range in {"day", "d", "week", "w"} else 30
        else:
            body["time_range"] = normalized_time_range

        try:
            async with httpx.AsyncClient(timeout=settings.tavily_timeout_seconds) as client:
                response = await client.post(
                    cls.ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {settings.tavily_api_key.strip()}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            return TavilySearchResponse(query=clean_query, answer=None, results=[], error=str(exc))

        results = []
        for item in data.get("results", [])[: body["max_results"]]:
            results.append(
                TavilySearchResult(
                    title=str(item.get("title") or "").strip(),
                    url=str(item.get("url") or "").strip(),
                    content=str(item.get("content") or "").strip(),
                    score=item.get("score"),
                    published_date=item.get("published_date") or item.get("date"),
                )
            )

        return TavilySearchResponse(
            query=str(data.get("query") or clean_query),
            answer=data.get("answer"),
            results=results,
        )

    @classmethod
    def format_for_prompt(cls, responses: list[TavilySearchResponse]) -> str:
        usable = [item for item in responses if item.results or item.answer or item.error]
        if not usable:
            return ""

        blocks: list[str] = []
        for index, response in enumerate(usable, start=1):
            lines = [f"### tavily_search #{index}", f"- query: {response.query}"]
            if response.error:
                lines.append(f"- error: {response.error}")
            if response.answer:
                lines.append(f"- answer: {response.answer}")
            if response.results:
                lines.append("- results:")
                for result_index, result in enumerate(response.results, start=1):
                    date_text = f", date={result.published_date}" if result.published_date else ""
                    score_text = f", score={result.score:.3f}" if isinstance(result.score, (int, float)) else ""
                    lines.append(
                        f"  {result_index}. title={result.title or 'Untitled'}; "
                        f"url={result.url or 'N/A'}{date_text}{score_text}; "
                        f"content={result.content or 'No snippet'}"
                    )
            blocks.append("\n".join(lines))

        return "\n\n".join(blocks)

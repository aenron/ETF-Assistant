from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import json


@dataclass
class SearchUsageInfo:
    provider: str
    enabled: bool
    used: bool | None = None
    source: str | None = None
    queries: list[str] = field(default_factory=list)
    result_count: int | None = None
    detail: str | None = None

    def to_log_payload(self, *, context: str) -> dict:
        return {
            "context": context,
            "provider": self.provider,
            "source": self.source,
            "search_enabled": self.enabled,
            "search_used": self.used,
            "search_queries": self.queries,
            "search_result_count": self.result_count,
            "detail": self.detail,
        }


class BaseLLMClient(ABC):
    """LLM客户端抽象基类"""

    def reset_search_usage(self, *, provider: str, enabled: bool, source: str | None = None) -> None:
        self._last_search_usage = SearchUsageInfo(
            provider=provider,
            enabled=enabled,
            used=None if enabled else False,
            source=source,
        )

    def update_search_usage(
        self,
        *,
        used: bool | None = None,
        queries: list[str] | None = None,
        result_count: int | None = None,
        detail: str | None = None,
    ) -> None:
        usage = self.get_last_search_usage()
        if usage is None:
            return
        if used is not None:
            usage.used = used
        if queries is not None:
            usage.queries = [query for query in queries if query]
        if result_count is not None:
            usage.result_count = result_count
        if detail is not None:
            usage.detail = detail

    def get_last_search_usage(self) -> SearchUsageInfo | None:
        return getattr(self, "_last_search_usage", None)

    def log_search_usage(self, *, context: str) -> None:
        usage = self.get_last_search_usage()
        if usage is None:
            return
        print(f"[Search] {json.dumps(usage.to_log_payload(context=context), ensure_ascii=False)}", flush=True)
    
    @abstractmethod
    async def chat(self, prompt: str) -> str:
        """发送prompt并获取响应"""
        pass
    
    @abstractmethod
    async def chat_json(self, prompt: str) -> dict:
        """发送prompt并获取JSON响应"""
        pass

    async def chat_stream(self, prompt: str) -> AsyncIterator[str]:
        """流式发送prompt并获取响应，默认降级为一次性返回"""
        text = await self.chat(prompt)
        if text:
            yield text

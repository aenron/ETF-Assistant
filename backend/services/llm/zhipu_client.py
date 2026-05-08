"""智谱 LLM 客户端（使用官方 zai-sdk，支持显式 Web Search API）"""
import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

try:
    from zai import ZhipuAiClient
except ImportError:  # pragma: no cover - runtime dependency guard
    ZhipuAiClient = None

from services.llm.base import BaseLLMClient
from utils.timezone import now_in_shanghai


class ZhipuClient(BaseLLMClient):
    """智谱客户端，支持可配置的显式 Web Search API + GLM 对话"""

    def __init__(
        self,
        api_key: str,
        model: str = "glm-4.5-air",
        enable_web_search: bool = True,
    ):
        self.api_key = api_key
        self.model = model
        self.enable_web_search = enable_web_search
        if ZhipuAiClient is None:
            raise RuntimeError("zai-sdk 未安装，请先安装 backend/requirements.txt 中的依赖")
        self.client = ZhipuAiClient(api_key=api_key)

    @staticmethod
    def _clean_text(value: str) -> str:
        return " ".join((value or "").split())

    @classmethod
    def _extract_latest_question(cls, prompt: str) -> str:
        match = re.search(r"用户最新问题:\s*\n(.+?)(?:\n\n|$)", prompt, re.S)
        if match:
            return cls._clean_text(match.group(1))
        return ""

    @classmethod
    def _extract_primary_instrument(cls, prompt: str) -> tuple[str, str]:
        match = re.search(r"代码:\s*([A-Za-z0-9._-]+)\s*,\s*名称:\s*([^\n]+)", prompt)
        if not match:
            return "", ""
        return cls._clean_text(match.group(1)), cls._clean_text(match.group(2))

    @classmethod
    def _extract_portfolio_symbols(cls, prompt: str, limit: int = 3) -> list[str]:
        symbols: list[str] = []
        for match in re.finditer(r"-\s*([A-Za-z0-9._-]{4,})\s+([^|\n]+)", prompt):
            code = cls._clean_text(match.group(1))
            name = cls._clean_text(match.group(2))
            entry = cls._clean_text(f"{code} {name}")
            if entry and entry not in symbols:
                symbols.append(entry)
            if len(symbols) >= limit:
                break
        return symbols

    @classmethod
    def _build_search_queries(cls, prompt: str, max_queries: int = 2) -> list[str]:
        queries: list[str] = []
        latest_question = cls._extract_latest_question(prompt)
        code, name = cls._extract_primary_instrument(prompt)
        portfolio_symbols = cls._extract_portfolio_symbols(prompt)

        if latest_question:
            suffix = "最新 公告 新闻 政策 宏观 市场"
            if code or name:
                queries.append(cls._clean_text(f"{latest_question} {code} {name} {suffix}")[:160])
            elif portfolio_symbols:
                queries.append(cls._clean_text(f"{latest_question} {' '.join(portfolio_symbols[:2])} {suffix}")[:160])
            else:
                queries.append(cls._clean_text(f"{latest_question} {suffix}")[:160])
        elif code or name:
            queries.append(cls._clean_text(f"{code} {name} ETF 最新 公告 新闻 政策 宏观 市场")[:160])

        if ("账户概况" in prompt or "当前持仓" in prompt) and portfolio_symbols:
            queries.append(cls._clean_text(f"{' '.join(portfolio_symbols)} 持仓组合 最新 政策 宏观 市场 风险")[:160])

        deduped: list[str] = []
        for query in queries:
            if query and query not in deduped:
                deduped.append(query)
            if len(deduped) >= max_queries:
                break
        return deduped

    @staticmethod
    def _normalize_search_results(search_result: Any) -> list[dict[str, Any]]:
        if search_result is None:
            return []
        raw_items = search_result if isinstance(search_result, list) else [search_result]
        normalized: list[dict[str, Any]] = []
        for item in raw_items:
            if hasattr(item, "model_dump"):
                data = item.model_dump(mode="python")
            elif isinstance(item, dict):
                data = item
            else:
                data = {
                    "title": getattr(item, "title", ""),
                    "link": getattr(item, "link", ""),
                    "content": getattr(item, "content", ""),
                    "media": getattr(item, "media", ""),
                    "publish_date": getattr(item, "publish_date", ""),
                    "refer": getattr(item, "refer", ""),
                }
            normalized.append(data)
        return normalized

    @classmethod
    async def _enrich_prompt_with_web_search(cls, client: ZhipuAiClient, prompt: str) -> tuple[str, list[str], int, list[str]]:
        queries = cls._build_search_queries(prompt)
        if not queries:
            return prompt, [], 0, []

        blocks: list[str] = []
        request_ids: list[str] = []
        total_results = 0
        for index, query in enumerate(queries, start=1):
            lines = [f"### zhipu_web_search #{index}", f"- query: {query}"]
            try:
                response = await asyncio.to_thread(
                    client.web_search.web_search,
                    search_engine="search_pro",
                    search_query=query,
                    count=5,
                    search_recency_filter="noLimit",
                    content_size="medium",
                    search_intent=True,
                )
                request_id = getattr(response, "request_id", None)
                if request_id:
                    request_ids.append(str(request_id))
                results = cls._normalize_search_results(getattr(response, "search_result", None))
                total_results += len(results)

                if request_id:
                    lines.append(f"- request_id: {request_id}")
                if results:
                    lines.append("- results:")
                    for result_index, result in enumerate(results, start=1):
                        lines.append(
                            f"  {result_index}. title={result.get('title') or 'Untitled'}; "
                            f"url={result.get('link') or 'N/A'}; "
                            f"source={result.get('media') or 'N/A'}; "
                            f"date={result.get('publish_date') or 'N/A'}; "
                            f"refer={result.get('refer') or 'N/A'}; "
                            f"content={result.get('content') or 'No snippet'}"
                        )
                else:
                    lines.append("- results: []")
            except Exception as exc:
                lines.append(f"- error: {exc}")
            blocks.append("\n".join(lines))

        if not blocks:
            return prompt, queries, total_results, request_ids

        block_text = "\n\n".join(blocks)

        enriched_prompt = (
            f"{prompt}\n\n"
            "## Zhipu Web Search API 结果\n"
            "以下内容是后端先调用智谱 Web Search API 获取的结构化搜索结果。"
            "请优先使用这些结果作为公告、新闻、政策、宏观与事件依据；必须判断相关性、时效性和是否可能已定价。"
            "如果搜索结果为空或相关性弱，不要编造搜索依据。\n\n"
            f"{block_text}"
        )
        return enriched_prompt, queries, total_results, request_ids

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)
        return str(content or "")

    @staticmethod
    def _parse_json(content: str) -> dict:
        text = content.strip()
        if "```json" in text:
            match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
            if match:
                text = match.group(1)
        elif "```" in text:
            match = re.search(r"```\s*([\s\S]*?)\s*```", text)
            if match:
                text = match.group(1)

        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            print(f"[ZhipuClient] JSON解析失败: {text[:500]}")
            return {"error": "No JSON found", "raw": text[:500]}

    async def chat(self, prompt: str) -> str:
        try:
            self.reset_search_usage(provider="zhipu", enabled=self.enable_web_search, source="zhipu_web_search_api")
            final_prompt = prompt
            if self.enable_web_search:
                final_prompt, queries, result_count, request_ids = await self._enrich_prompt_with_web_search(self.client, prompt)
                self.update_search_usage(
                    used=bool(queries),
                    queries=queries,
                    result_count=result_count,
                    detail=f"request_ids={','.join(request_ids)}" if request_ids else None,
                )
            else:
                self.update_search_usage(used=False)
            request = {
                "model": self.model,
                "messages": [{"role": "user", "content": final_prompt}],
                "temperature": 0.0,
            }
            response = await asyncio.to_thread(self.client.chat.completions.create, **request)
            message = response.choices[0].message
            content = self._extract_text_content(getattr(message, "content", ""))
            return content
        except Exception as e:
            print(f"[ZhipuClient] 错误: {e}")
            return json.dumps({"error": str(e)})

    async def chat_stream(self, prompt: str) -> AsyncIterator[str]:
        self.reset_search_usage(provider="zhipu", enabled=self.enable_web_search, source="zhipu_web_search_api")
        final_prompt = prompt
        if self.enable_web_search:
            final_prompt, queries, result_count, request_ids = await self._enrich_prompt_with_web_search(self.client, prompt)
            self.update_search_usage(
                used=bool(queries),
                queries=queries,
                result_count=result_count,
                detail=f"request_ids={','.join(request_ids)}" if request_ids else None,
            )
        else:
            self.update_search_usage(used=False)
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        error_holder: list[Exception | None] = [None]

        def _sync_stream():
            try:
                request = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": final_prompt}],
                    "temperature": 0.0,
                    "stream": True,
                }
                response = self.client.chat.completions.create(**request)
                for chunk in response:
                    choices = getattr(chunk, "choices", None) or []
                    if not choices:
                        continue
                    delta = getattr(choices[0], "delta", None)
                    if not delta:
                        continue
                    content = self._extract_text_content(getattr(delta, "content", ""))
                    if content:
                        queue.put_nowait(content)
            except Exception as e:
                print(f"[ZhipuClient] 流式响应失败: {e}")
                error_holder[0] = e
            finally:
                queue.put_nowait(None)

        task = asyncio.get_event_loop().run_in_executor(None, _sync_stream)
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
        await task
        if error_holder[0] is not None:
            raise error_holder[0]

    async def chat_json(self, prompt: str) -> dict:
        self.reset_search_usage(provider="zhipu", enabled=self.enable_web_search, source="zhipu_web_search_api")
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个专业的ETF投资顾问，请严格按照JSON格式输出结果。"
                    f"今天的日期是{now_in_shanghai().strftime('%Y-%m-%d')}。"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        try:
            if self.enable_web_search:
                final_prompt, queries, result_count, request_ids = await self._enrich_prompt_with_web_search(self.client, prompt)
                messages[-1]["content"] = final_prompt
                self.update_search_usage(
                    used=bool(queries),
                    queries=queries,
                    result_count=result_count,
                    detail=f"request_ids={','.join(request_ids)}" if request_ids else None,
                )
            else:
                self.update_search_usage(used=False)
            request = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.0,
            }
            response = await asyncio.to_thread(self.client.chat.completions.create, **request)
            message = response.choices[0].message
            content = self._extract_text_content(getattr(message, "content", ""))
            return self._parse_json(content)
        except Exception as e:
            print(f"[ZhipuClient] 请求失败: {e}")
            return {"error": f"请求失败: {e}"}

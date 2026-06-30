import asyncio
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Portfolio, AdviceLog, EtfInfo
from schemas.advice import AdviceResponse, AdviceLogResponse, AccountAnalysisResponse, EventContext, EventItem, PeriodAdvice
from schemas.portfolio import PortfolioWithMarket
from config import settings
from services.market_service import MarketService
from services.portfolio_service import PortfolioService
from services.tavily_service import TavilySearchService
from services.llm.base import BaseLLMClient


class AdvisorService:
    """智能决策服务"""

    ACCOUNT_ANALYSIS_CODE = "ACCOUNT"
    ACCOUNT_ANALYSIS_NAME = "账户分析"
    SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
    ADVICE_CONCURRENCY = 4

    _llm_client: Optional[BaseLLMClient] = None
    
    @classmethod
    def get_llm_client(cls) -> BaseLLMClient:
        """获取LLM客户端（单例）"""
        if cls._llm_client is None:
            if settings.llm_provider == "openai":
                from services.llm.openai_client import OpenAIClient

                cls._llm_client = OpenAIClient(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                    model=settings.openai_model,
                    enable_web_search=settings.openai_enable_web_search,
                    timeout_seconds=settings.openai_timeout_seconds,
                    reasoning_effort=settings.openai_reasoning_effort,
                )
                cls._llm_client.provider = "openai"
            elif settings.llm_provider == "deepseek":
                from services.llm.deepseek_client import DeepSeekClient

                cls._llm_client = DeepSeekClient(
                    api_key=settings.deepseek_api_key,
                    base_url=settings.deepseek_base_url,
                    model=settings.deepseek_model,
                )
                cls._llm_client.provider = "deepseek"
            elif settings.llm_provider == "gemini":
                from services.llm.gemini_client import GeminiClient

                cls._llm_client = GeminiClient(
                    api_key=settings.gemini_api_key,
                    model=settings.gemini_model,
                    enable_grounding=settings.gemini_enable_grounding,
                    timeout_seconds=settings.gemini_timeout_seconds,
                )
                cls._llm_client.provider = "gemini"
            elif settings.llm_provider == "qwen":
                from services.llm.qwen_client import QwenClient

                cls._llm_client = QwenClient(
                    api_key=settings.qwen_api_key,
                    model=settings.qwen_model,
                    enable_search=settings.qwen_enable_search,
                )
                cls._llm_client.provider = "qwen"
            elif settings.llm_provider == "zhipu":
                from services.llm.zhipu_client import ZhipuClient

                cls._llm_client = ZhipuClient(
                    api_key=settings.zhipu_api_key,
                    model=settings.zhipu_model,
                    enable_web_search=settings.zhipu_enable_web_search,
                )
                cls._llm_client.provider = "zhipu"
            else:
                raise ValueError(f"不支持的LLM提供商: {settings.llm_provider}")
        return cls._llm_client

    @classmethod
    def _llm_label(cls, llm: BaseLLMClient) -> str:
        provider = getattr(llm, "provider", None) or settings.llm_provider
        model = getattr(llm, "model", None) or getattr(llm, "model_name", None) or "unknown"
        return f"{provider}/{model}"

    @classmethod
    def _log_llm_prompt(cls, llm: BaseLLMClient, prompt: str, context: str) -> None:
        print(
            f"\n[LLM][{context}][{cls._llm_label(llm)}] >>> PROMPT START\n"
            f"{prompt}\n"
            f"[LLM][{context}][{cls._llm_label(llm)}] <<< PROMPT END\n",
            flush=True,
        )

    @classmethod
    def _log_llm_result(cls, llm: BaseLLMClient, result, context: str) -> None:
        if isinstance(result, (dict, list)):
            result_text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        else:
            result_text = str(result)
        print(
            f"\n[LLM][{context}][{cls._llm_label(llm)}] >>> RESULT START\n"
            f"{result_text}\n"
            f"[LLM][{context}][{cls._llm_label(llm)}] <<< RESULT END\n",
            flush=True,
        )

    @classmethod
    def _log_llm_error(cls, llm: BaseLLMClient, error: Exception, context: str) -> None:
        print(
            f"\n[LLM][{context}][{cls._llm_label(llm)}] !!! ERROR\n"
            f"{type(error).__name__}: {error}\n",
            flush=True,
        )

    @staticmethod
    def _log_search_usage(llm: BaseLLMClient, context: str) -> None:
        llm.log_search_usage(context=context)

    @classmethod
    def _parse_json_response_text(cls, llm: BaseLLMClient, response_text: str) -> dict:
        parser = getattr(llm, "_parse_json", None)
        if callable(parser):
            return parser(response_text)

        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(text[start:end])
            return {"error": "No JSON found", "raw": response_text}
        except json.JSONDecodeError:
            return {"error": "JSON decode failed", "raw": response_text}

    @classmethod
    async def collect_stream_text_with_logging(cls, llm: BaseLLMClient, prompt: str, context: str) -> str:
        cls._log_llm_prompt(llm, prompt, context)
        chunks: list[str] = []
        try:
            async for chunk in llm.chat_stream(prompt):
                chunks.append(chunk)
            result = "".join(chunks)
            cls._log_llm_result(llm, result, context)
            cls._log_search_usage(llm, context)
            return result
        except Exception as e:
            partial = "".join(chunks)
            if partial:
                cls._log_llm_result(llm, f"[partial stream before error]\n{partial}", context)
            cls._log_search_usage(llm, context)
            cls._log_llm_error(llm, e, context)
            raise

    @classmethod
    async def chat_with_logging(cls, llm: BaseLLMClient, prompt: str, context: str) -> str:
        return await cls.collect_stream_text_with_logging(llm, prompt, context)

    @classmethod
    async def chat_json_with_logging(cls, llm: BaseLLMClient, prompt: str, context: str) -> dict:
        response_text = await cls.collect_stream_text_with_logging(llm, prompt, context)
        return cls._parse_json_response_text(llm, response_text)

    @classmethod
    async def chat_stream_events_with_logging(cls, llm: BaseLLMClient, prompt: str, context: str):
        cls._log_llm_prompt(llm, prompt, context)
        chunks: list[str] = []
        try:
            async for event in llm.chat_stream_events(prompt):
                if event.get("type") == "text":
                    content = event.get("content")
                    if isinstance(content, str):
                        chunks.append(content)
                yield event
            cls._log_llm_result(llm, "".join(chunks), context)
            cls._log_search_usage(llm, context)
        except Exception as e:
            partial = "".join(chunks)
            if partial:
                cls._log_llm_result(llm, f"[partial stream before error]\n{partial}", context)
            cls._log_search_usage(llm, context)
            cls._log_llm_error(llm, e, context)
            raise

    @classmethod
    async def chat_stream_with_logging(cls, llm: BaseLLMClient, prompt: str, context: str):
        async for event in cls.chat_stream_events_with_logging(llm, prompt, context):
            if event.get("type") == "text":
                content = event.get("content")
                if isinstance(content, str) and content:
                    yield content

    @classmethod
    def _parse_tavily_tool_calls(cls, payload: dict, max_calls: int) -> list[dict]:
        raw_calls = payload.get("tool_calls") or payload.get("calls") or []
        if not isinstance(raw_calls, list):
            return []

        calls: list[dict] = []
        seen_queries: set[str] = set()
        for item in raw_calls:
            if not isinstance(item, dict):
                continue

            name = item.get("name") or item.get("tool") or item.get("function")
            arguments = item.get("arguments") or item.get("args") or item
            if name and name != "tavily_search":
                continue
            if not isinstance(arguments, dict):
                continue

            query = " ".join(str(arguments.get("query") or "").split())
            if not query or query in seen_queries:
                continue

            calls.append({
                "query": query[:240],
                "topic": arguments.get("topic"),
                "time_range": arguments.get("time_range"),
                "max_results": arguments.get("max_results"),
            })
            seen_queries.add(query)
            if len(calls) >= max_calls:
                break

        return calls

    @classmethod
    def _prompt_time_context(cls) -> str:
        now = cls.now_in_shanghai()
        current_date = now.strftime("%Y-%m-%d")
        return (
            f"当前北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}。"
            f"当前日期：{current_date}。"
            "所有新闻、政策、宏观和市场事件判断必须以该时间为基准；"
            f"调用搜索工具时，query 必须包含完整当前日期“{current_date}”，并可同时包含“最新”“近期”“今日”等时间约束，优先使用最近7天到30天的可核实信息。"
            "不要用旧年份或过期事件替代最新信息，除非明确说明其仍在持续影响当前市场。"
        )

    @classmethod
    def _dedupe_items(cls, items: list[str], *, limit: int = 4) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for item in items:
            clean = " ".join((item or "").split()).strip(" ,，:：;；")
            if not clean or clean in seen:
                continue
            seen.add(clean)
            values.append(clean)
            if len(values) >= limit:
                break
        return values

    @classmethod
    def _build_tavily_query_seed(cls, prompt: str, context: str) -> dict:
        current_date = cls.now_in_shanghai().strftime("%Y-%m-%d")
        scene = "general"
        focus = ""
        keywords: list[str] = []

        if context.startswith("portfolio_advice:"):
            scene = "portfolio_advice"
            parts = context.split(":")
            code = parts[1] if len(parts) > 1 else ""
            mode = parts[2] if len(parts) > 2 else ""
            match = re.search(r"代码:\s*([0-9A-Za-z]+),\s*名称:\s*([^\n]+)", prompt)
            if match:
                code = match.group(1).strip()
                name = match.group(2).strip()
                keywords.extend([code, name])
            elif code:
                keywords.append(code)
            focus = "ETF持仓分析" if mode != "scheduled" else "ETF收盘复盘"
        elif context.startswith("account_analysis:"):
            scene = "account_analysis"
            mode = context.split(":")[1] if ":" in context else ""
            holdings_section = ""
            match = re.search(r"## 持仓明细(?:.*)?\n(.*?)(?:\n## |\Z)", prompt, re.S)
            if match:
                holdings_section = match.group(1)
            holding_codes = re.findall(r"-\s*(\d{6})\s+([^\n:]+)", holdings_section)
            for code, name in holding_codes[:3]:
                keywords.extend([code.strip(), name.strip()])
            focus = "账户持仓再平衡" if mode != "scheduled" else "账户收盘后再平衡"
        else:
            scene = context.split(":", 1)[0]
            focus = "ETF市场新闻政策"
            code_match = re.search(r"\b(\d{6})\b", prompt)
            if code_match:
                keywords.append(code_match.group(1))
            name_match = re.search(r"名称:\s*([^\n]+)", prompt)
            if name_match:
                keywords.append(name_match.group(1).strip())

        compact_keywords = cls._dedupe_items(keywords, limit=4)
        return {
            "current_date": current_date,
            "scene": scene,
            "focus": focus,
            "keywords": compact_keywords,
            "context": context,
        }

    @classmethod
    def _build_tavily_planning_prompt(cls, prompt: str, context: str, max_calls: int) -> str:
        seed = cls._build_tavily_query_seed(prompt, context)
        return f"""你是搜索参数构造器。Tavily 工具已确定要调用，你只负责为后续联网搜索生成查询参数。

## 时间基准
{cls._prompt_time_context()}

## 任务场景
- scene: {seed["scene"]}
- focus: {seed["focus"] or "ETF市场信息"}
- keywords: {", ".join(seed["keywords"]) or "无"}

要求:
1. 直接输出 JSON，不要解释
2. 输出 1 到 {max_calls} 个 tavily_search 调用
3. query 必须简洁具体，优先围绕 keywords 和 focus 构建，并且必须包含完整当前日期 {seed["current_date"]}
4. query 必须加入“最近”“近期”“最新”中的至少两个时间词
5. portfolio_advice 场景优先生成“公告/新闻/政策/市场事件/基金动态”类查询，不要生成“持仓分析”“投资策略”这类分析型搜索词
6. account_analysis 场景优先生成“持仓相关公告/新闻/政策/市场事件”类查询
7. topic 优先使用 finance；只有明显是泛新闻时才用 news；不要输出无关 topic
8. time_range 优先使用配置值对应的范围，不要随意放大
9. max_results 取 3 到 5
10. 不要复述原始分析 prompt，不要输出和查询无关的内容

输出格式:
{{"tool_calls":[{{"name":"tavily_search","arguments":{{"query":"关键词 最近 近期 最新 公告 新闻 {seed["current_date"]}","topic":"finance","time_range":"week","max_results":5}}}}]}}"""

    @classmethod
    def _default_tavily_tool_calls(cls, prompt: str, context: str, max_calls: int) -> list[dict]:
        seed = cls._build_tavily_query_seed(prompt, context)
        current_date = seed["current_date"]
        keywords = seed["keywords"] or ["ETF", "市场"]
        if seed["scene"] == "portfolio_advice":
            suffix = ["最近", "近期", "最新", "公告", "新闻", "政策", current_date]
        elif seed["scene"] == "account_analysis":
            suffix = ["最近", "近期", "最新", "持仓", "公告", "新闻", current_date]
        else:
            suffix = ["最近", "近期", "最新", "新闻", current_date]
        query = " ".join([*keywords[:3], *suffix]).strip()
        return [{
            "query": query[:240],
            "topic": "finance",
            "time_range": settings.tavily_time_range,
            "max_results": min(max(settings.tavily_max_results, 3), 5),
        }][:max_calls]

    @classmethod
    async def enrich_prompt_with_tavily_tools(
        cls,
        llm: BaseLLMClient,
        prompt: str,
        *,
        context: str,
        max_calls: int = 2,
    ) -> str:
        """Build Tavily search params with a compact prompt, then append tool results."""
        if not TavilySearchService.is_enabled():
            print(
                f"[Tavily] {context}: disabled "
                f"(enabled={settings.tavily_enabled}, key_set={bool(settings.tavily_api_key.strip())})",
                flush=True,
            )
            print(
                f"[Search] {json.dumps({'context': context, 'provider': 'tavily', 'source': 'tavily_tool', 'search_enabled': False, 'search_used': False, 'search_queries': [], 'search_result_count': 0, 'detail': 'disabled'}, ensure_ascii=False)}",
                flush=True,
            )
            return prompt

        planning_prompt = cls._build_tavily_planning_prompt(prompt, context, max_calls)

        original_grounding = getattr(llm, "enable_grounding", None)
        planning_disable_grounding = isinstance(original_grounding, bool)
        if planning_disable_grounding:
            llm.enable_grounding = False

        try:
            try:
                plan = await cls.chat_json_with_logging(
                    llm,
                    planning_prompt,
                    context=f"tavily_tool_plan:{context}",
                )
            except Exception as exc:
                print(f"[Tavily] 工具规划失败，使用默认查询: {exc}", flush=True)
                calls = cls._default_tavily_tool_calls(prompt, context, max_calls)
            else:
                calls = cls._parse_tavily_tool_calls(plan, max_calls=max_calls)
        finally:
            if planning_disable_grounding:
                llm.enable_grounding = original_grounding

        if not calls:
            print(f"[Tavily] {context}: 规划结果为空，使用默认查询", flush=True)
            calls = cls._default_tavily_tool_calls(prompt, context, max_calls)

        responses = []
        for call in calls:
            response = await TavilySearchService.search(
                call["query"],
                topic=call.get("topic"),
                time_range=call.get("time_range"),
                max_results=call.get("max_results"),
            )
            responses.append(response)
            if response.error:
                print(f"[Tavily] {context}: 搜索失败 query={call['query']}, error={response.error}", flush=True)
            else:
                print(f"[Tavily] {context}: 搜索完成 query={call['query']}, results={len(response.results)}", flush=True)

        total_results = sum(len(response.results) for response in responses)
        print(
            f"[Search] {json.dumps({'context': context, 'provider': 'tavily', 'source': 'tavily_tool', 'search_enabled': True, 'search_used': True, 'search_queries': [call['query'] for call in calls], 'search_result_count': total_results, 'detail': None}, ensure_ascii=False)}",
            flush=True,
        )

        tool_context = TavilySearchService.format_for_prompt(responses)
        if not tool_context:
            return prompt

        return (
            f"{prompt}\n\n"
            "## Tavily 工具搜索结果\n"
            "以下内容是后端根据模型工具调用请求执行 tavily_search 得到的联网搜索结果。"
            "请优先使用这些结果作为新闻、政策、宏观与事件依据；引用时必须判断相关性、时效性和是否可能已定价。"
            "如果工具结果为空、报错或相关性弱，不要编造搜索依据。\n\n"
            f"{tool_context}"
        )
    
    @staticmethod
    def build_prompt(
        etf_code: str,
        etf_name: str,
        shares: Decimal,
        cost_price: Decimal,
        current_price: Decimal,
        pnl_pct: Decimal,
        holding_days: Optional[int],
        kline_summary: str,
        indicators: dict,
    ) -> str:
        """构造LLM Prompt"""
        return f"""你是一名专业的ETF投资顾问。请根据以下信息给出投资建议。

## 时间基准
{AdvisorService._prompt_time_context()}

## 品种信息
- 代码: {etf_code}, 名称: {etf_name}

## 持仓状态
- 份额: {shares}, 成本价: {cost_price:.4f}
- 当前价: {current_price:.4f}, 浮动盈亏: {pnl_pct:.2f}%
- 持仓天数: {holding_days or '未知'}

## 近期行情 (最近10个交易日)
{kline_summary}

## 技术指标
- MA5={indicators.get('ma5', 'N/A')}, MA10={indicators.get('ma10', 'N/A')}, MA20={indicators.get('ma20', 'N/A')}
- MA60={indicators.get('ma60', 'N/A')}, MA120={indicators.get('ma120', 'N/A')}, MA250={indicators.get('ma250', 'N/A')}
- RSI(14)={indicators.get('rsi', 'N/A')}
- MACD: DIF={indicators.get('dif', 'N/A')}, DEA={indicators.get('dea', 'N/A')}, 柱={indicators.get('macd_bar', 'N/A')}
- 20日区间: 高点={indicators.get('high_20', 'N/A')}, 低点={indicators.get('low_20', 'N/A')}
- 60日区间: 高点={indicators.get('high_60', 'N/A')}, 低点={indicators.get('low_60', 'N/A')}
- 120日高点={indicators.get('high_120', 'N/A')}, 250日高点={indicators.get('high_250', 'N/A')}
- 距60日高点回撤={indicators.get('drawdown_60', 'N/A')}%, 距250日高点回撤={indicators.get('drawdown_250', 'N/A')}%
- 20日波动率={indicators.get('volatility_20', 'N/A')}%, 60日波动率={indicators.get('volatility_60', 'N/A')}%

请综合考虑技术面、基本面、政策面和市场情绪，并通过模型自带的联网搜索能力主动搜索最新的相关新闻和政策消息，给出投资建议。搜索和事件判断必须围绕上述当前时间基准，不要引用过期信息作为当前决策依据。

输出要求：
1. 给出一个顶层主决策，格式上必须包含:
   - main_judgment: 一句话主判断，建议写成“中期继续持有，短期不追高”这类可执行结论，50字以内
   - summary: 综合决策说明，80-120字，需涵盖当前决策原因、短期操作节奏和长期配置逻辑，形成完整的决策叙述
   - action: 最终执行动作，必须是 "buy" / "sell" / "hold" / "add" / "reduce" 之一
   - why: 2到3条最关键依据，必须体现“因为哪些技术面/位置/波动信号/政策新闻，所以给出这个动作”，每条25字以内
   - news_basis: 0到2条和 ETF 相关的新闻依据，没有就返回空数组
   - policy_basis: 0到2条和政策相关的依据，没有就返回空数组
2. 同时给出 short_term、medium_term、long_term 三个周期的建议
3. 每个周期都包含:
   - advice_type: 必须是 "buy" / "sell" / "hold" / "add" / "reduce" 之一
   - action: 对应周期下的具体动作描述，20字以内，例如“观望等待回踩”“继续持有”“分批加仓”
   - conclusion: 一句话结论，30字以内
   - signals: 2到4条核心依据，优先引用均线、RSI、MACD、区间位置、回撤、波动率等已提供指标
   - risks: 1到2条主要风险，避免空泛表述
   - confidence: 0-100之间的整数
4. short_term 更关注 1-10 个交易日的节奏和短线波动
5. medium_term 更关注 1-3 个月趋势，作为主决策
6. long_term 更关注 3 个月以上趋势、回撤和配置价值
7. 三个周期的结论必须体现时间维度差异，不要重复同一句话
8. 顶层 main_judgment / action / why 必须和 medium_term 保持一致，形成“结论 -> 依据 -> 动作”的闭环
9. news_basis 和 policy_basis 必须来自模型联网搜索到的真实最新信息；如果当前模型不支持联网搜索或未检索到可靠结果，就返回空数组，不要编造
10. 必须输出 event_context，用于记录搜索状态、来源质量、事件相关性和是否可能已定价。search_status 为 success/partial 且有可用搜索结果时，events 输出 2到5条互不重复的新闻、政策或宏观事件；只有搜索不可用、结果不足或相关性弱时才允许少于2条，并在 summary 中说明限制。不要让新闻政策直接决定买卖，必须先判断事件和 ETF 的相关性、时效性、来源质量、已定价风险，再结合技术位置决定动作
11. 如果 event_context.search_status 不是 "success"，不能因为新闻政策给出 buy/add/sell；如果事件 relevance 是 "weak"，不能作为主要依据；如果利好但 priced_in_risk 是 "high"，短期不能追高，只能 hold 或等待回踩
12. 输出要直接、结构化，不要写额外解释文字

请直接输出JSON对象，不要添加任何markdown标记或代码块符号:
{{
  "main_judgment": "一句话主判断",
  "summary": "综合决策说明，80-120字",
  "action": "buy/add/hold/reduce/sell 中的一项",
  "why": ["关键依据1", "关键依据2"],
  "news_basis": ["相关新闻依据"],
  "policy_basis": ["政策依据"],
  "event_context": {{
    "search_status": "success/partial/unavailable",
    "source_quality": "high/medium/low/unknown",
    "policy_signal": "positive/neutral/negative/unknown",
    "macro_signal": "positive/neutral/negative/unknown",
    "news_signal": "positive/neutral/negative/unknown",
    "events": [
      {{"title": "事件标题1", "date": "YYYY-MM-DD", "source": "来源", "relevance": "direct/indirect/weak/unknown", "impact": "positive/neutral/negative/unknown", "priced_in_risk": "low/medium/high/unknown", "summary": "与ETF关系和影响摘要"}},
      {{"title": "事件标题2", "date": "YYYY-MM-DD", "source": "来源", "relevance": "direct/indirect/weak/unknown", "impact": "positive/neutral/negative/unknown", "priced_in_risk": "low/medium/high/unknown", "summary": "与ETF关系和影响摘要"}}
    ]
  }},
  "short_term": {{"advice_type": "操作建议", "action": "具体动作", "conclusion": "一句话结论", "signals": ["依据1", "依据2"], "risks": ["风险1"], "confidence": 置信度数值}},
  "medium_term": {{"advice_type": "操作建议", "action": "具体动作", "conclusion": "一句话结论", "signals": ["依据1", "依据2"], "risks": ["风险1"], "confidence": 置信度数值}},
  "long_term": {{"advice_type": "操作建议", "action": "具体动作", "conclusion": "一句话结论", "signals": ["依据1", "依据2"], "risks": ["风险1"], "confidence": 置信度数值}}
}}"""

    @staticmethod
    def build_scheduled_prompt(
        etf_code: str,
        etf_name: str,
        shares: Decimal,
        cost_price: Decimal,
        current_price: Decimal,
        pnl_pct: Decimal,
        holding_days: Optional[int],
        kline_summary: str,
        indicators: dict,
    ) -> str:
        """构造定时任务使用的收盘分析 Prompt"""
        return f"""你是一名专业的ETF投资顾问。请基于今日收盘后数据和最新可核实信息，对该ETF持仓给出投资建议。

## 时间基准
{AdvisorService._prompt_time_context()}

## 品种信息
- 代码: {etf_code}, 名称: {etf_name}

## 持仓状态
- 份额: {shares}, 成本价: {cost_price:.4f}
- 最新收盘价/最新可用收盘价: {current_price:.4f}, 浮动盈亏: {pnl_pct:.2f}%
- 持仓天数: {holding_days or '未知'}

## 近期行情 (截至今日收盘的最近10个交易日)
{kline_summary}

## 技术指标 (基于截至今日收盘的历史数据计算)
- MA5={indicators.get('ma5', 'N/A')}, MA10={indicators.get('ma10', 'N/A')}, MA20={indicators.get('ma20', 'N/A')}
- MA60={indicators.get('ma60', 'N/A')}, MA120={indicators.get('ma120', 'N/A')}, MA250={indicators.get('ma250', 'N/A')}
- RSI(14)={indicators.get('rsi', 'N/A')}
- MACD: DIF={indicators.get('dif', 'N/A')}, DEA={indicators.get('dea', 'N/A')}, 柱={indicators.get('macd_bar', 'N/A')}
- 20日区间: 高点={indicators.get('high_20', 'N/A')}, 低点={indicators.get('low_20', 'N/A')}
- 60日区间: 高点={indicators.get('high_60', 'N/A')}, 低点={indicators.get('low_60', 'N/A')}
- 120日高点={indicators.get('high_120', 'N/A')}, 250日高点={indicators.get('high_250', 'N/A')}
- 距60日高点回撤={indicators.get('drawdown_60', 'N/A')}%, 距250日高点回撤={indicators.get('drawdown_250', 'N/A')}%
- 20日波动率={indicators.get('volatility_20', 'N/A')}%, 60日波动率={indicators.get('volatility_60', 'N/A')}%

分析要求：
1. 本次分析默认基于今日收盘后数据，不按盘中波动口径给出判断
2. 请综合考虑技术面、基本面、政策面和市场情绪
3. 通过模型自带的联网搜索能力主动搜索最新的相关新闻和政策消息；搜索和事件判断必须围绕上述当前时间基准，不要引用过期信息作为当前决策依据
4. 结论要更偏向“收盘后的复盘判断”和“下一交易日到未来数周的执行策略”
5. 如果行情源暂未更新到今日，则按“最新可用交易日收盘数据”理解，不要假设存在盘中实时价格

输出要求：
1. 给出一个顶层主决策，格式上必须包含:
   - main_judgment: 一句话主判断，建议写成“收盘后继续持有，等待回踩再加仓”这类可执行结论，50字以内
   - summary: 综合决策说明，80-120字，需明确这是基于今日收盘后的综合判断，并涵盖短期操作节奏和长期配置逻辑
   - action: 最终执行动作，必须是 "buy" / "sell" / "hold" / "add" / "reduce" 之一
   - why: 2到3条最关键依据，必须体现“因为哪些技术面/位置/波动信号/政策新闻，所以给出这个动作”，每条25字以内
   - news_basis: 0到2条和 ETF 相关的新闻依据，没有就返回空数组
   - policy_basis: 0到2条和政策相关的依据，没有就返回空数组
2. 同时给出 short_term、medium_term、long_term 三个周期的建议
3. 每个周期都包含:
   - advice_type: 必须是 "buy" / "sell" / "hold" / "add" / "reduce" 之一
   - action: 对应周期下的具体动作描述，20字以内，例如“观望等待回踩”“继续持有”“分批加仓”
   - conclusion: 一句话结论，30字以内
   - signals: 2到4条核心依据，优先引用均线、RSI、MACD、区间位置、回撤、波动率等已提供指标
   - risks: 1到2条主要风险，避免空泛表述
   - confidence: 0-100之间的整数
4. short_term 更关注下一交易日到 1-10 个交易日的节奏和短线波动
5. medium_term 更关注未来 1-3 个月趋势，作为收盘后主决策
6. long_term 更关注 3 个月以上趋势、回撤和配置价值
7. 三个周期的结论必须体现时间维度差异，不要重复同一句话
8. 顶层 main_judgment / action / why 必须和 medium_term 保持一致，形成“结论 -> 依据 -> 动作”的闭环
9. news_basis 和 policy_basis 必须来自模型联网搜索到的真实最新信息；如果当前模型不支持联网搜索或未检索到可靠结果，就返回空数组，不要编造
10. 必须输出 event_context，用于记录搜索状态、来源质量、事件相关性和是否可能已定价。search_status 为 success/partial 且有可用搜索结果时，events 输出 2到5条互不重复的新闻、政策或宏观事件；只有搜索不可用、结果不足或相关性弱时才允许少于2条，并在 summary 中说明限制。不要让新闻政策直接决定买卖，必须先判断事件和 ETF 的相关性、时效性、来源质量、已定价风险，再结合技术位置决定动作
11. 如果 event_context.search_status 不是 "success"，不能因为新闻政策给出 buy/add/sell；如果事件 relevance 是 "weak"，不能作为主要依据；如果利好但 priced_in_risk 是 "high"，短期不能追高，只能 hold 或等待回踩
12. 输出要直接、结构化，不要写额外解释文字

请直接输出JSON对象，不要添加任何markdown标记或代码块符号:
{{
  "main_judgment": "一句话主判断",
  "summary": "综合决策说明，80-120字",
  "action": "buy/add/hold/reduce/sell 中的一项",
  "why": ["关键依据1", "关键依据2"],
  "news_basis": ["相关新闻依据"],
  "policy_basis": ["政策依据"],
  "event_context": {{
    "search_status": "success/partial/unavailable",
    "source_quality": "high/medium/low/unknown",
    "policy_signal": "positive/neutral/negative/unknown",
    "macro_signal": "positive/neutral/negative/unknown",
    "news_signal": "positive/neutral/negative/unknown",
    "events": [
      {{"title": "事件标题1", "date": "YYYY-MM-DD", "source": "来源", "relevance": "direct/indirect/weak/unknown", "impact": "positive/neutral/negative/unknown", "priced_in_risk": "low/medium/high/unknown", "summary": "与ETF关系和影响摘要"}},
      {{"title": "事件标题2", "date": "YYYY-MM-DD", "source": "来源", "relevance": "direct/indirect/weak/unknown", "impact": "positive/neutral/negative/unknown", "priced_in_risk": "low/medium/high/unknown", "summary": "与ETF关系和影响摘要"}}
    ]
  }},
  "short_term": {{"advice_type": "操作建议", "action": "具体动作", "conclusion": "一句话结论", "signals": ["依据1", "依据2"], "risks": ["风险1"], "confidence": 置信度数值}},
  "medium_term": {{"advice_type": "操作建议", "action": "具体动作", "conclusion": "一句话结论", "signals": ["依据1", "依据2"], "risks": ["风险1"], "confidence": 置信度数值}},
  "long_term": {{"advice_type": "操作建议", "action": "具体动作", "conclusion": "一句话结论", "signals": ["依据1", "依据2"], "risks": ["风险1"], "confidence": 置信度数值}}
}}"""

    @staticmethod
    def enrich_horizon_indicators(kline_data: list, indicators) -> dict:
        closes = [float(item.close_price) for item in kline_data]
        highs = [float(item.high_price) for item in kline_data]
        lows = [float(item.low_price) for item in kline_data]

        def avg_last(values: list[float], days: int):
            return round(sum(values[-days:]) / days, 4) if len(values) >= days else None

        def max_last(values: list[float], days: int):
            return round(max(values[-days:]), 4) if len(values) >= days else None

        def min_last(values: list[float], days: int):
            return round(min(values[-days:]), 4) if len(values) >= days else None

        def drawdown_from_high(days: int):
            if len(closes) < days:
                return None
            high = max(highs[-days:])
            current = closes[-1]
            return round((current - high) / high * 100, 2) if high else None

        def annualized_volatility(days: int):
            if len(closes) < days + 1:
                return None
            returns = []
            sample = closes[-(days + 1):]
            for prev, curr in zip(sample[:-1], sample[1:]):
                if prev:
                    returns.append((curr - prev) / prev)
            if len(returns) < 2:
                return None
            mean = sum(returns) / len(returns)
            variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
            return round((variance ** 0.5) * (252 ** 0.5) * 100, 2)

        return {
            'ma5': indicators.ma5,
            'ma10': indicators.ma10,
            'ma20': indicators.ma20,
            'ma60': avg_last(closes, 60),
            'ma120': avg_last(closes, 120),
            'ma250': avg_last(closes, 250),
            'rsi': indicators.rsi14,
            'dif': indicators.macd_dif,
            'dea': indicators.macd_dea,
            'macd_bar': indicators.macd_histogram,
            'high_20': max_last(highs, 20),
            'low_20': min_last(lows, 20),
            'high_60': max_last(highs, 60),
            'low_60': min_last(lows, 60),
            'high_120': max_last(highs, 120),
            'high_250': max_last(highs, 250),
            'drawdown_60': drawdown_from_high(60),
            'drawdown_250': drawdown_from_high(250),
            'volatility_20': annualized_volatility(20),
            'volatility_60': annualized_volatility(60),
        }

    @staticmethod
    def parse_period_advice(result_json: dict, key: str) -> PeriodAdvice:
        data = result_json.get(key) or {}
        signals = data.get("signals", [])
        risks = data.get("risks", [])
        if not isinstance(signals, list):
            signals = []
        if not isinstance(risks, list):
            risks = []
        return PeriodAdvice(
            advice_type=data.get("advice_type", "hold"),
            action=data.get("action", data.get("conclusion", data.get("reason", "继续观察"))),
            conclusion=data.get("conclusion", data.get("reason", "暂无建议")),
            signals=[str(item) for item in signals[:4] if str(item).strip()],
            risks=[str(item) for item in risks[:2] if str(item).strip()],
            confidence=float(data.get("confidence", 50)),
        )

    @staticmethod
    def parse_basis_items(result_json: dict, key: str, limit: int = 3) -> List[str]:
        value = result_json.get(key, [])
        if isinstance(value, list):
            return [str(item) for item in value[:limit] if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    @staticmethod
    def parse_event_context(result_json: dict) -> EventContext:
        """解析模型搜索得到的事件上下文"""
        raw = result_json.get("event_context") or {}
        if not isinstance(raw, dict):
            raw = {}

        def one_of(value, allowed: set[str], default: str):
            value = str(value or "").strip().lower()
            return value if value in allowed else default

        events = []
        raw_events = raw.get("events", [])
        if not isinstance(raw_events, list):
            raw_events = []
        for item in raw_events[:5]:
            if not isinstance(item, dict):
                continue
            events.append(EventItem(
                title=str(item.get("title") or "").strip()[:120],
                date=str(item.get("date") or "").strip()[:30] or None,
                source=str(item.get("source") or "").strip()[:80],
                relevance=one_of(item.get("relevance"), {"direct", "indirect", "weak", "unknown"}, "unknown"),
                impact=one_of(item.get("impact"), {"positive", "neutral", "negative", "unknown"}, "unknown"),
                priced_in_risk=one_of(item.get("priced_in_risk"), {"low", "medium", "high", "unknown"}, "unknown"),
                summary=str(item.get("summary") or "").strip()[:180],
            ))

        return EventContext(
            search_status=one_of(raw.get("search_status"), {"success", "partial", "unavailable"}, "unavailable"),
            source_quality=one_of(raw.get("source_quality"), {"high", "medium", "low", "unknown"}, "unknown"),
            policy_signal=one_of(raw.get("policy_signal"), {"positive", "neutral", "negative", "unknown"}, "unknown"),
            macro_signal=one_of(raw.get("macro_signal"), {"positive", "neutral", "negative", "unknown"}, "unknown"),
            news_signal=one_of(raw.get("news_signal"), {"positive", "neutral", "negative", "unknown"}, "unknown"),
            events=events,
        )

    @staticmethod
    def unavailable_event_context(reason: str = "") -> EventContext:
        return EventContext(
            search_status="unavailable",
            source_quality="low",
            policy_signal="unknown",
            macro_signal="unknown",
            news_signal="unknown",
            events=[EventItem(
                title="搜索或模型输出不可用",
                relevance="unknown",
                impact="unknown",
                priced_in_risk="unknown",
                summary=reason[:180],
            )] if reason else [],
        )

    @staticmethod
    def format_multi_horizon_reason(
        main_judgment: str,
        summary: str,
        action: str,
        why: List[str],
        news_basis: List[str],
        policy_basis: List[str],
        event_context: EventContext,
        short_term: PeriodAdvice,
        medium_term: PeriodAdvice,
        long_term: PeriodAdvice,
    ) -> str:
        why_text = ";".join(why) or "暂无"
        news_text = ";".join(news_basis) or "暂无"
        policy_text = ";".join(policy_basis) or "暂无"
        event_lines = [
            f"搜索状态：{event_context.search_status}",
            f"来源质量：{event_context.source_quality}",
            f"政策信号：{event_context.policy_signal}",
            f"宏观信号：{event_context.macro_signal}",
            f"新闻信号：{event_context.news_signal}",
        ]
        if event_context.events:
            event_lines.append("事件列表：")
            for index, event in enumerate(event_context.events[:5], start=1):
                event_lines.append(
                    f"{index}. {event.date or '日期未知'} {event.source or '来源未知'} "
                    f"[{event.relevance}/{event.impact}/priced_in={event.priced_in_risk}] "
                    f"{event.title or '未命名事件'} - {event.summary or '暂无摘要'}"
                )
        event_text = "\n".join(event_lines)
        return (
            f"主判断：{main_judgment}\n"
            f"综合说明：{summary}\n"
            f"执行动作：{action}\n"
            f"关键依据：{why_text}\n"
            f"新闻依据：{news_text}\n"
            f"政策依据：{policy_text}\n\n"
            f"事件上下文：\n{event_text}\n\n"
            f"【短期】{short_term.advice_type}（{short_term.confidence:.0f}%）\n"
            f"动作：{short_term.action}\n"
            f"结论：{short_term.conclusion}\n"
            f"信号：{'；'.join(short_term.signals) or '暂无'}\n"
            f"风险：{'；'.join(short_term.risks) or '暂无'}\n\n"
            f"【中期】{medium_term.advice_type}（{medium_term.confidence:.0f}%）\n"
            f"动作：{medium_term.action}\n"
            f"结论：{medium_term.conclusion}\n"
            f"信号：{'；'.join(medium_term.signals) or '暂无'}\n"
            f"风险：{'；'.join(medium_term.risks) or '暂无'}\n\n"
            f"【长期】{long_term.advice_type}（{long_term.confidence:.0f}%）\n"
            f"动作：{long_term.action}\n"
            f"结论：{long_term.conclusion}\n"
            f"信号：{'；'.join(long_term.signals) or '暂无'}\n"
            f"风险：{'；'.join(long_term.risks) or '暂无'}"
        )

    @staticmethod
    def build_account_analysis_prompt(
        portfolio_summary_text: str,
        holdings_text: str,
        account_balance: float,
    ) -> str:
        """构造账户级分析 Prompt"""
        return f"""你是一名专业的ETF投资顾问。请根据当前账户整体情况，给出账户层面的投资建议。

## 时间基准
{AdvisorService._prompt_time_context()}

## 账户概览
{portfolio_summary_text}

## 持仓明细
{holdings_text}

## 可用资金
- Cash (liquid funds available): {account_balance:.2f} 元

请重点分析：
1. 当前整体仓位是否偏高、偏低或合理
2. 当前持仓是否过于集中，是否需要分散或再平衡
3. 哪些方向应该继续持有，哪些方向应该减仓或观察
4. 接下来1-3条最重要的账户操作建议
5. 如引用市场、政策、宏观或新闻背景，必须以时间基准中的当前日期为准，优先使用近期信息，不要用过期事件作为当前调仓依据

输出要求：
1. summary: 对当前账户状态的总体判断，120字以内
2. position_advice: 对整体仓位的建议，80字以内
3. rebalance_advice: 对结构调整/分散配置的建议，120字以内
4. risk_level: 风险等级，必须是 "low" / "medium" / "high" 之一
5. key_actions: 1到3条具体行动建议的字符串数组
6. confidence: 0-100之间的整数

请直接输出JSON对象，不要添加markdown标记或代码块:
{{"summary":"...","position_advice":"...","rebalance_advice":"...","risk_level":"medium","key_actions":["..."],"confidence":75}}"""

    @staticmethod
    def build_scheduled_account_analysis_prompt(
        portfolio_summary_text: str,
        holdings_text: str,
        account_balance: float,
    ) -> str:
        """构造定时任务使用的账户级分析 Prompt"""
        return f"""你是一名专业的ETF投资顾问。请基于今日收盘后数据，对当前账户整体情况给出本周分析结论和后续投资建议。

## 时间基准
{AdvisorService._prompt_time_context()}

## 账户概览 (基于今日收盘后账户快照)
{portfolio_summary_text}

## 持仓明细 (基于今日收盘后持仓快照)
{holdings_text}

## 可用资金
- Cash (liquid funds available after close): {account_balance:.2f} 元

请重点分析：
1. 基于今日收盘后的账户状态，判断本周整体仓位是否偏高、偏低或合理
2. 判断当前持仓在本周视角下是否过于集中，是否需要分散或再平衡
3. 哪些方向本周应继续持有，哪些方向本周应减仓或观察
4. 给出接下来一周最重要的 1-3 条账户操作建议
5. 如果行情源未完全更新到今日，则按最新可用交易日收盘后的账户快照理解，不要按盘中口径推断
6. 如引用市场、政策、宏观或新闻背景，必须以时间基准中的当前日期为准，优先使用近期信息，不要用过期事件作为本周调仓依据

输出要求：
1. summary: 对当前账户状态的本周总体判断，120字以内，明确体现“本周分析结论”
2. position_advice: 对整体仓位的本周建议，80字以内
3. rebalance_advice: 对结构调整/分散配置的本周建议，120字以内
4. risk_level: 风险等级，必须是 "low" / "medium" / "high" 之一
5. key_actions: 1到3条本周内可执行的具体行动建议字符串数组
6. confidence: 0-100之间的整数

请直接输出JSON对象，不要添加markdown标记或代码块:
{{"summary":"...","position_advice":"...","rebalance_advice":"...","risk_level":"medium","key_actions":["..."],"confidence":75}}"""

    @staticmethod
    def format_account_summary(
        portfolios: List[PortfolioWithMarket],
        total_market_value: float,
        total_cost: float,
        total_pnl: float,
        total_pnl_pct: float,
        account_balance: float,
        category_distribution: dict,
    ) -> str:
        """格式化账户概览"""
        total_assets = total_market_value + account_balance
        cash_ratio = (account_balance / total_assets * 100) if total_assets > 0 else 0.0
        invested_ratio = (total_market_value / total_assets * 100) if total_assets > 0 else 0.0
        category_text = "、".join(
            f"{name}:{value / total_market_value * 100:.1f}%"
            for name, value in sorted(category_distribution.items(), key=lambda item: item[1], reverse=True)
            if total_market_value > 0
        ) or "暂无分类数据"

        return "\n".join([
            f"- 持仓数量: {len(portfolios)}",
            f"- 持仓市值: {total_market_value:.2f} 元",
            f"- 总成本: {total_cost:.2f} 元",
            f"- 总盈亏: {total_pnl:.2f} 元 ({total_pnl_pct:.2f}%)",
            f"- 账户总资产(持仓市值+现金余额): {total_assets:.2f} 元",
            f"- 现金占比: {cash_ratio:.2f}%",
            f"- 持仓占比: {invested_ratio:.2f}%",
            f"- 分类分布: {category_text}",
        ])

    @staticmethod
    def format_account_holdings(portfolios: List[PortfolioWithMarket], total_market_value: float) -> str:
        """格式化持仓明细"""
        if not portfolios:
            return "暂无持仓"

        lines = []
        for portfolio in portfolios:
            market_value = portfolio.market_value or 0.0
            weight = (market_value / total_market_value * 100) if total_market_value > 0 else 0.0
            category = MarketService._guess_category(portfolio.etf_name or "")
            lines.append(
                f"- {portfolio.etf_code} {portfolio.etf_name or ''}: "
                f"市值 {market_value:.2f} 元, 权重 {weight:.2f}%, "
                f"盈亏 {portfolio.pnl or 0.0:.2f} 元 ({portfolio.pnl_pct or 0.0:.2f}%), "
                f"分类 {category}, 持仓天数 {portfolio.holding_days if portfolio.holding_days is not None else '未知'}"
            )
        return "\n".join(lines)

    @staticmethod
    def format_account_analysis_reason(analysis: AccountAnalysisResponse) -> str:
        """格式化账户分析历史文本"""
        actions_text = "\n".join(
            f"{index + 1}. {action}" for index, action in enumerate(analysis.key_actions)
        ) or "暂无具体操作建议"
        return "\n".join([
            f"总体判断：{analysis.summary}",
            f"仓位建议：{analysis.position_advice}",
            f"调仓建议：{analysis.rebalance_advice}",
            f"风险等级：{analysis.risk_level}",
            "关键操作：",
            actions_text,
        ])

    @classmethod
    def now_in_shanghai(cls) -> datetime:
        """获取北京时间"""
        return datetime.now(cls.SHANGHAI_TZ)

    @staticmethod
    def now_in_utc_naive() -> datetime:
        """获取用于写入无时区数据库列的 UTC naive 时间"""
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @classmethod
    def ensure_shanghai_datetime(cls, value: Optional[datetime]) -> datetime:
        """将时间统一为北京时间"""
        if value is None:
            return cls.now_in_shanghai()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).astimezone(cls.SHANGHAI_TZ)
        return value.astimezone(cls.SHANGHAI_TZ)

    @classmethod
    def build_advice_log_response(
        cls,
        log: AdviceLog,
        etf_name: Optional[str] = None,
    ) -> AdviceLogResponse:
        """将持久化的建议日志转换为前端可直接展示的响应"""
        payload = {c.key: getattr(log, c.key) for c in AdviceLog.__table__.columns}
        payload["created_at"] = cls.ensure_shanghai_datetime(log.created_at)
        return AdviceLogResponse(
            **payload,
            etf_name=etf_name,
        )

    @classmethod
    def parse_account_analysis_reason(
        cls,
        reason: Optional[str],
        confidence: Optional[Decimal],
        created_at: Optional[datetime],
    ) -> AccountAnalysisResponse:
        """从历史文本恢复账户分析结构"""
        text = reason or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        key_actions: List[str] = []
        in_actions = False
        data = {
            "summary": "",
            "position_advice": "",
            "rebalance_advice": "",
            "risk_level": "medium",
        }

        for line in lines:
            if line == "关键操作：":
                in_actions = True
                continue

            if in_actions:
                action = line
                if ". " in action:
                    action = action.split(". ", 1)[1]
                key_actions.append(action)
                continue

            if line.startswith("总体判断："):
                data["summary"] = line.removeprefix("总体判断：").strip()
            elif line.startswith("仓位建议："):
                data["position_advice"] = line.removeprefix("仓位建议：").strip()
            elif line.startswith("调仓建议："):
                data["rebalance_advice"] = line.removeprefix("调仓建议：").strip()
            elif line.startswith("风险等级："):
                risk = line.removeprefix("风险等级：").strip().lower()
                data["risk_level"] = risk if risk in {"low", "medium", "high"} else "medium"

        return AccountAnalysisResponse(
            summary=data["summary"] or "暂无账户分析摘要",
            position_advice=data["position_advice"] or "暂无仓位建议",
            rebalance_advice=data["rebalance_advice"] or "暂无调仓建议",
            risk_level=data["risk_level"],
            key_actions=key_actions[:3],
            confidence=float(confidence) if confidence is not None else 0,
            created_at=cls.ensure_shanghai_datetime(created_at),
        )
    
    @staticmethod
    def format_kline_summary(kline_data: List) -> str:
        """格式化K线摘要"""
        if not kline_data:
            return "无数据"
        
        lines = []
        for item in kline_data[-10:]:
            lines.append(
                f"{item.trade_date}: 开{item.open_price:.3f} "
                f"收{item.close_price:.3f} "
                f"高{item.high_price:.3f} "
                f"低{item.low_price:.3f} "
                f"涨跌{item.change_pct:.2f}%"
            )
        return "\n".join(lines)

    @classmethod
    async def _build_advice_payload(
        cls,
        p: Portfolio,
        quote,
        llm: BaseLLMClient,
        analysis_mode: str = "manual",
    ) -> dict:
        """构建单个持仓建议结果，不在并发任务中访问数据库会话。"""
        market_value = float(p.shares) * quote.price
        cost = float(p.shares) * float(p.cost_price)
        pnl = market_value - cost
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0

        holding_days = None
        if p.buy_date:
            holding_days = (date.today() - p.buy_date).days

        kline_data = await MarketService.get_history_kline(p.etf_code, days=250)
        kline_summary = cls.format_kline_summary(kline_data)
        indicators = MarketService.calculate_technical_indicators(kline_data)
        indicators_dict = cls.enrich_horizon_indicators(kline_data, indicators)

        asset_type = getattr(p, "asset_type", "etf") or "etf"
        prompt_builder = cls.build_scheduled_prompt if analysis_mode == "scheduled" else cls.build_prompt
        prompt = prompt_builder(
            etf_code=p.etf_code,
            etf_name=quote.name,
            shares=p.shares,
            cost_price=p.cost_price,
            current_price=quote.price,
            pnl_pct=pnl_pct,
            holding_days=holding_days,
            kline_summary=kline_summary,
            indicators=indicators_dict,
        )
        if asset_type == "otc_fund":
            prompt = prompt.replace("你是一名专业的ETF投资顾问", "你是一名专业的场外基金投资顾问")
            prompt = prompt.replace("## 品种信息\n- 代码:", "## 品种信息\n- 资产类型: 场外基金（净值型资产，不适用场内溢价、IOPV、成交量追价规则）\n- 代码:")
            prompt = prompt.replace("成本价", "成本净值").replace("当前价", "最新单位净值").replace("最新收盘价/最新可用收盘价", "最新单位净值/最新可用净值")
            prompt = prompt.replace("ETF 相关", "该基金相关").replace("和 ETF 的相关性", "和该基金底层资产的相关性")
        elif asset_type == "stock":
            prompt = prompt.replace("你是一名专业的ETF投资顾问", "你是一名专业的股票投资顾问")
            prompt = prompt.replace("## 品种信息\n- 代码:", "## 品种信息\n- 资产类型: 股票（个股资产，不适用ETF估值百分位、IOPV和溢价率规则）\n- 代码:")
            prompt = prompt.replace("ETF 相关", "该股票相关").replace("和 ETF 的相关性", "和该股票所属行业及市场的相关性")
            prompt += "\n\n补充要求：股票建议必须强调单票集中度、波动、基本面和止损纪律，不要使用ETF定投增强或资产桶轮动话术。"
        elif asset_type in {"cash", "money_fund"}:
            label = "现金" if asset_type == "cash" else "货币基金"
            prompt = prompt.replace("你是一名专业的ETF投资顾问", "你是一名专业的现金管理顾问")
            prompt = prompt.replace("## 品种信息\n- 代码:", f"## 品种信息\n- 资产类型: {label}（现金管理资产，不生成趋势交易建议）\n- 代码:")
            prompt += f"\n\n补充要求：这是{label}仓位，只从流动性、组合现金比例、再平衡资金来源和收益率下行风险角度建议，不要给出追涨杀跌或技术交易信号。"
        prompt = await cls.enrich_prompt_with_tavily_tools(
            llm,
            prompt,
            context=f"portfolio_advice:{p.etf_code}:{analysis_mode}",
            max_calls=1,
        )

        try:
            result_json = await cls.chat_json_with_logging(
                llm,
                prompt,
                context=f"portfolio_advice:{p.etf_code}:{analysis_mode}",
            )
            if "error" in result_json:
                raw_reason = f"AI分析结果（JSON解析失败）:\n{result_json.get('raw', '无响应内容')}"
                short_term = PeriodAdvice(advice_type="hold", action="继续观察", conclusion=raw_reason, signals=[], risks=["返回格式异常"], confidence=30)
                medium_term = PeriodAdvice(advice_type="hold", action="继续观察", conclusion=raw_reason, signals=[], risks=["返回格式异常"], confidence=30)
                long_term = PeriodAdvice(advice_type="hold", action="继续观察", conclusion=raw_reason, signals=[], risks=["返回格式异常"], confidence=30)
                main_judgment = raw_reason
                summary = ""
                action = "hold"
                why = ["模型返回格式异常，未能提炼出稳定依据"]
                news_basis = []
                policy_basis = []
                event_context = cls.unavailable_event_context("模型返回格式异常，未能解析结构化搜索结果")
            else:
                short_term = cls.parse_period_advice(result_json, "short_term")
                medium_term = cls.parse_period_advice(result_json, "medium_term")
                long_term = cls.parse_period_advice(result_json, "long_term")
                main_judgment = str(result_json.get("main_judgment", medium_term.conclusion)).strip() or medium_term.conclusion
                summary = str(result_json.get("summary", "")).strip()
                action = str(result_json.get("action", medium_term.advice_type)).strip() or medium_term.advice_type
                why = cls.parse_basis_items(result_json, "why", limit=3)
                news_basis = cls.parse_basis_items(result_json, "news_basis", limit=2)
                policy_basis = cls.parse_basis_items(result_json, "policy_basis", limit=2)
                event_context = cls.parse_event_context(result_json)
        except Exception as e:
            short_term = PeriodAdvice(advice_type="hold", action="继续观察", conclusion=f"LLM调用失败: {str(e)}", signals=[], risks=["模型调用失败"], confidence=0)
            medium_term = PeriodAdvice(advice_type="hold", action="继续观察", conclusion=f"LLM调用失败: {str(e)}", signals=[], risks=["模型调用失败"], confidence=0)
            long_term = PeriodAdvice(advice_type="hold", action="继续观察", conclusion=f"LLM调用失败: {str(e)}", signals=[], risks=["模型调用失败"], confidence=0)
            main_judgment = medium_term.conclusion
            summary = ""
            action = medium_term.advice_type
            why = ["模型调用失败，暂时无法生成关键依据"]
            news_basis = []
            policy_basis = []
            event_context = cls.unavailable_event_context(f"模型调用失败: {str(e)}")

        advice_type = medium_term.advice_type
        reason = cls.format_multi_horizon_reason(
            main_judgment, summary, action, why, news_basis, policy_basis, event_context, short_term, medium_term, long_term
        )
        confidence = Decimal(str(medium_term.confidence))

        return {
            "portfolio": p,
            "quote": quote,
            "advice_type": advice_type,
            "main_judgment": main_judgment,
            "summary": summary,
            "action": action,
            "why": why,
            "news_basis": news_basis,
            "policy_basis": policy_basis,
            "event_context": event_context,
            "reason": reason,
            "confidence": confidence,
            "short_term": short_term,
            "medium_term": medium_term,
            "long_term": long_term,
            "pnl_pct": pnl_pct,
            "created_at": cls.now_in_shanghai(),
        }
    
    @classmethod
    async def generate_advice(
        cls,
        session: AsyncSession,
        etf_codes: Optional[List[str]] = None,
        user_id: Optional[int] = None,
        analysis_mode: str = "manual",
    ) -> List[AdviceResponse]:
        """生成投资建议"""
        if user_id is None:
            raise ValueError("generate_advice requires user_id")

        # 获取持仓
        query = select(Portfolio).where(Portfolio.user_id == user_id)
        if etf_codes:
            query = query.where(Portfolio.etf_code.in_(etf_codes))
        
        result = await session.execute(query)
        portfolios = result.scalars().all()
        
        if not portfolios:
            return []
        
        # 获取持仓ETF代码列表
        portfolio_codes = [p.etf_code for p in portfolios]
        
        # 获取实时行情（使用新的异步方法）
        quotes = await MarketService.get_quotes_for_codes(portfolio_codes)
        
        llm = cls.get_llm_client()
        semaphore = asyncio.Semaphore(cls.ADVICE_CONCURRENCY)

        async def analyze_portfolio(p: Portfolio) -> Optional[dict]:
            quote = quotes.get(p.etf_code)
            if not quote:
                return None
            async with semaphore:
                return await cls._build_advice_payload(p, quote, llm, analysis_mode=analysis_mode)

        advice_payloads = [
            payload
            for payload in await asyncio.gather(*(analyze_portfolio(p) for p in portfolios))
            if payload is not None
        ]

        advices = []
        for payload in advice_payloads:
            p = payload["portfolio"]
            quote = payload["quote"]
            log = AdviceLog(
                user_id=user_id,
                etf_code=p.etf_code,
                advice_type=payload["advice_type"],
                reason=payload["reason"],
                confidence=payload["confidence"],
                llm_provider=settings.llm_provider,
                llm_model=llm.model if hasattr(llm, 'model') else None,
                created_at=cls.now_in_utc_naive(),
            )
            session.add(log)

            advices.append(AdviceResponse(
                etf_code=p.etf_code,
                etf_name=quote.name,
                advice_type=payload["advice_type"],
                main_judgment=payload["main_judgment"],
                summary=payload["summary"],
                action=payload["action"],
                why=payload["why"],
                news_basis=payload["news_basis"],
                policy_basis=payload["policy_basis"],
                event_context=payload["event_context"],
                reason=payload["reason"],
                confidence=payload["confidence"],
                short_term=payload["short_term"],
                medium_term=payload["medium_term"],
                long_term=payload["long_term"],
                current_price=quote.price,
                pnl_pct=payload["pnl_pct"],
                created_at=payload["created_at"],
            ))
        
        await session.flush()
        return advices
    
    @classmethod
    async def generate_advice_for_portfolio(
        cls,
        session: AsyncSession,
        portfolio_id: int,
        user_id: Optional[int] = None,
    ) -> Optional[AdviceResponse]:
        """生成单个持仓的投资建议"""
        if user_id is None:
            raise ValueError("generate_advice_for_portfolio requires user_id")

        # 获取持仓
        query = select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user_id,
        )
        
        result = await session.execute(query)
        p = result.scalar_one_or_none()
        if not p:
            return None
        
        # 获取实时行情
        quotes = await MarketService.get_quotes_for_codes([p.etf_code])
        quote = quotes.get(p.etf_code)
        if not quote:
            return None
        
        llm = cls.get_llm_client()
        payload = await cls._build_advice_payload(p, quote, llm, analysis_mode="manual")
        
        # 保存日志
        log = AdviceLog(
            user_id=user_id,
            etf_code=p.etf_code,
            advice_type=payload["advice_type"],
            reason=payload["reason"],
            confidence=payload["confidence"],
            llm_provider=settings.llm_provider,
            llm_model=llm.model if hasattr(llm, 'model') else None,
            created_at=cls.now_in_utc_naive(),
        )
        session.add(log)
        await session.flush()
        
        return AdviceResponse(
            etf_code=p.etf_code,
            etf_name=quote.name,
            advice_type=payload["advice_type"],
            main_judgment=payload["main_judgment"],
            summary=payload["summary"],
            action=payload["action"],
            why=payload["why"],
            news_basis=payload["news_basis"],
            policy_basis=payload["policy_basis"],
            event_context=payload["event_context"],
            reason=payload["reason"],
            confidence=payload["confidence"],
            short_term=payload["short_term"],
            medium_term=payload["medium_term"],
            long_term=payload["long_term"],
            current_price=quote.price,
            pnl_pct=payload["pnl_pct"],
            created_at=payload["created_at"],
        )
    
    @classmethod
    async def get_history(
        cls,
        session: AsyncSession, 
        limit: int = 50,
        user_id: Optional[int] = None,
    ) -> List[AdviceLogResponse]:
        """获取历史建议记录"""
        if user_id is None:
            raise ValueError("get_history requires user_id")

        query = (
            select(AdviceLog, EtfInfo.name.label("etf_name"))
            .where(AdviceLog.user_id == user_id)
            .outerjoin(EtfInfo, AdviceLog.etf_code == EtfInfo.code)
            .order_by(AdviceLog.created_at.desc())
        )
        query = query.limit(limit)
        
        result = await session.execute(query)
        rows = result.all()
        
        # 收集需要补充名称的 ETF 代码
        etf_codes_to_fetch = set()
        for log, etf_name in rows:
            if (
                not etf_name
                and log.etf_code
                and log.etf_code != cls.ACCOUNT_ANALYSIS_CODE
            ):
                etf_codes_to_fetch.add(log.etf_code)
        
        # 从实时行情获取缺失的 ETF 名称
        etf_names_from_market = {}
        if etf_codes_to_fetch:
            try:
                quotes = await MarketService.get_quotes_for_codes(list(etf_codes_to_fetch))
                etf_names_from_market = {code: quote.name for code, quote in quotes.items() if quote.name}
            except Exception as e:
                print(f"[AdvisorService] 从行情获取ETF名称失败: {e}")
        
        return [
            cls.build_advice_log_response(
                log,
                etf_name=(
                    cls.ACCOUNT_ANALYSIS_NAME
                    if log.etf_code == cls.ACCOUNT_ANALYSIS_CODE
                    else etf_name or etf_names_from_market.get(log.etf_code, None)
                ),
            )
            for log, etf_name in rows
        ]

    @classmethod
    async def generate_account_analysis(
        cls,
        session: AsyncSession,
        user_id: int,
        account_balance: Optional[Decimal] = None,
        analysis_mode: str = "manual",
    ) -> AccountAnalysisResponse:
        """生成账户级投资建议"""
        portfolios = await PortfolioService.get_with_market(session, user_id=user_id)
        summary = PortfolioService.build_summary_from_portfolios(portfolios)
        available_cash = float(account_balance) if account_balance is not None else 0.0

        if not portfolios:
            analysis = AccountAnalysisResponse(
                summary="当前账户暂无持仓，整体风险暴露较低。",
                position_advice="当前仓位偏低，可先保持观望并逐步建立仓位。",
                rebalance_advice="暂无调仓需求，建议先明确投资目标后再分批配置ETF。",
                risk_level="low",
                key_actions=[
                    "先建立关注ETF清单，避免一次性满仓",
                    "优先从宽基ETF开始分批建仓",
                ],
                confidence=85,
                created_at=cls.now_in_shanghai(),
            )
            session.add(AdviceLog(
                user_id=user_id,
                etf_code=cls.ACCOUNT_ANALYSIS_CODE,
                advice_type="account",
                reason=cls.format_account_analysis_reason(analysis),
                confidence=Decimal(str(analysis.confidence)),
                llm_provider=settings.llm_provider,
                llm_model=None,
                created_at=cls.now_in_utc_naive(),
            ))
            await session.flush()
            return analysis

        portfolio_summary_text = cls.format_account_summary(
            portfolios=portfolios,
            total_market_value=summary.total_market_value,
            total_cost=summary.total_cost,
            total_pnl=summary.total_pnl,
            total_pnl_pct=summary.total_pnl_pct,
            account_balance=available_cash,
            category_distribution=summary.category_distribution,
        )
        holdings_text = cls.format_account_holdings(portfolios, summary.total_market_value)
        prompt_builder = (
            cls.build_scheduled_account_analysis_prompt
            if analysis_mode == "scheduled"
            else cls.build_account_analysis_prompt
        )
        prompt = prompt_builder(
            portfolio_summary_text=portfolio_summary_text,
            holdings_text=holdings_text,
            account_balance=available_cash,
        )

        llm = cls.get_llm_client()
        prompt = await cls.enrich_prompt_with_tavily_tools(
            llm,
            prompt,
            context=f"account_analysis:{analysis_mode}",
            max_calls=1,
        )
        try:
            result_json = await cls.chat_json_with_logging(
                llm,
                prompt,
                context=f"account_analysis:{analysis_mode}",
            )
            key_actions = result_json.get("key_actions", [])
            if not isinstance(key_actions, list):
                key_actions = []

            analysis = AccountAnalysisResponse(
                summary=result_json.get("summary", "当前账户整体结构中性，建议结合风险偏好持续跟踪。"),
                position_advice=result_json.get("position_advice", "当前仓位基本合理，建议分批调整。"),
                rebalance_advice=result_json.get("rebalance_advice", "建议关注持仓集中度，必要时逐步再平衡。"),
                risk_level=result_json.get("risk_level", "medium"),
                key_actions=[str(item) for item in key_actions[:3] if str(item).strip()],
                confidence=float(result_json.get("confidence", 70)),
                created_at=cls.now_in_shanghai(),
            )
            session.add(AdviceLog(
                user_id=user_id,
                etf_code=cls.ACCOUNT_ANALYSIS_CODE,
                advice_type="account",
                reason=cls.format_account_analysis_reason(analysis),
                confidence=Decimal(str(analysis.confidence)),
                llm_provider=settings.llm_provider,
                llm_model=llm.model if hasattr(llm, 'model') else None,
                created_at=cls.now_in_utc_naive(),
            ))
            await session.flush()
            return analysis
        except Exception as e:
            analysis = AccountAnalysisResponse(
                summary="账户分析暂时失败，建议先根据总仓位和集中度人工复核。",
                position_advice="当前建议暂缓大幅加仓，等待分析恢复后再调整。",
                rebalance_advice=f"LLM调用失败: {str(e)}",
                risk_level="medium",
                key_actions=["稍后重试账户分析", "优先检查高权重持仓的风险集中度"],
                confidence=0,
                created_at=cls.now_in_shanghai(),
            )
            session.add(AdviceLog(
                user_id=user_id,
                etf_code=cls.ACCOUNT_ANALYSIS_CODE,
                advice_type="account",
                reason=cls.format_account_analysis_reason(analysis),
                confidence=Decimal("0"),
                llm_provider=settings.llm_provider,
                llm_model=llm.model if hasattr(llm, 'model') else None,
                created_at=cls.now_in_utc_naive(),
            ))
            await session.flush()
            return analysis

    @classmethod
    async def get_latest_account_analysis(
        cls,
        session: AsyncSession,
        user_id: int,
    ) -> Optional[AccountAnalysisResponse]:
        """获取最近一次账户级投资建议"""
        result = await session.execute(
            select(AdviceLog)
            .where(
                AdviceLog.user_id == user_id,
                AdviceLog.etf_code == cls.ACCOUNT_ANALYSIS_CODE,
                AdviceLog.advice_type == "account",
            )
            .order_by(AdviceLog.created_at.desc(), AdviceLog.id.desc())
            .limit(1)
        )
        log = result.scalar_one_or_none()
        if not log:
            return None

        return cls.parse_account_analysis_reason(log.reason, log.confidence, log.created_at)

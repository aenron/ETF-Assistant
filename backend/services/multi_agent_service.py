from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import MultiAgentRun, Portfolio, User
from schemas.multi_agent import (
    MultiAgentArbiterSummary,
    MultiAgentContextSummary,
    MultiAgentDebateRound,
    MultiAgentFinalConclusion,
    MultiAgentRunCreate,
    MultiAgentRunDetailResponse,
    MultiAgentRunListResponse,
    MultiAgentRunResponse,
    MultiAgentRunUpdate,
    MultiAgentRoleOpinion,
    MultiAgentScene,
    MultiAgentSearchMetadata,
)
from services.tavily_service import TavilySearchResponse, TavilySearchService
from utils.timezone import now_in_shanghai


@dataclass(frozen=True)
class RoleBlueprint:
    key: str
    role_name: str
    focus: str


@dataclass(frozen=True)
class SearchBundle:
    prompt_block: str
    metadata: list[MultiAgentSearchMetadata]


@dataclass(frozen=True)
class TechnicalContextBundle:
    prompt_block: str
    codes: list[str]


@dataclass(frozen=True)
class PolicyEventContextBundle:
    prompt_block: str
    metadata: list[MultiAgentSearchMetadata]


class MultiAgentService:
    """场景化 LLM 多智能体投资辩论编排器。"""

    ROLE_COUNT_LIMIT = 4
    ROLE_MAX_ATTEMPTS = 3

    @staticmethod
    def now_in_shanghai() -> datetime:
        return now_in_shanghai()

    @staticmethod
    def now_in_utc_naive() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    async def _commit_if_available(session: AsyncSession) -> None:
        commit = getattr(session, "commit", None)
        if commit is not None:
            await commit()

    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split())

    @classmethod
    def _create_llm_client(cls, provider: str | None = None):
        provider = provider or settings.llm_provider
        if provider == "openai":
            from services.llm.openai_client import OpenAIClient

            client = OpenAIClient(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_model,
                enable_web_search=False,
                timeout_seconds=settings.openai_timeout_seconds,
                reasoning_effort=settings.openai_reasoning_effort,
            )
            client.provider = "openai"
            return client
        if provider == "deepseek":
            from services.llm.deepseek_client import DeepSeekClient

            client = DeepSeekClient(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_model,
            )
            client.provider = "deepseek"
            return client
        if provider == "gemini":
            from services.llm.gemini_client import GeminiClient

            client = GeminiClient(
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
                enable_grounding=False,
                timeout_seconds=settings.gemini_timeout_seconds,
            )
            client.provider = "gemini"
            return client
        if provider == "qwen":
            from services.llm.qwen_client import QwenClient

            client = QwenClient(
                api_key=settings.qwen_api_key,
                model=settings.qwen_model,
                enable_search=False,
            )
            client.provider = "qwen"
            return client
        if provider == "zhipu":
            from services.llm.zhipu_client import ZhipuClient

            client = ZhipuClient(
                api_key=settings.zhipu_api_key,
                model=settings.zhipu_model,
                enable_web_search=False,
            )
            client.provider = "zhipu"
            return client
        raise ValueError(f"不支持的LLM提供商: {provider}")

    @classmethod
    def _supports_native_agent(cls, provider: str | None) -> bool:
        return (provider or settings.llm_provider) == "gemini"

    @classmethod
    def _build_role_agent_tools(
        cls,
        *,
        scene: MultiAgentScene,
        role: RoleBlueprint,
        question: str | None,
        portfolio_summary: dict | None,
        holdings_preview: Sequence[str],
        account_balance: float | None,
    ):
        from services.agents.types import AgentTool

        async def get_portfolio_summary(_: dict[str, Any]) -> dict[str, Any]:
            return {
                "portfolio_summary": portfolio_summary or {},
                "holdings_preview": list(holdings_preview),
                "account_balance": account_balance,
            }

        async def get_holdings(_: dict[str, Any]) -> dict[str, Any]:
            return {"holdings_preview": list(holdings_preview)}

        async def get_kline_indicators(args: dict[str, Any]) -> dict[str, Any]:
            codes = args.get("codes")
            if not isinstance(codes, list) or not codes:
                codes = cls._extract_etf_codes(question, holdings_preview)
            if scene != MultiAgentScene.ETF:
                return {"error": "K线工具仅支持 ETF 场景", "codes": codes}
            context = await cls._build_technical_context(
                scene=scene,
                question=" ".join(str(code) for code in codes),
                holdings_preview=holdings_preview,
            )
            return {"codes": context.codes, "summary": context.prompt_block}

        def ensure_recent_query(value: Any) -> str:
            clean = cls._normalize_text(value)
            if not clean:
                clean = cls._normalize_text(question or "")
            current_date = now_in_shanghai().strftime("%Y-%m-%d")
            recent_tokens = ("最新", "近期", "今日", "当前", current_date, "本周", "本月")
            historical_tokens = ("历史", "回顾", "复盘", "当时", "过去")
            if any(year in clean for year in ("2024", "2025")) and not any(token in clean for token in historical_tokens):
                clean = (
                    clean.replace("2024年", "")
                    .replace("2024", "")
                    .replace("2025年", "")
                    .replace("2025", "")
                )
                clean = cls._normalize_text(clean)
            if current_date not in clean:
                clean = cls._normalize_text(f"{clean} 最新 近期 {current_date}")
            elif not any(token in clean for token in recent_tokens):
                clean = cls._normalize_text(f"{clean} 最新 近期")
            return clean[:180]

        async def search_latest_news(args: dict[str, Any]) -> dict[str, Any]:
            query = ensure_recent_query(args.get("query") or question or "")
            if not query:
                query = ensure_recent_query(
                    " ".join(cls._build_search_queries(scene, question, holdings_preview, portfolio_summary))
                )
            if not TavilySearchService.is_enabled():
                return {"enabled": False, "error": "Tavily is not configured", "query": query, "results": []}
            response = await TavilySearchService.search(
                query=query[:180],
                topic="finance" if scene in {MultiAgentScene.ETF, MultiAgentScene.ACCOUNT} else "news",
                time_range="week",
                max_results=5,
            )
            return {
                "enabled": True,
                "query": response.query,
                "answer": response.answer,
                "error": response.error,
                "results": [
                    {
                        "title": result.title,
                        "url": result.url,
                        "content": result.content,
                        "score": result.score,
                        "published_date": result.published_date,
                    }
                    for result in response.results
                ],
            }

        async def search_policy_events(args: dict[str, Any]) -> dict[str, Any]:
            query = ensure_recent_query(args.get("query") or "")
            queries = [query] if query else [
                ensure_recent_query(item) for item in cls._build_policy_event_queries(question, holdings_preview)
            ]
            if not TavilySearchService.is_enabled():
                return {"enabled": False, "error": "Tavily is not configured", "queries": queries, "results": []}
            responses = await asyncio.gather(
                *[
                    TavilySearchService.search(
                        item[:180],
                        topic="finance",
                        time_range="week",
                        max_results=5,
                    )
                    for item in queries[:2]
                ]
            )
            return {
                "enabled": True,
                "queries": [response.query for response in responses],
                "results": [
                    {
                        "query": response.query,
                        "answer": response.answer,
                        "error": response.error,
                        "items": [
                            {
                                "title": result.title,
                                "url": result.url,
                                "content": result.content,
                                "score": result.score,
                                "published_date": result.published_date,
                            }
                            for result in response.results
                        ],
                    }
                    for response in responses
                ],
            }

        tool_map = {
            "get_portfolio_summary": AgentTool(
                name="get_portfolio_summary",
                description="获取当前用户账户、组合总览、今日/累计盈亏、可用资金和持仓预览。",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                handler=get_portfolio_summary,
            ),
            "get_holdings": AgentTool(
                name="get_holdings",
                description="获取当前用户持仓预览，用于识别需要分析的 ETF 代码和仓位背景。",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                handler=get_holdings,
            ),
            "get_kline_indicators": AgentTool(
                name="get_kline_indicators",
                description="获取 ETF 最近 K 线、均线、RSI、MACD 和趋势摘要。技术面角色必须优先调用。",
                parameters={
                    "type": "object",
                    "properties": {
                        "codes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "需要查询的 6 位 ETF 代码列表。",
                        }
                    },
                    "additionalProperties": False,
                },
                handler=get_kline_indicators,
            ),
            "search_latest_news": AgentTool(
                name="search_latest_news",
                description="搜索最新市场、行业、宏观、公告或新闻信息。",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "搜索关键词"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                handler=search_latest_news,
            ),
            "search_policy_events": AgentTool(
                name="search_policy_events",
                description="搜索最新政策、监管、产业政策、公告和事件催化。政策事件角色必须优先调用。",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "政策/事件搜索关键词"}},
                    "additionalProperties": False,
                },
                handler=search_policy_events,
            ),
        }
        role_tools: dict[str, list[str]] = {
            "technical": ["get_holdings", "get_kline_indicators"],
            "policy_event": ["get_portfolio_summary", "get_holdings", "search_policy_events", "search_latest_news"],
            "allocation": ["get_portfolio_summary", "get_holdings", "search_latest_news"],
            "risk_arbiter": ["get_portfolio_summary", "get_holdings", "search_latest_news"],
            "portfolio_structure": ["get_portfolio_summary", "get_holdings"],
            "rebalance": ["get_portfolio_summary", "get_holdings", "search_latest_news"],
            "risk_exposure": ["get_portfolio_summary", "get_holdings", "search_latest_news"],
            "capital_executor": ["get_portfolio_summary", "get_holdings"],
            "researcher": ["get_portfolio_summary", "get_holdings", "search_latest_news"],
            "counterpoint": ["get_portfolio_summary", "get_holdings", "search_latest_news"],
            "evidence": ["get_portfolio_summary", "get_holdings", "search_latest_news"],
        }
        names = role_tools.get(role.key, ["get_portfolio_summary", "get_holdings", "search_latest_news"])
        return [tool_map[name] for name in names if name in tool_map]

    @classmethod
    def build_roles_for_scenario(cls, scene: MultiAgentScene) -> list[RoleBlueprint]:
        if scene == MultiAgentScene.ETF:
            return [
                RoleBlueprint(
                    "policy_event",
                    "政策事件角色",
                    "判断最新政策、公告、行业事件是否直接影响该 ETF 的方向和节奏。",
                ),
                RoleBlueprint(
                    "technical",
                    "技术面角色",
                    "判断价格位置、趋势、超买超卖和短期执行节奏。",
                ),
                RoleBlueprint(
                    "allocation",
                    "配置视角角色",
                    "判断长期配置价值、仓位适配度和是否适合继续持有。",
                ),
                RoleBlueprint(
                    "risk_arbiter",
                    "风控裁决角色",
                    "优先从回撤、集中度和风险收益比角度给出保守判断。",
                ),
            ]
        if scene == MultiAgentScene.ACCOUNT:
            return [
                RoleBlueprint(
                    "portfolio_structure",
                    "组合结构角色",
                    "判断组合集中度、分散度和仓位结构是否健康。",
                ),
                RoleBlueprint(
                    "rebalance",
                    "再平衡角色",
                    "判断当前是否应该再平衡而不是继续追涨或加仓。",
                ),
                RoleBlueprint(
                    "risk_exposure",
                    "风险暴露角色",
                    "判断当前账户的相关性、回撤和资金压力。",
                ),
                RoleBlueprint(
                    "capital_executor",
                    "资金执行角色",
                    "判断现金、执行窗口和调仓节奏是否支持后续操作。",
                ),
            ]
        return [
            RoleBlueprint(
                "researcher",
                "研究员角色",
                "梳理问题边界、对象、时间范围与关键信息缺口。",
            ),
            RoleBlueprint(
                "counterpoint",
                "反方质疑角色",
                "专门挑出可能被忽略的风险、反证和过度乐观假设。",
            ),
            RoleBlueprint(
                "evidence",
                "证据搜索角色",
                "优先整合最新新闻、政策和市场证据，判断是否已被定价。",
            ),
            RoleBlueprint(
                "risk_arbiter",
                "风控裁决角色",
                "在信息不完全时坚持保守输出，避免编造确定性。",
            ),
        ]

    @classmethod
    def _scene_title(cls, scene: MultiAgentScene, question: str | None) -> str:
        if question and question.strip():
            return question.strip()[:60]
        if scene == MultiAgentScene.ETF:
            return "ETF 多智能体辩论"
        if scene == MultiAgentScene.ACCOUNT:
            return "账户多智能体辩论"
        return "通用投资问答辩论"

    @classmethod
    def _scene_bullets(
        cls,
        scene: MultiAgentScene,
        question: str | None,
        use_portfolio_context: bool,
        max_debate_rounds: int,
        portfolio_summary: dict | None,
        holdings_preview: Sequence[str],
        account_balance: float | None,
        search_bundle: SearchBundle,
    ) -> list[str]:
        bullets: list[str] = []
        if question and question.strip():
            bullets.append(f"用户问题：{question.strip()}")
        bullets.append(f"场景：{scene.value}")
        bullets.append(f"引用持仓上下文：{'开启' if use_portfolio_context else '关闭'}")
        bullets.append(f"最大辩论轮数：{max_debate_rounds}")
        bullets.append(f"外部搜索：{'已启用' if search_bundle.metadata else '未启用'}")
        if portfolio_summary:
            total_assets = portfolio_summary.get("total_assets")
            total_pnl_pct = portfolio_summary.get("total_pnl_pct")
            if total_assets is not None:
                bullets.append(f"总资产：{float(total_assets):.2f}")
            if total_pnl_pct is not None:
                bullets.append(f"总盈亏：{float(total_pnl_pct):.2f}%")
        if account_balance is not None:
            bullets.append(f"可用资金：{account_balance:.2f}")
        for item in holdings_preview[:8]:
            bullets.append(item)
        if len(holdings_preview) > 8:
            bullets.append(f"其余持仓：{len(holdings_preview) - 8} 个")
        return bullets[:16]

    @classmethod
    async def _build_portfolio_context(
        cls,
        session: AsyncSession,
        user_id: int,
        portfolio_ids: Sequence[int] | None = None,
    ) -> tuple[dict | None, list[str], float | None]:
        from services.portfolio_service import PortfolioService

        holdings = await PortfolioService.get_with_market(session, user_id=user_id)
        if portfolio_ids is not None:
            allowed_ids = {int(item) for item in portfolio_ids}
            holdings = [item for item in holdings if item.id in allowed_ids]
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        account_balance = float(user.account_balance) if user and user.account_balance is not None else None
        summary = PortfolioService.build_summary_from_portfolios(holdings, account_balance or 0.0)

        holdings_preview = []
        for item in holdings:
            name = cls._normalize_text(item.etf_name) or "名称未知"
            market_parts = []
            if item.current_price is not None:
                market_parts.append(f"现价 {float(item.current_price):.4f}")
            if item.market_value is not None:
                market_parts.append(f"市值 {float(item.market_value):.2f}")
            if item.pnl_pct is not None:
                market_parts.append(f"盈亏 {float(item.pnl_pct):+.2f}%")
            market_text = f" | {' | '.join(market_parts)}" if market_parts else ""
            holdings_preview.append(
                f"{item.etf_code} {name} | 份额 {item.shares:.2f} | 成本 {item.cost_price:.4f}{market_text}"
            )

        return summary.model_dump(), holdings_preview, account_balance

    @classmethod
    def _build_search_queries(
        cls,
        scene: MultiAgentScene,
        question: str | None,
        holdings_preview: Sequence[str],
        portfolio_summary: dict | None,
    ) -> list[str]:
        question_text = cls._normalize_text(question)
        codes = []
        current_date = now_in_shanghai().strftime("%Y-%m-%d")
        for item in holdings_preview:
            code = cls._normalize_text(item.split("|", 1)[0])
            code_match = re.search(r"(?<!\d)\d{6}(?!\d)", code)
            if code_match and code_match.group(0) not in codes:
                codes.append(code_match.group(0))
            if len(codes) >= 7:
                break

        holding_context = " ".join(codes)
        if holdings_preview:
            holding_names = []
            for item in holdings_preview[:5]:
                head = cls._normalize_text(item.split("|", 1)[0])
                if head:
                    holding_names.append(head)
            if holding_names:
                holding_context = cls._normalize_text(f"{holding_context} {' '.join(holding_names)}")

        queries: list[str] = []
        if scene == MultiAgentScene.ETF:
            if question_text:
                base = question_text
                if holding_context:
                    base = f"{base} {holding_context}"
                queries.append(f"{base} 最新 公告 新闻 政策 宏观 市场 {current_date}")
            elif holding_context:
                queries.append(f"{holding_context} 最新 公告 新闻 政策 宏观 市场 {current_date}")
        elif scene == MultiAgentScene.ACCOUNT:
            base = question_text or "账户组合 再平衡 风险"
            if holding_context:
                base = f"{base} {holding_context}"
            queries.append(f"{base} 最新 政策 新闻 风险 市场 {current_date}")
        else:
            if question_text:
                base = question_text
                if holding_context:
                    base = f"{base} {holding_context}"
                queries.append(f"{base} 最新 公告 新闻 政策 宏观 市场 {current_date}")
            elif portfolio_summary:
                queries.append(f"投资 {holding_context} 最新 公告 新闻 政策 宏观 市场 {current_date}".strip())

        deduped: list[str] = []
        for query in queries:
            clean_query = cls._normalize_text(query)
            if clean_query and clean_query not in deduped:
                deduped.append(clean_query[:180])
            if len(deduped) >= 2:
                break
        return deduped

    @classmethod
    def _extract_etf_codes(
        cls,
        question: str | None,
        holdings_preview: Sequence[str],
    ) -> list[str]:
        codes: list[str] = []
        for item in holdings_preview:
            head = cls._normalize_text(item.split("|", 1)[0])
            match = re.search(r"(?<!\d)\d{6}(?!\d)", head)
            code = match.group(0) if match else ""
            if code and code not in codes:
                codes.append(code)

        for code in re.findall(r"(?<!\d)\d{6}(?!\d)", question or ""):
            if code not in codes:
                codes.append(code)

        return codes[:8]

    @classmethod
    async def _build_technical_context(
        cls,
        *,
        scene: MultiAgentScene,
        question: str | None,
        holdings_preview: Sequence[str],
    ) -> TechnicalContextBundle:
        if scene != MultiAgentScene.ETF:
            return TechnicalContextBundle(prompt_block="", codes=[])

        codes = cls._extract_etf_codes(question, holdings_preview)
        if not codes:
            return TechnicalContextBundle(prompt_block="", codes=[])

        try:
            from services.market_service import MarketService
        except Exception as exc:
            return TechnicalContextBundle(
                prompt_block=f"技术面数据暂不可用：{type(exc).__name__}: {exc}",
                codes=codes,
            )

        async def build_one(code: str) -> str:
            try:
                klines = await MarketService.get_history_kline(code, days=60)
                if not klines:
                    return f"### {code}\n- 技术面数据：未获取到最近 K 线。"

                indicators = MarketService.calculate_technical_indicators(klines)
                latest = klines[-1]
                recent = klines[-5:]
                recent_lines = [
                    f"- {item.trade_date}: 开{item.open_price:.3f} 收{item.close_price:.3f} 高{item.high_price:.3f} 低{item.low_price:.3f} 涨跌{item.change_pct:.2f}% 量{item.volume}"
                    for item in recent
                ]
                ma5 = indicators.ma5
                ma10 = indicators.ma10
                ma20 = indicators.ma20
                trend_parts = []
                if ma5 is not None and ma20 is not None:
                    trend_parts.append("MA5在MA20上方" if ma5 >= ma20 else "MA5在MA20下方")
                if latest.close_price and ma20 is not None:
                    distance = (latest.close_price - ma20) / ma20 * 100
                    trend_parts.append(f"收盘价距MA20 {distance:+.2f}%")

                return "\n".join(
                    [
                        f"### {code}",
                        f"- 最近交易日：{latest.trade_date}，收盘 {latest.close_price:.3f}，当日涨跌 {latest.change_pct:.2f}%",
                        f"- 均线：MA5={ma5 if ma5 is not None else 'N/A'}，MA10={ma10 if ma10 is not None else 'N/A'}，MA20={ma20 if ma20 is not None else 'N/A'}",
                        f"- RSI(14)：{indicators.rsi14 if indicators.rsi14 is not None else 'N/A'}",
                        f"- MACD：DIF={indicators.macd_dif if indicators.macd_dif is not None else 'N/A'}，DEA={indicators.macd_dea if indicators.macd_dea is not None else 'N/A'}，柱={indicators.macd_histogram if indicators.macd_histogram is not None else 'N/A'}",
                        f"- 趋势摘要：{'；'.join(trend_parts) if trend_parts else 'K线数量不足，趋势摘要有限'}",
                        "- 最近5根日K：",
                        *recent_lines,
                    ]
                )
            except Exception as exc:
                return f"### {code}\n- 技术面数据获取失败：{type(exc).__name__}: {exc}"

        blocks = await asyncio.gather(*(build_one(code) for code in codes))
        prompt_block = "\n\n".join(block for block in blocks if block)
        if prompt_block:
            prompt_block = (
                "以下技术面数据仅供技术面角色判断价格位置、趋势、超买超卖和短期节奏；"
                "请优先引用 K 线、均线、RSI、MACD 和最近涨跌变化。\n\n"
                f"{prompt_block}"
            )
        return TechnicalContextBundle(prompt_block=prompt_block, codes=codes)

    @classmethod
    def _build_policy_event_queries(
        cls,
        question: str | None,
        holdings_preview: Sequence[str],
    ) -> list[str]:
        question_text = cls._normalize_text(question)
        codes = cls._extract_etf_codes(question, holdings_preview)[:3]
        current_date = now_in_shanghai().strftime("%Y-%m-%d")
        base = question_text or "ETF 市场"
        if codes:
            base = f"{base} {' '.join(codes)}"
        queries = [
            f"{base} 最新 政策 公告 监管 新闻 行业 影响 {current_date}",
            f"{base} 最新 宏观 政策 产业政策 事件 催化 风险 {current_date}",
        ]
        deduped: list[str] = []
        for query in queries:
            clean_query = cls._normalize_text(query)
            if clean_query and clean_query not in deduped:
                deduped.append(clean_query[:180])
        return deduped[:2]

    @classmethod
    def _role_evidence_requirements(cls, scene: MultiAgentScene, role: RoleBlueprint) -> list[str]:
        if scene == MultiAgentScene.ACCOUNT:
            base = [
                "## 账户场景证据输出要求",
                "必须给出明确的账户层面决策结论，summary 需要先说结论再说明数据依据。",
                "evidence 至少 2 条，必须引用结构化上下文中的账户/组合数据，例如总资产、总市值、总盈亏、今日盈亏、可用资金、持仓数量或具体持仓。",
                "如果使用外部搜索，evidence 需说明搜索结果如何影响账户再平衡、风险暴露或执行节奏。",
                "不得只写泛泛建议；如果账户数据不足，必须在 evidence 和 risk_notes 中明确说明缺口。",
            ]
            role_specific: dict[str, str] = {
                "portfolio_structure": "重点引用持仓数量、资产分类、集中度、总市值和具体持仓，说明组合结构是否健康。",
                "rebalance": "重点引用总盈亏、今日盈亏、仓位结构、现金比例或持仓偏离，说明是否需要再平衡。",
                "risk_exposure": "重点引用总盈亏、今日盈亏、持仓集中度、相关赛道暴露和潜在回撤来源，说明风险是否可承受。",
                "capital_executor": "重点引用可用资金、总资产、持仓规模和执行窗口，说明调仓是否有资金和节奏条件。",
            }
            return [*base, role_specific.get(role.key, "请结合账户数据给出可验证证据。")]

        if scene == MultiAgentScene.GENERAL:
            base = [
                "## 通用场景证据输出要求",
                "必须给出明确结论，summary 需要先回答用户问题，再说明证据依据。",
                "evidence 至少 2 条，优先引用用户问题边界、外部搜索结果标题/URL/发布日期、结构化上下文中的持仓或账户数据。",
                "如果搜索结果不足或问题边界不清，必须在 evidence 和 risk_notes 中明确说明信息缺口，不得编造事实。",
            ]
            role_specific: dict[str, str] = {
                "researcher": "重点引用问题对象、时间范围、已知条件和信息缺口，说明判断边界。",
                "counterpoint": "重点引用反证、风险事件、估值/政策/市场不确定性或搜索结果中的负面证据。",
                "evidence": "重点引用最新搜索结果，evidence 应包含来源标题或URL以及该证据对结论的影响。",
                "risk_arbiter": "重点引用信息缺口、强反对点、资金风险或不可验证来源，给出保守依据。",
            }
            return [*base, role_specific.get(role.key, "请结合可验证来源给出证据。")]

        return []

    @classmethod
    def _account_evidence_block(
        cls,
        portfolio_summary: dict | None,
        holdings_preview: Sequence[str],
        account_balance: float | None,
    ) -> str:
        if not portfolio_summary and not holdings_preview and account_balance is None:
            return ""

        lines = ["以下账户数据供账户场景各角色引用为决策证据："]
        if portfolio_summary:
            total_market_value = float(portfolio_summary.get("total_market_value") or 0.0)
            total_cost = float(portfolio_summary.get("total_cost") or 0.0)
            total_pnl = float(portfolio_summary.get("total_pnl") or 0.0)
            total_pnl_pct = float(portfolio_summary.get("total_pnl_pct") or 0.0)
            today_pnl = portfolio_summary.get("today_pnl")
            today_pnl_pct = portfolio_summary.get("today_pnl_pct")
            total_assets = float(portfolio_summary.get("total_assets") or 0.0)
            category_distribution = portfolio_summary.get("category_distribution") or {}
            lines.extend(
                [
                    f"- 总市值：¥{total_market_value:,.2f}",
                    f"- 总成本：¥{total_cost:,.2f}",
                    f"- 总盈亏：{total_pnl:+.2f} ({total_pnl_pct:+.2f}%)",
                    f"- 今日盈亏：{float(today_pnl or 0.0):+.2f} ({float(today_pnl_pct or 0.0):+.2f}%)",
                    f"- 总资产：¥{total_assets:,.2f}",
                ]
            )
            if category_distribution:
                category_lines = []
                for name, value in sorted(category_distribution.items(), key=lambda item: float(item[1]), reverse=True)[:5]:
                    ratio = float(value) / total_market_value * 100 if total_market_value > 0 else 0.0
                    category_lines.append(f"{name} ¥{float(value):,.2f} ({ratio:.1f}%)")
                lines.append(f"- 资产分类Top：{'；'.join(category_lines)}")
        if account_balance is not None:
            lines.append(f"- 可用资金：¥{account_balance:,.2f}")
        if holdings_preview:
            lines.append("- 持仓预览：")
            lines.extend(f"  - {item}" for item in holdings_preview)
        return "\n".join(lines)

    @classmethod
    def _general_evidence_block(
        cls,
        *,
        question: str | None,
        portfolio_summary: dict | None,
        holdings_preview: Sequence[str],
    ) -> str:
        lines = ["以下通用场景数据供各角色引用为决策证据："]
        if question and question.strip():
            lines.append(f"- 用户问题：{question.strip()}")
        else:
            lines.append("- 用户问题：未提供明确问题，需先说明判断边界。")
        if portfolio_summary:
            lines.append(f"- 组合总资产：¥{float(portfolio_summary.get('total_assets') or 0.0):,.2f}")
            lines.append(f"- 组合总盈亏：{float(portfolio_summary.get('total_pnl') or 0.0):+.2f} ({float(portfolio_summary.get('total_pnl_pct') or 0.0):+.2f}%)")
        if holdings_preview:
            lines.append("- 持仓预览：")
            lines.extend(f"  - {item}" for item in holdings_preview)
        return "\n".join(lines)

    @classmethod
    async def _collect_policy_event_context(
        cls,
        *,
        scene: MultiAgentScene,
        question: str | None,
        holdings_preview: Sequence[str],
    ) -> PolicyEventContextBundle:
        if scene != MultiAgentScene.ETF:
            return PolicyEventContextBundle(prompt_block="", metadata=[])

        queries = cls._build_policy_event_queries(question, holdings_preview)
        if not queries:
            return PolicyEventContextBundle(prompt_block="", metadata=[])

        if not TavilySearchService.is_enabled():
            return PolicyEventContextBundle(
                prompt_block="政策事件搜索未启用或未配置 Tavily，不能确认最新新闻/政策事件；请在结论中明确该限制。",
                metadata=[],
            )

        responses = await asyncio.gather(
            *[
                TavilySearchService.search(
                    query,
                    topic="finance",
                    time_range="week",
                    max_results=5,
                )
                for query in queries
            ]
        )
        prompt_block = TavilySearchService.format_for_prompt(list(responses))
        metadata: list[MultiAgentSearchMetadata] = []
        for response in responses:
            metadata.append(
                MultiAgentSearchMetadata(
                    provider="tavily",
                    enabled=True,
                    query=response.query,
                    answer=response.answer,
                    result_count=len(response.results),
                    error=response.error,
                    results=[
                        {
                            "title": result.title,
                            "url": result.url,
                            "content": result.content,
                            "score": result.score,
                            "published_date": result.published_date,
                        }
                        for result in response.results
                    ],
                )
            )

        if prompt_block:
            prompt_block = (
                "以下为政策事件角色专用的最新新闻/政策/公告检索结果。"
                "请优先引用标题、来源URL、发布日期和摘要内容作为决策证据。\n\n"
                f"{prompt_block}"
            )
        return PolicyEventContextBundle(prompt_block=prompt_block, metadata=metadata)

    @classmethod
    async def _collect_search_context(
        cls,
        scene: MultiAgentScene,
        question: str | None,
        holdings_preview: Sequence[str],
        portfolio_summary: dict | None,
    ) -> SearchBundle:
        if not TavilySearchService.is_enabled():
            print(
                f"[MultiAgent][Search] {json.dumps({'enabled': False, 'scene': scene.value, 'queries': [], 'result_count': 0}, ensure_ascii=False)}",
                flush=True,
            )
            return SearchBundle(prompt_block="", metadata=[])

        queries = cls._build_search_queries(scene, question, holdings_preview, portfolio_summary)
        if not queries:
            print(
                f"[MultiAgent][Search] {json.dumps({'enabled': True, 'scene': scene.value, 'queries': [], 'result_count': 0}, ensure_ascii=False)}",
                flush=True,
            )
            return SearchBundle(prompt_block="", metadata=[])

        topic = "finance" if scene in {MultiAgentScene.ETF, MultiAgentScene.ACCOUNT} else "news"
        responses = await asyncio.gather(
            *[
                TavilySearchService.search(
                    query,
                    topic=topic,
                    time_range="week",
                    max_results=5,
                )
                for query in queries
            ]
        )
        prompt_block = TavilySearchService.format_for_prompt(list(responses))
        metadata: list[MultiAgentSearchMetadata] = []
        for response in responses:
            metadata.append(
                MultiAgentSearchMetadata(
                    provider="tavily",
                    enabled=True,
                    query=response.query,
                    answer=response.answer,
                    result_count=len(response.results),
                    error=response.error,
                    results=[
                        {
                            "title": result.title,
                            "url": result.url,
                            "content": result.content,
                            "score": result.score,
                            "published_date": result.published_date,
                        }
                        for result in response.results
                    ],
                )
            )

        print(
            f"[MultiAgent][Search] {json.dumps({'enabled': True, 'scene': scene.value, 'queries': queries, 'result_count': sum(item.result_count for item in metadata)}, ensure_ascii=False, default=str)}",
            flush=True,
        )
        return SearchBundle(prompt_block=prompt_block, metadata=metadata)

    @classmethod
    def _build_context_summary(
        cls,
        scene: MultiAgentScene,
        question: str | None,
        use_portfolio_context: bool,
        max_debate_rounds: int,
        portfolio_summary: dict | None,
        holdings_preview: Sequence[str],
        account_balance: float | None,
        search_bundle: SearchBundle,
    ) -> MultiAgentContextSummary:
        metrics: dict[str, str] = {}
        if portfolio_summary:
            total_market_value = float(portfolio_summary.get("total_market_value") or 0.0)
            total_pnl = float(portfolio_summary.get("total_pnl") or 0.0)
            total_pnl_pct = float(portfolio_summary.get("total_pnl_pct") or 0.0)
            today_pnl = float(portfolio_summary.get("today_pnl") or 0.0)
            today_pnl_pct = float(portfolio_summary.get("today_pnl_pct") or 0.0)
            total_assets = float(portfolio_summary.get("total_assets") or 0.0)
            metrics = {
                "总市值": f"¥{total_market_value:,.2f}",
                "总盈亏": f"{total_pnl:+.2f} ({total_pnl_pct:+.2f}%)",
                "今日盈亏": f"{today_pnl:+.2f} ({today_pnl_pct:+.2f}%)",
                "总资产": f"¥{total_assets:,.2f}",
            }
            if account_balance is not None:
                metrics["可用资金"] = f"¥{account_balance:,.2f}"
        if holdings_preview:
            metrics["持仓数量"] = str(len(holdings_preview))
        metrics["最大辩论轮数"] = str(max_debate_rounds)
        metrics["外部搜索"] = "已启用" if search_bundle.metadata else "未启用"
        metrics["搜索查询数"] = str(len(search_bundle.metadata))

        return MultiAgentContextSummary(
            scenario=scene,
            title=cls._scene_title(scene, question),
            question=question,
            bullets=cls._scene_bullets(
                scene=scene,
                question=question,
                use_portfolio_context=use_portfolio_context,
                max_debate_rounds=max_debate_rounds,
                portfolio_summary=portfolio_summary,
                holdings_preview=holdings_preview,
                account_balance=account_balance,
                search_bundle=search_bundle,
            ),
            metrics=metrics,
        )

    @classmethod
    def _string_list(cls, value: Any, default: list[str] | None = None) -> list[str]:
        default_list = default or []
        if isinstance(value, list):
            items = [cls._normalize_text(item) for item in value]
            return [item for item in items if item]
        if isinstance(value, tuple):
            items = [cls._normalize_text(item) for item in value]
            return [item for item in items if item]
        if isinstance(value, str):
            text = cls._normalize_text(value)
            return [text] if text else default_list
        return list(default_list)

    @classmethod
    def _extract_llm_payload(cls, raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if raw is None:
            return {}
        if isinstance(raw, str):
            text = raw.strip()
            if text.startswith("```"):
                text = text.strip("`")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                start = text.find("{")
                end = text.rfind("}") + 1
                if start != -1 and end > start:
                    try:
                        return json.loads(text[start:end])
                    except json.JSONDecodeError:
                        pass
        return {"raw": raw}

    @classmethod
    def _normalize_role_opinion(
        cls,
        payload: Any,
        *,
        role: RoleBlueprint,
        round_index: int,
    ) -> MultiAgentRoleOpinion:
        data = cls._extract_llm_payload(payload)
        stance = data.get("stance")
        if stance not in {"bullish", "neutral", "bearish", "mixed"}:
            stance = "neutral"
        return MultiAgentRoleOpinion(
            round_index=round_index,
            role_id=role.key,
            role_name=role.role_name,
            stance=stance,
            action=cls._normalize_text(data.get("action") or "继续观察"),
            summary=cls._normalize_text(
                data.get("summary")
                or data.get("conclusion")
                or data.get("main_judgment")
                or "模型未返回摘要，采取保守判断。"
            ),
            evidence=cls._string_list(data.get("evidence"), default=["模型未返回可验证证据"]),
            risk_notes=cls._string_list(data.get("risk_notes"), default=["模型未返回风险说明"]),
            confidence=float(data.get("confidence") or 55.0),
            rebuttals=cls._string_list(data.get("rebuttals")),
        )

    @classmethod
    def _fallback_role_opinion(
        cls,
        *,
        role: RoleBlueprint,
        round_index: int,
        error: Exception,
    ) -> MultiAgentRoleOpinion:
        return MultiAgentRoleOpinion(
            round_index=round_index,
            role_id=role.key,
            role_name=role.role_name,
            stance="neutral",
            action="继续观察",
            summary=f"该角色在第{round_index}轮调用失败，采用保守兜底。",
            evidence=["LLM 调用失败，无法生成有效观点"],
            risk_notes=[f"{type(error).__name__}: {error}"],
            confidence=0.0,
            rebuttals=[],
        )

    @classmethod
    def _normalize_arbiter_summary(
        cls,
        payload: Any,
        *,
        round_index: int,
        latest_opinions: Sequence[MultiAgentRoleOpinion],
        scene: MultiAgentScene,
    ) -> MultiAgentArbiterSummary:
        data = cls._extract_llm_payload(payload)
        consensus_reached = bool(data.get("consensus_reached"))
        why_stop = cls._normalize_text(data.get("why_stop") or data.get("reason") or "")
        strong_opposition = cls._string_list(data.get("strong_opposition"))
        supporting_roles = cls._string_list(data.get("supporting_roles"))
        disagreements = cls._string_list(data.get("disagreements"))
        risk_notes = cls._string_list(data.get("risk_notes"))
        final_recommendation = cls._normalize_text(data.get("final_recommendation") or data.get("conclusion") or "hold")
        recommended_action = cls._normalize_text(data.get("recommended_action") or data.get("action") or final_recommendation)
        conclusion = cls._normalize_text(
            data.get("conclusion")
            or data.get("summary")
            or f"{scene.value.upper()} 场景研判保持保守，等待更明确共识。"
        )
        confidence = float(data.get("confidence") or 60.0)
        convergence_state = "converged" if consensus_reached else "contested"
        if not consensus_reached and round_index >= 1:
            if why_stop.lower().find("max") != -1 or data.get("max_rounds_reached"):
                convergence_state = "max_rounds"
            elif data.get("failed"):
                convergence_state = "failed"
        if not supporting_roles:
            supporting_roles = [role.role_name for role in latest_opinions if role.stance in {"bullish", "neutral"}]
        if not disagreements:
            disagreements = [role.summary for role in latest_opinions if role.stance in {"mixed", "bearish"}]
        if not risk_notes:
            risk_notes = [note for role in latest_opinions for note in role.risk_notes[:1]]
        if not why_stop:
            why_stop = "裁决角色认为剩余分歧已不可忽略，继续辩论或达到轮次上限。"

        return MultiAgentArbiterSummary(
            round_index=round_index,
            consensus_reached=consensus_reached,
            why_stop=why_stop,
            strong_opposition=strong_opposition,
            confidence=confidence,
            final_recommendation=final_recommendation,
            recommended_action=recommended_action,
            conclusion=conclusion,
            supporting_roles=supporting_roles[:4],
            disagreements=disagreements[:6],
            risk_notes=risk_notes[:6],
            convergence_state=convergence_state,  # type: ignore[arg-type]
        )

    @classmethod
    def _build_final_conclusion(
        cls,
        scene: MultiAgentScene,
        arbiter_summary: MultiAgentArbiterSummary | None,
        latest_opinions: Sequence[MultiAgentRoleOpinion],
    ) -> MultiAgentFinalConclusion:
        if arbiter_summary is not None:
            return MultiAgentFinalConclusion(
                recommended_action=arbiter_summary.recommended_action or arbiter_summary.final_recommendation,
                action=arbiter_summary.final_recommendation,
                conclusion=arbiter_summary.conclusion,
                confidence=arbiter_summary.confidence,
                supporting_roles=list(arbiter_summary.supporting_roles),
                disagreements=list(arbiter_summary.disagreements),
                risk_notes=list(arbiter_summary.risk_notes),
            )

        bullish = sum(1 for role in latest_opinions if role.stance == "bullish")
        bearish = sum(1 for role in latest_opinions if role.stance == "bearish")
        if bearish > bullish:
            recommended_action = "reduce"
            conclusion = "分歧偏向风险控制，优先降低暴露或等待更明确的确认信号。"
            action_text = "优先减仓或等待"
        elif bullish > bearish:
            recommended_action = "hold"
            conclusion = "共识偏正面，但仍保留节奏控制，不追求过激动作。"
            action_text = "保持持有并控制节奏"
        else:
            recommended_action = "hold"
            conclusion = "共识偏中性，维持持有并观察后续证据。"
            action_text = "继续持有并观察"

        supporting_roles = [role.role_name for role in latest_opinions if role.stance in {"bullish", "neutral"}]
        disagreements = [role.summary for role in latest_opinions if role.stance == "mixed"]
        risk_notes: list[str] = []
        for role in latest_opinions:
            risk_notes.extend(role.risk_notes[:1])

        return MultiAgentFinalConclusion(
            recommended_action=recommended_action,
            action=action_text,
            conclusion=f"{scene.value.upper()} 场景下，{conclusion}",
            confidence=min(90.0, 62.0 + bullish * 4 - bearish * 3),
            supporting_roles=supporting_roles[:4],
            disagreements=disagreements[:6],
            risk_notes=risk_notes[:6],
        )

    @classmethod
    async def _generate_role_opinion(
        cls,
        *,
        scene: MultiAgentScene,
        role: RoleBlueprint,
        round_index: int,
        question: str | None,
        context_summary: MultiAgentContextSummary,
        search_bundle: SearchBundle,
        technical_context: TechnicalContextBundle | None = None,
        policy_event_context: PolicyEventContextBundle | None = None,
        account_evidence_block: str = "",
        general_evidence_block: str = "",
        provider: str,
        previous_opinion: MultiAgentRoleOpinion | None = None,
        opposing_points: Sequence[str] = (),
        disagreement_summary: str = "",
        portfolio_summary: dict | None = None,
        holdings_preview: Sequence[str] = (),
        account_balance: float | None = None,
    ) -> MultiAgentRoleOpinion:
        if cls._supports_native_agent(provider):
            return await cls._generate_role_opinion_with_agent(
                scene=scene,
                role=role,
                round_index=round_index,
                question=question,
                context_summary=context_summary,
                provider=provider,
                portfolio_summary=portfolio_summary,
                holdings_preview=holdings_preview,
                account_balance=account_balance,
                previous_opinion=previous_opinion,
                opposing_points=opposing_points,
                disagreement_summary=disagreement_summary,
            )
        prompt = cls._build_role_prompt(
            scene=scene,
            role=role,
            round_index=round_index,
            question=question,
            context_summary=context_summary,
            search_bundle=search_bundle,
            technical_context=technical_context,
            policy_event_context=policy_event_context,
            account_evidence_block=account_evidence_block,
            general_evidence_block=general_evidence_block,
            previous_opinion=previous_opinion,
            opposing_points=opposing_points,
            disagreement_summary=disagreement_summary,
        )
        llm = cls._create_llm_client(provider)
        context = f"multi_agent:{scene.value}:{role.key}:r{round_index}"
        from services.advisor_service import AdvisorService
        raw = await AdvisorService.chat_json_with_logging(llm, prompt, context=context)
        return cls._normalize_role_opinion(raw, role=role, round_index=round_index)

    @classmethod
    async def _generate_role_opinion_with_retries(cls, **kwargs: Any) -> MultiAgentRoleOpinion:
        last_error: Exception | None = None
        role = kwargs["role"]
        round_index = kwargs["round_index"]
        for attempt in range(1, cls.ROLE_MAX_ATTEMPTS + 1):
            try:
                return await cls._generate_role_opinion(**kwargs)
            except Exception as exc:
                last_error = exc
                print(
                    f"[MultiAgent] role generation failed role={role.key} round={round_index} attempt={attempt}/{cls.ROLE_MAX_ATTEMPTS}: {exc}",
                    flush=True,
                )
        assert last_error is not None
        raise last_error

    @classmethod
    async def _generate_role_opinion_with_agent(
        cls,
        *,
        scene: MultiAgentScene,
        role: RoleBlueprint,
        round_index: int,
        question: str | None,
        context_summary: MultiAgentContextSummary,
        provider: str,
        portfolio_summary: dict | None,
        holdings_preview: Sequence[str],
        account_balance: float | None,
        previous_opinion: MultiAgentRoleOpinion | None = None,
        opposing_points: Sequence[str] = (),
        disagreement_summary: str = "",
    ) -> MultiAgentRoleOpinion:
        from services.agents.providers.gemini_agent_client import GeminiNativeAgentClient
        from services.agents.role_agent_executor import RoleAgentExecutor

        llm = cls._create_llm_client(provider)
        executor = RoleAgentExecutor(
            scene=scene,
            role_id=role.key,
            role_name=role.role_name,
            role_focus=role.focus,
            round_index=round_index,
            question=question,
            context_summary=context_summary,
            tools=cls._build_role_agent_tools(
                scene=scene,
                role=role,
                question=question,
                portfolio_summary=portfolio_summary,
                holdings_preview=holdings_preview,
                account_balance=account_balance,
            ),
            client=GeminiNativeAgentClient(llm),
            previous_opinion=previous_opinion,
            opposing_points=opposing_points,
            disagreement_summary=disagreement_summary,
        )
        return await executor.run()

    @classmethod
    def _build_role_prompt(
        cls,
        *,
        scene: MultiAgentScene,
        role: RoleBlueprint,
        round_index: int,
        question: str | None,
        context_summary: MultiAgentContextSummary,
        search_bundle: SearchBundle,
        technical_context: TechnicalContextBundle | None = None,
        policy_event_context: PolicyEventContextBundle | None = None,
        account_evidence_block: str = "",
        general_evidence_block: str = "",
        previous_opinion: MultiAgentRoleOpinion | None = None,
        opposing_points: Sequence[str] = (),
        disagreement_summary: str = "",
    ) -> str:
        from services.advisor_service import AdvisorService

        prompt_sections = [
            f"你是多智能体投资辩论系统中的【{role.role_name}】。",
            f"场景：{scene.value}",
            f"轮次：第{round_index}轮{'初评' if round_index == 1 else '辩论'}",
            f"角色职责：{role.focus}",
            "",
            "## 时间基准",
            AdvisorService._prompt_time_context(),
            "请输出 JSON，字段必须包含：stance, action, summary, evidence, risk_notes, confidence, rebuttals。",
            "stance 只能是 bullish / neutral / bearish / mixed 之一；confidence 为 0-100 的数字。",
            "rebuttals 用于列出你对其他角色最强反对点的回应，首轮可为空数组。",
            "不要输出多余解释，不要输出 markdown 代码块。",
            "",
            "## 问题",
            question.strip() if question and question.strip() else "未提供明确问题，请基于场景和上下文判断。",
            "",
            "## 结构化上下文",
            json.dumps(context_summary.model_dump(mode="python"), ensure_ascii=False, indent=2, default=str),
        ]
        if search_bundle.prompt_block:
            prompt_sections.extend(["", "## 外部搜索证据", search_bundle.prompt_block])
        if account_evidence_block and scene == MultiAgentScene.ACCOUNT:
            prompt_sections.extend(["", "## 账户数据证据", account_evidence_block])
        if general_evidence_block and scene == MultiAgentScene.GENERAL:
            prompt_sections.extend(["", "## 通用场景证据", general_evidence_block])
        prompt_sections.extend(cls._role_evidence_requirements(scene, role))
        if role.key == "policy_event" and policy_event_context and policy_event_context.prompt_block:
            prompt_sections.extend(
                [
                    "",
                    "## 政策事件专用搜索证据",
                    policy_event_context.prompt_block,
                    "",
                    "## 政策事件输出要求",
                    "必须给出明确的政策/新闻事件结论，summary 需要先说事件对方向和节奏的影响。",
                    "evidence 至少 2 条；每条应包含新闻/政策/公告事件名称、发布日期或时间线、来源标题或URL、以及它如何影响该 ETF。",
                    "如果搜索结果不足或不可用，必须在 evidence 和 risk_notes 中明确说明“未找到足够最新政策/新闻证据”，不得编造事件。",
                ]
            )
        if role.key == "policy_event":
            prompt_sections.extend(
                [
                    "",
                    "## 政策事件强制要求",
                    "summary 必须先说明最新新闻/政策/公告对方向和节奏的影响，不能只基于账户、现金、持仓结构给结论。",
                    "evidence 至少 2 条；每条必须包含新闻/政策/公告事件名称、发布日期或时间线、来源标题或URL，以及它如何影响判断。",
                    "如果没有找到足够最新新闻/政策证据，evidence 和 risk_notes 必须明确写“未找到足够最新政策/新闻证据”，不得用账户数据冒充政策事件证据。",
                ]
            )
        if role.key == "technical" and technical_context and technical_context.prompt_block:
            prompt_sections.extend(
                [
                    "",
                    "## 技术面K线与指标数据",
                    technical_context.prompt_block,
                    "",
                    "## 技术面输出要求",
                    "必须给出明确的技术面结论，summary 需要先说结论再说依据。",
                    "evidence 至少 2 条，且至少 1 条必须直接引用 K 线、均线、RSI、MACD、关键支撑/压力、最近涨跌变化中的具体信息。",
                    "不要只写泛泛判断，避免出现没有指标依据的结论。",
                ]
            )
        if previous_opinion is not None:
            prompt_sections.extend(
                [
                    "",
                    "## 本角色上一轮观点",
                    json.dumps(previous_opinion.model_dump(mode="python"), ensure_ascii=False, indent=2, default=str),
                ]
            )
        if opposing_points:
            prompt_sections.extend(["", "## 最强反对点", "\n".join(f"- {item}" for item in opposing_points)])
        if disagreement_summary:
            prompt_sections.extend(["", "## 当前分歧摘要", disagreement_summary])
        return "\n".join(prompt_sections)

    @classmethod
    async def _stream_role_opinion_events(
        cls,
        *,
        scene: MultiAgentScene,
        role: RoleBlueprint,
        round_index: int,
        question: str | None,
        context_summary: MultiAgentContextSummary,
        search_bundle: SearchBundle,
        provider: str,
        output: list[MultiAgentRoleOpinion],
        technical_context: TechnicalContextBundle | None = None,
        policy_event_context: PolicyEventContextBundle | None = None,
        account_evidence_block: str = "",
        general_evidence_block: str = "",
        previous_opinion: MultiAgentRoleOpinion | None = None,
        opposing_points: Sequence[str] = (),
        disagreement_summary: str = "",
        portfolio_summary: dict | None = None,
        holdings_preview: Sequence[str] = (),
        account_balance: float | None = None,
    ) -> AsyncIterator[str]:
        message_id = f"role-{round_index}-{role.key}"
        if cls._supports_native_agent(provider):
            from services.agents.providers.gemini_agent_client import GeminiNativeAgentClient
            from services.agents.role_agent_executor import RoleAgentExecutor

            for attempt in range(1, cls.ROLE_MAX_ATTEMPTS + 1):
                if attempt > 1:
                    yield cls._sse_event(
                        "status",
                        {
                            "message": f"{role.role_name} 第 {attempt}/{cls.ROLE_MAX_ATTEMPTS} 次重试",
                            "role_id": role.key,
                            "round_index": round_index,
                        },
                    )
                try:
                    llm = cls._create_llm_client(provider)
                    executor = RoleAgentExecutor(
                        scene=scene,
                        role_id=role.key,
                        role_name=role.role_name,
                        role_focus=role.focus,
                        round_index=round_index,
                        question=question,
                        context_summary=context_summary,
                        tools=cls._build_role_agent_tools(
                            scene=scene,
                            role=role,
                            question=question,
                            portfolio_summary=portfolio_summary,
                            holdings_preview=holdings_preview,
                            account_balance=account_balance,
                        ),
                        client=GeminiNativeAgentClient(llm),
                        previous_opinion=previous_opinion,
                        opposing_points=opposing_points,
                        disagreement_summary=disagreement_summary,
                    )
                    async for agent_event in executor.stream():
                        payload = dict(agent_event.payload)
                        opinion = payload.get("opinion")
                        if isinstance(opinion, MultiAgentRoleOpinion):
                            output.append(opinion)
                            payload["opinion"] = opinion.model_dump(mode="json")
                        yield cls._sse_event(agent_event.type, payload)
                    if output:
                        return
                except Exception as exc:
                    print(
                        f"[MultiAgent] stream role generation failed role={role.key} round={round_index} attempt={attempt}/{cls.ROLE_MAX_ATTEMPTS}: {exc}",
                        flush=True,
                    )
                    if attempt >= cls.ROLE_MAX_ATTEMPTS:
                        opinion = cls._fallback_role_opinion(role=role, round_index=round_index, error=exc)
                        output.append(opinion)
                        yield cls._sse_event("role_done", {"message_id": message_id, "opinion": opinion.model_dump(mode="json")})
                        return
            return

        yield cls._sse_event(
            "role_start",
            {
                "message_id": message_id,
                "round_index": round_index,
                "role_id": role.key,
                "role_name": role.role_name,
            },
        )
        prompt = cls._build_role_prompt(
            scene=scene,
            role=role,
            round_index=round_index,
            question=question,
            context_summary=context_summary,
            search_bundle=search_bundle,
            technical_context=technical_context,
            policy_event_context=policy_event_context,
            account_evidence_block=account_evidence_block,
            general_evidence_block=general_evidence_block,
            previous_opinion=previous_opinion,
            opposing_points=opposing_points,
            disagreement_summary=disagreement_summary,
        )
        llm = cls._create_llm_client(provider)
        context = f"multi_agent:{scene.value}:{role.key}:r{round_index}"
        from services.advisor_service import AdvisorService

        opinion: MultiAgentRoleOpinion | None = None
        for attempt in range(1, cls.ROLE_MAX_ATTEMPTS + 1):
            if attempt > 1:
                yield cls._sse_event(
                    "status",
                    {
                        "message": f"{role.role_name} 第 {attempt}/{cls.ROLE_MAX_ATTEMPTS} 次重试",
                        "role_id": role.key,
                        "round_index": round_index,
                    },
                )
            chunks: list[str] = []
            try:
                async for chunk in AdvisorService.chat_stream_with_logging(llm, prompt, context=context):
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    yield cls._sse_event(
                        "role_chunk",
                        {
                            "message_id": message_id,
                            "round_index": round_index,
                            "role_id": role.key,
                            "role_name": role.role_name,
                            "content": chunk,
                        },
                    )
                raw_text = "".join(chunks)
                opinion = cls._normalize_role_opinion(raw_text, role=role, round_index=round_index)
                break
            except Exception as exc:
                print(
                    f"[MultiAgent] stream role generation failed role={role.key} round={round_index} attempt={attempt}/{cls.ROLE_MAX_ATTEMPTS}: {exc}",
                    flush=True,
                )
                if attempt >= cls.ROLE_MAX_ATTEMPTS:
                    opinion = cls._fallback_role_opinion(role=role, round_index=round_index, error=exc)
        if opinion is None:
            opinion = cls._fallback_role_opinion(
                role=role,
                round_index=round_index,
                error=RuntimeError("角色未返回观点"),
            )
        output.append(opinion)
        yield cls._sse_event(
            "role_done",
            {
                "message_id": message_id,
                "opinion": opinion.model_dump(mode="json"),
            },
        )

    @classmethod
    async def _generate_arbiter_summary(
        cls,
        *,
        scene: MultiAgentScene,
        round_index: int,
        question: str | None,
        context_summary: MultiAgentContextSummary,
        search_bundle: SearchBundle,
        opinions: Sequence[MultiAgentRoleOpinion],
        provider: str,
        previous_arbiter: MultiAgentArbiterSummary | None = None,
    ) -> MultiAgentArbiterSummary:
        llm = cls._create_llm_client(provider)
        prompt_sections = [
            f"你是多智能体投资辩论系统中的【裁决角色】。",
            f"场景：{scene.value}",
            f"当前评估轮次：第{round_index}轮",
            "你的任务：判断剩余分歧是否已经可以忽略，且是否仍存在强烈反对意见。",
            "如果可以停止辩论，请明确说明原因；如果不能，请说明还需继续辩论的关键分歧。",
            "请输出 JSON，字段必须包含：consensus_reached, why_stop, strong_opposition, confidence, final_recommendation, recommended_action, conclusion, supporting_roles, disagreements, risk_notes。",
            "consensus_reached 只能是 true/false。",
            "不要输出 markdown 代码块，不要输出额外解释。",
            "",
            "## 问题",
            question.strip() if question and question.strip() else "未提供明确问题，请根据上下文裁决。",
            "",
            "## 结构化上下文",
            json.dumps(context_summary.model_dump(mode="python"), ensure_ascii=False, indent=2, default=str),
            "",
            "## 当前轮角色观点",
            json.dumps([item.model_dump(mode="python") for item in opinions], ensure_ascii=False, indent=2, default=str),
        ]
        if search_bundle.prompt_block:
            prompt_sections.extend(["", "## 外部搜索证据", search_bundle.prompt_block])
        if previous_arbiter is not None:
            prompt_sections.extend(
                [
                    "",
                    "## 上一轮裁决",
                    json.dumps(previous_arbiter.model_dump(mode="python"), ensure_ascii=False, indent=2, default=str),
                ]
            )
        if len(opinions) > 1:
            opposition_summary = []
            for opinion in opinions:
                opposition_summary.append(
                    f"- {opinion.role_name} | stance={opinion.stance} | summary={opinion.summary}"
                )
            prompt_sections.extend(["", "## 分歧摘要", "\n".join(opposition_summary)])
        prompt = "\n".join(prompt_sections)
        context = f"multi_agent:{scene.value}:arbiter:r{round_index}"
        from services.advisor_service import AdvisorService

        raw = await AdvisorService.chat_json_with_logging(llm, prompt, context=context)
        return cls._normalize_arbiter_summary(raw, round_index=round_index, latest_opinions=opinions, scene=scene)

    @classmethod
    def _select_debate_roles(
        cls,
        roles: Sequence[RoleBlueprint],
        opinions: Sequence[MultiAgentRoleOpinion],
        arbiter_summary: MultiAgentArbiterSummary,
    ) -> list[RoleBlueprint]:
        """后续轮只让冲突相关角色继续发言，并保留风控角色兜底。"""
        if not roles:
            return []

        conflict_text = " ".join([
            *arbiter_summary.strong_opposition,
            *arbiter_summary.disagreements,
            arbiter_summary.why_stop,
            arbiter_summary.conclusion,
        ])
        selected_keys: set[str] = set()
        opinion_by_role = {opinion.role_id: opinion for opinion in opinions}

        for role in roles:
            opinion = opinion_by_role.get(role.key)
            if role.key in conflict_text or role.role_name in conflict_text:
                selected_keys.add(role.key)
            if opinion and opinion.stance in {"bearish", "mixed"}:
                selected_keys.add(role.key)
            if opinion and any(note and note in conflict_text for note in opinion.risk_notes[:2]):
                selected_keys.add(role.key)

        risk_role = next((role for role in roles if role.key in {"risk_arbiter", "risk_exposure"}), None)
        if risk_role:
            selected_keys.add(risk_role.key)

        if not selected_keys:
            return list(roles)

        return [role for role in roles if role.key in selected_keys]

    @classmethod
    def _build_opposing_points(
        cls,
        *,
        role: RoleBlueprint,
        opinions: Sequence[MultiAgentRoleOpinion],
    ) -> list[str]:
        points: list[str] = []
        for opinion in opinions:
            if opinion.role_id == role.key:
                continue
            if opinion.summary:
                points.append(f"{opinion.role_name}：{opinion.summary}")
            points.extend(opinion.risk_notes[:1])
            if len(points) >= 4:
                break
        deduped: list[str] = []
        for point in points:
            clean = cls._normalize_text(point)
            if clean and clean not in deduped:
                deduped.append(clean)
            if len(deduped) >= 3:
                break
        return deduped

    @classmethod
    def _build_disagreement_summary(
        cls,
        opinions: Sequence[MultiAgentRoleOpinion],
    ) -> str:
        if not opinions:
            return "暂无可用角色观点。"
        bullish = [item.role_name for item in opinions if item.stance == "bullish"]
        bearish = [item.role_name for item in opinions if item.stance == "bearish"]
        mixed = [item.role_name for item in opinions if item.stance == "mixed"]
        lines = [
            f"看多角色：{', '.join(bullish) if bullish else '无'}",
            f"看空角色：{', '.join(bearish) if bearish else '无'}",
            f"中性/分歧角色：{', '.join(mixed) if mixed else '无'}",
        ]
        strongest_notes = []
        for item in opinions:
            strongest_notes.extend(item.risk_notes[:1])
        if strongest_notes:
            lines.append("主要风险点：")
            for note in strongest_notes[:4]:
                lines.append(f"- {note}")
        return "\n".join(lines)

    @classmethod
    def _round_convergence_state(
        cls,
        arbiter_summary: MultiAgentArbiterSummary,
        *,
        is_last_round: bool,
    ) -> str:
        if arbiter_summary.consensus_reached:
            return "converged"
        if is_last_round:
            return "max_rounds"
        return "contested"

    @classmethod
    def _build_run_response(
        cls,
        *,
        run_id: int,
        title: str,
        request: MultiAgentRunCreate,
        llm_provider: str,
        context_summary: MultiAgentContextSummary,
        search_bundle: SearchBundle,
        initial_role_opinions: Sequence[MultiAgentRoleOpinion],
        debate_rounds: Sequence[MultiAgentDebateRound],
        arbiter_summary: MultiAgentArbiterSummary,
        final_conclusion: MultiAgentFinalConclusion,
        status: str,
        created_at: datetime,
        chat_transcript: Sequence[dict[str, Any]] = (),
    ) -> MultiAgentRunResponse:
        response = MultiAgentRunResponse(
            run_id=run_id,
            title=title,
            scene=request.scene,
            question=request.question,
            use_portfolio_context=request.use_portfolio_context,
            max_debate_rounds=request.max_debate_rounds,
            collapse_debate_by_default=request.collapse_debate_by_default,
            llm_provider=llm_provider,
            created_at=created_at,
            context_summary=context_summary,
            initial_role_opinions=list(initial_role_opinions),
            role_opinions=list(debate_rounds[-1].role_opinions if debate_rounds else initial_role_opinions),
            debate_rounds=list(debate_rounds),
            search_metadata=list(search_bundle.metadata),
            arbiter_summary=arbiter_summary,
            final_conclusion=final_conclusion,
            chat_transcript=list(chat_transcript),
            status=status,  # type: ignore[arg-type]
        )
        return response

    @staticmethod
    def _sse_event(event: str, payload: dict[str, Any]) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

    @classmethod
    def _response_from_run(cls, run: MultiAgentRun) -> MultiAgentRunResponse:
        payload = json.loads(run.result_json or "{}")
        title = getattr(run, "title", None) or payload.get("title") or payload.get("context_summary", {}).get("title", "")
        payload["title"] = title
        if payload.get("context_summary") and not payload["context_summary"].get("title"):
            payload["context_summary"]["title"] = title
        return MultiAgentRunResponse.model_validate(payload)

    @classmethod
    async def create_run(
        cls,
        session: AsyncSession,
        user_id: int,
        request: MultiAgentRunCreate,
    ) -> MultiAgentRunResponse:
        response_created_at = cls.now_in_shanghai()
        db_created_at = cls.now_in_utc_naive()
        provider_snapshot = settings.llm_provider

        portfolio_summary = None
        holdings_preview: list[str] = []
        account_balance = None
        search_bundle = SearchBundle(prompt_block="", metadata=[])
        technical_context = TechnicalContextBundle(prompt_block="", codes=[])
        policy_event_context = PolicyEventContextBundle(prompt_block="", metadata=[])
        account_evidence_block = ""
        general_evidence_block = ""
        context_summary = MultiAgentContextSummary(
            scenario=request.scene,
            title=cls._scene_title(request.scene, request.question),
            question=request.question,
        )
        initial_role_opinions: list[MultiAgentRoleOpinion] = []
        debate_rounds: list[MultiAgentDebateRound] = []
        current_opinions: list[MultiAgentRoleOpinion] = []
        arbiter_summary: MultiAgentArbiterSummary = MultiAgentArbiterSummary(
            round_index=1,
            consensus_reached=False,
            why_stop="尚未开始辩论。",
            strong_opposition=[],
            confidence=0.0,
            final_recommendation="hold",
            recommended_action="继续观望",
            conclusion="多智能体辩论尚未执行。",
            supporting_roles=[],
            disagreements=[],
            risk_notes=[],
            convergence_state="forming",
        )
        final_conclusion = MultiAgentFinalConclusion(
            recommended_action="hold",
            action="继续观望",
            conclusion="多智能体辩论尚未执行。",
            confidence=0.0,
            supporting_roles=[],
            disagreements=[],
            risk_notes=[],
        )
        status = "failed"
        had_role_failure = False

        try:
            if request.use_portfolio_context:
                portfolio_summary, holdings_preview, account_balance = await cls._build_portfolio_context(session, user_id, request.portfolio_ids)
            if request.scene == MultiAgentScene.ACCOUNT:
                account_evidence_block = cls._account_evidence_block(portfolio_summary, holdings_preview, account_balance)
            elif request.scene == MultiAgentScene.GENERAL:
                general_evidence_block = cls._general_evidence_block(
                    question=request.question,
                    portfolio_summary=portfolio_summary,
                    holdings_preview=holdings_preview,
                )

            search_bundle = SearchBundle(prompt_block="", metadata=[])
            context_summary = cls._build_context_summary(
                scene=request.scene,
                question=request.question,
                use_portfolio_context=request.use_portfolio_context,
                max_debate_rounds=request.max_debate_rounds,
                portfolio_summary=portfolio_summary,
                holdings_preview=holdings_preview,
                account_balance=account_balance,
                search_bundle=search_bundle,
            )

            roles = cls.build_roles_for_scenario(request.scene)
            if any(role.key == "technical" for role in roles):
                technical_context = await cls._build_technical_context(
                    scene=request.scene,
                    question=request.question,
                    holdings_preview=holdings_preview,
                )
            policy_event_context = PolicyEventContextBundle(prompt_block="", metadata=[])

            async def generate_role_opinion(
                role: RoleBlueprint,
                *,
                round_index: int,
                previous_opinion: MultiAgentRoleOpinion | None = None,
                opposing_points: Sequence[str] = (),
                disagreement_summary: str = "",
            ) -> tuple[MultiAgentRoleOpinion, bool]:
                try:
                    opinion = await cls._generate_role_opinion_with_retries(
                        scene=request.scene,
                        role=role,
                        round_index=round_index,
                        question=request.question,
                        context_summary=context_summary,
                        search_bundle=search_bundle,
                        technical_context=technical_context,
                        policy_event_context=policy_event_context,
                        account_evidence_block=account_evidence_block,
                        general_evidence_block=general_evidence_block,
                        provider=provider_snapshot,
                        portfolio_summary=portfolio_summary,
                        holdings_preview=holdings_preview,
                        account_balance=account_balance,
                        previous_opinion=previous_opinion,
                        opposing_points=opposing_points,
                        disagreement_summary=disagreement_summary,
                    )
                    return opinion, opinion.confidence == 0.0
                except Exception as exc:
                    return cls._fallback_role_opinion(role=role, round_index=round_index, error=exc), True

            initial_results = await asyncio.gather(
                *(generate_role_opinion(role, round_index=1) for role in roles)
            )
            initial_role_opinions = [opinion for opinion, _ in initial_results]
            had_role_failure = had_role_failure or any(failed for _, failed in initial_results)

            debate_rounds: list[MultiAgentDebateRound] = []
            current_opinions = list(initial_role_opinions)
            arbiter_summary = await cls._generate_arbiter_summary(
                scene=request.scene,
                round_index=1,
                question=request.question,
                context_summary=context_summary,
                search_bundle=search_bundle,
                opinions=current_opinions,
                provider=provider_snapshot,
            )

            if not arbiter_summary.consensus_reached and request.max_debate_rounds > 1:
                previous_arbiter = arbiter_summary
                for round_index in range(2, request.max_debate_rounds + 1):
                    disagreement_summary = cls._build_disagreement_summary(current_opinions)
                    debate_roles = cls._select_debate_roles(roles, current_opinions, previous_arbiter)
                    round_results = await asyncio.gather(
                        *(
                            generate_role_opinion(
                                role,
                                round_index=round_index,
                                previous_opinion=next((item for item in current_opinions if item.role_id == role.key), None),
                                opposing_points=cls._build_opposing_points(role=role, opinions=current_opinions),
                                disagreement_summary=disagreement_summary,
                            )
                            for role in debate_roles
                        )
                    )
                    round_opinions = [opinion for opinion, _ in round_results]
                    had_role_failure = had_role_failure or any(failed for _, failed in round_results)
                    current_opinions = list(round_opinions)
                    arbiter_summary = await cls._generate_arbiter_summary(
                        scene=request.scene,
                        round_index=round_index,
                        question=request.question,
                        context_summary=context_summary,
                        search_bundle=search_bundle,
                        opinions=current_opinions,
                        provider=provider_snapshot,
                        previous_arbiter=previous_arbiter,
                    )
                    debate_rounds.append(
                        MultiAgentDebateRound(
                            round_index=round_index,
                            role_opinions=round_opinions,
                            round_summary=disagreement_summary,
                            open_disagreements=arbiter_summary.disagreements,
                            convergence_state=cls._round_convergence_state(
                                arbiter_summary,
                                is_last_round=round_index >= request.max_debate_rounds,
                            ),
                            arbiter_summary=arbiter_summary,
                        )
                    )
                    if arbiter_summary.consensus_reached:
                        break
                    previous_arbiter = arbiter_summary

            if not arbiter_summary.consensus_reached and (len(debate_rounds) + 1) >= request.max_debate_rounds:
                arbiter_summary = MultiAgentArbiterSummary.model_validate(
                    {
                        **arbiter_summary.model_dump(mode="python"),
                        "convergence_state": "max_rounds",
                        "why_stop": arbiter_summary.why_stop
                        or "已达到最大辩论轮数，裁决角色仍未认为分歧可以忽略。",
                    }
                )

            final_conclusion = cls._build_final_conclusion(
                scene=request.scene,
                arbiter_summary=arbiter_summary,
                latest_opinions=current_opinions,
            )
            status = "success" if arbiter_summary.consensus_reached and not had_role_failure else "partial"

        except Exception as exc:
            print(f"[MultiAgent] run creation failed: {exc}", flush=True)
            arbiter_summary = MultiAgentArbiterSummary(
                round_index=1,
                consensus_reached=False,
                why_stop=f"执行过程中发生异常：{exc}",
                strong_opposition=[],
                confidence=0.0,
                final_recommendation="hold",
                recommended_action="继续观望",
                conclusion="多智能体辩论执行失败，建议先观望。",
                supporting_roles=[],
                disagreements=[],
                risk_notes=[str(exc)],
                convergence_state="failed",
            )
            final_conclusion = MultiAgentFinalConclusion(
                recommended_action="hold",
                action="继续观望",
                conclusion="多智能体辩论执行失败，建议先观望。",
                confidence=0.0,
                supporting_roles=[],
                disagreements=[],
                risk_notes=[str(exc)],
            )
            status = "failed"

        title = context_summary.title
        response = cls._build_run_response(
            run_id=0,
            title=title,
            request=request,
            llm_provider=provider_snapshot,
            context_summary=context_summary,
            search_bundle=SearchBundle(
                prompt_block="\n\n".join(block for block in [search_bundle.prompt_block, account_evidence_block, general_evidence_block] if block),
                metadata=[*search_bundle.metadata, *policy_event_context.metadata],
            ),
            initial_role_opinions=initial_role_opinions,
            debate_rounds=debate_rounds,
            arbiter_summary=arbiter_summary,
            final_conclusion=final_conclusion,
            status=status,
            created_at=response_created_at,
        )

        run = MultiAgentRun(
            user_id=user_id,
            title=response.title,
            scene=request.scene.value,
            question=request.question,
            use_portfolio_context=request.use_portfolio_context,
            max_debate_rounds=request.max_debate_rounds,
            collapse_debate_by_default=request.collapse_debate_by_default,
            status=response.status,
            result_json=response.model_dump_json(),
            created_at=db_created_at,
            updated_at=db_created_at,
        )
        session.add(run)
        await session.flush()
        response.run_id = run.id
        run.result_json = response.model_dump_json()
        await session.flush()
        await cls._commit_if_available(session)
        return response

    @classmethod
    async def create_run_stream(
        cls,
        session: AsyncSession,
        user_id: int,
        request: MultiAgentRunCreate,
    ) -> AsyncIterator[str]:
        response_created_at = cls.now_in_shanghai()
        db_created_at = cls.now_in_utc_naive()
        provider_snapshot = settings.llm_provider

        portfolio_summary = None
        holdings_preview: list[str] = []
        account_balance = None
        search_bundle = SearchBundle(prompt_block="", metadata=[])
        technical_context = TechnicalContextBundle(prompt_block="", codes=[])
        policy_event_context = PolicyEventContextBundle(prompt_block="", metadata=[])
        account_evidence_block = ""
        general_evidence_block = ""
        context_summary = MultiAgentContextSummary(
            scenario=request.scene,
            title=cls._scene_title(request.scene, request.question),
            question=request.question,
        )
        initial_role_opinions: list[MultiAgentRoleOpinion] = []
        debate_rounds: list[MultiAgentDebateRound] = []
        current_opinions: list[MultiAgentRoleOpinion] = []
        arbiter_summary = MultiAgentArbiterSummary(
            round_index=1,
            consensus_reached=False,
            why_stop="尚未开始辩论。",
            strong_opposition=[],
            confidence=0.0,
            final_recommendation="hold",
            recommended_action="继续观望",
            conclusion="多智能体辩论尚未执行。",
            supporting_roles=[],
            disagreements=[],
            risk_notes=[],
            convergence_state="forming",
        )
        final_conclusion = MultiAgentFinalConclusion(
            recommended_action="hold",
            action="继续观望",
            conclusion="多智能体辩论尚未执行。",
            confidence=0.0,
            supporting_roles=[],
            disagreements=[],
            risk_notes=[],
        )
        status = "failed"
        had_role_failure = False
        chat_transcript: list[dict[str, Any]] = []

        def emit(event: str, payload: dict[str, Any], *, persist: bool = True) -> str:
            json_payload = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
            if persist:
                chat_transcript.append({"event": event, "payload": json_payload})
            return cls._sse_event(event, json_payload)

        def persist_sse_text(event_text: str) -> None:
            event_name = ""
            data = ""
            for line in event_text.splitlines():
                if line.startswith("event:"):
                    event_name = line.replace("event:", "", 1).strip()
                elif line.startswith("data:"):
                    data = line.replace("data:", "", 1).strip()
            if not event_name or not data:
                return
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                payload = {"raw": data}
            chat_transcript.append({"event": event_name, "payload": payload})

        async def emit_parallel_role_opinions(
            *,
            round_index: int,
            target: list[MultiAgentRoleOpinion],
            role_subset: Sequence[RoleBlueprint] | None = None,
            previous_opinions: Sequence[MultiAgentRoleOpinion] = (),
            disagreement_summary: str = "",
        ) -> AsyncIterator[str]:
            queue: asyncio.Queue[tuple[str, str, Any]] = asyncio.Queue()
            opinions_by_role: dict[str, MultiAgentRoleOpinion] = {}

            async def run_role(role: RoleBlueprint) -> None:
                output: list[MultiAgentRoleOpinion] = []
                message_id = f"role-{round_index}-{role.key}"
                try:
                    async for event in cls._stream_role_opinion_events(
                        scene=request.scene,
                        role=role,
                        round_index=round_index,
                        question=request.question,
                        context_summary=context_summary,
                        search_bundle=search_bundle,
                        technical_context=technical_context,
                        policy_event_context=policy_event_context,
                        account_evidence_block=account_evidence_block,
                        general_evidence_block=general_evidence_block,
                        provider=provider_snapshot,
                        previous_opinion=next((item for item in previous_opinions if item.role_id == role.key), None),
                        opposing_points=cls._build_opposing_points(role=role, opinions=previous_opinions) if previous_opinions else (),
                        disagreement_summary=disagreement_summary,
                        output=output,
                        portfolio_summary=portfolio_summary,
                        holdings_preview=holdings_preview,
                        account_balance=account_balance,
                    ):
                        await queue.put(("event", role.key, event))
                    opinion = output[0] if output else cls._fallback_role_opinion(
                        role=role,
                        round_index=round_index,
                        error=RuntimeError("角色未返回观点"),
                    )
                except Exception as exc:
                    opinion = cls._fallback_role_opinion(role=role, round_index=round_index, error=exc)
                    await queue.put((
                        "event",
                        role.key,
                        cls._sse_event("role_done", {"message_id": message_id, "opinion": opinion.model_dump(mode="json")}),
                    ))
                await queue.put(("done", role.key, opinion))

            active_roles = list(role_subset or roles)
            tasks = [asyncio.create_task(run_role(role)) for role in active_roles]
            completed = 0
            try:
                while completed < len(tasks):
                    kind, role_key, payload = await queue.get()
                    if kind == "event":
                        persist_sse_text(payload)
                        yield payload
                    elif kind == "done":
                        opinions_by_role[role_key] = payload
                        completed += 1
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            target.extend(
                opinions_by_role[role.key]
                for role in active_roles
                if role.key in opinions_by_role
            )

        yield emit(
            "meta",
            {
                "title": context_summary.title,
                "scene": request.scene.value,
                "llm_provider": provider_snapshot,
                "max_debate_rounds": request.max_debate_rounds,
                "collapse_debate_by_default": request.collapse_debate_by_default,
                "created_at": response_created_at.isoformat(),
            },
        )

        try:
            yield emit("status", {"message": "正在汇总持仓和账户上下文"})
            if request.use_portfolio_context:
                portfolio_summary, holdings_preview, account_balance = await cls._build_portfolio_context(session, user_id, request.portfolio_ids)
            if request.scene == MultiAgentScene.ACCOUNT:
                account_evidence_block = cls._account_evidence_block(portfolio_summary, holdings_preview, account_balance)
            elif request.scene == MultiAgentScene.GENERAL:
                general_evidence_block = cls._general_evidence_block(
                    question=request.question,
                    portfolio_summary=portfolio_summary,
                    holdings_preview=holdings_preview,
                )

            if cls._supports_native_agent(provider_snapshot):
                yield emit("status", {"message": "Gemini 将使用内置 Google Search 获取外部信息"})
            else:
                yield emit("status", {"message": "外部信息由智能体按需调用 Tavily 工具获取"})
            search_bundle = SearchBundle(prompt_block="", metadata=[])
            context_summary = cls._build_context_summary(
                scene=request.scene,
                question=request.question,
                use_portfolio_context=request.use_portfolio_context,
                max_debate_rounds=request.max_debate_rounds,
                portfolio_summary=portfolio_summary,
                holdings_preview=holdings_preview,
                account_balance=account_balance,
                search_bundle=search_bundle,
            )
            yield emit("context", context_summary.model_dump(mode="json"))

            roles = cls.build_roles_for_scenario(request.scene)
            if any(role.key == "technical" for role in roles):
                yield emit("status", {"message": "正在准备技术面K线和指标数据"})
                technical_context = await cls._build_technical_context(
                    scene=request.scene,
                question=request.question,
                holdings_preview=holdings_preview,
            )
            policy_event_context = PolicyEventContextBundle(prompt_block="", metadata=[])
            yield emit(
                "round_start",
                {"round_index": 1, "title": "第 1 轮初始并行分析", "role_count": len(roles)},
            )
            async for event in emit_parallel_role_opinions(
                round_index=1,
                target=initial_role_opinions,
            ):
                yield event
            had_role_failure = had_role_failure or any(opinion.confidence == 0.0 for opinion in initial_role_opinions)

            current_opinions = list(initial_role_opinions)
            yield emit("status", {"message": "裁决角色正在判断首轮分歧"})
            arbiter_summary = await cls._generate_arbiter_summary(
                scene=request.scene,
                round_index=1,
                question=request.question,
                context_summary=context_summary,
                search_bundle=search_bundle,
                opinions=current_opinions,
                provider=provider_snapshot,
            )
            yield emit("arbiter", arbiter_summary.model_dump(mode="json"))

            if not arbiter_summary.consensus_reached and request.max_debate_rounds > 1:
                previous_arbiter = arbiter_summary
                for round_index in range(2, request.max_debate_rounds + 1):
                    disagreement_summary = cls._build_disagreement_summary(current_opinions)
                    debate_roles = cls._select_debate_roles(roles, current_opinions, previous_arbiter)
                    yield emit(
                        "round_start",
                        {
                            "round_index": round_index,
                            "title": f"第 {round_index} 轮反驳与回应",
                            "summary": disagreement_summary,
                            "role_count": len(debate_roles),
                            "roles": [role.role_name for role in debate_roles],
                        },
                    )
                    round_opinions: list[MultiAgentRoleOpinion] = []
                    async for event in emit_parallel_role_opinions(
                        round_index=round_index,
                        target=round_opinions,
                        role_subset=debate_roles,
                        previous_opinions=current_opinions,
                        disagreement_summary=disagreement_summary,
                    ):
                        yield event
                    had_role_failure = had_role_failure or any(opinion.confidence == 0.0 for opinion in round_opinions)

                    current_opinions = list(round_opinions)
                    yield emit("status", {"message": f"裁决角色正在判断第 {round_index} 轮分歧"})
                    arbiter_summary = await cls._generate_arbiter_summary(
                        scene=request.scene,
                        round_index=round_index,
                        question=request.question,
                        context_summary=context_summary,
                        search_bundle=search_bundle,
                        opinions=current_opinions,
                        provider=provider_snapshot,
                        previous_arbiter=previous_arbiter,
                    )
                    debate_round = MultiAgentDebateRound(
                        round_index=round_index,
                        role_opinions=round_opinions,
                        round_summary=disagreement_summary,
                        open_disagreements=arbiter_summary.disagreements,
                        convergence_state=cls._round_convergence_state(
                            arbiter_summary,
                            is_last_round=round_index >= request.max_debate_rounds,
                        ),
                        arbiter_summary=arbiter_summary,
                    )
                    debate_rounds.append(debate_round)
                    yield emit("debate_round", debate_round.model_dump(mode="json"))
                    yield emit("arbiter", arbiter_summary.model_dump(mode="json"))
                    if arbiter_summary.consensus_reached:
                        break
                    previous_arbiter = arbiter_summary

            if not arbiter_summary.consensus_reached and (len(debate_rounds) + 1) >= request.max_debate_rounds:
                arbiter_summary = MultiAgentArbiterSummary.model_validate(
                    {
                        **arbiter_summary.model_dump(mode="python"),
                        "convergence_state": "max_rounds",
                        "why_stop": arbiter_summary.why_stop
                        or "已达到最大辩论轮数，裁决角色仍未认为分歧可以忽略。",
                    }
                )
                yield emit("arbiter", arbiter_summary.model_dump(mode="json"))

            final_conclusion = cls._build_final_conclusion(
                scene=request.scene,
                arbiter_summary=arbiter_summary,
                latest_opinions=current_opinions,
            )
            status = "success" if arbiter_summary.consensus_reached and not had_role_failure else "partial"

        except Exception as exc:
            print(f"[MultiAgent] stream run creation failed: {exc}", flush=True)
            arbiter_summary = MultiAgentArbiterSummary(
                round_index=1,
                consensus_reached=False,
                why_stop=f"执行过程中发生异常：{exc}",
                strong_opposition=[],
                confidence=0.0,
                final_recommendation="hold",
                recommended_action="继续观望",
                conclusion="多智能体辩论执行失败，建议先观望。",
                supporting_roles=[],
                disagreements=[],
                risk_notes=[str(exc)],
                convergence_state="failed",
            )
            final_conclusion = MultiAgentFinalConclusion(
                recommended_action="hold",
                action="继续观望",
                conclusion="多智能体辩论执行失败，建议先观望。",
                confidence=0.0,
                supporting_roles=[],
                disagreements=[],
                risk_notes=[str(exc)],
            )
            status = "failed"
            yield emit("error", {"message": str(exc)})

        title = context_summary.title
        final_payload = final_conclusion.model_dump(mode="json")
        chat_transcript.append({"event": "final", "payload": json.loads(json.dumps(final_payload, ensure_ascii=False, default=str))})
        response = cls._build_run_response(
            run_id=0,
            title=title,
            request=request,
            llm_provider=provider_snapshot,
            context_summary=context_summary,
            search_bundle=SearchBundle(
                prompt_block="\n\n".join(block for block in [search_bundle.prompt_block, account_evidence_block, general_evidence_block] if block),
                metadata=[*search_bundle.metadata, *policy_event_context.metadata],
            ),
            initial_role_opinions=initial_role_opinions,
            debate_rounds=debate_rounds,
            arbiter_summary=arbiter_summary,
            final_conclusion=final_conclusion,
            status=status,
            created_at=response_created_at,
            chat_transcript=chat_transcript,
        )

        run = MultiAgentRun(
            user_id=user_id,
            title=response.title,
            scene=request.scene.value,
            question=request.question,
            use_portfolio_context=request.use_portfolio_context,
            max_debate_rounds=request.max_debate_rounds,
            collapse_debate_by_default=request.collapse_debate_by_default,
            status=response.status,
            result_json=response.model_dump_json(),
            created_at=db_created_at,
            updated_at=db_created_at,
        )
        session.add(run)
        await session.flush()
        response.run_id = run.id
        run.result_json = response.model_dump_json()
        await session.flush()
        await cls._commit_if_available(session)
        yield emit("final", final_payload, persist=False)
        yield emit("done", response.model_dump(mode="json"), persist=False)

    @classmethod
    async def create_run_stream_with_managed_session(
        cls,
        user_id: int,
        request: MultiAgentRunCreate,
    ) -> AsyncIterator[str]:
        from database import async_session_maker

        async with async_session_maker() as session:
            try:
                async for event in cls.create_run_stream(session, user_id, request):
                    yield event
            except Exception:
                await session.rollback()
                raise

    @classmethod
    async def list_runs(
        cls,
        session: AsyncSession,
        user_id: int,
        limit: int = 20,
    ) -> MultiAgentRunListResponse:
        result = await session.execute(
            select(MultiAgentRun)
            .where(MultiAgentRun.user_id == user_id)
            .order_by(MultiAgentRun.created_at.desc(), MultiAgentRun.id.desc())
            .limit(limit)
        )
        runs = [cls._response_from_run(item) for item in result.scalars().all()]
        return MultiAgentRunListResponse(runs=runs)

    @classmethod
    async def get_run(
        cls,
        session: AsyncSession,
        user_id: int,
        run_id: int,
    ) -> MultiAgentRunDetailResponse | None:
        result = await session.execute(
            select(MultiAgentRun).where(MultiAgentRun.user_id == user_id, MultiAgentRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            return None
        return MultiAgentRunDetailResponse.model_validate(cls._response_from_run(run).model_dump())

    @classmethod
    async def update_run(
        cls,
        session: AsyncSession,
        user_id: int,
        run_id: int,
        request: MultiAgentRunUpdate,
    ) -> MultiAgentRunResponse | None:
        result = await session.execute(
            select(MultiAgentRun).where(MultiAgentRun.user_id == user_id, MultiAgentRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            return None

        title = request.title.strip()
        response = cls._response_from_run(run)
        response.title = title
        response.context_summary.title = title
        run.title = title
        run.result_json = response.model_dump_json()
        run.updated_at = cls.now_in_utc_naive()
        await session.flush()
        return response

    @classmethod
    async def delete_run(
        cls,
        session: AsyncSession,
        user_id: int,
        run_id: int,
    ) -> bool:
        result = await session.execute(
            select(MultiAgentRun).where(MultiAgentRun.user_id == user_id, MultiAgentRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            return False

        await session.delete(run)
        await session.flush()
        return True

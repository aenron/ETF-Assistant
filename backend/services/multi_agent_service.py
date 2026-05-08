from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

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


class MultiAgentService:
    """场景化 LLM 多智能体投资辩论编排器。"""

    ROLE_COUNT_LIMIT = 4

    @staticmethod
    def now_in_shanghai() -> datetime:
        return now_in_shanghai()

    @staticmethod
    def now_in_utc_naive() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

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
        for item in holdings_preview:
            bullets.append(item)
        return bullets[:10]

    @classmethod
    async def _build_portfolio_context(
        cls,
        session: AsyncSession,
        user_id: int,
    ) -> tuple[dict | None, list[str], float | None]:
        from services.portfolio_service import PortfolioService

        summary = await PortfolioService.get_summary(session, user_id=user_id)
        holdings = await PortfolioService.get_all(session, user_id=user_id)
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        account_balance = float(user.account_balance) if user and user.account_balance is not None else None

        holdings_preview = []
        for item in holdings[:3]:
            holdings_preview.append(f"{item.etf_code} | 份额 {item.shares:.2f} | 成本 {item.cost_price:.4f}")

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
        for item in holdings_preview[:2]:
            code = cls._normalize_text(item.split("|", 1)[0])
            if code:
                codes.append(code)

        queries: list[str] = []
        if scene == MultiAgentScene.ETF:
            if question_text:
                base = question_text
                if codes:
                    base = f"{base} {' '.join(codes)}"
                queries.append(f"{base} 最新 公告 新闻 政策 宏观 市场")
            elif codes:
                queries.append(f"{' '.join(codes)} 最新 公告 新闻 政策 宏观 市场")
        elif scene == MultiAgentScene.ACCOUNT:
            base = question_text or "账户组合 再平衡 风险"
            if codes:
                base = f"{base} {' '.join(codes)}"
            queries.append(f"{base} 最新 政策 新闻 风险 市场")
        else:
            if question_text:
                queries.append(f"{question_text} 最新 公告 新闻 政策 宏观 市场")
            elif portfolio_summary:
                queries.append("投资 最新 公告 新闻 政策 宏观 市场")

        deduped: list[str] = []
        for query in queries:
            clean_query = cls._normalize_text(query)
            if clean_query and clean_query not in deduped:
                deduped.append(clean_query[:180])
            if len(deduped) >= 2:
                break
        return deduped

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
        provider: str,
        previous_opinion: MultiAgentRoleOpinion | None = None,
        opposing_points: Sequence[str] = (),
        disagreement_summary: str = "",
    ) -> MultiAgentRoleOpinion:
        llm = cls._create_llm_client(provider)
        prompt_sections = [
            f"你是多智能体投资辩论系统中的【{role.role_name}】。",
            f"场景：{scene.value}",
            f"轮次：第{round_index}轮{'初评' if round_index == 1 else '辩论'}",
            f"角色职责：{role.focus}",
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
        prompt = "\n".join(prompt_sections)
        context = f"multi_agent:{scene.value}:{role.key}:r{round_index}"
        from services.advisor_service import AdvisorService

        raw = await AdvisorService.chat_json_with_logging(llm, prompt, context=context)
        return cls._normalize_role_opinion(raw, role=role, round_index=round_index)

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
    ) -> MultiAgentRunResponse:
        response = MultiAgentRunResponse(
            run_id=run_id,
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
            status=status,  # type: ignore[arg-type]
        )
        return response

    @classmethod
    def _response_from_run(cls, run: MultiAgentRun) -> MultiAgentRunResponse:
        payload = json.loads(run.result_json or "{}")
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
                portfolio_summary, holdings_preview, account_balance = await cls._build_portfolio_context(session, user_id)

            search_bundle = await cls._collect_search_context(
                scene=request.scene,
                question=request.question,
                holdings_preview=holdings_preview,
                portfolio_summary=portfolio_summary,
            )
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
            initial_tasks = [
                cls._generate_role_opinion(
                    scene=request.scene,
                    role=role,
                    round_index=1,
                    question=request.question,
                    context_summary=context_summary,
                    search_bundle=search_bundle,
                    provider=provider_snapshot,
                )
                for role in roles
            ]
            initial_results = await asyncio.gather(*initial_tasks, return_exceptions=True)
            initial_role_opinions = []
            for role, item in zip(roles, initial_results, strict=False):
                if isinstance(item, Exception):
                    had_role_failure = True
                    initial_role_opinions.append(cls._fallback_role_opinion(role=role, round_index=1, error=item))
                else:
                    initial_role_opinions.append(item)

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
                    round_tasks = [
                        cls._generate_role_opinion(
                            scene=request.scene,
                            role=role,
                            round_index=round_index,
                            question=request.question,
                            context_summary=context_summary,
                            search_bundle=search_bundle,
                            provider=provider_snapshot,
                            previous_opinion=next((item for item in current_opinions if item.role_id == role.key), None),
                            opposing_points=cls._build_opposing_points(role=role, opinions=current_opinions),
                            disagreement_summary=disagreement_summary,
                        )
                        for role in roles
                    ]
                    round_results = await asyncio.gather(*round_tasks, return_exceptions=True)
                    round_opinions = []
                    for role, item in zip(roles, round_results, strict=False):
                        if isinstance(item, Exception):
                            had_role_failure = True
                            round_opinions.append(
                                cls._fallback_role_opinion(role=role, round_index=round_index, error=item)
                            )
                        else:
                            round_opinions.append(item)
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

        response = cls._build_run_response(
            run_id=0,
            request=request,
            llm_provider=provider_snapshot,
            context_summary=context_summary,
            search_bundle=search_bundle,
            initial_role_opinions=initial_role_opinions,
            debate_rounds=debate_rounds,
            arbiter_summary=arbiter_summary,
            final_conclusion=final_conclusion,
            status=status,
            created_at=response_created_at,
        )

        run = MultiAgentRun(
            user_id=user_id,
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
        return response

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

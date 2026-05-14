import asyncio
import json
import unittest
import unittest.mock
import types
from dataclasses import asdict
from pathlib import Path
from datetime import datetime
import sys


backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from schemas.multi_agent import (
    MultiAgentArbiterSummary,
    MultiAgentContextSummary,
    MultiAgentDebateRound,
    MultiAgentFinalConclusion,
    MultiAgentRunCreate,
    MultiAgentRunResponse,
    MultiAgentRoleOpinion,
    MultiAgentScene,
    MultiAgentSearchMetadata,
)
from services.multi_agent_service import (
    MultiAgentService,
    PolicyEventContextBundle,
    RoleBlueprint,
    SearchBundle,
    TechnicalContextBundle,
)

fake_advisor_service = types.ModuleType("services.advisor_service")


class _FakeAdvisorService:
    @staticmethod
    def _prompt_time_context():
        return "当前测试时间。"

    async def chat_json_with_logging(self, *args, **kwargs):  # pragma: no cover - patched in tests
        raise AssertionError("Unexpected AdvisorService call")


fake_advisor_service.AdvisorService = _FakeAdvisorService()
sys.modules.setdefault("services.advisor_service", fake_advisor_service)


class _FakeRun:
    def __init__(self):
        self.id = 1
        self.result_json = None


class _FakeSession:
    def __init__(self):
        self.added = []
        self.flush_count = 0

    def add(self, obj):
        self.added.append(obj)
        obj.id = 1

    async def flush(self):
        self.flush_count += 1

    async def execute(self, statement):  # pragma: no cover - not used in these tests
        raise AssertionError(f"Unexpected database access: {statement}")


class MultiAgentServiceContractTests(unittest.TestCase):
    def test_request_includes_debate_controls(self):
        payload = MultiAgentRunCreate(
            scene=MultiAgentScene.ETF,
            question="159655 近期是否适合加仓？",
            use_portfolio_context=True,
            max_debate_rounds=4,
            collapse_debate_by_default=False,
        )
        self.assertEqual(payload.max_debate_rounds, 4)
        self.assertFalse(payload.collapse_debate_by_default)

    def test_run_response_exposes_debate_transcript_fields(self):
        payload = MultiAgentRunResponse(
            run_id=1,
            scene=MultiAgentScene.ACCOUNT,
            question="账户要不要再平衡",
            use_portfolio_context=True,
            max_debate_rounds=3,
            collapse_debate_by_default=True,
            created_at=datetime(2026, 5, 7, 15, 6, 2),
            context_summary=MultiAgentContextSummary(
                scenario=MultiAgentScene.ACCOUNT,
                title="账户研判",
                bullets=["账户总金额：100000"],
            ),
            initial_role_opinions=[
                MultiAgentRoleOpinion(
                    round_index=1,
                    role_id="portfolio_structure",
                    role_name="组合结构角色",
                    stance="neutral",
                    summary="先看仓位结构",
                    evidence=["组合需要看集中度"],
                    risk_notes=["仓位过高会放大回撤"],
                    confidence=70.0,
                )
            ],
            debate_rounds=[
                MultiAgentDebateRound(
                    round_index=2,
                    role_opinions=[],
                    round_summary="分歧仍在",
                    open_disagreements=["再平衡优先级"],
                    convergence_state="contested",
                )
            ],
            search_metadata=[
                MultiAgentSearchMetadata(
                    query="账户再平衡 风险",
                    answer=None,
                    result_count=2,
                    results=[{"title": "示例", "url": "https://example.com", "content": "snippet"}],
                )
            ],
            arbiter_summary=MultiAgentArbiterSummary(
                round_index=2,
                consensus_reached=False,
                why_stop="仍有强烈反对意见",
                strong_opposition=["风险暴露角色"],
                confidence=68.0,
                final_recommendation="hold",
                recommended_action="继续观察",
                conclusion="暂时保持观望",
                supporting_roles=["组合结构角色"],
                disagreements=["再平衡时机未定"],
                risk_notes=["相关性偏高"],
                convergence_state="contested",
            ),
            final_conclusion=MultiAgentFinalConclusion(
                recommended_action="hold",
                action="继续观察",
                conclusion="暂时保持观望",
                confidence=68.0,
                supporting_roles=["组合结构角色"],
                disagreements=["再平衡时机未定"],
                risk_notes=["相关性偏高"],
            ),
            status="partial",
        )
        self.assertEqual(payload.initial_role_opinions[0].role_id, "portfolio_structure")
        self.assertEqual(payload.role_opinions[0].role_id, "portfolio_structure")
        self.assertEqual(payload.debate_rounds[0].round_index, 2)
        self.assertEqual(payload.arbiter_summary.round_index, 2)
        self.assertEqual(payload.max_debate_rounds, 3)

    def test_portfolio_context_includes_all_holdings_with_names(self):
        class _UserResult:
            def scalar_one_or_none(self):
                return types.SimpleNamespace(account_balance=1234.56)

        class _Session:
            async def execute(self, statement):
                return _UserResult()

        holdings = [
            types.SimpleNamespace(
                etf_code="513300",
                etf_name="纳斯达克ETF华夏",
                shares=100.0,
                cost_price=1.2345,
                current_price=1.3456,
                market_value=134.56,
                pnl_pct=9.0,
                today_pnl=None,
                today_pnl_pct=None,
            ),
            types.SimpleNamespace(
                etf_code="511380",
                etf_name="可转债ETF",
                shares=200.0,
                cost_price=10.0,
                current_price=10.1,
                market_value=2020.0,
                pnl_pct=1.0,
                today_pnl=None,
                today_pnl_pct=None,
            ),
            *[
                types.SimpleNamespace(
                    etf_code=f"15900{index}",
                    etf_name=f"测试ETF{index}",
                    shares=10.0,
                    cost_price=1.0,
                    current_price=1.0,
                    market_value=10.0,
                    pnl_pct=0.0,
                    today_pnl=None,
                    today_pnl_pct=None,
                )
                for index in range(1, 6)
            ],
        ]

        async def run_test():
            from services.portfolio_service import PortfolioService

            with unittest.mock.patch.object(PortfolioService, "get_with_market", return_value=holdings):
                return await MultiAgentService._build_portfolio_context(_Session(), user_id=7)

        summary, holdings_preview, account_balance = asyncio.run(run_test())

        self.assertEqual(len(holdings_preview), 7)
        self.assertEqual(account_balance, 1234.56)
        self.assertIn("513300 纳斯达克ETF华夏", holdings_preview[0])
        self.assertIn("511380 可转债ETF", holdings_preview[1])
        self.assertGreater(float(summary["total_assets"]), 0)

    def test_search_and_code_extraction_use_full_holding_preview(self):
        holdings_preview = [
            "513300 纳斯达克ETF华夏 | 份额 100.00 | 成本 1.0000",
            "511380 可转债ETF | 份额 100.00 | 成本 1.0000",
            "159001 测试ETF1 | 份额 100.00 | 成本 1.0000",
            "159002 测试ETF2 | 份额 100.00 | 成本 1.0000",
            "159003 测试ETF3 | 份额 100.00 | 成本 1.0000",
            "159004 测试ETF4 | 份额 100.00 | 成本 1.0000",
            "159005 测试ETF5 | 份额 100.00 | 成本 1.0000",
        ]

        codes = MultiAgentService._extract_etf_codes(None, holdings_preview)
        queries = MultiAgentService._build_search_queries(
            MultiAgentScene.ETF,
            None,
            holdings_preview,
            portfolio_summary={},
        )

        self.assertEqual(codes, ["513300", "511380", "159001", "159002", "159003", "159004", "159005"])
        self.assertTrue(queries)
        self.assertIn("513300", queries[0])
        self.assertIn("159005", queries[0])
        self.assertIn("纳斯达克ETF华夏", queries[0])

    def test_create_run_runs_initial_round_sequentially_and_stops_on_consensus(self):
        session = _FakeSession()
        request = MultiAgentRunCreate(
            scene=MultiAgentScene.ETF,
            question="159655 近期是否适合加仓？",
            use_portfolio_context=True,
            max_debate_rounds=3,
            collapse_debate_by_default=True,
        )
        initial_role_opinions = [
            MultiAgentRoleOpinion(
                round_index=1,
                role_id="policy_event",
                role_name="政策事件角色",
                stance="bullish",
                action="可小幅加仓",
                summary="政策环境偏正面",
                evidence=["最新公告偏利好"],
                risk_notes=["已部分定价"],
                confidence=78.0,
            ),
            MultiAgentRoleOpinion(
                round_index=1,
                role_id="technical",
                role_name="技术面角色",
                stance="neutral",
                action="等待确认",
                summary="技术面尚可但不追高",
                evidence=["趋势尚稳"],
                risk_notes=["短线波动仍在"],
                confidence=74.0,
            ),
            MultiAgentRoleOpinion(
                round_index=1,
                role_id="allocation",
                role_name="配置视角角色",
                stance="bullish",
                action="保持配置",
                summary="长期配置仍合理",
                evidence=["长期逻辑未破"],
                risk_notes=["仓位过重需控制节奏"],
                confidence=76.0,
            ),
            MultiAgentRoleOpinion(
                round_index=1,
                role_id="risk_arbiter",
                role_name="风控裁决角色",
                stance="neutral",
                action="保守持有",
                summary="整体可继续持有",
                evidence=["风险可控"],
                risk_notes=["关注回撤"],
                confidence=80.0,
            ),
        ]
        max_active = 0
        active = 0

        async def fake_build_portfolio_context(*args, **kwargs):
            return (
                {
                    "total_assets": 100000,
                    "total_market_value": 70000,
                    "total_pnl": 1000,
                    "total_pnl_pct": 1.5,
                    "today_pnl": 100,
                    "today_pnl_pct": 0.2,
                },
                ["159655 | 份额 100.00 | 成本 1.0000"],
                30000.0,
            )

        async def fake_collect_search_context(*args, **kwargs):
            return SearchBundle(
                prompt_block="### tavily_search #1\n- query: 159655 最新 公告 新闻 政策 宏观 市场",
                metadata=[
                    MultiAgentSearchMetadata(
                        query="159655 最新 公告 新闻 政策 宏观 市场",
                        answer=None,
                        result_count=1,
                        results=[{"title": "示例新闻", "url": "https://example.com", "content": "snippet"}],
                    )
                ],
            )

        async def fake_generate_role_opinion(*, role, round_index, **kwargs):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return next(item for item in initial_role_opinions if item.role_id == role.key)

        async def fake_generate_arbiter_summary(*, round_index, **kwargs):
            return MultiAgentArbiterSummary(
                round_index=round_index,
                consensus_reached=True,
                why_stop="分歧已可忽略",
                strong_opposition=[],
                confidence=84.0,
                final_recommendation="hold",
                recommended_action="继续持有",
                conclusion="保持持有并观察",
                supporting_roles=["政策事件角色", "技术面角色"],
                disagreements=[],
                risk_notes=["短线仍有波动"],
                convergence_state="converged",
            )

        async def run_case():
            with (
                unittest.mock.patch.object(MultiAgentService, "_build_portfolio_context", new=fake_build_portfolio_context),
                unittest.mock.patch.object(MultiAgentService, "_collect_search_context", new=fake_collect_search_context),
                unittest.mock.patch.object(MultiAgentService, "_generate_role_opinion", new=fake_generate_role_opinion),
                unittest.mock.patch.object(MultiAgentService, "_generate_arbiter_summary", new=fake_generate_arbiter_summary),
            ):
                return await MultiAgentService.create_run(session, user_id=7, request=request)

        response = asyncio.run(run_case())

        self.assertEqual(max_active, 1)
        self.assertEqual(response.status, "success")
        self.assertEqual(len(response.initial_role_opinions), 4)
        self.assertEqual(len(response.debate_rounds), 0)
        self.assertEqual(response.arbiter_summary.consensus_reached, True)
        self.assertEqual(len(session.added), 1)
        self.assertIn("initial_role_opinions", session.added[0].result_json)
        self.assertIn("search_metadata", session.added[0].result_json)

    def test_create_run_runs_until_max_rounds_when_no_consensus(self):
        session = _FakeSession()
        request = MultiAgentRunCreate(
            scene=MultiAgentScene.GENERAL,
            question="最近黄金还能加吗",
            use_portfolio_context=False,
            max_debate_rounds=3,
            collapse_debate_by_default=True,
        )
        current_by_round = {
            1: [
                MultiAgentRoleOpinion(
                    round_index=1,
                    role_id="researcher",
                    role_name="研究员角色",
                    stance="neutral",
                    action="先确认边界",
                    summary="问题边界要先明确",
                    evidence=["缺少目标期限"],
                    risk_notes=["信息不足"],
                    confidence=60.0,
                )
            ],
            2: [
                MultiAgentRoleOpinion(
                    round_index=2,
                    role_id="researcher",
                    role_name="研究员角色",
                    stance="neutral",
                    action="继续观察",
                    summary="仍未形成统一意见",
                    evidence=["新闻证据有限"],
                    risk_notes=["仍有分歧"],
                    confidence=58.0,
                )
            ],
            3: [
                MultiAgentRoleOpinion(
                    round_index=3,
                    role_id="researcher",
                    role_name="研究员角色",
                    stance="neutral",
                    action="保持观望",
                    summary="已接近轮次上限",
                    evidence=["仍缺少关键证据"],
                    risk_notes=["继续辩论收益有限"],
                    confidence=55.0,
                )
            ],
        }
        call_rounds: list[int] = []

        async def fake_collect_search_context(*args, **kwargs):
            return SearchBundle(prompt_block="", metadata=[])

        async def fake_generate_role_opinion(*, role, round_index, **kwargs):
            call_rounds.append(round_index)
            return current_by_round[round_index][0] if round_index in current_by_round else current_by_round[3][0]

        async def fake_generate_arbiter_summary(*, round_index, **kwargs):
            return MultiAgentArbiterSummary(
                round_index=round_index,
                consensus_reached=False,
                why_stop="仍存在强烈反对意见",
                strong_opposition=["反方质疑角色"],
                confidence=66.0,
                final_recommendation="hold",
                recommended_action="继续观望",
                conclusion="证据仍不足，暂不收敛",
                supporting_roles=["研究员角色"],
                disagreements=["结论分歧明显"],
                risk_notes=["搜索结果不足"],
                convergence_state="contested",
            )

        async def run_case():
            with (
                unittest.mock.patch.object(MultiAgentService, "_collect_search_context", new=fake_collect_search_context),
                unittest.mock.patch.object(MultiAgentService, "_generate_role_opinion", new=fake_generate_role_opinion),
                unittest.mock.patch.object(MultiAgentService, "_generate_arbiter_summary", new=fake_generate_arbiter_summary),
            ):
                return await MultiAgentService.create_run(session, user_id=7, request=request)

        response = asyncio.run(run_case())

        self.assertEqual(response.status, "partial")
        self.assertEqual(response.arbiter_summary.convergence_state, "max_rounds")
        self.assertEqual(len(response.debate_rounds), 2)
        self.assertEqual([item.round_index for item in response.debate_rounds], [2, 3])
        self.assertEqual(call_rounds.count(1), 4)
        self.assertEqual(call_rounds.count(2), 4)
        self.assertEqual(call_rounds.count(3), 4)

    def test_search_disabled_skips_tavily(self):
        session = _FakeSession()
        request = MultiAgentRunCreate(
            scene=MultiAgentScene.GENERAL,
            question="黄金还值得看吗",
            use_portfolio_context=False,
            max_debate_rounds=1,
            collapse_debate_by_default=True,
        )

        async def fake_generate_role_opinion(*, role, round_index, **kwargs):
            return MultiAgentRoleOpinion(
                round_index=round_index,
                role_id=role.key,
                role_name=role.role_name,
                stance="neutral",
                action="观望",
                summary="先看边界",
                evidence=["无外部搜索"],
                risk_notes=["信息不足"],
                confidence=60.0,
            )

        async def fake_generate_arbiter_summary(*, round_index, **kwargs):
            return MultiAgentArbiterSummary(
                round_index=round_index,
                consensus_reached=True,
                why_stop="无需搜索也可收敛",
                strong_opposition=[],
                confidence=65.0,
                final_recommendation="hold",
                recommended_action="观望",
                conclusion="先观望",
                supporting_roles=["研究员角色"],
                disagreements=[],
                risk_notes=[],
                convergence_state="converged",
            )

        async def run_case():
            with (
                unittest.mock.patch("services.multi_agent_service.TavilySearchService.is_enabled", return_value=False),
                unittest.mock.patch("services.multi_agent_service.TavilySearchService.search") as mock_search,
                unittest.mock.patch.object(MultiAgentService, "_generate_role_opinion", new=fake_generate_role_opinion),
                unittest.mock.patch.object(MultiAgentService, "_generate_arbiter_summary", new=fake_generate_arbiter_summary),
            ):
                result = await MultiAgentService.create_run(session, user_id=7, request=request)
                return result, mock_search

        response, mock_search = asyncio.run(run_case())

        self.assertEqual(response.arbiter_summary.consensus_reached, True)
        mock_search.assert_not_called()
        self.assertEqual(response.search_metadata, [])

    def test_technical_context_is_only_injected_for_technical_role(self):
        prompts: dict[str, str] = {}
        context_summary = MultiAgentContextSummary(
            scenario=MultiAgentScene.ETF,
            title="159655 技术面研判",
            bullets=[],
        )
        technical_context = TechnicalContextBundle(
            prompt_block="### 159655\n- 最近5根日K：\n- 2026-05-08: 开1.000 收1.020 高1.030 低0.990 涨跌2.00% 量1000\n- RSI(14)：68.5\n- MACD：DIF=0.01，DEA=0.02，柱=-0.02",
            codes=["159655"],
        )

        async def fake_chat_json_with_logging(llm, prompt, context):
            prompts[context] = prompt
            return {
                "stance": "neutral",
                "action": "等待确认",
                "summary": "技术面等待突破确认",
                "evidence": ["RSI 与 MACD 已纳入判断"],
                "risk_notes": ["短线波动"],
                "confidence": 66,
                "rebuttals": [],
            }

        async def run_case():
            with (
                unittest.mock.patch.object(MultiAgentService, "_create_llm_client", return_value=object()),
                unittest.mock.patch("services.advisor_service.AdvisorService.chat_json_with_logging", new=fake_chat_json_with_logging),
            ):
                await MultiAgentService._generate_role_opinion(
                    scene=MultiAgentScene.ETF,
                    role=RoleBlueprint("technical", "技术面角色", "判断价格位置。"),
                    round_index=1,
                    question="159655 技术面怎么看",
                    context_summary=context_summary,
                    search_bundle=SearchBundle(prompt_block="", metadata=[]),
                    technical_context=technical_context,
                    provider="openai",
                )
                await MultiAgentService._generate_role_opinion(
                    scene=MultiAgentScene.ETF,
                    role=RoleBlueprint("policy_event", "政策事件角色", "判断政策事件。"),
                    round_index=1,
                    question="159655 技术面怎么看",
                    context_summary=context_summary,
                    search_bundle=SearchBundle(prompt_block="", metadata=[]),
                    technical_context=technical_context,
                    provider="openai",
                )

        asyncio.run(run_case())

        technical_prompt = prompts["multi_agent:etf:technical:r1"]
        policy_prompt = prompts["multi_agent:etf:policy_event:r1"]
        self.assertIn("## 技术面K线与指标数据", technical_prompt)
        self.assertIn("最近5根日K", technical_prompt)
        self.assertIn("RSI(14)", technical_prompt)
        self.assertIn("## 技术面输出要求", technical_prompt)
        self.assertIn("evidence 至少 2 条", technical_prompt)
        self.assertIn("K 线、均线、RSI、MACD", technical_prompt)
        self.assertNotIn("## 技术面K线与指标数据", policy_prompt)

    def test_policy_event_context_requires_news_policy_evidence(self):
        prompts: dict[str, str] = {}
        context_summary = MultiAgentContextSummary(
            scenario=MultiAgentScene.ETF,
            title="159655 政策事件研判",
            bullets=[],
        )
        policy_context = PolicyEventContextBundle(
            prompt_block=(
                "### tavily_search #1\n"
                "- query: 159655 最新 政策 公告 新闻\n"
                "- results:\n"
                "  1. title=示例政策新闻; url=https://example.com/policy; date=2026-05-08; content=监管政策影响行业估值"
            ),
            metadata=[],
        )

        async def fake_chat_json_with_logging(llm, prompt, context):
            prompts[context] = prompt
            return {
                "stance": "neutral",
                "action": "等待政策落地",
                "summary": "政策事件证据有限，先观察",
                "evidence": ["示例政策新闻 | 2026-05-08 | https://example.com/policy | 影响行业估值"],
                "risk_notes": ["政策落地节奏不确定"],
                "confidence": 62,
                "rebuttals": [],
            }

        async def run_case():
            with (
                unittest.mock.patch.object(MultiAgentService, "_create_llm_client", return_value=object()),
                unittest.mock.patch("services.advisor_service.AdvisorService.chat_json_with_logging", new=fake_chat_json_with_logging),
            ):
                await MultiAgentService._generate_role_opinion(
                    scene=MultiAgentScene.ETF,
                    role=RoleBlueprint("policy_event", "政策事件角色", "判断政策事件。"),
                    round_index=1,
                    question="159655 政策事件怎么看",
                    context_summary=context_summary,
                    search_bundle=SearchBundle(prompt_block="", metadata=[]),
                    policy_event_context=policy_context,
                    provider="openai",
                )
                await MultiAgentService._generate_role_opinion(
                    scene=MultiAgentScene.ETF,
                    role=RoleBlueprint("allocation", "配置视角角色", "判断配置价值。"),
                    round_index=1,
                    question="159655 政策事件怎么看",
                    context_summary=context_summary,
                    search_bundle=SearchBundle(prompt_block="", metadata=[]),
                    policy_event_context=policy_context,
                    provider="openai",
                )

        asyncio.run(run_case())

        policy_prompt = prompts["multi_agent:etf:policy_event:r1"]
        allocation_prompt = prompts["multi_agent:etf:allocation:r1"]
        self.assertIn("## 政策事件专用搜索证据", policy_prompt)
        self.assertIn("示例政策新闻", policy_prompt)
        self.assertIn("## 政策事件输出要求", policy_prompt)
        self.assertIn("evidence 至少 2 条", policy_prompt)
        self.assertIn("来源标题或URL", policy_prompt)
        self.assertNotIn("## 政策事件专用搜索证据", allocation_prompt)

    def test_account_roles_require_account_data_evidence(self):
        prompts: dict[str, str] = {}
        context_summary = MultiAgentContextSummary(
            scenario=MultiAgentScene.ACCOUNT,
            title="账户再平衡研判",
            bullets=[],
        )
        account_block = "\n".join(
            [
                "以下账户数据供账户场景各角色引用为决策证据：",
                "- 总市值：¥70,000.00",
                "- 总盈亏：+1,000.00 (+1.50%)",
                "- 可用资金：¥30,000.00",
                "- 持仓预览：",
                "  - 510300 | 份额 1000.00 | 成本 4.0000",
            ]
        )

        async def fake_chat_json_with_logging(llm, prompt, context):
            prompts[context] = prompt
            return {
                "stance": "neutral",
                "action": "小幅再平衡",
                "summary": "账户结构需小幅再平衡",
                "evidence": ["可用资金 30000 支持分批执行", "总盈亏 +1.50% 可适度锁定收益"],
                "risk_notes": ["集中度待确认"],
                "confidence": 70,
                "rebuttals": [],
            }

        async def run_case():
            with (
                unittest.mock.patch.object(MultiAgentService, "_create_llm_client", return_value=object()),
                unittest.mock.patch("services.advisor_service.AdvisorService.chat_json_with_logging", new=fake_chat_json_with_logging),
            ):
                await MultiAgentService._generate_role_opinion(
                    scene=MultiAgentScene.ACCOUNT,
                    role=RoleBlueprint("rebalance", "再平衡角色", "判断是否应该再平衡。"),
                    round_index=1,
                    question="账户要不要再平衡",
                    context_summary=context_summary,
                    search_bundle=SearchBundle(prompt_block="### tavily_search #1\n- query: 账户再平衡 风险", metadata=[]),
                    account_evidence_block=account_block,
                    provider="openai",
                )

        asyncio.run(run_case())

        prompt = prompts["multi_agent:account:rebalance:r1"]
        self.assertIn("## 账户数据证据", prompt)
        self.assertIn("总市值：¥70,000.00", prompt)
        self.assertIn("## 账户场景证据输出要求", prompt)
        self.assertIn("evidence 至少 2 条", prompt)
        self.assertIn("总资产、总市值、总盈亏、今日盈亏、可用资金", prompt)
        self.assertIn("重点引用总盈亏、今日盈亏、仓位结构、现金比例或持仓偏离", prompt)

    def test_general_roles_require_source_evidence(self):
        prompts: dict[str, str] = {}
        context_summary = MultiAgentContextSummary(
            scenario=MultiAgentScene.GENERAL,
            title="黄金还能买吗",
            bullets=[],
        )
        general_block = "\n".join(
            [
                "以下通用场景数据供各角色引用为决策证据：",
                "- 用户问题：最近黄金还能买吗",
                "- 组合总资产：¥100,000.00",
            ]
        )

        async def fake_chat_json_with_logging(llm, prompt, context):
            prompts[context] = prompt
            return {
                "stance": "mixed",
                "action": "等待更多证据",
                "summary": "问题需要结合最新金价和宏观证据",
                "evidence": ["用户问题缺少期限", "搜索结果显示宏观不确定"],
                "risk_notes": ["信息边界不清"],
                "confidence": 60,
                "rebuttals": [],
            }

        async def run_case():
            with (
                unittest.mock.patch.object(MultiAgentService, "_create_llm_client", return_value=object()),
                unittest.mock.patch("services.advisor_service.AdvisorService.chat_json_with_logging", new=fake_chat_json_with_logging),
            ):
                await MultiAgentService._generate_role_opinion(
                    scene=MultiAgentScene.GENERAL,
                    role=RoleBlueprint("evidence", "证据搜索角色", "整合最新证据。"),
                    round_index=1,
                    question="最近黄金还能买吗",
                    context_summary=context_summary,
                    search_bundle=SearchBundle(prompt_block="### tavily_search #1\n- query: 黄金 最新 新闻\n- results:\n  1. title=黄金新闻; url=https://example.com/gold", metadata=[]),
                    general_evidence_block=general_block,
                    provider="openai",
                )

        asyncio.run(run_case())

        prompt = prompts["multi_agent:general:evidence:r1"]
        self.assertIn("## 通用场景证据", prompt)
        self.assertIn("用户问题：最近黄金还能买吗", prompt)
        self.assertIn("## 通用场景证据输出要求", prompt)
        self.assertIn("evidence 至少 2 条", prompt)
        self.assertIn("来源标题或URL", prompt)


if __name__ == "__main__":
    unittest.main()

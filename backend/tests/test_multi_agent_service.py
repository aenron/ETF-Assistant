import asyncio
import json
import unittest
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
from services.multi_agent_service import MultiAgentService, RoleBlueprint, SearchBundle


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

    def test_create_run_runs_initial_round_in_parallel_and_stops_on_consensus(self):
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

        self.assertGreater(max_active, 1)
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


if __name__ == "__main__":
    unittest.main()

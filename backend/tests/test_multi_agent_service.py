import asyncio
import json
import unittest
import unittest.mock
import types
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

    async def chat_stream_with_logging(self, *args, **kwargs):  # pragma: no cover - patched in tests
        raise AssertionError("Unexpected AdvisorService call")
        yield ""


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

    def test_stream_run_emits_parallel_roles_and_stops_on_consensus(self):
        session = _FakeSession()
        request = MultiAgentRunCreate(
            scene=MultiAgentScene.ETF,
            question="159655 近期是否适合加仓？",
            use_portfolio_context=False,
            max_debate_rounds=3,
        )
        active = 0
        max_active = 0

        async def fake_stream_role(*, role, round_index, output, **kwargs):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            message_id = f"role-{round_index}-{role.key}"
            yield MultiAgentService._sse_event("role_start", {
                "message_id": message_id,
                "round_index": round_index,
                "role_id": role.key,
                "role_name": role.role_name,
            })
            if role.key == "policy_event":
                yield MultiAgentService._sse_event("tool_call_start", {
                    "message_id": message_id,
                    "tool_name": "search_latest_news",
                    "arguments": {"query": "159655"},
                })
                yield MultiAgentService._sse_event("tool_call_done", {
                    "message_id": message_id,
                    "tool_name": "search_latest_news",
                    "result": {"results": []},
                })
            await asyncio.sleep(0.01)
            opinion = MultiAgentRoleOpinion(
                round_index=round_index,
                role_id=role.key,
                role_name=role.role_name,
                stance="neutral",
                action="继续观察",
                summary=f"{role.role_name}观点",
                evidence=["已核对数据"],
                risk_notes=["关注波动"],
                confidence=75.0,
            )
            output.append(opinion)
            yield MultiAgentService._sse_event("role_done", {
                "message_id": message_id,
                "opinion": opinion.model_dump(mode="json"),
            })
            active -= 1

        async def fake_technical_context(**kwargs):
            return TechnicalContextBundle(prompt_block="", codes=[])

        async def fake_arbiter(*, round_index, **kwargs):
            return MultiAgentArbiterSummary(
                round_index=round_index,
                consensus_reached=True,
                why_stop="分歧已可忽略",
                confidence=84.0,
                final_recommendation="hold",
                recommended_action="继续持有",
                conclusion="保持持有并观察",
                supporting_roles=["政策事件角色", "技术面角色"],
                risk_notes=["短线仍有波动"],
                convergence_state="converged",
            )

        async def run_case():
            with (
                unittest.mock.patch.object(MultiAgentService, "_build_technical_context", new=fake_technical_context),
                unittest.mock.patch.object(MultiAgentService, "_stream_role_opinion_events", new=fake_stream_role),
                unittest.mock.patch.object(MultiAgentService, "_generate_arbiter_summary", new=fake_arbiter),
            ):
                return [event async for event in MultiAgentService.create_run_stream(session, user_id=7, request=request)]

        events = asyncio.run(run_case())
        event_names = [event.split("\n", 1)[0] for event in events]
        response = MultiAgentRunResponse.model_validate(json.loads(events[-1].split("data: ", 1)[1]))

        self.assertEqual(max_active, 4)
        self.assertEqual(event_names.count("event: role_done"), 4)
        self.assertEqual(event_names.count("event: tool_call_start"), 1)
        self.assertEqual(event_names.count("event: tool_call_done"), 1)
        self.assertEqual(event_names.count("event: arbiter"), 1)
        self.assertEqual(response.status, "success")
        self.assertEqual(len(response.initial_role_opinions), 4)
        self.assertEqual(len(response.debate_rounds), 0)
        self.assertEqual(len(session.added), 1)
        self.assertIn("chat_transcript", session.added[0].result_json)
        self.assertIn("tool_call_done", session.added[0].result_json)

    def test_stream_run_stops_at_max_rounds_when_no_consensus(self):
        session = _FakeSession()
        request = MultiAgentRunCreate(
            scene=MultiAgentScene.GENERAL,
            question="最近黄金还能加吗",
            use_portfolio_context=False,
            max_debate_rounds=3,
        )
        call_rounds: list[int] = []

        async def fake_stream_role(*, role, round_index, output, **kwargs):
            call_rounds.append(round_index)
            opinion = MultiAgentRoleOpinion(
                round_index=round_index,
                role_id=role.key,
                role_name=role.role_name,
                stance="neutral",
                action="继续观察",
                summary=f"{role.role_name}仍需观察",
                evidence=["证据有限"],
                risk_notes=["仍有分歧"],
                confidence=60.0,
            )
            output.append(opinion)
            yield MultiAgentService._sse_event("role_done", {
                "message_id": f"role-{round_index}-{role.key}",
                "opinion": opinion.model_dump(mode="json"),
            })

        async def fake_arbiter(*, round_index, **kwargs):
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
                risk_notes=["证据不足"],
                convergence_state="contested",
            )

        async def run_case():
            with (
                unittest.mock.patch.object(MultiAgentService, "_stream_role_opinion_events", new=fake_stream_role),
                unittest.mock.patch.object(MultiAgentService, "_generate_arbiter_summary", new=fake_arbiter),
            ):
                return [event async for event in MultiAgentService.create_run_stream(session, user_id=7, request=request)]

        events = asyncio.run(run_case())
        response = MultiAgentRunResponse.model_validate(json.loads(events[-1].split("data: ", 1)[1]))

        self.assertEqual(response.status, "partial")
        self.assertEqual(response.arbiter_summary.convergence_state, "max_rounds")
        self.assertEqual([round_item.round_index for round_item in response.debate_rounds], [2, 3])
        self.assertEqual(call_rounds.count(1), 4)
        self.assertEqual(call_rounds.count(2), 2)
        self.assertEqual(call_rounds.count(3), 2)

    def test_non_native_role_emits_streamed_content(self):
        output: list[MultiAgentRoleOpinion] = []

        async def fake_chat_stream(llm, prompt, context):
            yield '{"stance":"neutral","summary":"分批观察",'
            yield '"evidence":["价格"],"risk_notes":["波动"],"confidence":60}'

        async def run_case():
            with (
                unittest.mock.patch.object(MultiAgentService, "_create_llm_client", return_value=object()),
                unittest.mock.patch("services.advisor_service.AdvisorService.chat_stream_with_logging", new=fake_chat_stream),
            ):
                return [event async for event in MultiAgentService._stream_role_opinion_events(
                    scene=MultiAgentScene.GENERAL,
                    role=RoleBlueprint("researcher", "研究员角色", "梳理问题。"),
                    round_index=1,
                    question="最近黄金还能加吗",
                    context_summary=MultiAgentContextSummary(scenario=MultiAgentScene.GENERAL, title="黄金研判"),
                    search_bundle=SearchBundle(prompt_block="", metadata=[]),
                    provider="deepseek",
                    output=output,
                )]

        events = asyncio.run(run_case())
        event_names = [event.split("\n", 1)[0] for event in events]
        self.assertEqual(event_names, ["event: role_start", "event: role_chunk", "event: role_chunk", "event: role_done"])
        self.assertEqual(output[0].summary, "分批观察")

    def test_arbiter_uses_streamed_model_call(self):
        async def fake_chat_stream(llm, prompt, context):
            yield '{"consensus_reached":true,"why_stop":"分歧已消除",'
            yield '"final_recommendation":"hold","conclusion":"继续观察","confidence":80}'

        async def run_case():
            with (
                unittest.mock.patch.object(MultiAgentService, "_create_llm_client", return_value=object()),
                unittest.mock.patch("services.advisor_service.AdvisorService.chat_stream_with_logging", new=fake_chat_stream),
            ):
                return await MultiAgentService._generate_arbiter_summary(
                    scene=MultiAgentScene.GENERAL,
                    round_index=1,
                    question="最近黄金还能加吗",
                    context_summary=MultiAgentContextSummary(scenario=MultiAgentScene.GENERAL, title="黄金研判"),
                    search_bundle=SearchBundle(prompt_block="", metadata=[]),
                    opinions=[],
                    provider="deepseek",
                )

        summary = asyncio.run(run_case())
        self.assertTrue(summary.consensus_reached)
        self.assertEqual(summary.conclusion, "继续观察")

    def test_gemini_agent_streams_content_and_tool_calls(self):
        try:
            from services.agents.providers.gemini_agent_client import GeminiNativeAgentClient
        except ModuleNotFoundError as exc:
            if exc.name == "google.genai":
                self.skipTest("google-genai is not installed")
            raise

        class FakeModels:
            async def generate_content_stream(self, **kwargs):
                async def chunks():
                    yield types.SimpleNamespace(
                        function_calls=[],
                        candidates=[types.SimpleNamespace(content=types.SimpleNamespace(parts=[types.SimpleNamespace(text="前段")]))],
                    )
                    yield types.SimpleNamespace(
                        function_calls=[types.SimpleNamespace(name="search_latest_news", args={"query": "黄金"})],
                        candidates=[types.SimpleNamespace(content=types.SimpleNamespace(parts=[types.SimpleNamespace(text="后段")]))],
                    )

                return chunks()

        llm = types.SimpleNamespace(
            client=types.SimpleNamespace(aio=types.SimpleNamespace(models=FakeModels())),
            model_name="gemini-test",
        )

        async def run_case():
            client = GeminiNativeAgentClient(llm)
            return [event async for event in client.stream_with_tools(messages=[], tools=[], context="test")]

        events = asyncio.run(run_case())
        self.assertEqual([event.type for event in events], ["content", "tool_call", "content", "done"])
        self.assertEqual(events[0].content + events[2].content, "前段后段")
        self.assertEqual(events[1].tool_call.name, "search_latest_news")

    def test_technical_context_only_enters_technical_prompt(self):
        context = MultiAgentContextSummary(scenario=MultiAgentScene.ETF, title="技术面研判")
        technical = TechnicalContextBundle(prompt_block="RSI(14)：68.5\nMACD：DIF=0.01", codes=["159655"])
        common = dict(
            scene=MultiAgentScene.ETF,
            round_index=1,
            question="159655 技术面怎么看",
            context_summary=context,
            search_bundle=SearchBundle(prompt_block="", metadata=[]),
            technical_context=technical,
        )
        technical_prompt = MultiAgentService._build_role_prompt(
            role=RoleBlueprint("technical", "技术面角色", "判断价格位置。"), **common
        )
        policy_prompt = MultiAgentService._build_role_prompt(
            role=RoleBlueprint("policy_event", "政策事件角色", "判断政策事件。"), **common
        )
        self.assertIn("## 技术面K线与指标数据", technical_prompt)
        self.assertIn("RSI(14)：68.5", technical_prompt)
        self.assertNotIn("## 技术面K线与指标数据", policy_prompt)

    def test_policy_evidence_only_enters_policy_prompt(self):
        context = MultiAgentContextSummary(scenario=MultiAgentScene.ETF, title="政策事件研判")
        policy = PolicyEventContextBundle(prompt_block="示例政策新闻 https://example.com/policy", metadata=[])
        common = dict(
            scene=MultiAgentScene.ETF,
            round_index=1,
            question="159655 政策事件怎么看",
            context_summary=context,
            search_bundle=SearchBundle(prompt_block="", metadata=[]),
            policy_event_context=policy,
        )
        policy_prompt = MultiAgentService._build_role_prompt(
            role=RoleBlueprint("policy_event", "政策事件角色", "判断政策事件。"), **common
        )
        allocation_prompt = MultiAgentService._build_role_prompt(
            role=RoleBlueprint("allocation", "配置视角角色", "判断配置价值。"), **common
        )
        self.assertIn("## 政策事件专用搜索证据", policy_prompt)
        self.assertIn("示例政策新闻", policy_prompt)
        self.assertNotIn("## 政策事件专用搜索证据", allocation_prompt)

    def test_account_prompt_requires_account_data_evidence(self):
        prompt = MultiAgentService._build_role_prompt(
            scene=MultiAgentScene.ACCOUNT,
            role=RoleBlueprint("rebalance", "再平衡角色", "判断是否应该再平衡。"),
            round_index=1,
            question="账户要不要再平衡",
            context_summary=MultiAgentContextSummary(scenario=MultiAgentScene.ACCOUNT, title="账户再平衡研判"),
            search_bundle=SearchBundle(prompt_block="", metadata=[]),
            account_evidence_block="总市值：¥70,000.00\n可用资金：¥30,000.00",
        )
        self.assertIn("## 账户数据证据", prompt)
        self.assertIn("总市值：¥70,000.00", prompt)
        self.assertIn("## 账户场景证据输出要求", prompt)

    def test_general_prompt_requires_source_evidence(self):
        prompt = MultiAgentService._build_role_prompt(
            scene=MultiAgentScene.GENERAL,
            role=RoleBlueprint("evidence", "证据搜索角色", "整合最新证据。"),
            round_index=1,
            question="最近黄金还能买吗",
            context_summary=MultiAgentContextSummary(scenario=MultiAgentScene.GENERAL, title="黄金还能买吗"),
            search_bundle=SearchBundle(prompt_block="黄金新闻 https://example.com/gold", metadata=[]),
            general_evidence_block="用户问题：最近黄金还能买吗",
        )
        self.assertIn("## 通用场景证据", prompt)
        self.assertIn("用户问题：最近黄金还能买吗", prompt)
        self.assertIn("## 通用场景证据输出要求", prompt)
        self.assertIn("黄金新闻", prompt)


if __name__ == "__main__":
    unittest.main()

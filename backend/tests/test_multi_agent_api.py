import unittest
from pathlib import Path
import sys
import importlib.util
import types
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from database import get_session
from models.user import User
from schemas.multi_agent import (
    MultiAgentArbiterSummary,
    MultiAgentContextSummary,
    MultiAgentDebateRound,
    MultiAgentFinalConclusion,
    MultiAgentRunListResponse,
    MultiAgentRunResponse,
    MultiAgentRunUpdate,
    MultiAgentRoleOpinion,
    MultiAgentScene,
    MultiAgentSearchMetadata,
)

routers_package = types.ModuleType("routers")
routers_package.__path__ = []  # type: ignore[attr-defined]
sys.modules.setdefault("routers", routers_package)

auth_module = types.ModuleType("routers.auth")

async def get_current_user():
    return User(
        id=1,
        username="tester",
        email=None,
        hashed_password="hash",
        is_active=True,
        is_admin=False,
        account_balance=None,
    )

auth_module.get_current_user = get_current_user
sys.modules["routers.auth"] = auth_module

multi_agent_path = backend_root / "routers" / "multi_agent.py"
multi_agent_spec = importlib.util.spec_from_file_location("routers.multi_agent", multi_agent_path)
multi_agent_module = importlib.util.module_from_spec(multi_agent_spec)
assert multi_agent_spec is not None and multi_agent_spec.loader is not None
multi_agent_spec.loader.exec_module(multi_agent_module)
multi_agent_router = multi_agent_module.router
routers_package.auth = auth_module
routers_package.multi_agent = multi_agent_module


class MultiAgentApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(multi_agent_router)

        async def override_session():
            yield object()

        self.app.dependency_overrides[get_session] = override_session
        self.app.dependency_overrides[auth_module.get_current_user] = get_current_user
        self.client = TestClient(self.app)

    def test_create_run_returns_run_payload(self):
        payload = MultiAgentRunResponse(
            run_id=10,
            title="最近黄金还能加吗",
            scene=MultiAgentScene.GENERAL,
            question="最近黄金还能加吗",
            use_portfolio_context=True,
            max_debate_rounds=3,
            collapse_debate_by_default=True,
            created_at="2026-05-07T15:06:02+08:00",
            context_summary=MultiAgentContextSummary(
                scenario=MultiAgentScene.GENERAL,
                title="通用投资问答研判",
                question="最近黄金还能加吗",
                bullets=["用户问题：最近黄金还能加吗"],
                metrics={},
            ),
            initial_role_opinions=[
                MultiAgentRoleOpinion(
                    round_index=1,
                    role_id="researcher",
                    role_name="研究员角色",
                    stance="neutral",
                    action="先看问题边界",
                    summary="等待更多证据",
                    evidence=["信息不足"],
                    risk_notes=["波动较大"],
                    confidence=61.0,
                )
            ],
            debate_rounds=[
                MultiAgentDebateRound(
                    round_index=2,
                    role_opinions=[],
                    round_summary="仍需辩论",
                    open_disagreements=["信息不足"],
                    convergence_state="contested",
                )
            ],
            search_metadata=[
                MultiAgentSearchMetadata(
                    query="黄金 最新 新闻 政策",
                    answer=None,
                    result_count=1,
                    results=[{"title": "示例", "url": "https://example.com", "content": "snippet"}],
                )
            ],
            arbiter_summary=MultiAgentArbiterSummary(
                round_index=2,
                consensus_reached=True,
                why_stop="分歧可忽略",
                strong_opposition=[],
                confidence=76.0,
                final_recommendation="hold",
                recommended_action="继续观察",
                conclusion="建议继续观察",
                supporting_roles=["研究员角色"],
                disagreements=[],
                risk_notes=[],
                convergence_state="converged",
            ),
            final_conclusion=MultiAgentFinalConclusion(
                recommended_action="hold",
                action="继续观察",
                conclusion="证据不足时先观望",
                confidence=66.0,
                supporting_roles=["研究员角色"],
                disagreements=[],
                risk_notes=["未检索到可靠新信息"],
            ),
            status="success",
        )

        with patch("routers.multi_agent.MultiAgentService.create_run", new=AsyncMock(return_value=payload)):
            response = self.client.post(
                "/api/multi-agent/runs",
                json={
                    "scene": "general",
                    "question": "最近黄金还能加吗",
                    "use_portfolio_context": True,
                    "max_debate_rounds": 3,
                    "collapse_debate_by_default": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run_id"], 10)
        self.assertEqual(response.json()["title"], "最近黄金还能加吗")
        self.assertEqual(response.json()["final_conclusion"]["recommended_action"], "hold")
        self.assertEqual(response.json()["max_debate_rounds"], 3)
        self.assertEqual(response.json()["collapse_debate_by_default"], True)
        self.assertEqual(len(response.json()["initial_role_opinions"]), 1)
        self.assertIn("debate_rounds", response.json())

    def test_stream_run_returns_event_stream(self):
        async def fake_stream(*args, **kwargs):
            yield 'event: status\ndata: {"message":"开始"}\n\n'
            yield 'event: done\ndata: {"run_id":1}\n\n'

        with patch("routers.multi_agent.MultiAgentService.create_run_stream", new=fake_stream):
            response = self.client.post(
                "/api/multi-agent/runs/stream",
                json={
                    "scene": "general",
                    "question": "最近黄金还能加吗",
                    "use_portfolio_context": True,
                    "max_debate_rounds": 3,
                    "collapse_debate_by_default": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertIn("event: status", response.text)
        self.assertIn("event: done", response.text)

    def test_list_runs_returns_history_wrapper(self):
        payload = MultiAgentRunResponse(
            run_id=11,
            title="ETF 单只持仓研判",
            scene=MultiAgentScene.ETF,
            question="纳指 ETF 还能追吗",
            use_portfolio_context=True,
            max_debate_rounds=3,
            collapse_debate_by_default=True,
            created_at="2026-05-07T15:06:02+08:00",
            context_summary=MultiAgentContextSummary(
                scenario=MultiAgentScene.ETF,
                title="ETF 单只持仓研判",
                question="纳指 ETF 还能追吗",
                bullets=["当前共有 1 笔持仓"],
                metrics={},
            ),
            initial_role_opinions=[],
            debate_rounds=[],
            final_conclusion=MultiAgentFinalConclusion(
                recommended_action="hold",
                action="观望",
                conclusion="等待回踩",
                confidence=70.0,
                supporting_roles=[],
                disagreements=[],
                risk_notes=[],
            ),
            status="success",
        )

        wrapper = MultiAgentRunListResponse(runs=[payload])
        with patch("routers.multi_agent.MultiAgentService.list_runs", new=AsyncMock(return_value=wrapper)):
            response = self.client.get("/api/multi-agent/runs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["runs"][0]["run_id"], 11)
        self.assertEqual(response.json()["runs"][0]["title"], "ETF 单只持仓研判")
        self.assertEqual(response.json()["runs"][0]["max_debate_rounds"], 3)

    def test_update_run_title(self):
        payload = MultiAgentRunResponse(
            run_id=12,
            title="新标题",
            scene=MultiAgentScene.ETF,
            question="纳指 ETF 还能追吗",
            created_at="2026-05-07T15:06:02+08:00",
            context_summary=MultiAgentContextSummary(
                scenario=MultiAgentScene.ETF,
                title="新标题",
                bullets=[],
                metrics={},
            ),
            initial_role_opinions=[],
            debate_rounds=[],
            final_conclusion=MultiAgentFinalConclusion(
                recommended_action="hold",
                action="观望",
                conclusion="等待回踩",
                confidence=70.0,
                supporting_roles=[],
                disagreements=[],
                risk_notes=[],
            ),
            status="success",
        )

        with patch("routers.multi_agent.MultiAgentService.update_run", new=AsyncMock(return_value=payload)) as mock_update:
            response = self.client.patch("/api/multi-agent/runs/12", json={"title": "新标题"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "新标题")
        self.assertEqual(response.json()["context_summary"]["title"], "新标题")
        self.assertEqual(mock_update.await_args.args[2], 12)
        self.assertIsInstance(mock_update.await_args.args[3], MultiAgentRunUpdate)

    def test_delete_run(self):
        with patch("routers.multi_agent.MultiAgentService.delete_run", new=AsyncMock(return_value=True)) as mock_delete:
            response = self.client.delete("/api/multi-agent/runs/12")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True})
        self.assertEqual(mock_delete.await_args.args[2], 12)


if __name__ == "__main__":
    unittest.main()

import asyncio
import json
import unittest
from datetime import datetime
from pathlib import Path
import sys


backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from schemas.multi_agent import (
    MultiAgentContextSummary,
    MultiAgentFinalConclusion,
    MultiAgentRunCreate,
    MultiAgentRunResponse,
    MultiAgentRoleOpinion,
    MultiAgentScene,
)
from services.multi_agent_service import MultiAgentService


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None


class _FakeRun:
    def __init__(self, payload_json: str, run_id: int = 1, user_id: int = 7):
        self.id = run_id
        self.user_id = user_id
        payload = json.loads(payload_json)
        self.scene = payload["scene"]
        self.question = payload.get("question")
        self.use_portfolio_context = payload.get("use_portfolio_context", True)
        self.status = payload["status"]
        self.result_json = payload_json
        self.created_at = datetime(2026, 5, 7, 15, 6, 2)
        self.updated_at = self.created_at


class _FakeSession:
    def __init__(self, run: _FakeRun):
        self.run = run
        self.added = []
        self.flushed = 0

    async def execute(self, statement):
        sql = str(statement)
        if "multi_agent_run" in sql:
            return _ScalarResult([self.run])
        raise AssertionError(f"Unexpected statement: {sql}")

    def add(self, obj):
        self.added.append(obj)
        obj.id = 1

    async def flush(self):
        self.flushed += 1


class MultiAgentHistoryTests(unittest.TestCase):
    def test_list_runs_restores_same_response_shape(self):
        payload = MultiAgentRunResponse(
            run_id=1,
            scene=MultiAgentScene.ETF,
            created_at=datetime(2026, 5, 7, 15, 6, 2),
            context_summary=MultiAgentContextSummary(
                scenario=MultiAgentScene.ETF,
                title="510300 研判",
                bullets=["用户问题：510300 现在能不能加仓"],
            ),
            role_opinions=[
                MultiAgentRoleOpinion(
                    role_id="technical",
                    role_name="技术面角色",
                    stance="neutral",
                    summary="短期观望",
                    evidence=["RSI 偏高"],
                    risk_notes=["追高风险"],
                    confidence=66.0,
                )
            ],
            final_conclusion=MultiAgentFinalConclusion(
                recommended_action="hold",
                conclusion="短期观望",
                confidence=78.0,
                supporting_roles=["技术面角色"],
                disagreements=[],
                risk_notes=["短期回调风险"],
            ),
            status="success",
        )
        fake_run = _FakeRun(payload.model_dump_json())
        session = _FakeSession(fake_run)

        result = asyncio.run(MultiAgentService.list_runs(session, user_id=7))

        self.assertEqual(len(result.runs), 1)
        self.assertEqual(result.runs[0].final_conclusion.recommended_action, "hold")
        self.assertEqual(result.runs[0].context_summary.title, "510300 研判")

    def test_get_run_restores_detail_shape(self):
        payload = MultiAgentRunResponse(
            run_id=1,
            scene=MultiAgentScene.ACCOUNT,
            created_at=datetime(2026, 5, 7, 15, 6, 2),
            context_summary=MultiAgentContextSummary(
                scenario=MultiAgentScene.ACCOUNT,
                title="账户研判",
                bullets=["账户总金额：100000"],
            ),
            role_opinions=[],
            final_conclusion=MultiAgentFinalConclusion(
                recommended_action="hold",
                conclusion="继续持有",
                confidence=80.0,
                supporting_roles=[],
                disagreements=[],
                risk_notes=[],
            ),
            status="success",
        )
        fake_run = _FakeRun(payload.model_dump_json())
        session = _FakeSession(fake_run)

        result = asyncio.run(MultiAgentService.get_run(session, user_id=7, run_id=1))

        self.assertIsNotNone(result)
        self.assertEqual(result.scene, MultiAgentScene.ACCOUNT)
        self.assertEqual(result.final_conclusion.conclusion, "继续持有")


if __name__ == "__main__":
    unittest.main()

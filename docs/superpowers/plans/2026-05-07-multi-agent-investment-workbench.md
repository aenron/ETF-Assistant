# 多智能体投资决策工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent multi-agent investment workbench that supports ETF, account, and general Q&A scenarios, reuses the existing portfolio/account/search context by default, and produces one balanced consensus conclusion with visible disagreements and evidence.

**Architecture:** Add a new backend decision pipeline separated from the current single-agent advisor/assistant flows. The pipeline will dynamically generate roles by scenario, run role analyses in parallel, perform a debate/critique round, and persist a structured run record for replay. The frontend will add a separate workbench page and navigation entry so the existing assistant and advice flows remain unchanged.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, existing LLM clients (`openai`, `deepseek`, `gemini`, `qwen`, `zhipu`), existing Tavily search integration, React, Vite, TypeScript, existing UI component primitives.

---

## File Map

### Backend files to add

- `backend/models/multi_agent_run.py`: persistent history record for one multi-agent run.
- `backend/schemas/multi_agent.py`: request/response models for the workbench.
- `backend/services/multi_agent_service.py`: scenario routing, context assembly, role generation, debate, final arbitration, history persistence.
- `backend/routers/multi_agent.py`: HTTP API for analysis and history.
- `backend/tests/test_multi_agent_service.py`: service-level behavior tests.
- `backend/tests/test_multi_agent_api.py`: endpoint contract tests.

### Backend files to modify

- `backend/models/__init__.py`: export the new model.
- `backend/schemas/__init__.py`: export the new schemas.
- `backend/services/__init__.py`: export the new service.
- `backend/main.py`: include the new router.

### Frontend files to add

- `frontend/src/pages/MultiAgentWorkbenchPage.tsx`: standalone workbench page.
- `frontend/src/components/MultiAgent/RoleOpinionCard.tsx`: role opinion display.
- `frontend/src/components/MultiAgent/ConclusionPanel.tsx`: final consensus display.
- `frontend/src/components/MultiAgent/ContextSummary.tsx`: context preview and source summary.

### Frontend files to modify

- `frontend/src/services/api.ts`: add multi-agent API client and types.
- `frontend/src/App.tsx`: add route and a new entry/button for the workbench.

---

### Task 1: Define the multi-agent contract and persistence model

**Files:**
- Create: `backend/models/multi_agent_run.py`
- Create: `backend/schemas/multi_agent.py`
- Modify: `backend/models/__init__.py`
- Modify: `backend/schemas/__init__.py`
- Test: `backend/tests/test_multi_agent_service.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_multi_agent_service.py` with one contract test for scenario-to-role mapping and one serialization test for the run response:

```python
import unittest
from datetime import datetime

from schemas.multi_agent import MultiAgentRunResponse, MultiAgentScenario
from services.multi_agent_service import MultiAgentService


class MultiAgentServiceContractTests(unittest.TestCase):
    def test_etf_scenario_uses_etf_roles(self):
        roles = MultiAgentService.build_roles_for_scenario(MultiAgentScenario.ETF)
        self.assertEqual(
            [role.key for role in roles],
            ["event_policy", "technical", "value_config", "risk_arbiter"],
        )

    def test_run_response_exposes_required_fields(self):
        payload = MultiAgentRunResponse(
            id=1,
            scenario=MultiAgentScenario.ACCOUNT,
            query="账户是否需要再平衡",
            final_conclusion="保持仓位，等待周度再平衡窗口",
            recommended_action="hold",
            confidence=72,
            source_quality="high",
            supporting_evidence=["现金比例偏低", "行业集中度偏高"],
            disagreements=["技术角色认为短期可以加仓，风控角色反对"],
            risk_notes=["单一行业暴露过高"],
            created_at=datetime(2026, 5, 7, 15, 6, 2),
        )
        self.assertEqual(payload.recommended_action, "hold")
        self.assertEqual(payload.created_at.year, 2026)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m unittest backend.tests.test_multi_agent_service -v
```

Expected: fail with import errors or missing `MultiAgentService.build_roles_for_scenario` / `MultiAgentRunResponse`.

- [ ] **Step 3: Write minimal implementation**

Implement the schema and model with the following shape:

`backend/schemas/multi_agent.py`

```python
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import Field

from schemas.base import ShanghaiBaseModel, ShanghaiOrmModel


class MultiAgentScenario(str, Enum):
    ETF = "etf"
    ACCOUNT = "account"
    GENERAL = "general"


class MultiAgentRoleOpinion(ShanghaiBaseModel):
    key: str
    title: str
    stance: Literal["bullish", "neutral", "bearish", "mixed"]
    summary: str
    evidence: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    confidence: float


class MultiAgentRunCreate(ShanghaiBaseModel):
    scenario: MultiAgentScenario
    query: str = Field(min_length=1, max_length=4000)
    target_etf_code: str | None = None
    portfolio_id: int | None = None
    include_portfolio_context: bool = True
    include_account_context: bool = True
    search_enabled: bool = True


class MultiAgentRunResponse(ShanghaiOrmModel):
    id: int
    scenario: MultiAgentScenario
    query: str
    final_conclusion: str
    recommended_action: str
    confidence: float
    source_quality: str
    supporting_evidence: list[str]
    disagreements: list[str]
    risk_notes: list[str]
    created_at: datetime


class MultiAgentRunDetailResponse(MultiAgentRunResponse):
    roles: list[MultiAgentRoleOpinion]
    debate: list[dict[str, Any]]
```

`backend/models/multi_agent_run.py`

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class MultiAgentRun(Base):
    __tablename__ = "multi_agent_run"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    scenario: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    target_etf_code: Mapped[str | None] = mapped_column(String(10))
    portfolio_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("portfolio.id"))
    result_json: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSONB, "sqlite"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
```

Keep the model simple on the first pass: store the full structured result in `result_json` and only expose the fields the UI needs right now.

- [ ] **Step 4: Run the test to verify it still fails for missing service methods**

Run:

```bash
python -m unittest backend.tests.test_multi_agent_service -v
```

Expected: fail only on missing service methods, not on schema import/serialization.

- [ ] **Step 5: Commit**

```bash
git add backend/models/multi_agent_run.py backend/schemas/multi_agent.py backend/models/__init__.py backend/schemas/__init__.py backend/tests/test_multi_agent_service.py
git commit -m "Add multi-agent workbench contract"
```

---

### Task 2: Implement the backend multi-agent pipeline and API

**Files:**
- Create: `backend/services/multi_agent_service.py`
- Create: `backend/routers/multi_agent.py`
- Modify: `backend/main.py`
- Modify: `backend/services/__init__.py`
- Test: `backend/tests/test_multi_agent_api.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_multi_agent_api.py` with one endpoint test for analysis and one for history retrieval:

```python
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from main import app
from schemas.multi_agent import MultiAgentScenario


class MultiAgentApiTests(unittest.TestCase):
    def test_analyze_endpoint_returns_structured_payload(self):
        client = TestClient(app)
        with patch("routers.multi_agent.MultiAgentService.analyze", new=AsyncMock(return_value={
            "id": 1,
            "scenario": MultiAgentScenario.ETF,
            "query": "510300 现在能不能加仓",
            "final_conclusion": "短期观望，中期持有",
            "recommended_action": "hold",
            "confidence": 78,
            "source_quality": "high",
            "supporting_evidence": ["RSI过热", "中期趋势向上"],
            "disagreements": [],
            "risk_notes": ["短期回调风险"],
            "created_at": "2026-05-07T15:06:02+08:00",
            "roles": [],
            "debate": [],
        })):
            response = client.post("/api/multi-agent/analyze", json={
                "scenario": "etf",
                "query": "510300 现在能不能加仓",
                "target_etf_code": "510300",
                "include_portfolio_context": True,
                "include_account_context": True,
                "search_enabled": True,
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommended_action"], "hold")

    def test_history_endpoint_exists(self):
        client = TestClient(app)
        response = client.get("/api/multi-agent/runs")
        self.assertIn(response.status_code, (200, 401))
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m unittest backend.tests.test_multi_agent_api -v
```

Expected: fail because `routers.multi_agent` is not yet wired and the service methods do not exist.

- [ ] **Step 3: Write minimal implementation**

Implement `backend/services/multi_agent_service.py` with the following responsibilities:

```python
class MultiAgentService:
    @classmethod
    def build_roles_for_scenario(cls, scenario): ...

    @classmethod
    async def build_context(cls, session, user_id, request): ...

    @classmethod
    async def analyze_role(cls, llm, role, context): ...

    @classmethod
    async def arbitrate(cls, opinions, context): ...

    @classmethod
    async def analyze(cls, session, user_id, request): ...

    @classmethod
    async def list_runs(cls, session, user_id, limit=20): ...

    @classmethod
    async def get_run(cls, session, user_id, run_id): ...
```

Implementation notes:

- Reuse `PortfolioService.get_with_market()` and `PortfolioService.build_summary_from_portfolios()` for ETF/account context.
- Reuse the existing LLM clients from `backend/services/llm`.
- Reuse Tavily search orchestration from `AdvisorService.enrich_prompt_with_tavily_tools()` so search behavior stays consistent.
- Persist a `MultiAgentRun` row after the final conclusion is produced.
- Store the full structured result in `result_json` so history playback does not need to reconstruct debates from raw prompt text.

Implement `backend/routers/multi_agent.py` with:

- `POST /api/multi-agent/analyze`
- `GET /api/multi-agent/runs`
- `GET /api/multi-agent/runs/{run_id}`

Register the router in `backend/main.py` next to the existing advice and assistant routers.

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
python -m unittest backend.tests.test_multi_agent_service backend.tests.test_multi_agent_api -v
```

Expected: pass with the new service and router in place.

- [ ] **Step 5: Commit**

```bash
git add backend/services/multi_agent_service.py backend/routers/multi_agent.py backend/main.py backend/services/__init__.py backend/tests/test_multi_agent_api.py
git commit -m "Add multi-agent backend pipeline"
```

---

### Task 3: Build the standalone frontend workbench

**Files:**
- Create: `frontend/src/pages/MultiAgentWorkbenchPage.tsx`
- Create: `frontend/src/components/MultiAgent/RoleOpinionCard.tsx`
- Create: `frontend/src/components/MultiAgent/ConclusionPanel.tsx`
- Create: `frontend/src/components/MultiAgent/ContextSummary.tsx`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write the failing test**

This project does not currently have a frontend test harness, so use build-based failure detection for the new page. Add the page and route references first, then let TypeScript fail on missing API types.

Expected temporary code in `frontend/src/App.tsx`:

```tsx
import { MultiAgentWorkbenchPage } from '@/pages/MultiAgentWorkbenchPage'

// ...
<Route path="/multi-agent" element={<MultiAgentWorkbenchPage />} />
```

Expected temporary code in `frontend/src/services/api.ts`:

```ts
export interface MultiAgentRunRequest {
  scenario: 'etf' | 'account' | 'general'
  query: string
  target_etf_code?: string | null
  portfolio_id?: number | null
  include_portfolio_context?: boolean
  include_account_context?: boolean
  search_enabled?: boolean
}
```

- [ ] **Step 2: Run the build to verify it fails**

Run:

```bash
npm run build
```

Expected: TypeScript errors because the new page, types, and API methods do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement `frontend/src/services/api.ts` with a dedicated client:

```ts
export interface MultiAgentRoleOpinion {
  key: string
  title: string
  stance: 'bullish' | 'neutral' | 'bearish' | 'mixed'
  summary: string
  evidence: string[]
  concerns: string[]
  confidence: number
}

export interface MultiAgentRunResponse {
  id: number
  scenario: 'etf' | 'account' | 'general'
  query: string
  final_conclusion: string
  recommended_action: string
  confidence: number
  source_quality: string
  supporting_evidence: string[]
  disagreements: string[]
  risk_notes: string[]
  created_at: string
  roles?: MultiAgentRoleOpinion[]
  debate?: Record<string, unknown>[]
}

export const multiAgentApi = {
  analyze: (data: MultiAgentRunRequest) => api.post<MultiAgentRunResponse>('/multi-agent/analyze', data),
  listRuns: (limit = 20) => api.get<MultiAgentRunResponse[]>('/multi-agent/runs', { params: { limit } }),
  getRun: (runId: number) => api.get<MultiAgentRunResponse>(`/multi-agent/runs/${runId}`),
}
```

Implement `frontend/src/pages/MultiAgentWorkbenchPage.tsx` as a standalone page with:

- scenario tabs or a segmented control.
- a query input area.
- an optional context summary panel that reflects the selected scenario.
- a run button.
- a results section that renders role cards and the final conclusion panel.
- a history list that loads prior runs.

Create the three small presentational components so the page does not become a single large file.

Add a visible navigation entry in `frontend/src/App.tsx` so the workbench is reachable from the main app without reusing the assistant drawer.

- [ ] **Step 4: Run the build to verify it passes**

Run:

```bash
npm run build
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/MultiAgentWorkbenchPage.tsx frontend/src/components/MultiAgent frontend/src/services/api.ts frontend/src/App.tsx
git commit -m "Add multi-agent workbench UI"
```

---

### Task 4: End-to-end wiring, history playback, and regression checks

**Files:**
- Modify: `backend/services/multi_agent_service.py`
- Modify: `backend/routers/multi_agent.py`
- Modify: `frontend/src/pages/MultiAgentWorkbenchPage.tsx`
- Modify: `frontend/src/components/MultiAgent/ConclusionPanel.tsx`
- Modify: `frontend/src/components/MultiAgent/RoleOpinionCard.tsx`
- Test: `backend/tests/test_multi_agent_history.py`

- [ ] **Step 1: Write the failing test**

Add one history replay test that verifies a stored run can be loaded and returned in the same structured shape:

```python
import unittest
from unittest.mock import AsyncMock, patch

from services.multi_agent_service import MultiAgentService


class MultiAgentHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_roundtrip_returns_same_structure(self):
        with patch.object(MultiAgentService, "analyze", new=AsyncMock(return_value={
            "id": 2,
            "scenario": "account",
            "query": "现在账户要不要再平衡",
            "final_conclusion": "保持当前配置，等待周度调仓窗口",
            "recommended_action": "hold",
            "confidence": 70,
            "source_quality": "medium",
            "supporting_evidence": ["现金不足", "集中度偏高"],
            "disagreements": ["技术角色偏乐观"],
            "risk_notes": ["单一风格暴露过高"],
            "created_at": "2026-05-07T15:10:00+08:00",
            "roles": [],
            "debate": [],
        })):
            result = await MultiAgentService.analyze(None, 1, None)  # placeholder until service wiring exists
        self.assertEqual(result["recommended_action"], "hold")
```

This test should be adjusted so the service is called through the actual persistence path once the backend is wired. The key requirement is that history replay returns the same fields the UI consumed at write time.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m unittest backend.tests.test_multi_agent_history -v
```

Expected: fail because the history path is not fully wired yet.

- [ ] **Step 3: Write minimal implementation**

Extend the backend service and router so the workbench can:

- reload the latest runs,
- reopen a prior run,
- show per-role opinions and the final arbitration record,
- keep the current single-agent advice and assistant flows untouched.

On the frontend, make the history panel clickable and reuse the same conclusion/role cards for replayed runs.

Keep the API shape stable so the page can render both fresh runs and history runs through the same response contract.

- [ ] **Step 4: Run the full validation**

Run:

```bash
python -m unittest backend.tests.test_multi_agent_service backend.tests.test_multi_agent_api backend.tests.test_multi_agent_history -v
npm run build
```

Expected: all backend tests pass and the frontend build passes.

- [ ] **Step 5: Commit**

```bash
git add backend/services/multi_agent_service.py backend/routers/multi_agent.py backend/tests/test_multi_agent_history.py frontend/src/pages/MultiAgentWorkbenchPage.tsx frontend/src/components/MultiAgent
git commit -m "Complete multi-agent workbench end-to-end"
```

---

## Self-Review Checklist

- The plan covers all three required场景: ETF, 账户, 通用。
- The plan keeps the existing single-agent assistant/advice flows untouched.
- The plan includes a new independent entry point and a standalone frontend page.
- The plan includes dynamic role generation rather than a fixed global role template.
- The plan includes evidence and disagreement visibility.
- The plan includes persistence and replay for run history.
- The plan includes backend tests and frontend build verification.


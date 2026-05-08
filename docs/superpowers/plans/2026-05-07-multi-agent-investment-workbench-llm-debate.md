# 多智能体投资决策工作台（LLM 辩论版）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Use checkbox (`- [ ]`) syntax to track progress.

**Goal:** Upgrade the existing independent multi-agent workbench into a real LLM-driven debate system. Each role must call the LLM, the first round runs in parallel, later rounds perform critique and counter-arguments, and a final arbiter stops the debate only when differences are ignorable and there is no strong opposition. The frontend must keep the debate process collapsed by default, with user expansion and a configurable maximum debate round count.

**Architecture:** Keep the current standalone `/multi-agent` workbench entry, but replace the static role templates with a backend debate orchestrator. The orchestrator will assemble scenario-specific context, spawn scenario-specific roles, run parallel role analyses, iterate debate rounds with contradiction summaries, and ask an arbiter role to determine whether consensus has been reached. The result will persist the full run transcript for replay. The frontend will render a compact summary first, then a collapsible round-by-round debate timeline.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, existing multi-provider LLM layer (`openai`, `deepseek`, `gemini`, `qwen`, `zhipu`), existing Tavily / search integration, React, Vite, TypeScript, existing component primitives.

---

## File Map

### Backend files to add or substantially rewrite

- `backend/services/multi_agent_service.py`: LLM debate orchestrator, scenario-specific role assembly, parallel initial pass, multi-round rebuttal loop, arbiter convergence check, persistence.
- `backend/schemas/multi_agent.py`: extend the multi-agent contract to include debate rounds, role prompts, arbitration metadata, max round controls, and replay-friendly payloads.
- `backend/tests/test_multi_agent_service.py`: service-level tests for scenario routing, convergence logic, and debate serialization.
- `backend/tests/test_multi_agent_api.py`: endpoint contract tests for create/list/get with the new debate payload.

### Backend files to modify

- `backend/models/multi_agent_run.py`: store the persisted run record and debate transcript JSON.
- `backend/models/__init__.py`: export the run model.
- `backend/schemas/__init__.py`: export the updated schemas.
- `backend/services/__init__.py`: export the updated service.
- `backend/routers/multi_agent.py`: accept the new request fields and expose the richer response.
- `backend/main.py`: keep router registration unchanged if already present, otherwise ensure the router is mounted.

### Frontend files to modify

- `frontend/src/pages/MultiAgentWorkbenchPage.tsx`: add max-round controls, show compact summary first, and add collapsible debate rounds.
- `frontend/src/components/MultiAgent/RoleOpinionCard.tsx`: render one role opinion per round with rebuttal markers.
- `frontend/src/components/MultiAgent/ConclusionPanel.tsx`: render the final arbiter result and consensus / disagreement summary.
- `frontend/src/components/MultiAgent/ContextSummary.tsx`: show the scenario context, search summary, and inputs used to seed the debate.
- `frontend/src/services/api.ts`: update request/response types for debate rounds and max-round controls.
- `frontend/src/App.tsx`: keep the standalone route and navigation entry.

---

## Task 1: Extend the multi-agent contract for debate rounds and controls

**Objective:** Replace the static workbench contract with a debate-ready schema that can represent multiple rounds, per-role outputs, arbitration results, and UI controls such as maximum rounds and default collapse state.

**Files:**
- Modify: `backend/schemas/multi_agent.py`
- Modify: `backend/models/multi_agent_run.py`
- Modify: `backend/models/__init__.py`
- Modify: `backend/schemas/__init__.py`
- Test: `backend/tests/test_multi_agent_service.py`

- [ ] **Step 1: Write the failing tests**

Add contract tests for the new debate payload shape and a serialization test for the persisted run record. The tests should assert:

1. `MultiAgentRunCreate` accepts `max_debate_rounds`, `collapse_debate_by_default`, and `use_portfolio_context`.
2. A run response includes:
   - `context_summary`
   - `initial_role_opinions`
   - `debate_rounds`
   - `final_conclusion`
   - `arbiter_summary`
   - `status`
3. The persisted model can store the full result JSON without losing debate rounds.

Example assertions:

```python
from schemas.multi_agent import MultiAgentRunCreate, MultiAgentRunResponse, MultiAgentScene


def test_request_includes_debate_controls(self):
    payload = MultiAgentRunCreate(
        scene=MultiAgentScene.ETF,
        question="159655 近期是否适合加仓？",
        use_portfolio_context=True,
        max_debate_rounds=3,
        collapse_debate_by_default=True,
    )
    self.assertEqual(payload.max_debate_rounds, 3)
```

- [ ] **Step 2: Implement the schema changes**

Add or extend the following fields in `backend/schemas/multi_agent.py`:

- `MultiAgentRunCreate`
  - `scene`
  - `question`
  - `use_portfolio_context`
  - `max_debate_rounds` with a safe default, such as `3`
  - `collapse_debate_by_default` with default `True`
- `MultiAgentRoleOpinion`
  - `round_index`
  - `role_id`
  - `role_name`
  - `stance`
  - `action`
  - `summary`
  - `evidence`
  - `risk_notes`
  - `confidence`
  - `rebuttals` if the role responds to another role
- `MultiAgentDebateRound`
  - `round_index`
  - `role_opinions`
  - `round_summary`
  - `open_disagreements`
  - `convergence_state`
- `MultiAgentArbiterSummary`
  - `consensus_reached`
  - `why_stop`
  - `strong_opposition`
  - `confidence`
  - `final_recommendation`
- `MultiAgentRunResponse`
  - `run_id`
  - `scene`
  - `question`
  - `use_portfolio_context`
  - `max_debate_rounds`
  - `collapse_debate_by_default`
  - `created_at`
  - `context_summary`
  - `initial_role_opinions`
  - `debate_rounds`
  - `arbiter_summary`
  - `final_conclusion`
  - `status`

Keep the response model replay-friendly so the frontend can render the full debate without re-deriving anything.

- [ ] **Step 3: Update the persistence model**

Keep `backend/models/multi_agent_run.py` simple on the first pass:

- store `user_id`, `scene`, `question`
- store `use_portfolio_context`
- store `max_debate_rounds`
- store `collapse_debate_by_default`
- store `status`
- store the entire structured result in `result_json`
- keep DB timestamps naive UTC at write time, but serialize to Beijing time at the API layer

Do not split the debate into many tables yet; the full JSON transcript is enough for MVP replay and keeps migrations lighter.

- [ ] **Step 4: Run the tests and confirm the schema is now the contract**

Run:

```bash
python -m unittest backend.tests.test_multi_agent_service -v
```

Expected: the tests should now fail only if the implementation has not been updated yet, not because of import / serialization mismatches.

---

## Task 2: Build the real LLM debate orchestrator

**Objective:** Replace the deterministic role template path with an orchestrator that calls LLMs for each role, runs the first round in parallel, iterates critique rounds, and stops when the arbiter says the remaining disagreement is ignorable.

**Files:**
- Replace: `backend/services/multi_agent_service.py`
- Modify: `backend/services/__init__.py`
- Modify: `backend/routers/multi_agent.py`
- Test: `backend/tests/test_multi_agent_service.py`

- [ ] **Step 1: Write the failing service tests**

Add tests that assert the following orchestration behaviors:

1. `build_roles_for_scenario()` returns different role sets for `ETF`, `ACCOUNT`, and `GENERAL`.
2. The first round submits all roles in parallel.
3. The debate loop stops before the max round count when the arbiter marks the disagreement as ignorable.
4. The debate loop continues until the max round count when consensus is not reached.
5. A run with search disabled does not try to call search tools.

Use fakes/mocks for the LLM layer so the tests verify orchestration, not provider-specific output quality.

- [ ] **Step 2: Implement scenario-specific role blueprints**

Implement dynamic role generation by scene:

- `ETF`
  - policy / event analyst
  - technical analyst
  - trend / allocation analyst
  - risk arbiter
- `ACCOUNT`
  - portfolio structure analyst
  - rebalancing analyst
  - risk exposure analyst
  - execution / cash analyst
- `GENERAL`
  - research analyst
  - contrary reviewer
  - evidence / search analyst
  - risk arbiter

Each role should have a dedicated prompt template and a role-specific output schema.

- [ ] **Step 3: Implement the parallel first round**

For the initial round:

- assemble scenario context
- optionally attach portfolio/account context
- optionally attach search results or search evidence
- send each role its own prompt
- collect role outputs in parallel

The orchestrator should preserve:

- the role prompt input
- the LLM response
- any search metadata
- confidence / evidence / risk notes

Do not serialize this as a single summary too early; keep raw role outputs so later rounds can refer back to them.

- [ ] **Step 4: Implement critique rounds**

For each additional round:

- feed each role:
  - its prior round output
  - the strongest opposing points from other roles
  - the current disagreement summary
  - any new search evidence if search is enabled
- ask the role to either defend, revise, or concede
- build an updated disagreement summary for the next round

The loop should continue until one of these is true:

- the arbiter says remaining differences are ignorable and there is no strong opposition
- the max debate round count is reached
- the system cannot get a stable answer and must degrade to a conservative conclusion

- [ ] **Step 5: Implement the arbiter and final conclusion**

Add a final arbiter pass that synthesizes:

- consensus status
- strongest shared evidence
- unresolved disagreements
- final recommendation
- confidence
- why the debate stopped

The arbiter should not blindly follow the most confident role. It should explicitly check for:

- strong opposition
- missing evidence
- search failure / low-quality sources
- scenario-specific risk conditions

- [ ] **Step 6: Wire search and logging into the debate path**

Reuse the existing search framework so roles can request context or evidence when the scenario warrants it.

Log each run with:

- search enabled / disabled
- search provider(s) used
- search queries
- search usage result
- round count
- convergence state

Keep the current `AdvisorService` / `Tavily` / provider logs intact, but add multi-agent-specific markers so debate runs are easy to inspect.

- [ ] **Step 7: Persist the full run transcript**

Store the final structured result in `result_json`, including:

- all rounds
- role outputs per round
- arbiter summary
- final conclusion
- search metadata
- the exact controls used for the run

This must be enough to replay the workbench without recomputing the debate.

- [ ] **Step 8: Run service-level tests**

Run:

```bash
python -m unittest backend.tests.test_multi_agent_service -v
```

Expected: the tests should verify the parallel / round / convergence behavior and the payload shape.

---

## Task 3: Update the standalone workbench UI for debate review

**Objective:** Keep the current `/multi-agent` standalone workbench, but make it feel like a debate viewer rather than a static summary screen. The debate process must be collapsed by default, and the user must be able to control the maximum round count from the page.

**Files:**
- Modify: `frontend/src/pages/MultiAgentWorkbenchPage.tsx`
- Modify: `frontend/src/components/MultiAgent/RoleOpinionCard.tsx`
- Modify: `frontend/src/components/MultiAgent/ConclusionPanel.tsx`
- Modify: `frontend/src/components/MultiAgent/ContextSummary.tsx`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write the failing UI tests / type assertions**

Add or update TypeScript-level expectations for:

- `max_debate_rounds` in the create request
- `collapse_debate_by_default` in the create request
- the response carrying `debate_rounds` and `arbiter_summary`

If there is no dedicated UI test harness, use type-safe API changes plus `npm run build` as the gate.

- [ ] **Step 2: Add page controls**

On the workbench page:

- add a `max debate rounds` numeric control
- keep `use portfolio context` as a toggle
- keep the scene selector (`ETF` / `账户` / `通用`)
- keep the standalone “开始研判” entry

The default round limit should be conservative, such as `3`, and the UI should make clear that the arbiter may stop earlier if consensus is reached.

- [ ] **Step 3: Render a collapsed debate timeline**

The page should show:

- a compact top summary first
- the final arbiter conclusion
- a collapsed round list by default
- per-round role cards inside each round

Each round should be expandable to reveal:

- each role’s initial / revised position
- the strongest rebuttals
- the round-level disagreement summary
- the convergence state

- [ ] **Step 4: Keep the current summary panels, but repurpose them**

Reuse the current components so the page remains familiar:

- `ContextSummary` shows the problem framing and source context
- `RoleOpinionCard` shows one role opinion per round
- `ConclusionPanel` shows the arbiter’s final conclusion

Adjust labels and layout so the page reads like a debate transcript rather than a single-shot answer.

- [ ] **Step 5: Update API types**

In `frontend/src/services/api.ts`, add the new request/response fields and keep the standalone client aligned with the backend payload.

Do not change the existing single-agent assistant / advice contracts while doing this.

- [ ] **Step 6: Verify the build**

Run:

```bash
npm run build
```

The workbench page should compile cleanly with the new response shape and controls.

---

## Task 4: End-to-end verification and cleanup

**Objective:** Make sure the new debate pipeline works end to end, persists correctly, and does not disturb the existing advisor / assistant flows.

**Files:**
- `backend/tests/test_multi_agent_api.py`
- `backend/tests/test_multi_agent_history.py`
- `backend/tests/test_multi_agent_service.py`
- `backend/main.py`
- `frontend/src/App.tsx`

- [ ] **Step 1: Write the API contract tests**

Add tests that verify:

- run creation accepts the new debate controls
- history listing returns the stored debate summary
- run detail returns the full debate transcript
- the route stays isolated from existing assistant/advice endpoints

- [ ] **Step 2: Verify no regressions in existing flows**

Run the minimum regression set:

```bash
python -m unittest backend.tests.test_multi_agent_service backend.tests.test_multi_agent_api backend.tests.test_multi_agent_history -v
python -m py_compile backend/services/multi_agent_service.py backend/schemas/multi_agent.py backend/routers/multi_agent.py backend/main.py
npm run build
```

If the debate pipeline uses any provider-specific functionality, add a focused provider smoke test only if needed; do not broaden the scope unnecessarily.

- [ ] **Step 3: Rebuild the backend and frontend containers**

Once the tests pass, rebuild both containers so the standalone workbench and the backend API are using the new debate chain.

---

## Implementation Notes

- Keep the new multi-agent debate pipeline isolated from the existing single-agent assistant and advice flows.
- Prefer conservative default behavior when evidence is weak or the search layer is unavailable.
- Preserve the full debate transcript for replay and debugging.
- Do not force the arbiter to produce a strong action when the debate never converges.
- The frontend must not auto-expand the full debate transcript; collapse it by default and let the user drill in.


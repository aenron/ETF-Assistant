from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Literal, Optional

from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from schemas.base import ShanghaiBaseModel, ShanghaiOrmModel


class MultiAgentScene(str, Enum):
    ETF = "etf"
    ACCOUNT = "account"
    GENERAL = "general"


class MultiAgentRunCreate(ShanghaiBaseModel):
    scene: MultiAgentScene
    question: Optional[str] = None
    use_portfolio_context: bool = True
    portfolio_ids: Optional[list[int]] = None
    max_debate_rounds: int = Field(default=3, ge=1, le=8)
    collapse_debate_by_default: bool = True


class MultiAgentRunUpdate(ShanghaiBaseModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("标题不能为空")
        return title


class MultiAgentContextSummary(ShanghaiBaseModel):
    scenario: MultiAgentScene
    title: str
    question: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)
    metrics: Dict[str, str] = Field(default_factory=dict)


class MultiAgentSearchMetadata(ShanghaiBaseModel):
    provider: str = "tavily"
    enabled: bool = True
    query: str
    answer: Optional[str] = None
    result_count: int = 0
    error: Optional[str] = None
    results: list[Dict[str, Any]] = Field(default_factory=list)


class MultiAgentRoleOpinion(ShanghaiBaseModel):
    round_index: int = 1
    role_id: str
    role_name: str
    stance: Literal["bullish", "neutral", "bearish", "mixed"]
    action: str = ""
    summary: str
    evidence: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    confidence: float
    rebuttals: list[str] = Field(default_factory=list)


class MultiAgentArbiterSummary(ShanghaiBaseModel):
    round_index: int
    consensus_reached: bool
    why_stop: str
    strong_opposition: list[str] = Field(default_factory=list)
    confidence: float
    final_recommendation: str
    recommended_action: str = ""
    conclusion: str
    supporting_roles: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    convergence_state: Literal["forming", "contested", "converged", "max_rounds", "failed"] = "contested"


class MultiAgentDebateRound(ShanghaiBaseModel):
    round_index: int
    role_opinions: list[MultiAgentRoleOpinion] = Field(default_factory=list)
    round_summary: str
    open_disagreements: list[str] = Field(default_factory=list)
    convergence_state: Literal["forming", "contested", "converged", "max_rounds", "failed"] = "forming"
    arbiter_summary: Optional[MultiAgentArbiterSummary] = None


class MultiAgentFinalConclusion(ShanghaiBaseModel):
    recommended_action: str
    action: str = ""
    conclusion: str
    confidence: float
    supporting_roles: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class MultiAgentChatTranscriptEvent(ShanghaiBaseModel):
    event: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class MultiAgentRunResponse(ShanghaiOrmModel):
    run_id: int
    title: str = ""
    scene: MultiAgentScene
    question: Optional[str] = None
    use_portfolio_context: bool = True
    max_debate_rounds: int = 3
    collapse_debate_by_default: bool = True
    llm_provider: str = ""
    created_at: datetime
    context_summary: MultiAgentContextSummary
    initial_role_opinions: list[MultiAgentRoleOpinion] = Field(default_factory=list)
    role_opinions: list[MultiAgentRoleOpinion] = Field(default_factory=list)
    debate_rounds: list[MultiAgentDebateRound] = Field(default_factory=list)
    search_metadata: list[MultiAgentSearchMetadata] = Field(default_factory=list)
    arbiter_summary: Optional[MultiAgentArbiterSummary] = None
    final_conclusion: MultiAgentFinalConclusion
    chat_transcript: list[MultiAgentChatTranscriptEvent] = Field(default_factory=list)
    status: Literal["running", "success", "partial", "failed"]

    @model_validator(mode="after")
    def _sync_role_opinions(self):
        if not self.initial_role_opinions and self.role_opinions:
            self.initial_role_opinions = list(self.role_opinions)
        elif not self.role_opinions and self.initial_role_opinions:
            self.role_opinions = list(self.initial_role_opinions)
        return self


class MultiAgentRunDetailResponse(MultiAgentRunResponse):
    pass


class MultiAgentRunListResponse(ShanghaiBaseModel):
    runs: list[MultiAgentRunResponse] = Field(default_factory=list)

from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Literal


class PeriodAdvice(BaseModel):
    """单个周期建议"""
    advice_type: str
    action: str
    conclusion: str
    signals: List[str]
    risks: List[str]
    confidence: float


class EventItem(BaseModel):
    """新闻/政策/宏观事件依据"""
    title: str = ""
    date: Optional[str] = None
    source: str = ""
    relevance: Literal["direct", "indirect", "weak", "unknown"] = "unknown"
    impact: Literal["positive", "neutral", "negative", "unknown"] = "unknown"
    priced_in_risk: Literal["low", "medium", "high", "unknown"] = "unknown"
    summary: str = ""


class EventContext(BaseModel):
    """模型搜索得到的事件上下文"""
    search_status: Literal["success", "partial", "unavailable"] = "unavailable"
    source_quality: Literal["high", "medium", "low", "unknown"] = "unknown"
    policy_signal: Literal["positive", "neutral", "negative", "unknown"] = "unknown"
    macro_signal: Literal["positive", "neutral", "negative", "unknown"] = "unknown"
    news_signal: Literal["positive", "neutral", "negative", "unknown"] = "unknown"
    events: List[EventItem] = Field(default_factory=list)


class AdviceGenerateRequest(BaseModel):
    """生成建议请求"""
    etf_codes: Optional[List[str]] = None  # 为空则生成全部持仓建议


class AdviceResponse(BaseModel):
    """单条建议"""
    etf_code: str
    etf_name: Optional[str] = None
    advice_type: str  # buy/sell/hold/add/reduce
    main_judgment: str
    summary: str = ""
    action: str
    why: List[str]
    news_basis: List[str]
    policy_basis: List[str]
    event_context: EventContext = Field(default_factory=EventContext)
    reason: str
    confidence: float
    short_term: PeriodAdvice
    medium_term: PeriodAdvice
    long_term: PeriodAdvice
    current_price: Optional[float] = None
    pnl_pct: Optional[float] = None


class AccountAnalysisResponse(BaseModel):
    """账户级分析建议"""
    summary: str
    position_advice: str
    rebalance_advice: str
    risk_level: str
    key_actions: List[str]
    confidence: float
    created_at: datetime


class AdviceLogResponse(BaseModel):
    """建议日志"""
    id: int
    etf_code: Optional[str] = None
    etf_name: Optional[str] = None
    advice_type: Optional[str] = None
    reason: Optional[str] = None
    confidence: Optional[float] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

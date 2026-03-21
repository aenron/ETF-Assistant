from pydantic import BaseModel, ConfigDict
from datetime import datetime
from decimal import Decimal
from typing import Optional, List


class AdviceGenerateRequest(BaseModel):
    """生成建议请求"""
    etf_codes: Optional[List[str]] = None  # 为空则生成全部持仓建议


class AdviceResponse(BaseModel):
    """单条建议"""
    etf_code: str
    etf_name: Optional[str] = None
    advice_type: str  # buy/sell/hold/add/reduce
    reason: str
    confidence: float
    current_price: Optional[float] = None
    pnl_pct: Optional[float] = None


class AdviceLogResponse(BaseModel):
    """建议日志"""
    id: int
    etf_code: Optional[str] = None
    advice_type: Optional[str] = None
    reason: Optional[str] = None
    confidence: Optional[float] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

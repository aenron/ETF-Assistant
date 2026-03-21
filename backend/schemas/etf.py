from pydantic import BaseModel
from typing import Optional


class EtfSearchResult(BaseModel):
    """ETF搜索结果"""
    code: str
    name: str
    category: Optional[str] = None
    exchange: Optional[str] = None

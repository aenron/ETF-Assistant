from typing import Optional

from schemas.base import ShanghaiBaseModel


class EtfSearchResult(ShanghaiBaseModel):
    """ETF搜索结果"""
    code: str
    name: str
    category: Optional[str] = None
    exchange: Optional[str] = None

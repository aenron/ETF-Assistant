import logging

logger = logging.getLogger("uvicorn.error.tencent")

from services.market.http_client import market_http_client
from typing import Optional, List, Dict


# 设置环境变量模拟浏览器

from schemas.market import MarketQuote


from services.market.formats import MarketFormatMixin

class TencentProviderMixin(MarketFormatMixin):
    """tencent market parsing and retrieval."""

    @classmethod
    def _tencent_symbol(cls, code: str) -> Optional[str]:
        """Return a Tencent Finance symbol for a listed A-share security."""
        clean = str(code or "").strip().lower()
        if clean.startswith(("sh", "sz")) and len(clean) == 8 and clean[2:].isdigit():
            return clean
        if not clean.isdigit() or len(clean) != 6:
            return None
        if clean.startswith(("5", "6", "9")):
            return f"sh{clean}"
        if clean.startswith(("0", "1", "2", "3")):
            return f"sz{clean}"
        return None


    @classmethod
    def _parse_tencent_quotes(cls, text: str, requested_codes: List[str]) -> Dict[str, MarketQuote]:
        """Parse qt.gtimg.cn's tilde-separated full-quote payload."""
        result: Dict[str, MarketQuote] = {}
        for line in text.splitlines():
            if '="' not in line:
                continue
            _, payload = line.split('="', 1)
            payload = payload.rstrip('";').strip()
            if not payload:
                continue
            parts = payload.split("~")
            if len(parts) < 35:
                continue
            code = str(parts[2] or "").strip()
            if code not in requested_codes:
                continue
            price = cls._to_float(parts[3])
            if price is None or price <= 0:
                continue
            prev_close = cls._to_float(parts[4])
            change_pct = cls._to_float(parts[32])
            if change_pct is None and prev_close and prev_close > 0:
                change_pct = (price - prev_close) / prev_close * 100
            amount = None
            if len(parts) > 35 and "/" in parts[35]:
                amount = cls._to_float(parts[35].split("/")[-1])
            # Tencent reports volume in lots (100 shares); app quote volume is shares.
            volume_lots = cls._to_int(parts[6])
            result[code] = MarketQuote(
                code=code,
                name=str(parts[1] or "").strip(),
                price=price,
                change_pct=round(change_pct or 0.0, 2),
                open_price=cls._to_float(parts[5]),
                high_price=cls._to_float(parts[33]),
                low_price=cls._to_float(parts[34]),
                volume=volume_lots * 100 if volume_lots is not None else None,
                amount=amount,
            )
        return result


    @classmethod
    async def _fetch_from_tencent_api(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """Fetch listed-stock and ETF quotes from Tencent Finance as a fallback."""
        symbols = [cls._tencent_symbol(code) for code in codes if cls._looks_like_listed_security_code(code)]
        symbols = [symbol for symbol in symbols if symbol]
        if not symbols:
            return {}
        url = f"https://qt.gtimg.cn/q={','.join(symbols)}"
        headers = cls._build_default_headers("https://gu.qq.com/")
        try:
            async with market_http_client(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
            text = response.content.decode("gbk", errors="replace")
        except Exception as e:
            logger.info(f"[MarketService] 腾讯财经API请求失败: {e}")
            return {}
        return cls._parse_tencent_quotes(text, codes)

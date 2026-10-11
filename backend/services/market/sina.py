import logging

logger = logging.getLogger("uvicorn.error.sina")

from services.market.http_client import market_http_client
from datetime import date
from typing import List, Dict


# 设置环境变量模拟浏览器

from schemas.market import MarketQuote, KLineItem


from services.market.formats import MarketFormatMixin

class SinaProviderMixin(MarketFormatMixin):
    """sina market parsing and retrieval."""

    @classmethod
    async def _fetch_from_sina_api(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """从新浪财经API获取行情（备用）"""
        # 新浪财经实时行情API
        # 格式: https://hq.sinajs.cn/list=sh513300,sz300059
        code_list = [cls._sina_symbol(code) for code in codes]

        url = f"https://hq.sinajs.cn/list={','.join(code_list)}"
        headers = cls._build_default_headers("https://finance.sina.com.cn/")

        try:
            async with market_http_client(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
            # 返回格式: var hq_str_sh513300="名称,今开,昨收,当前价格,最高,最低,买一,卖一,成交量,成交额,..."
            text = response.text
            result = {}

            for line in text.strip().split('\n'):
                if '=' in line and '"' in line:
                    # 解析: var hq_str_sh513300="..."
                    match = line.split('="')
                    if len(match) == 2:
                        full_code = match[0].replace('var hq_str_', '')
                        data_str = match[1].rstrip('";')

                        # 提取纯代码
                        code = full_code[2:] if full_code.startswith(('sh', 'sz')) else full_code

                        if data_str and code in codes:
                            parts = data_str.split(',')
                            if len(parts) >= 6:
                                name = parts[0]
                                open_price = float(parts[1]) if parts[1] else None
                                prev_close = float(parts[2]) if parts[2] else 0
                                price = float(parts[3]) if parts[3] else 0
                                high = float(parts[4]) if parts[4] else None
                                low = float(parts[5]) if parts[5] else None

                                # 计算涨跌幅
                                change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0

                                result[code] = MarketQuote(
                                    code=code,
                                    name=name,
                                    price=price,
                                    change_pct=round(change_pct, 2),
                                    open_price=open_price,
                                    high_price=high,
                                    low_price=low,
                                    volume=int(parts[8]) if len(parts) > 8 and parts[8] else None,
                                    amount=cls._to_float(parts[9]) if len(parts) > 9 and parts[9] else None,
                                )
            return result
        except Exception as e:
            logger.info(f"[MarketService] 新浪API请求失败: {e}")

        return {}


    @classmethod
    @classmethod
    def _sina_symbol(cls, code: str) -> str:
        clean = str(code or "").strip()
        if clean.startswith(("00", "30", "15", "16", "18", "39")):
            return f"sz{clean}"
        if clean.startswith(("60", "68", "51", "58", "50", "56", "000")):
            return f"sh{clean}"
        return f"sh{clean}"


    @classmethod
    async def _fetch_history_kline_sina(cls, code: str, days: int = 60) -> List[KLineItem]:
        """从新浪财经API获取历史K线数据"""
        symbol = cls._sina_symbol(code)

        url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {
            "symbol": symbol,
            "scale": "240",
            "ma": "no",
            "datalen": str(days),
        }
        headers = cls._build_default_headers("https://finance.sina.com.cn/")

        try:
            logger.info(f"[MarketService] >>> 新浪API获取历史K线: {code} ({symbol})")
            async with market_http_client(timeout=10.0) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()

            if data and isinstance(data, list):
                result = []
                for i, item in enumerate(data):
                    change_pct = 0.0
                    if i > 0:
                        prev_close = result[-1].close_price
                        close = float(item["close"])
                        if prev_close > 0:
                            change_pct = (close - prev_close) / prev_close * 100

                    result.append(KLineItem(
                        trade_date=date.fromisoformat(item["day"].split(" ")[0]),
                        open_price=float(item["open"]),
                        close_price=float(item["close"]),
                        high_price=float(item["high"]),
                        low_price=float(item["low"]),
                        volume=int(item["volume"]),
                        amount=cls._to_float(item.get("amount")),
                        change_pct=round(change_pct, 2),
                    ))

                logger.info(f"[MarketService] ✓ 新浪API获取到 {len(result)} 条K线")
                return result
        except Exception as e:
            logger.info(f"[MarketService] 新浪API获取历史K线失败: {e}")

        return []

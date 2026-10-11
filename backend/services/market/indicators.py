from typing import List


# 设置环境变量模拟浏览器

from schemas.market import KLineItem, TechnicalIndicators


class TechnicalIndicatorMixin:
    """TechnicalIndicatorMixin implementation used by TechnicalIndicatorMixin."""

    @classmethod
    def calculate_technical_indicators(cls, klines: List[KLineItem]) -> TechnicalIndicators:
        """计算技术指标"""
        if len(klines) < 5:
            return TechnicalIndicators()

        # 收盘价列表
        closes = [k.close_price for k in klines]

        # MA均线
        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else None
        ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else None
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None

        # RSI(14)
        rsi14 = None
        if len(closes) >= 15:
            gains = []
            losses = []
            for i in range(1, 15):
                change = closes[-i] - closes[-i-1]
                if change > 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(change))

            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14

            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi14 = 100 - (100 / (1 + rs))
            else:
                rsi14 = 100.0

        # MACD (12, 26, 9)
        macd_dif = None
        macd_dea = None
        macd_histogram = None

        if len(closes) >= 26:
            # 计算EMA
            def ema(prices: List[float], period: int) -> List[float]:
                multiplier = 2 / (period + 1)
                ema_values = [sum(prices[:period]) / period]
                for price in prices[period:]:
                    ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
                return ema_values

            ema12 = ema(closes, 12)
            ema26 = ema(closes, 26)

            # DIF
            dif_values = []
            for i in range(len(ema26)):
                dif_values.append(ema12[i + (len(ema12) - len(ema26))] - ema26[i])

            macd_dif = dif_values[-1]

            # DEA (DIF的9日EMA)
            if len(dif_values) >= 9:
                dea_values = ema(dif_values, 9)
                macd_dea = dea_values[-1]
                macd_histogram = 2 * (macd_dif - macd_dea)

        return TechnicalIndicators(
            ma5=round(ma5, 3) if ma5 else None,
            ma10=round(ma10, 3) if ma10 else None,
            ma20=round(ma20, 3) if ma20 else None,
            rsi14=round(rsi14, 2) if rsi14 else None,
            macd_dif=round(macd_dif, 4) if macd_dif else None,
            macd_dea=round(macd_dea, 4) if macd_dea else None,
            macd_histogram=round(macd_histogram, 4) if macd_histogram else None,
        )

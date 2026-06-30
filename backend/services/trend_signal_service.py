from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from schemas.market import KLineItem


BenchmarkHistories = dict[str, list[KLineItem] | None]


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _moving_average(data: list[dict[str, Any]], period: int) -> list[float | None]:
    values: list[float | None] = []
    for index in range(len(data)):
        if index < period - 1:
            values.append(None)
            continue
        window = data[index - period + 1:index + 1]
        values.append(sum(item["close"] for item in window) / period)
    return values


def _ema(values: list[float], period: int) -> list[float]:
    multiplier = 2 / (period + 1)
    result: list[float] = []
    for index, value in enumerate(values):
        if index == 0:
            result.append(value)
        else:
            result.append((value - result[index - 1]) * multiplier + result[index - 1])
    return result


def _macd(data: list[dict[str, Any]]) -> dict[str, list[float]]:
    closes = [item["close"] for item in data]
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [ema12[index] - ema26[index] for index in range(len(closes))]
    dea = _ema(dif, 9)
    histogram = [(value - dea[index]) * 2 for index, value in enumerate(dif)]
    return {"dif": dif, "dea": dea, "histogram": histogram}


def _rsi(data: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(data) <= period:
        return None
    closes = [item["close"] for item in data]
    gains = 0.0
    losses = 0.0
    for index in range(len(closes) - period, len(closes)):
        change = closes[index] - closes[index - 1]
        if change > 0:
            gains += change
        else:
            losses += abs(change)
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))


def _long_upper_shadow(candle: dict[str, Any]) -> bool:
    price_range = candle["high"] - candle["low"]
    if price_range <= 0:
        return False
    body = abs(candle["close"] - candle["open"])
    upper_shadow = candle["high"] - max(candle["open"], candle["close"])
    return upper_shadow / price_range >= 0.4 and upper_shadow >= max(body * 1.5, price_range * 0.25)


def _amount_label(value: float | None) -> str:
    if value is None:
        return "N/A"
    if value >= 100000000:
        return f"{value / 100000000:.2f}亿"
    if value >= 10000:
        return f"{value / 10000:.2f}万"
    return f"{value:.0f}"


def _num(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}"


def _signed_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2f}%"


def _rule(label: str, passed: bool | None, detail: str) -> dict[str, Any]:
    return {"label": label, "passed": passed, "detail": detail}


def _signal(action: str, label: str, tone: str, summary: str, buy_checks: list[dict[str, Any]], sell_checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "action": action,
        "label": label,
        "toneClassName": tone,
        "summary": summary,
        "buyChecks": buy_checks,
        "sellChecks": sell_checks,
    }


def build_trend_signal(history: list[KLineItem] | None, benchmarks: BenchmarkHistories | None = None) -> dict[str, Any]:
    benchmarks = benchmarks or {}
    data = [
        {
            "open": float(item.open_price),
            "close": float(item.close_price),
            "high": float(item.high_price),
            "low": float(item.low_price),
            "amount": float(item.amount) if item.amount is not None else None,
            "change": float(item.change_pct),
        }
        for item in (history or [])
    ]

    ma5_values = _moving_average(data, 5)
    ma10_values = _moving_average(data, 10)
    ma20_values = _moving_average(data, 20)
    macd = _macd(data) if data else {"dif": [], "dea": [], "histogram": []}
    latest = data[-1] if data else None
    previous = data[-2] if len(data) >= 2 else None
    latest_index = len(data) - 1
    latest_ma5 = ma5_values[-1] if ma5_values else None
    latest_ma10 = ma10_values[-1] if ma10_values else None
    latest_ma20 = ma20_values[-1] if ma20_values else None
    previous_ma10 = ma10_values[-2] if len(ma10_values) >= 2 else None
    previous_ma20 = ma20_values[-2] if len(ma20_values) >= 2 else None
    ma20_five_days_ago = ma20_values[-5] if len(ma20_values) >= 5 else None
    ma20_flat_or_up = latest_ma20 >= ma20_five_days_ago * 0.998 if latest_ma20 is not None and ma20_five_days_ago is not None else None
    ma20_down = latest_ma20 < ma20_five_days_ago * 0.998 if latest_ma20 is not None and ma20_five_days_ago is not None else None

    previous_amount_avg = _avg([item["amount"] for item in data[-6:-1] if item.get("amount") and item["amount"] > 0]) if len(data) >= 6 else None
    if latest and latest.get("amount") is not None and previous_amount_avg is not None:
        amount_passed = latest["amount"] > previous_amount_avg * 1.2
        amount_strong_passed = latest["amount"] > previous_amount_avg * 1.3
        amount_detail = f"成交额 {_amount_label(latest['amount'])} / 过去5日均额 {_amount_label(previous_amount_avg)}"
    else:
        amount_passed = None
        amount_strong_passed = None
        amount_detail = "成交额数据不足，等待行情刷新补齐"

    highest_close60 = max((item["close"] for item in data[-60:]), default=None)
    drawdown_pct = ((highest_close60 - latest["close"]) / highest_close60 * 100) if latest and highest_close60 and highest_close60 > 0 else None
    hs300_change = benchmarks.get("hs300")[-1].change_pct if benchmarks.get("hs300") else None
    csi_a500_change = benchmarks.get("csiA500")[-1].change_pct if benchmarks.get("csiA500") else None
    has_benchmark = hs300_change is not None or csi_a500_change is not None
    stronger_than_benchmark = any(latest["change"] > value for value in [hs300_change, csi_a500_change] if value is not None) if latest and has_benchmark else None

    latest_dif = macd["dif"][-1] if macd["dif"] else None
    latest_dea = macd["dea"][-1] if macd["dea"] else None
    latest_hist = macd["histogram"][-1] if macd["histogram"] else None
    prev_hist = macd["histogram"][-2] if len(macd["histogram"]) >= 2 else None
    macd_turned_strong = (latest_dif > latest_dea or (prev_hist is not None and prev_hist <= 0 and latest_hist > 0)) if latest_dif is not None and latest_dea is not None and latest_hist is not None else None
    rsi14 = _rsi(data, 14)
    rsi_healthy = 45 <= rsi14 <= 70 if rsi14 is not None else None
    rsi_overheated = rsi14 > 75 if rsi14 is not None else False
    distance_from_ma20_pct = ((latest["close"] - latest_ma20) / latest_ma20 * 100) if latest and latest_ma20 and latest_ma20 > 0 else None
    too_far_from_ma20 = distance_from_ma20_pct > 7 if distance_from_ma20_pct is not None else False
    previous_long_upper = _long_upper_shadow(previous) if previous else False
    failed_repair = bool(previous and latest and previous_long_upper and latest["close"] <= max(previous["open"], previous["close"]))
    latest_long_upper_with_volume = bool(latest and _long_upper_shadow(latest) and amount_strong_passed is True)

    price_above_ma20 = latest["close"] > latest_ma20 if latest and latest_ma20 is not None else None
    ma5_above_ma10 = latest_ma5 > latest_ma10 if latest_ma5 is not None and latest_ma10 is not None else None
    buy_required = [
        _rule("收盘站上 MA20", price_above_ma20, f"收盘 {_num(latest['close'] if latest else None)} / MA20 {_num(latest_ma20)}"),
        _rule("MA5 高于 MA10", ma5_above_ma10, f"MA5 {_num(latest_ma5)} / MA10 {_num(latest_ma10)}"),
        _rule("MA20 走平或上行", ma20_flat_or_up, f"MA20 {_num(latest_ma20)} / 5日前 {_num(ma20_five_days_ago)}"),
    ]
    buy_bonus = [
        _rule("成交额放大 1.2x", amount_passed, amount_detail),
        _rule("强于沪深300或中证A500", stronger_than_benchmark, f"ETF {_signed_pct(latest['change'] if latest else None)} / 沪深300 {_signed_pct(hs300_change)} / 中证A500 {_signed_pct(csi_a500_change)}"),
        _rule("MACD 转强", macd_turned_strong, f"DIF {_num(latest_dif, 4)} / DEA {_num(latest_dea, 4)} / 柱 {_num(latest_hist, 4)}"),
        _rule("RSI 45-70", rsi_healthy, f"RSI {_num(rsi14, 2)}"),
    ]
    buy_checks = [*buy_required, *buy_bonus]
    required_buy_passed = all(item["passed"] is True for item in buy_required)
    bonus_passed_count = sum(1 for item in buy_bonus if item["passed"] is True)
    avoid_chase = rsi_overheated or too_far_from_ma20

    below_ma10 = latest["close"] < latest_ma10 if latest and latest_ma10 is not None else None
    previous_below_ma10 = previous["close"] < previous_ma10 if previous and previous_ma10 is not None else False
    confirmed_below_ma10 = below_ma10 is True and (previous_below_ma10 or amount_strong_passed is True)
    below_ma20 = latest["close"] < latest_ma20 if latest and latest_ma20 is not None else None
    previous_below_ma20 = previous["close"] < previous_ma20 if previous and previous_ma20 is not None else False
    confirmed_below_ma20 = below_ma20 is True and (previous_below_ma20 or ma20_down is True)
    clearly_weaker = any(latest["change"] < value - 0.8 for value in [hs300_change, csi_a500_change] if value is not None) if latest and has_benchmark else None

    sell_checks = [
        _rule("MA20 破位确认，清仓", confirmed_below_ma20, f"收盘 {_num(latest['close'] if latest else None)} / MA20 {_num(latest_ma20)}；{'连续2日低于MA20' if previous_below_ma20 else 'MA20下行确认' if ma20_down else '尚未确认'}"),
        _rule("MA10 破位确认，减仓", confirmed_below_ma10, f"收盘 {_num(latest['close'] if latest else None)} / MA10 {_num(latest_ma10)}；{'连续2日低于MA10' if previous_below_ma10 else '放量跌破' if amount_strong_passed else '尚未确认'}"),
        _rule("60日高点回撤 5%-8%，移动止盈", drawdown_pct >= 5 and drawdown_pct <= 8 and below_ma20 is not True if drawdown_pct is not None else None, f"60日最高收盘 {_num(highest_close60)} / 当前回撤 {'N/A' if drawdown_pct is None else f'-{drawdown_pct:.2f}%'}"),
        _rule("放量长上影次日未修复，减仓", failed_repair if previous and latest else None, f"前一日{'出现' if previous_long_upper else '未出现'}长上影，今日收盘 {_num(latest['close'] if latest else None)} / 前一日实体高点 {_num(max(previous['open'], previous['close']) if previous else None)}" if previous and latest else "需要至少两个交易日数据"),
        _rule("相对指数明显走弱", clearly_weaker, f"ETF {_signed_pct(latest['change'] if latest else None)} / 沪深300 {_signed_pct(hs300_change)} / 中证A500 {_signed_pct(csi_a500_change)}"),
    ]

    if len(data) < 20 or latest_index < 19:
        return _signal("insufficient", "数据不足", "border-slate-200 bg-slate-50 text-slate-700", "至少需要 20 个交易日 K 线才能判断 MA20 相关规则。", buy_checks, sell_checks)
    if confirmed_below_ma20 or (below_ma20 and ma20_down and clearly_weaker):
        return _signal("clear", "清仓", "border-green-200 bg-green-50 text-green-700", "MA20 破位已确认，或破位同时伴随趋势下行与相对走弱，优先执行清仓风控。", buy_checks, sell_checks)
    if confirmed_below_ma10 or failed_repair:
        summary = "MA10 破位已确认，按该方案触发减仓观察。" if confirmed_below_ma10 else "前一日长上影后未修复，按该方案触发减仓观察。"
        return _signal("reduce", "减仓", "border-amber-200 bg-amber-50 text-amber-700", summary, buy_checks, sell_checks)
    if drawdown_pct is not None and drawdown_pct >= 5 and drawdown_pct <= 8 and below_ma20 is not True:
        return _signal("take_profit", "移动止盈", "border-blue-200 bg-blue-50 text-blue-700", "从 60 日高点回撤进入 5%-8% 区间，但尚未跌破 MA20，适合执行移动止盈纪律。", buy_checks, sell_checks)
    if required_buy_passed and bonus_passed_count >= 3 and not avoid_chase:
        return _signal("buy", "正常买入", "border-red-200 bg-red-50 text-red-700", "趋势必要条件成立，且成交额、相对强弱、MACD、RSI 中至少 3 项加分条件满足。", buy_checks, sell_checks)
    if required_buy_passed and bonus_passed_count >= 2 and not avoid_chase:
        return _signal("buy", "试探买入", "border-orange-200 bg-orange-50 text-orange-700", "趋势必要条件成立，且至少 2 项强度条件满足，适合小仓位试探。", buy_checks, sell_checks)
    if required_buy_passed and avoid_chase:
        reason = "RSI过热" if rsi_overheated else "价格距离MA20过远"
        return _signal("watch", "等待回踩", "border-slate-200 bg-slate-50 text-slate-700", f"趋势条件成立，但{reason}，不宜追高。", buy_checks, sell_checks)
    if latest_long_upper_with_volume:
        return _signal("watch", "观察修复", "border-slate-200 bg-slate-50 text-slate-700", "当日出现放量长上影，需要观察次日能否重新站上实体高点。", buy_checks, sell_checks)
    return _signal("watch", "观察", "border-slate-200 bg-slate-50 text-slate-700", "当前没有满足分层买入条件，也未触发确认后的卖出条件。", buy_checks, sell_checks)


def build_otc_fund_trend_signal(history: list[KLineItem] | None) -> dict[str, Any]:
    data = [float(item.close_price) for item in (history or []) if float(item.close_price) > 0]
    if len(data) < 20:
        return _signal(
            "insufficient",
            "净值数据不足",
            "border-slate-200 bg-slate-50 text-slate-700",
            "场外基金至少需要 20 个净值点才能判断 MA20 和回撤。",
            [_rule("净值点不少于20个", False, f"当前 {len(data)} 个")],
            [],
        )

    latest = data[-1]
    ma20 = sum(data[-20:]) / 20
    ma60 = sum(data[-60:]) / 60 if len(data) >= 60 else None
    ma20_prev = sum(data[-25:-5]) / 20 if len(data) >= 25 else None
    ma20_slope_pct = (ma20 - ma20_prev) / ma20_prev * 100 if ma20_prev and ma20_prev > 0 else None
    high60 = max(data[-60:]) if len(data) >= 60 else max(data)
    drawdown_pct = (high60 - latest) / high60 * 100 if high60 > 0 else None
    return20_pct = (latest - data[-20]) / data[-20] * 100 if len(data) >= 21 and data[-20] > 0 else None
    return60_pct = (latest - data[-60]) / data[-60] * 100 if len(data) >= 61 and data[-60] > 0 else None
    above_ma20 = latest >= ma20
    ma20_up = ma20_slope_pct is not None and ma20_slope_pct >= 0
    above_ma60 = latest >= ma60 if ma60 is not None else None

    buy_checks = [
        _rule("净值站上 MA20", above_ma20, f"净值 {_num(latest)} / MA20 {_num(ma20)}"),
        _rule("MA20 走平或上行", ma20_up if ma20_slope_pct is not None else None, f"MA20斜率 {_signed_pct(ma20_slope_pct)}"),
        _rule("回撤进入可定投区间", drawdown_pct is not None and drawdown_pct >= 3, f"60日高点回撤 {'N/A' if drawdown_pct is None else f'-{drawdown_pct:.2f}%'}"),
    ]
    sell_checks = [
        _rule("净值跌破 MA20 且 MA20 下行", (not above_ma20) and ma20_slope_pct is not None and ma20_slope_pct < -0.5, f"净值 {_num(latest)} / MA20 {_num(ma20)} / 斜率 {_signed_pct(ma20_slope_pct)}"),
        _rule("60日回撤超过 10%", drawdown_pct is not None and drawdown_pct >= 10, f"回撤 {'N/A' if drawdown_pct is None else f'-{drawdown_pct:.2f}%'}"),
        _rule("近20日涨幅过快", return20_pct is not None and return20_pct >= 8, f"近20日 {_signed_pct(return20_pct)}"),
    ]

    if drawdown_pct is not None and drawdown_pct >= 12 and not above_ma20:
        return _signal("watch", "观察修复", "border-slate-200 bg-slate-50 text-slate-700", "净值回撤较深且尚未站回 MA20，先观察修复，不扩大单次投入。", buy_checks, sell_checks)
    if (not above_ma20) and ma20_slope_pct is not None and ma20_slope_pct < -0.5:
        return _signal("reduce", "放缓定投", "border-amber-200 bg-amber-50 text-amber-700", "净值低于 MA20 且 MA20 下行，场外基金先降低定投节奏。", buy_checks, sell_checks)
    if return20_pct is not None and return20_pct >= 8:
        return _signal("watch", "等待回撤", "border-slate-200 bg-slate-50 text-slate-700", "近20个净值点涨幅较快，避免在场外基金净值高位追投。", buy_checks, sell_checks)
    if above_ma20 and ma20_up and (above_ma60 is not False):
        return _signal("buy", "正常定投", "border-red-200 bg-red-50 text-red-700", "净值站上 MA20，短期均线走平或上行，适合按计划定投。", buy_checks, sell_checks)
    if drawdown_pct is not None and drawdown_pct >= 5:
        return _signal("buy", "小额定投", "border-orange-200 bg-orange-50 text-orange-700", "净值已有一定回撤，但趋势尚未完全修复，适合小额分批。", buy_checks, sell_checks)
    summary = f"净值趋势中性，近20日 {_signed_pct(return20_pct)}，近60日 {_signed_pct(return60_pct)}。"
    return _signal("watch", "观察", "border-slate-200 bg-slate-50 text-slate-700", summary, buy_checks, sell_checks)


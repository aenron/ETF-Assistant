import inspect
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import akshare as ak
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.macro_cycle_state import MacroCycleState
from models.macro_indicator import MacroIndicator
from utils.timezone import now_in_utc_naive


@dataclass(frozen=True)
class MacroIndicatorSpec:
    region: str
    code: str
    name: str
    category: str
    unit: str
    functions: tuple[Any, ...]
    date_keywords: tuple[str, ...]
    value_keywords: tuple[str, ...]
    positive_when: str = "up"
    weight: float = 25
    max_abs_value: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    row_keywords: tuple[str, ...] = ()
    previous_keywords: tuple[str, ...] = ("前值", "昨日结算价", "昨结", "previous")
    avoid_value_keywords: tuple[str, ...] = ("日期", "时间", "月份", "商品", "名称", "代码", "序号", "总价值", "成交额", "成交量", "数量", "市值", "持仓量")


class MacroDataService:
    SPECS = (
        MacroIndicatorSpec(
            region="cn",
            code="cn_pmi_manufacturing",
            name="中国制造业PMI",
            category="growth",
            unit="%",
            functions=("macro_china_pmi", "macro_china_pmi_yearly"),
            date_keywords=("月份", "时间", "日期", "month", "date"),
            value_keywords=("制造业-指数", "PMI", "pmi"),
            min_value=0,
            max_value=100,
            positive_when="up",
            weight=30,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_cpi_yoy",
            name="中国CPI同比",
            category="inflation",
            unit="%",
            functions=("macro_china_cpi_monthly", "macro_china_cpi_yearly"),
            date_keywords=("月份", "时间", "日期", "month", "date"),
            value_keywords=("今值", "实际值", "同比", "CPI", "cpi"),
            max_abs_value=50,
            positive_when="up",
            weight=35,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_ppi_yoy",
            name="中国PPI同比",
            category="inflation",
            unit="%",
            functions=("macro_china_ppi_yearly", "macro_china_ppi"),
            date_keywords=("月份", "时间", "日期", "month", "date"),
            value_keywords=("今值", "实际值", "同比", "PPI", "ppi"),
            max_abs_value=50,
            positive_when="up",
            weight=35,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_social_financing",
            name="中国社会融资规模",
            category="growth",
            unit="亿元",
            functions=("macro_china_shrzgm", "macro_china_money_supply"),
            date_keywords=("月份", "时间", "日期", "统计时间", "month", "date"),
            value_keywords=("社会融资规模增量", "社融", "社会融资规模"),
            min_value=0,
            max_abs_value=1000000,
            positive_when="up",
            weight=25,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_industrial_added_value",
            name="中国工业增加值",
            category="growth",
            unit="%",
            functions=("macro_china_industrial_production_yoy", "macro_china_industrial_production"),
            date_keywords=("月份", "时间", "日期", "month", "date"),
            value_keywords=("今值", "实际值", "同比", "工业增加值", "增长"),
            max_abs_value=50,
            positive_when="up",
            weight=20,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_m2",
            name="中国M2货币供应",
            category="liquidity",
            unit="%",
            functions=("macro_china_money_supply",),
            date_keywords=("月份", "时间", "日期", "统计时间", "month", "date"),
            value_keywords=("货币和准货币(M2)-同比增长", "M2)-同比增长", "同比增长"),
            max_abs_value=50,
            positive_when="up",
            weight=25,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_export_yoy",
            name="中国出口同比",
            category="growth",
            unit="%",
            functions=("macro_china_exports_yoy", "macro_china_hgjck"),
            date_keywords=("月份", "时间", "日期", "month", "date"),
            value_keywords=("今值", "实际值", "出口", "同比", "出口金额"),
            max_abs_value=100,
            positive_when="up",
            weight=20,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_retail_sales",
            name="中国社会消费品零售",
            category="growth",
            unit="%",
            functions=("macro_china_consumer_goods_retail", "macro_china_retail_sales"),
            date_keywords=("月份", "时间", "日期", "month", "date"),
            value_keywords=("同比增长", "社会消费品", "零售"),
            max_abs_value=100,
            positive_when="up",
            weight=20,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_house_price",
            name="中国房价指数",
            category="property",
            unit="%",
            functions=("macro_china_new_house_price", "macro_china_real_estate"),
            date_keywords=("月份", "时间", "日期", "month", "date"),
            value_keywords=("新建商品住宅价格指数-同比",),
            max_abs_value=200,
            row_keywords=("北京",),
            avoid_value_keywords=("日期", "时间", "月份", "城市", "名称", "代码", "序号", "总价值", "成交额", "成交量", "数量", "市值", "持仓量"),
            positive_when="up",
            weight=20,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_caixin_pmi",
            name="中国财新制造业PMI",
            category="growth",
            unit="%",
            functions=("macro_china_cx_pmi_yearly",),
            date_keywords=("月份", "时间", "日期", "month", "date"),
            value_keywords=("今值", "实际值", "PMI", "value"),
            min_value=0,
            max_value=100,
            positive_when="up",
            weight=18,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_services_pmi",
            name="中国服务业PMI",
            category="growth",
            unit="%",
            functions=("macro_china_cx_services_pmi_yearly", "macro_china_non_man_pmi"),
            date_keywords=("月份", "时间", "日期", "month", "date"),
            value_keywords=("今值", "实际值", "PMI", "value"),
            min_value=0,
            max_value=100,
            positive_when="up",
            weight=16,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_fixed_asset_investment",
            name="中国固定资产投资",
            category="growth",
            unit="%",
            functions=("macro_china_gdzctz",),
            date_keywords=("月份", "时间", "日期", "month", "date"),
            value_keywords=("同比增长",),
            max_abs_value=100,
            positive_when="up",
            weight=18,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_m1",
            name="中国M1货币供应",
            category="liquidity",
            unit="%",
            functions=("macro_china_money_supply", "macro_china_supply_of_money"),
            date_keywords=("月份", "时间", "日期", "统计时间", "month", "date"),
            value_keywords=("货币(M1)-同比增长", "货币(狭义货币M1)同比增长", "M1)同比增长"),
            max_abs_value=50,
            positive_when="up",
            weight=25,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_m1_m2_gap",
            name="中国M1-M2剪刀差",
            category="liquidity",
            unit="pct",
            functions=(),
            date_keywords=("月份", "时间", "日期", "统计时间", "month", "date"),
            value_keywords=("M1-M2",),
            max_abs_value=50,
            positive_when="up",
            weight=25,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_lpr_1y",
            name="中国1年期LPR",
            category="liquidity",
            unit="%",
            functions=("macro_china_lpr",),
            date_keywords=("TRADE_DATE", "日期", "时间", "date"),
            value_keywords=("LPR1Y",),
            min_value=0,
            max_value=20,
            positive_when="down",
            weight=15,
        ),
        MacroIndicatorSpec(
            region="cn",
            code="cn_real_estate_index",
            name="中国房地产景气指数",
            category="property",
            unit="",
            functions=("macro_china_real_estate",),
            date_keywords=("日期", "时间", "month", "date"),
            value_keywords=("最新值",),
            min_value=0,
            max_value=200,
            positive_when="up",
            weight=25,
        ),
        MacroIndicatorSpec(
            region="us",
            code="us_cpi_yoy",
            name="美国CPI同比",
            category="inflation",
            unit="%",
            functions=("macro_usa_cpi_monthly", "macro_usa_cpi"),
            date_keywords=("月份", "时间", "日期", "date", "month"),
            value_keywords=("今值", "实际值", "CPI", "cpi", "value"),
            max_abs_value=50,
            positive_when="up",
            weight=35,
        ),
        MacroIndicatorSpec(
            region="us",
            code="us_pmi",
            name="美国PMI",
            category="growth",
            unit="%",
            functions=("macro_usa_pmi", "macro_usa_ism_pmi"),
            date_keywords=("月份", "时间", "日期", "date", "month"),
            value_keywords=("今值", "实际值", "PMI", "pmi", "ISM", "value"),
            min_value=0,
            max_value=100,
            positive_when="up",
            weight=30,
        ),
        MacroIndicatorSpec(
            region="us",
            code="us_unemployment_rate",
            name="美国失业率",
            category="growth",
            unit="%",
            functions=("macro_usa_unemployment_rate", "macro_usa_unemployment"),
            date_keywords=("月份", "时间", "日期", "date", "month"),
            value_keywords=("今值", "实际值", "失业率", "unemployment", "value"),
            min_value=0,
            max_value=30,
            positive_when="down",
            weight=25,
        ),
        MacroIndicatorSpec(
            region="us",
            code="us_fed_rate",
            name="美国联邦基金利率",
            category="liquidity",
            unit="%",
            functions=("macro_usa_fed_interest_rate", "macro_bank_usa_interest_rate"),
            date_keywords=("日期", "时间", "date", "month"),
            value_keywords=("今值", "实际值", "利率", "value", "rate"),
            min_value=0,
            max_value=30,
            positive_when="down",
            weight=35,
        ),
        MacroIndicatorSpec(
            region="us",
            code="us_nonfarm",
            name="美国非农就业",
            category="growth",
            unit="万人",
            functions=("macro_usa_non_farm", "macro_usa_nonfarm_payrolls"),
            date_keywords=("日期", "时间", "date", "month"),
            value_keywords=("今值", "实际值", "非农", "value"),
            positive_when="up",
            weight=25,
        ),
        MacroIndicatorSpec(
            region="us",
            code="us_pce",
            name="美国PCE物价",
            category="inflation",
            unit="%",
            functions=("macro_usa_core_pce_price", "macro_usa_pce"),
            date_keywords=("日期", "时间", "date", "month"),
            value_keywords=("今值", "实际值", "PCE", "value"),
            positive_when="up",
            weight=30,
        ),
        MacroIndicatorSpec(
            region="us",
            code="us_10y_yield",
            name="美国10年期国债收益率",
            category="liquidity",
            unit="%",
            functions=(("bond_zh_us_rate", {"start_date": "20200101"}), "bond_zh_us_rate"),
            date_keywords=("日期", "时间", "date"),
            value_keywords=("美国国债收益率10年", "美国10年", "10Y"),
            min_value=0,
            max_value=20,
            avoid_value_keywords=("日期", "时间", "月份", "中国"),
            positive_when="down",
            weight=35,
        ),
        MacroIndicatorSpec(
            region="global",
            code="global_vix",
            name="VIX波动率",
            category="risk",
            unit="",
            functions=("index_vix",),
            date_keywords=("日期", "时间", "date"),
            value_keywords=("收盘", "最新价", "最新", "close", "value"),
            positive_when="down",
            weight=35,
            min_value=0,
            max_value=100,
        ),
        MacroIndicatorSpec(
            region="global",
            code="global_gold",
            name="黄金价格",
            category="risk",
            unit="",
            functions=(("futures_foreign_commodity_realtime", {"symbol": ["GC"]}), ("futures_global_spot_em", {})),
            date_keywords=("日期", "时间", "date"),
            value_keywords=("最新价", "收盘", "价格", "close", "value"),
            positive_when="up",
            weight=20,
            min_value=100,
            max_abs_value=100000,
            row_keywords=("黄金", "GC"),
        ),
        MacroIndicatorSpec(
            region="global",
            code="global_dxy",
            name="美元指数",
            category="currency",
            unit="",
            functions=(("index_global_hist_em", {"symbol": "美元指数"}),),
            date_keywords=("日期", "时间", "date"),
            value_keywords=("收盘", "最新价", "最新", "close", "value"),
            positive_when="down",
            weight=35,
            min_value=50,
            max_value=200,
        ),
        MacroIndicatorSpec(
            region="global",
            code="global_oil",
            name="原油价格",
            category="inflation",
            unit="",
            functions=(("futures_foreign_commodity_realtime", {"symbol": ["CL"]}), ("futures_global_spot_em", {})),
            date_keywords=("日期", "时间", "date"),
            value_keywords=("最新价", "收盘", "价格", "close", "value"),
            positive_when="up",
            weight=30,
            min_value=1,
            max_abs_value=100000,
            row_keywords=("原油", "WTI", "NYMEX", "CL"),
        ),
        MacroIndicatorSpec(
            region="global",
            code="global_copper",
            name="铜价",
            category="inflation",
            unit="",
            functions=(("futures_foreign_commodity_realtime", {"symbol": ["CAD"]}), ("futures_global_spot_em", {})),
            date_keywords=("日期", "时间", "date"),
            value_keywords=("最新价", "收盘", "价格", "close", "value"),
            positive_when="up",
            weight=25,
            min_value=1000,
            max_abs_value=1000000,
            row_keywords=("铜", "LME", "CAD"),
        ),
        MacroIndicatorSpec(
            region="global",
            code="global_usdcny",
            name="美元兑人民币",
            category="currency",
            unit="",
            functions=("fx_spot_quote", ("forex_spot_em", {})),
            date_keywords=("日期", "时间", "date"),
            value_keywords=("卖报价", "买报价", "最新价", "收盘", "最新", "close", "value"),
            positive_when="down",
            weight=30,
            min_value=4,
            max_value=10,
            row_keywords=("USD/CNY", "美元人民币", "USDCNY"),
        ),
    )

    @classmethod
    def _normalize_function_entry(cls, entry: Any) -> tuple[str, dict[str, Any]]:
        if isinstance(entry, tuple) and entry:
            name = str(entry[0])
            kwargs = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
            return name, kwargs
        return str(entry), {}

    @classmethod
    def _call_akshare(cls, entry: Any):
        fn_name, kwargs = cls._normalize_function_entry(entry)
        fn = getattr(ak, fn_name, None)
        if fn is None:
            return None
        try:
            if inspect.iscoroutinefunction(fn):
                return None
            return fn(**kwargs)
        except Exception as e:
            print(f"[MacroDataService] AkShare函数调用失败: {fn_name}, {e}")
            return None

    @staticmethod
    def _normalize_number(value: Any) -> float | None:
        if value is None:
            return None
        text = str(value).strip().replace(",", "").replace("%", "")
        if not text or text in {"--", "-", "nan", "None"}:
            return None
        try:
            parsed = float(text)
        except ValueError:
            return None
        if pd.isna(parsed):
            return None
        return parsed


    @staticmethod
    def _valid_indicator_value(value: float, spec: MacroIndicatorSpec) -> bool:
        if spec.min_value is not None and value < spec.min_value:
            return False
        if spec.max_value is not None and value > spec.max_value:
            return False
        if spec.max_abs_value is not None and abs(value) > spec.max_abs_value:
            return False
        if abs(value) >= 10_000_000_000:
            return False
        return True

    @classmethod
    def _pick_column(cls, columns: list[str], keywords: tuple[str, ...], avoid: tuple[str, ...] = ()) -> str | None:
        for keyword in keywords:
            for column in columns:
                name = str(column)
                if keyword.lower() in name.lower() and not any(item.lower() in name.lower() for item in avoid):
                    return column
        return None

    @classmethod
    def _filter_rows(cls, frame: pd.DataFrame, spec: MacroIndicatorSpec) -> pd.DataFrame:
        if not spec.row_keywords:
            return frame
        mask = pd.Series(False, index=frame.index)
        for column in frame.columns:
            values = frame[column].astype(str)
            for keyword in spec.row_keywords:
                mask = mask | values.str.contains(str(keyword), case=False, na=False)
        filtered = frame[mask]
        return filtered if not filtered.empty else frame.iloc[0:0]

    @staticmethod
    def _period_sort_value(value: Any) -> pd.Timestamp:
        text = str(value).strip()
        match = re.search(r"(\d{4})年(\d{1,2})月", text)
        if match:
            return pd.Timestamp(year=int(match.group(1)), month=int(match.group(2)), day=1)
        if re.fullmatch(r"\d{6}", text):
            return pd.Timestamp(year=int(text[:4]), month=int(text[4:6]), day=1)
        if re.fullmatch(r"\d{8}", text):
            return pd.Timestamp(year=int(text[:4]), month=int(text[4:6]), day=int(text[6:8]))
        normalized = text.replace("年", "-").replace("月份", "").replace("月", "-").replace("日", "")
        parsed = pd.to_datetime(normalized, errors="coerce")
        if pd.isna(parsed):
            parsed = pd.to_datetime(text, errors="coerce")
        return parsed if not pd.isna(parsed) else pd.Timestamp.min

    @classmethod
    def _extract_latest(cls, df: pd.DataFrame, spec: MacroIndicatorSpec) -> tuple[str, float, float | None, str, str] | None:
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return None
        frame = df.copy().dropna(how="all")
        if frame.empty:
            return None
        frame = cls._filter_rows(frame, spec)
        if frame.empty:
            return None
        columns = [str(column) for column in frame.columns]
        matched_date_col = cls._pick_column(columns, spec.date_keywords)
        date_col = matched_date_col or columns[0]
        value_col = cls._pick_column(columns, spec.value_keywords, avoid=spec.avoid_value_keywords)
        if not value_col:
            numeric_candidates = []
            for column in columns:
                if any(item.lower() in str(column).lower() for item in spec.avoid_value_keywords):
                    continue
                values = [cls._normalize_number(item) for item in frame[column].tail(5)]
                if any(item is not None and cls._valid_indicator_value(item, spec) for item in values):
                    numeric_candidates.append(column)
            value_col = numeric_candidates[-1] if numeric_candidates else None
        if not value_col:
            return None

        previous_col = cls._pick_column(columns, spec.previous_keywords, avoid=spec.avoid_value_keywords)
        values = []
        for _, row in frame.iterrows():
            value = cls._normalize_number(row.get(value_col))
            if value is None or not cls._valid_indicator_value(value, spec):
                continue
            period = str(row.get(date_col)) if matched_date_col else now_in_utc_naive().date().isoformat()
            previous_value = None
            if previous_col:
                previous_value = cls._normalize_number(row.get(previous_col))
                if previous_value is not None and not cls._valid_indicator_value(previous_value, spec):
                    previous_value = None
            values.append((cls._period_sort_value(period), period, value, previous_value))
        if not values:
            return None
        values.sort(key=lambda item: item[0])
        _, period, value, explicit_previous = values[-1]
        previous = explicit_previous if explicit_previous is not None else (values[-2][2] if len(values) >= 2 else None)
        return period, value, previous, str(period), str(value_col)

    @staticmethod
    def _trend(value: float, previous: float | None) -> str:
        if previous is None:
            return "unclear"
        if value > previous:
            return "up"
        if value < previous:
            return "down"
        return "flat"

    @classmethod
    async def _save_indicator(cls, session: AsyncSession, spec: MacroIndicatorSpec, period: str, value: float, previous: float | None, source_function: str, source_column: str | None, raw_period: str | None) -> MacroIndicator:
        trend = cls._trend(value, previous)
        result = await session.execute(
            select(MacroIndicator).where(
                MacroIndicator.region == spec.region,
                MacroIndicator.indicator_code == spec.code,
                MacroIndicator.period == period,
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            item = MacroIndicator(region=spec.region, indicator_code=spec.code, period=period)
            session.add(item)
        item.region = spec.region
        item.indicator_name = spec.name
        item.category = spec.category
        item.value = Decimal(str(value))
        item.previous_value = Decimal(str(previous)) if previous is not None else None
        item.trend = trend
        item.unit = spec.unit
        item.source = "akshare"
        item.source_note = source_function
        item.source_function = source_function
        item.source_column = source_column
        item.raw_period = raw_period
        item.fetched_at = now_in_utc_naive()
        return item

    @classmethod
    async def _save_cn_m1_m2_gap(cls, session: AsyncSession, saved: list[MacroIndicator]) -> MacroIndicator | None:
        latest = {item.indicator_code: item for item in saved if item.region == "cn"}
        m1 = latest.get("cn_m1")
        m2 = latest.get("cn_m2")
        spec = next((item for item in cls.SPECS if item.code == "cn_m1_m2_gap"), None)
        if not spec or not m1 or not m2:
            return None
        value = float(m1.value) - float(m2.value)
        previous = None
        if m1.previous_value is not None and m2.previous_value is not None:
            previous = float(m1.previous_value) - float(m2.previous_value)
        period = str(m1.period if m1.fetched_at >= m2.fetched_at else m2.period)
        item = await cls._save_indicator(session, spec, period, value, previous, "derived:m1_minus_m2", "M1同比-M2同比", period)
        saved.append(item)
        return item

    @classmethod
    async def collect_indicators(cls, session: AsyncSession, region: str | None = None) -> tuple[list[MacroIndicator], list[str]]:
        saved: list[MacroIndicator] = []
        errors: list[str] = []
        for spec in cls.SPECS:
            if region and spec.region != region:
                continue
            if not spec.functions:
                continue
            extracted = None
            used_function = None
            for fn_entry in spec.functions:
                fn_name, _ = cls._normalize_function_entry(fn_entry)
                df = cls._call_akshare(fn_entry)
                if df is None:
                    continue
                extracted = cls._extract_latest(df, spec)
                if extracted:
                    used_function = fn_name
                    break
            if not extracted:
                errors.append(f"{spec.name} 采集失败")
                continue
            period, value, previous, raw_period, source_column = extracted
            saved.append(await cls._save_indicator(session, spec, period, value, previous, used_function or "akshare", source_column, raw_period))
        if region in (None, "cn"):
            await cls._save_cn_m1_m2_gap(session, saved)
        await session.flush()
        return saved, errors

    @classmethod
    async def latest_indicators(cls, session: AsyncSession, region: str | None = None, limit: int = 20) -> list[MacroIndicator]:
        stmt = select(MacroIndicator)
        if region:
            stmt = stmt.where(MacroIndicator.region == region)
        result = await session.execute(
            stmt.order_by(MacroIndicator.fetched_at.desc(), MacroIndicator.id.desc()).limit(limit)
        )
        items = result.scalars().all()
        latest_by_code: dict[str, MacroIndicator] = {}
        for item in items:
            latest_by_code.setdefault(f"{item.region}:{item.indicator_code}", item)
        return list(latest_by_code.values())

    @classmethod
    def _score_category(cls, indicators: list[MacroIndicator], category: str, region: str) -> tuple[float, str]:
        specs = {spec.code: spec for spec in cls.SPECS if spec.category == category and spec.region == region}
        total_weight = 0.0
        score = 0.0
        trends = []
        for item in indicators:
            spec = specs.get(item.indicator_code)
            if not spec:
                continue
            total_weight += spec.weight
            trend = item.trend
            trends.append(trend)
            value = float(item.value)
            previous = float(item.previous_value) if item.previous_value is not None else None
            if trend == spec.positive_when:
                score += spec.weight
            elif trend == "flat" or trend == "unclear":
                score += spec.weight * 0.5
            if item.indicator_code == "cn_pmi_manufacturing" and value >= 50:
                score += spec.weight * 0.25
            if previous is not None and abs(value - previous) < 0.01:
                score += spec.weight * 0.1
        if total_weight <= 0:
            return 50.0, "unclear"
        normalized = max(0.0, min(100.0, score / total_weight * 100))
        up_count = trends.count("up")
        down_count = trends.count("down")
        if up_count > down_count:
            trend = "up"
        elif down_count > up_count:
            trend = "down"
        elif trends:
            trend = "flat"
        else:
            trend = "unclear"
        return normalized, trend


    @classmethod
    def _score_categories(cls, indicators: list[MacroIndicator], categories: tuple[str, ...], region: str) -> tuple[float, str]:
        scores = []
        trends = []
        for category in categories:
            score, trend = cls._score_category(indicators, category, region)
            category_specs = [spec for spec in cls.SPECS if spec.category == category and spec.region == region]
            if category_specs:
                scores.append(score)
                trends.append(trend)
        if not scores:
            return 50.0, "unclear"
        up_count = trends.count("up")
        down_count = trends.count("down")
        if up_count > down_count:
            trend = "up"
        elif down_count > up_count:
            trend = "down"
        elif trends:
            trend = "flat"
        else:
            trend = "unclear"
        return sum(scores) / len(scores), trend

    @staticmethod
    def _indicator_value_map(indicators: list[MacroIndicator]) -> dict[str, tuple[float, str]]:
        values: dict[str, tuple[float, str]] = {}
        for item in indicators:
            try:
                values[item.indicator_code] = (float(item.value), item.trend)
            except (TypeError, ValueError):
                continue
        return values

    @classmethod
    def _score_cn_cycle(cls, indicators: list[MacroIndicator]) -> tuple[float, float, str, str]:
        values = cls._indicator_value_map(indicators)

        growth_score = 50.0
        for code, strong, ok, weak, weight in (
            ("cn_pmi_manufacturing", 52.0, 50.0, 48.0, 14),
            ("cn_caixin_pmi", 52.0, 50.0, 48.0, 10),
            ("cn_services_pmi", 53.0, 50.0, 48.0, 8),
        ):
            item = values.get(code)
            if not item:
                continue
            value, trend = item
            if value >= strong:
                growth_score += weight
            elif value >= ok:
                growth_score += weight * 0.55
            elif value < weak:
                growth_score -= weight
            else:
                growth_score -= weight * 0.35
            if trend == "up":
                growth_score += 3
            elif trend == "down":
                growth_score -= 3

        for code, high, mid, low, weight in (
            ("cn_industrial_added_value", 6.0, 4.0, 2.0, 10),
            ("cn_retail_sales", 5.0, 3.0, 1.0, 10),
            ("cn_fixed_asset_investment", 5.0, 3.0, 0.0, 8),
            ("cn_export_yoy", 8.0, 3.0, -3.0, 6),
        ):
            item = values.get(code)
            if not item:
                continue
            value, trend = item
            if value >= high:
                growth_score += weight
            elif value >= mid:
                growth_score += weight * 0.55
            elif value < low:
                growth_score -= weight
            else:
                growth_score -= weight * 0.25
            if trend == "up":
                growth_score += 2
            elif trend == "down":
                growth_score -= 2

        credit_score = 50.0
        m2 = values.get("cn_m2")
        if m2:
            value, trend = m2
            if 7 <= value <= 10:
                credit_score += 8
            elif value > 10:
                credit_score += 4
            elif value < 6:
                credit_score -= 10
            if trend == "up":
                credit_score += 3
            elif trend == "down":
                credit_score -= 3
        m1 = values.get("cn_m1")
        if m1:
            value, trend = m1
            if value >= 8:
                credit_score += 14
            elif value >= 5:
                credit_score += 8
            elif value < 2:
                credit_score -= 14
            if trend == "up":
                credit_score += 4
            elif trend == "down":
                credit_score -= 4
        gap = values.get("cn_m1_m2_gap")
        if gap:
            value, trend = gap
            if value >= 0:
                credit_score += 16
            elif value >= -3:
                credit_score += 6
            elif value < -6:
                credit_score -= 18
            else:
                credit_score -= 8
            if trend == "up":
                credit_score += 5
            elif trend == "down":
                credit_score -= 5
        lpr = values.get("cn_lpr_1y")
        if lpr:
            value, trend = lpr
            if trend == "down":
                credit_score += 8
            elif trend == "up":
                credit_score -= 8
            if value <= 3.0:
                credit_score += 4

        property_score = 50.0
        house = values.get("cn_house_price")
        if house:
            value, trend = house
            if value >= 100:
                property_score += 8
            elif value < 98:
                property_score -= 12
            if trend == "up":
                property_score += 5
            elif trend == "down":
                property_score -= 5
        estate = values.get("cn_real_estate_index")
        if estate:
            value, trend = estate
            if value >= 100:
                property_score += 12
            elif value >= 95:
                property_score += 4
            elif value < 92:
                property_score -= 14
            else:
                property_score -= 6
            if trend == "up":
                property_score += 5
            elif trend == "down":
                property_score -= 5

        price_score = 35.0
        ppi = values.get("cn_ppi_yoy")
        if ppi:
            value, trend = ppi
            if value >= 5:
                price_score += 30
            elif value >= 2:
                price_score += 20
            elif value >= 0:
                price_score += 10
            elif value < -3:
                price_score -= 8
            if trend == "up":
                price_score += 8
            elif trend == "down":
                price_score -= 5
        cpi = values.get("cn_cpi_yoy")
        if cpi:
            value, trend = cpi
            if value >= 3:
                price_score += 20
            elif value >= 2:
                price_score += 12
            elif value >= 1:
                price_score += 5
            elif value < 0:
                price_score -= 8
            if trend == "up":
                price_score += 6
            elif trend == "down":
                price_score -= 4

        growth_score = growth_score * 0.55 + max(0.0, min(100.0, credit_score)) * 0.30 + max(0.0, min(100.0, property_score)) * 0.15
        inflation_score = price_score
        growth_score = max(0.0, min(100.0, growth_score))
        inflation_score = max(0.0, min(100.0, inflation_score))
        growth_trend = "up" if growth_score >= 55 else "down" if growth_score < 45 else "flat"
        inflation_trend = "up" if inflation_score >= 55 else "down" if inflation_score < 45 else "flat"
        return growth_score, inflation_score, growth_trend, inflation_trend

    @classmethod
    def _score_us_cycle(cls, indicators: list[MacroIndicator]) -> tuple[float, float, str, str]:
        values = cls._indicator_value_map(indicators)

        growth_score = 50.0
        pmi = values.get("us_pmi")
        if pmi:
            value, trend = pmi
            if value >= 55:
                growth_score += 22
            elif value >= 52:
                growth_score += 16
            elif value >= 50:
                growth_score += 8
            elif value < 48:
                growth_score -= 18
            if trend == "up":
                growth_score += 6
            elif trend == "down":
                growth_score -= 4

        nonfarm = values.get("us_nonfarm")
        if nonfarm:
            value, trend = nonfarm
            if value >= 15:
                growth_score += 16
            elif value >= 8:
                growth_score += 10
            elif value >= 3:
                growth_score += 4
            elif value < 0:
                growth_score -= 18
            if trend == "up":
                growth_score += 4
            elif trend == "down":
                growth_score -= 4

        unemployment = values.get("us_unemployment_rate")
        if unemployment:
            value, trend = unemployment
            if value <= 4.0:
                growth_score += 14
            elif value <= 4.5:
                growth_score += 8
            elif value >= 5.5:
                growth_score -= 18
            elif value >= 5.0:
                growth_score -= 10
            if trend == "up":
                growth_score -= 4
            elif trend == "down":
                growth_score += 4

        inflation_score = 35.0
        cpi = values.get("us_cpi_yoy")
        if cpi:
            value, trend = cpi
            if value >= 4.0:
                inflation_score += 28
            elif value >= 3.0:
                inflation_score += 22
            elif value >= 2.5:
                inflation_score += 14
            elif value <= 1.5:
                inflation_score -= 12
            if trend == "up":
                inflation_score += 8
            elif trend == "down":
                inflation_score -= 4

        pce = values.get("us_pce")
        if pce:
            value, trend = pce
            if value >= 3.5:
                inflation_score += 26
            elif value >= 3.0:
                inflation_score += 22
            elif value >= 2.5:
                inflation_score += 16
            elif value <= 2.0:
                inflation_score -= 8
            if trend == "up":
                inflation_score += 8
            elif trend == "down":
                inflation_score -= 4

        fed_rate = values.get("us_fed_rate")
        if fed_rate:
            value, trend = fed_rate
            if value >= 5.0:
                inflation_score += 16
            elif value >= 4.0:
                inflation_score += 12
            elif value <= 2.5:
                inflation_score -= 6
            if trend == "up":
                inflation_score += 5
            elif trend == "down":
                inflation_score -= 5

        ten_year = values.get("us_10y_yield")
        if ten_year:
            value, trend = ten_year
            if value >= 4.5:
                inflation_score += 12
            elif value >= 4.0:
                inflation_score += 8
            elif value <= 3.0:
                inflation_score -= 5
            if trend == "up":
                inflation_score += 4
            elif trend == "down":
                inflation_score -= 3

        growth_score = max(0.0, min(100.0, growth_score))
        inflation_score = max(0.0, min(100.0, inflation_score))
        growth_trend = "up" if growth_score >= 55 else "down" if growth_score < 45 else "flat"
        inflation_trend = "up" if inflation_score >= 55 else "down" if inflation_score < 45 else "flat"
        return growth_score, inflation_score, growth_trend, inflation_trend

    @staticmethod
    def _phase(growth_score: float, inflation_score: float) -> str:
        if growth_score >= 50 and inflation_score < 50:
            return "recovery"
        if growth_score >= 50 and inflation_score >= 50:
            return "overheating"
        if growth_score < 50 and inflation_score >= 50:
            return "stagflation"
        return "recession"

    @staticmethod
    def _dca_impact(cycle_phase: str, region: str = "cn") -> str:
        region_prefix = {
            "cn": "中国宏观",
            "us": "美国宏观",
            "global": "全球流动性",
        }.get(region, "宏观")
        impact = {
            "recovery": f"{region_prefix}自动判断为复苏/风险友好，权益风险预算可适度提高，绿灯可按常规或增强倍率执行。",
            "overheating": f"{region_prefix}自动判断为过热/压力上行，避免追高，绿灯仍可执行但建议降低增强倍率上限。",
            "stagflation": f"{region_prefix}自动判断为滞涨/压力偏高，权益风险预算应下调，黄灯偏观察，深绿/绿灯也应小额分批。",
            "recession": f"{region_prefix}自动判断为衰退/风险偏弱，控制总仓位，红绿灯只作为低位分批观察信号。",
        }
        return impact.get(cycle_phase, "宏观状态不明确，红绿灯策略维持默认倍率。")

    @classmethod
    async def build_cycle_state(cls, session: AsyncSession, region: str = "cn", indicators: list[MacroIndicator] | None = None) -> MacroCycleState:
        if indicators is None:
            indicators = await cls.latest_indicators(session, region=region)
        indicators = [item for item in indicators if item.region == region]
        if region == "cn":
            growth_score, inflation_score, growth_trend, inflation_trend = cls._score_cn_cycle(indicators)
        elif region == "us":
            growth_score, inflation_score, growth_trend, inflation_trend = cls._score_us_cycle(indicators)
        elif region == "global":
            growth_score, growth_trend = cls._score_categories(indicators, ("risk", "currency"), region)
            inflation_score, inflation_trend = cls._score_category(indicators, "inflation", region)
        else:
            growth_score, growth_trend = cls._score_category(indicators, "growth", region)
            inflation_score, inflation_trend = cls._score_category(indicators, "inflation", region)
        phase = cls._phase(growth_score, inflation_score)
        confidence = min(95.0, 45.0 + len(indicators) * 10.0)
        names = "、".join(item.indicator_name for item in indicators[:5])
        state = MacroCycleState(
            region=region,
            cycle_phase=phase,
            growth_score=Decimal(str(round(growth_score, 2))),
            inflation_score=Decimal(str(round(inflation_score, 2))),
            growth_trend=growth_trend,
            inflation_trend=inflation_trend,
            confidence=Decimal(str(round(confidence, 2))),
            summary=f"自动采集 {len(indicators)} 个宏观指标生成判断。主要指标：{names or '暂无'}。",
            dca_impact=cls._dca_impact(phase, region),
            source_note=f"自动采集 AkShare · {region}",
            source_type="auto",
            override_until=None,
            observed_at=now_in_utc_naive(),
        )
        session.add(state)
        await session.flush()
        return state

    @classmethod
    async def refresh(cls, session: AsyncSession, region: str | None = None) -> tuple[MacroCycleState | None, list[MacroIndicator], list[str]]:
        indicators, errors = await cls.collect_indicators(session, region=region)
        if not indicators:
            return None, indicators, errors
        states: list[MacroCycleState] = []
        for region in sorted({item.region for item in indicators}):
            region_indicators = [item for item in indicators if item.region == region]
            if region_indicators:
                states.append(await cls.build_cycle_state(session, region=region, indicators=region_indicators))
        primary_state = next((state for state in states if state.region == (region or "cn")), states[0] if states else None)
        return primary_state, indicators, errors

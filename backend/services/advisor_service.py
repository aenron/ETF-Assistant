import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Portfolio, AdviceLog, EtfInfo
from schemas.advice import AdviceResponse, AdviceLogResponse, AccountAnalysisResponse, PeriodAdvice
from schemas.portfolio import PortfolioWithMarket
from config import settings
from services.market_service import MarketService
from services.portfolio_service import PortfolioService
from services.llm import BaseLLMClient, OpenAIClient, DeepSeekClient, GeminiClient, QwenClient


class AdvisorService:
    """智能决策服务"""

    ACCOUNT_ANALYSIS_CODE = "ACCOUNT"
    ACCOUNT_ANALYSIS_NAME = "账户分析"
    SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
    ADVICE_CONCURRENCY = 4

    _llm_client: Optional[BaseLLMClient] = None
    
    @classmethod
    def get_llm_client(cls) -> BaseLLMClient:
        """获取LLM客户端（单例）"""
        if cls._llm_client is None:
            if settings.llm_provider == "openai":
                cls._llm_client = OpenAIClient(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                    model=settings.openai_model,
                )
            elif settings.llm_provider == "deepseek":
                cls._llm_client = DeepSeekClient(
                    api_key=settings.deepseek_api_key,
                    base_url=settings.deepseek_base_url,
                    model=settings.deepseek_model,
                )
            elif settings.llm_provider == "gemini":
                cls._llm_client = GeminiClient(
                    api_key=settings.gemini_api_key,
                    model=settings.gemini_model,
                    enable_grounding=settings.gemini_enable_grounding,
                )
            elif settings.llm_provider == "qwen":
                cls._llm_client = QwenClient(
                    api_key=settings.qwen_api_key,
                    model=settings.qwen_model,
                    enable_search=settings.qwen_enable_search,
                )
            else:
                raise ValueError(f"不支持的LLM提供商: {settings.llm_provider}")
        return cls._llm_client
    
    @staticmethod
    def build_prompt(
        etf_code: str,
        etf_name: str,
        shares: Decimal,
        cost_price: Decimal,
        current_price: Decimal,
        pnl_pct: Decimal,
        holding_days: Optional[int],
        kline_summary: str,
        indicators: dict,
    ) -> str:
        """构造LLM Prompt"""
        return f"""你是一名专业的ETF投资顾问。请根据以下信息给出投资建议。

## 品种信息
- 代码: {etf_code}, 名称: {etf_name}

## 持仓状态
- 份额: {shares}, 成本价: {cost_price:.4f}
- 当前价: {current_price:.4f}, 浮动盈亏: {pnl_pct:.2f}%
- 持仓天数: {holding_days or '未知'}

## 近期行情 (最近10个交易日)
{kline_summary}

## 技术指标
- MA5={indicators.get('ma5', 'N/A')}, MA10={indicators.get('ma10', 'N/A')}, MA20={indicators.get('ma20', 'N/A')}
- MA60={indicators.get('ma60', 'N/A')}, MA120={indicators.get('ma120', 'N/A')}, MA250={indicators.get('ma250', 'N/A')}
- RSI(14)={indicators.get('rsi', 'N/A')}
- MACD: DIF={indicators.get('dif', 'N/A')}, DEA={indicators.get('dea', 'N/A')}, 柱={indicators.get('macd_bar', 'N/A')}
- 20日区间: 高点={indicators.get('high_20', 'N/A')}, 低点={indicators.get('low_20', 'N/A')}
- 60日区间: 高点={indicators.get('high_60', 'N/A')}, 低点={indicators.get('low_60', 'N/A')}
- 120日高点={indicators.get('high_120', 'N/A')}, 250日高点={indicators.get('high_250', 'N/A')}
- 距60日高点回撤={indicators.get('drawdown_60', 'N/A')}%, 距250日高点回撤={indicators.get('drawdown_250', 'N/A')}%
- 20日波动率={indicators.get('volatility_20', 'N/A')}%, 60日波动率={indicators.get('volatility_60', 'N/A')}%

请综合考虑技术面、基本面、政策面和市场情绪，并通过模型自带的联网搜索能力主动搜索最新的相关新闻和政策消息，给出投资建议。

输出要求：
1. 给出一个顶层主决策，格式上必须包含:
   - main_judgment: 一句话主判断，建议写成“中期继续持有，短期不追高”这类可执行结论，50字以内
   - action: 最终执行动作，必须是 "buy" / "sell" / "hold" / "add" / "reduce" 之一
   - why: 2到3条最关键依据，必须体现“因为哪些技术面/位置/波动信号，所以给出这个动作”
   - news_basis: 0到2条和 ETF 相关的新闻依据，没有就返回空数组
   - policy_basis: 0到2条和政策相关的依据，没有就返回空数组
2. 同时给出 short_term、medium_term、long_term 三个周期的建议
3. 每个周期都包含:
   - advice_type: 必须是 "buy" / "sell" / "hold" / "add" / "reduce" 之一
   - action: 对应周期下的具体动作描述，20字以内，例如“观望等待回踩”“继续持有”“分批加仓”
   - conclusion: 一句话结论，60字以内
   - signals: 2到4条核心依据，优先引用均线、RSI、MACD、区间位置、回撤、波动率等已提供指标
   - risks: 1到2条主要风险，避免空泛表述
   - confidence: 0-100之间的整数
4. short_term 更关注 1-10 个交易日的节奏和短线波动
5. medium_term 更关注 1-3 个月趋势，作为主决策
6. long_term 更关注 3 个月以上趋势、回撤和配置价值
7. 三个周期的结论必须体现时间维度差异，不要重复同一句话
8. 顶层 main_judgment / action / why 必须和 medium_term 保持一致，形成“结论 -> 依据 -> 动作”的闭环
9. news_basis 和 policy_basis 必须来自模型联网搜索到的真实最新信息；如果当前模型不支持联网搜索或未检索到可靠结果，就返回空数组，不要编造
10. 输出要直接、结构化，不要写额外解释文字

请直接输出JSON对象，不要添加任何markdown标记或代码块符号:
{{
  "main_judgment": "一句话主判断",
  "action": "hold",
  "why": ["关键依据1", "关键依据2"],
  "news_basis": ["相关新闻依据"],
  "policy_basis": ["政策依据"],
  "short_term": {{"advice_type": "操作建议", "action": "具体动作", "conclusion": "一句话结论", "signals": ["依据1", "依据2"], "risks": ["风险1"], "confidence": 置信度数值}},
  "medium_term": {{"advice_type": "操作建议", "action": "具体动作", "conclusion": "一句话结论", "signals": ["依据1", "依据2"], "risks": ["风险1"], "confidence": 置信度数值}},
  "long_term": {{"advice_type": "操作建议", "action": "具体动作", "conclusion": "一句话结论", "signals": ["依据1", "依据2"], "risks": ["风险1"], "confidence": 置信度数值}}
}}"""

    @staticmethod
    def enrich_horizon_indicators(kline_data: list, indicators) -> dict:
        closes = [float(item.close_price) for item in kline_data]
        highs = [float(item.high_price) for item in kline_data]
        lows = [float(item.low_price) for item in kline_data]

        def avg_last(values: list[float], days: int):
            return round(sum(values[-days:]) / days, 4) if len(values) >= days else None

        def max_last(values: list[float], days: int):
            return round(max(values[-days:]), 4) if len(values) >= days else None

        def min_last(values: list[float], days: int):
            return round(min(values[-days:]), 4) if len(values) >= days else None

        def drawdown_from_high(days: int):
            if len(closes) < days:
                return None
            high = max(highs[-days:])
            current = closes[-1]
            return round((current - high) / high * 100, 2) if high else None

        def annualized_volatility(days: int):
            if len(closes) < days + 1:
                return None
            returns = []
            sample = closes[-(days + 1):]
            for prev, curr in zip(sample[:-1], sample[1:]):
                if prev:
                    returns.append((curr - prev) / prev)
            if len(returns) < 2:
                return None
            mean = sum(returns) / len(returns)
            variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
            return round((variance ** 0.5) * (252 ** 0.5) * 100, 2)

        return {
            'ma5': indicators.ma5,
            'ma10': indicators.ma10,
            'ma20': indicators.ma20,
            'ma60': avg_last(closes, 60),
            'ma120': avg_last(closes, 120),
            'ma250': avg_last(closes, 250),
            'rsi': indicators.rsi14,
            'dif': indicators.macd_dif,
            'dea': indicators.macd_dea,
            'macd_bar': indicators.macd_histogram,
            'high_20': max_last(highs, 20),
            'low_20': min_last(lows, 20),
            'high_60': max_last(highs, 60),
            'low_60': min_last(lows, 60),
            'high_120': max_last(highs, 120),
            'high_250': max_last(highs, 250),
            'drawdown_60': drawdown_from_high(60),
            'drawdown_250': drawdown_from_high(250),
            'volatility_20': annualized_volatility(20),
            'volatility_60': annualized_volatility(60),
        }

    @staticmethod
    def parse_period_advice(result_json: dict, key: str) -> PeriodAdvice:
        data = result_json.get(key) or {}
        signals = data.get("signals", [])
        risks = data.get("risks", [])
        if not isinstance(signals, list):
            signals = []
        if not isinstance(risks, list):
            risks = []
        return PeriodAdvice(
            advice_type=data.get("advice_type", "hold"),
            action=data.get("action", data.get("conclusion", data.get("reason", "继续观察"))),
            conclusion=data.get("conclusion", data.get("reason", "暂无建议")),
            signals=[str(item) for item in signals[:4] if str(item).strip()],
            risks=[str(item) for item in risks[:2] if str(item).strip()],
            confidence=float(data.get("confidence", 50)),
        )

    @staticmethod
    def parse_basis_items(result_json: dict, key: str, limit: int = 3) -> List[str]:
        value = result_json.get(key, [])
        if isinstance(value, list):
            return [str(item) for item in value[:limit] if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    @staticmethod
    def format_multi_horizon_reason(
        main_judgment: str,
        action: str,
        why: List[str],
        news_basis: List[str],
        policy_basis: List[str],
        short_term: PeriodAdvice,
        medium_term: PeriodAdvice,
        long_term: PeriodAdvice,
    ) -> str:
        why_text = "；".join(why) or "暂无"
        news_text = "；".join(news_basis) or "暂无"
        policy_text = "；".join(policy_basis) or "暂无"
        return (
            f"主判断：{main_judgment}\n"
            f"执行动作：{action}\n"
            f"关键依据：{why_text}\n"
            f"新闻依据：{news_text}\n"
            f"政策依据：{policy_text}\n\n"
            f"【短期】{short_term.advice_type}（{short_term.confidence:.0f}%）\n"
            f"动作：{short_term.action}\n"
            f"结论：{short_term.conclusion}\n"
            f"信号：{'；'.join(short_term.signals) or '暂无'}\n"
            f"风险：{'；'.join(short_term.risks) or '暂无'}\n\n"
            f"【中期】{medium_term.advice_type}（{medium_term.confidence:.0f}%）\n"
            f"动作：{medium_term.action}\n"
            f"结论：{medium_term.conclusion}\n"
            f"信号：{'；'.join(medium_term.signals) or '暂无'}\n"
            f"风险：{'；'.join(medium_term.risks) or '暂无'}\n\n"
            f"【长期】{long_term.advice_type}（{long_term.confidence:.0f}%）\n"
            f"动作：{long_term.action}\n"
            f"结论：{long_term.conclusion}\n"
            f"信号：{'；'.join(long_term.signals) or '暂无'}\n"
            f"风险：{'；'.join(long_term.risks) or '暂无'}"
        )

    @staticmethod
    def build_account_analysis_prompt(
        portfolio_summary_text: str,
        holdings_text: str,
        account_balance: float,
    ) -> str:
        """构造账户级分析 Prompt"""
        return f"""你是一名专业的ETF投资顾问。请根据当前账户整体情况，给出账户层面的投资建议。

## 账户概览
{portfolio_summary_text}

## 持仓明细
{holdings_text}

## 可用资金
- 账户金额: {account_balance:.2f} 元

请重点分析：
1. 当前整体仓位是否偏高、偏低或合理
2. 当前持仓是否过于集中，是否需要分散或再平衡
3. 哪些方向应该继续持有，哪些方向应该减仓或观察
4. 接下来1-3条最重要的账户操作建议

输出要求：
1. summary: 对当前账户状态的总体判断，120字以内
2. position_advice: 对整体仓位的建议，80字以内
3. rebalance_advice: 对结构调整/分散配置的建议，120字以内
4. risk_level: 风险等级，必须是 "low" / "medium" / "high" 之一
5. key_actions: 1到3条具体行动建议的字符串数组
6. confidence: 0-100之间的整数

请直接输出JSON对象，不要添加markdown标记或代码块:
{{"summary":"...","position_advice":"...","rebalance_advice":"...","risk_level":"medium","key_actions":["..."],"confidence":75}}"""

    @staticmethod
    def format_account_summary(
        portfolios: List[PortfolioWithMarket],
        total_market_value: float,
        total_cost: float,
        total_pnl: float,
        total_pnl_pct: float,
        account_balance: float,
        category_distribution: dict,
    ) -> str:
        """格式化账户概览"""
        total_assets = total_market_value + account_balance
        cash_ratio = (account_balance / total_assets * 100) if total_assets > 0 else 0.0
        invested_ratio = (total_market_value / total_assets * 100) if total_assets > 0 else 0.0
        category_text = "、".join(
            f"{name}:{value / total_market_value * 100:.1f}%"
            for name, value in sorted(category_distribution.items(), key=lambda item: item[1], reverse=True)
            if total_market_value > 0
        ) or "暂无分类数据"

        return "\n".join([
            f"- 持仓数量: {len(portfolios)}",
            f"- 持仓市值: {total_market_value:.2f} 元",
            f"- 总成本: {total_cost:.2f} 元",
            f"- 总盈亏: {total_pnl:.2f} 元 ({total_pnl_pct:.2f}%)",
            f"- 账户总资产(持仓+账户金额): {total_assets:.2f} 元",
            f"- 现金占比: {cash_ratio:.2f}%",
            f"- 持仓占比: {invested_ratio:.2f}%",
            f"- 分类分布: {category_text}",
        ])

    @staticmethod
    def format_account_holdings(portfolios: List[PortfolioWithMarket], total_market_value: float) -> str:
        """格式化持仓明细"""
        if not portfolios:
            return "暂无持仓"

        lines = []
        for portfolio in portfolios:
            market_value = portfolio.market_value or 0.0
            weight = (market_value / total_market_value * 100) if total_market_value > 0 else 0.0
            category = MarketService._guess_category(portfolio.etf_name or "")
            lines.append(
                f"- {portfolio.etf_code} {portfolio.etf_name or ''}: "
                f"市值 {market_value:.2f} 元, 权重 {weight:.2f}%, "
                f"盈亏 {portfolio.pnl or 0.0:.2f} 元 ({portfolio.pnl_pct or 0.0:.2f}%), "
                f"分类 {category}, 持仓天数 {portfolio.holding_days if portfolio.holding_days is not None else '未知'}"
            )
        return "\n".join(lines)

    @staticmethod
    def format_account_analysis_reason(analysis: AccountAnalysisResponse) -> str:
        """格式化账户分析历史文本"""
        actions_text = "\n".join(
            f"{index + 1}. {action}" for index, action in enumerate(analysis.key_actions)
        ) or "暂无具体操作建议"
        return "\n".join([
            f"总体判断：{analysis.summary}",
            f"仓位建议：{analysis.position_advice}",
            f"调仓建议：{analysis.rebalance_advice}",
            f"风险等级：{analysis.risk_level}",
            "关键操作：",
            actions_text,
        ])

    @classmethod
    def now_in_shanghai(cls) -> datetime:
        """获取北京时间"""
        return datetime.now(cls.SHANGHAI_TZ)

    @classmethod
    def ensure_shanghai_datetime(cls, value: Optional[datetime]) -> datetime:
        """将时间统一为北京时间"""
        if value is None:
            return cls.now_in_shanghai()
        if value.tzinfo is None:
            return value.replace(tzinfo=ZoneInfo("UTC")).astimezone(cls.SHANGHAI_TZ)
        return value.astimezone(cls.SHANGHAI_TZ)

    @classmethod
    def parse_account_analysis_reason(
        cls,
        reason: Optional[str],
        confidence: Optional[Decimal],
        created_at: Optional[datetime],
    ) -> AccountAnalysisResponse:
        """从历史文本恢复账户分析结构"""
        text = reason or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        key_actions: List[str] = []
        in_actions = False
        data = {
            "summary": "",
            "position_advice": "",
            "rebalance_advice": "",
            "risk_level": "medium",
        }

        for line in lines:
            if line == "关键操作：":
                in_actions = True
                continue

            if in_actions:
                action = line
                if ". " in action:
                    action = action.split(". ", 1)[1]
                key_actions.append(action)
                continue

            if line.startswith("总体判断："):
                data["summary"] = line.removeprefix("总体判断：").strip()
            elif line.startswith("仓位建议："):
                data["position_advice"] = line.removeprefix("仓位建议：").strip()
            elif line.startswith("调仓建议："):
                data["rebalance_advice"] = line.removeprefix("调仓建议：").strip()
            elif line.startswith("风险等级："):
                risk = line.removeprefix("风险等级：").strip().lower()
                data["risk_level"] = risk if risk in {"low", "medium", "high"} else "medium"

        return AccountAnalysisResponse(
            summary=data["summary"] or "暂无账户分析摘要",
            position_advice=data["position_advice"] or "暂无仓位建议",
            rebalance_advice=data["rebalance_advice"] or "暂无调仓建议",
            risk_level=data["risk_level"],
            key_actions=key_actions[:3],
            confidence=float(confidence) if confidence is not None else 0,
            created_at=cls.ensure_shanghai_datetime(created_at),
        )
    
    @staticmethod
    def format_kline_summary(kline_data: List) -> str:
        """格式化K线摘要"""
        if not kline_data:
            return "无数据"
        
        lines = []
        for item in kline_data[-10:]:
            lines.append(
                f"{item.trade_date}: 开{item.open_price:.3f} "
                f"收{item.close_price:.3f} "
                f"高{item.high_price:.3f} "
                f"低{item.low_price:.3f} "
                f"涨跌{item.change_pct:.2f}%"
            )
        return "\n".join(lines)

    @classmethod
    async def _build_advice_payload(
        cls,
        p: Portfolio,
        quote,
        llm: BaseLLMClient,
    ) -> dict:
        """构建单个持仓建议结果，不在并发任务中访问数据库会话。"""
        market_value = float(p.shares) * quote.price
        cost = float(p.shares) * float(p.cost_price)
        pnl = market_value - cost
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0

        holding_days = None
        if p.buy_date:
            holding_days = (date.today() - p.buy_date).days

        kline_data = await MarketService.get_history_kline(p.etf_code, days=250)
        kline_summary = cls.format_kline_summary(kline_data)
        indicators = MarketService.calculate_technical_indicators(kline_data)
        indicators_dict = cls.enrich_horizon_indicators(kline_data, indicators)

        prompt = cls.build_prompt(
            etf_code=p.etf_code,
            etf_name=quote.name,
            shares=p.shares,
            cost_price=p.cost_price,
            current_price=quote.price,
            pnl_pct=pnl_pct,
            holding_days=holding_days,
            kline_summary=kline_summary,
            indicators=indicators_dict,
        )

        try:
            result_json = await llm.chat_json(prompt)
            if "error" in result_json:
                raw_reason = f"AI分析结果（JSON解析失败）:\n{result_json.get('raw', '无响应内容')}"
                short_term = PeriodAdvice(advice_type="hold", action="继续观察", conclusion=raw_reason, signals=[], risks=["返回格式异常"], confidence=30)
                medium_term = PeriodAdvice(advice_type="hold", action="继续观察", conclusion=raw_reason, signals=[], risks=["返回格式异常"], confidence=30)
                long_term = PeriodAdvice(advice_type="hold", action="继续观察", conclusion=raw_reason, signals=[], risks=["返回格式异常"], confidence=30)
                main_judgment = raw_reason
                action = "hold"
                why = ["模型返回格式异常，未能提炼出稳定依据"]
                news_basis = []
                policy_basis = []
            else:
                short_term = cls.parse_period_advice(result_json, "short_term")
                medium_term = cls.parse_period_advice(result_json, "medium_term")
                long_term = cls.parse_period_advice(result_json, "long_term")
                main_judgment = str(result_json.get("main_judgment", medium_term.conclusion)).strip() or medium_term.conclusion
                action = str(result_json.get("action", medium_term.advice_type)).strip() or medium_term.advice_type
                why = cls.parse_basis_items(result_json, "why", limit=3)
                news_basis = cls.parse_basis_items(result_json, "news_basis", limit=2)
                policy_basis = cls.parse_basis_items(result_json, "policy_basis", limit=2)
        except Exception as e:
            short_term = PeriodAdvice(advice_type="hold", action="继续观察", conclusion=f"LLM调用失败: {str(e)}", signals=[], risks=["模型调用失败"], confidence=0)
            medium_term = PeriodAdvice(advice_type="hold", action="继续观察", conclusion=f"LLM调用失败: {str(e)}", signals=[], risks=["模型调用失败"], confidence=0)
            long_term = PeriodAdvice(advice_type="hold", action="继续观察", conclusion=f"LLM调用失败: {str(e)}", signals=[], risks=["模型调用失败"], confidence=0)
            main_judgment = medium_term.conclusion
            action = medium_term.advice_type
            why = ["模型调用失败，暂时无法生成关键依据"]
            news_basis = []
            policy_basis = []

        advice_type = medium_term.advice_type
        reason = cls.format_multi_horizon_reason(
            main_judgment, action, why, news_basis, policy_basis, short_term, medium_term, long_term
        )
        confidence = Decimal(str(medium_term.confidence))

        return {
            "portfolio": p,
            "quote": quote,
            "advice_type": advice_type,
            "main_judgment": main_judgment,
            "action": action,
            "why": why,
            "news_basis": news_basis,
            "policy_basis": policy_basis,
            "reason": reason,
            "confidence": confidence,
            "short_term": short_term,
            "medium_term": medium_term,
            "long_term": long_term,
            "pnl_pct": pnl_pct,
        }
    
    @classmethod
    async def generate_advice(
        cls,
        session: AsyncSession,
        etf_codes: Optional[List[str]] = None,
        user_id: Optional[int] = None,
    ) -> List[AdviceResponse]:
        """生成投资建议"""
        if user_id is None:
            raise ValueError("generate_advice requires user_id")

        # 获取持仓
        query = select(Portfolio).where(Portfolio.user_id == user_id)
        if etf_codes:
            query = query.where(Portfolio.etf_code.in_(etf_codes))
        
        result = await session.execute(query)
        portfolios = result.scalars().all()
        
        if not portfolios:
            return []
        
        # 获取持仓ETF代码列表
        portfolio_codes = [p.etf_code for p in portfolios]
        
        # 获取实时行情（使用新的异步方法）
        quotes = await MarketService.get_quotes_for_codes(portfolio_codes)
        
        llm = cls.get_llm_client()
        semaphore = asyncio.Semaphore(cls.ADVICE_CONCURRENCY)

        async def analyze_portfolio(p: Portfolio) -> Optional[dict]:
            quote = quotes.get(p.etf_code)
            if not quote:
                return None
            async with semaphore:
                return await cls._build_advice_payload(p, quote, llm)

        advice_payloads = [
            payload
            for payload in await asyncio.gather(*(analyze_portfolio(p) for p in portfolios))
            if payload is not None
        ]

        advices = []
        for payload in advice_payloads:
            p = payload["portfolio"]
            quote = payload["quote"]
            log = AdviceLog(
                user_id=user_id,
                etf_code=p.etf_code,
                advice_type=payload["advice_type"],
                reason=payload["reason"],
                confidence=payload["confidence"],
                llm_provider=settings.llm_provider,
                llm_model=llm.model if hasattr(llm, 'model') else None,
            )
            session.add(log)

            advices.append(AdviceResponse(
                etf_code=p.etf_code,
                etf_name=quote.name,
                advice_type=payload["advice_type"],
                main_judgment=payload["main_judgment"],
                action=payload["action"],
                why=payload["why"],
                news_basis=payload["news_basis"],
                policy_basis=payload["policy_basis"],
                reason=payload["reason"],
                confidence=payload["confidence"],
                short_term=payload["short_term"],
                medium_term=payload["medium_term"],
                long_term=payload["long_term"],
                current_price=quote.price,
                pnl_pct=payload["pnl_pct"],
            ))
        
        await session.flush()
        return advices
    
    @classmethod
    async def generate_advice_for_portfolio(
        cls,
        session: AsyncSession,
        portfolio_id: int,
        user_id: Optional[int] = None,
    ) -> Optional[AdviceResponse]:
        """生成单个持仓的投资建议"""
        if user_id is None:
            raise ValueError("generate_advice_for_portfolio requires user_id")

        # 获取持仓
        query = select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user_id,
        )
        
        result = await session.execute(query)
        p = result.scalar_one_or_none()
        if not p:
            return None
        
        # 获取实时行情
        quotes = await MarketService.get_quotes_for_codes([p.etf_code])
        quote = quotes.get(p.etf_code)
        if not quote:
            return None
        
        llm = cls.get_llm_client()
        payload = await cls._build_advice_payload(p, quote, llm)
        
        # 保存日志
        log = AdviceLog(
            user_id=user_id,
            etf_code=p.etf_code,
            advice_type=payload["advice_type"],
            reason=payload["reason"],
            confidence=payload["confidence"],
            llm_provider=settings.llm_provider,
            llm_model=llm.model if hasattr(llm, 'model') else None,
        )
        session.add(log)
        await session.flush()
        
        return AdviceResponse(
            etf_code=p.etf_code,
            etf_name=quote.name,
            advice_type=payload["advice_type"],
            main_judgment=payload["main_judgment"],
            action=payload["action"],
            why=payload["why"],
            news_basis=payload["news_basis"],
            policy_basis=payload["policy_basis"],
            reason=payload["reason"],
            confidence=payload["confidence"],
            short_term=payload["short_term"],
            medium_term=payload["medium_term"],
            long_term=payload["long_term"],
            current_price=quote.price,
            pnl_pct=payload["pnl_pct"],
        )
    
    @classmethod
    async def get_history(
        cls,
        session: AsyncSession, 
        limit: int = 50,
        user_id: Optional[int] = None,
    ) -> List[AdviceLogResponse]:
        """获取历史建议记录"""
        if user_id is None:
            raise ValueError("get_history requires user_id")

        query = (
            select(AdviceLog, EtfInfo.name.label("etf_name"))
            .where(AdviceLog.user_id == user_id)
            .outerjoin(EtfInfo, AdviceLog.etf_code == EtfInfo.code)
            .order_by(AdviceLog.created_at.desc())
        )
        query = query.limit(limit)
        
        result = await session.execute(query)
        rows = result.all()
        
        # 收集需要补充名称的 ETF 代码
        etf_codes_to_fetch = set()
        for log, etf_name in rows:
            if (
                not etf_name
                and log.etf_code
                and log.etf_code != cls.ACCOUNT_ANALYSIS_CODE
            ):
                etf_codes_to_fetch.add(log.etf_code)
        
        # 从实时行情获取缺失的 ETF 名称
        etf_names_from_market = {}
        if etf_codes_to_fetch:
            try:
                quotes = await MarketService.get_quotes_for_codes(list(etf_codes_to_fetch))
                etf_names_from_market = {code: quote.name for code, quote in quotes.items() if quote.name}
            except Exception as e:
                print(f"[AdvisorService] 从行情获取ETF名称失败: {e}")
        
        return [
            AdviceLogResponse(
                **{c.key: getattr(log, c.key) for c in AdviceLog.__table__.columns},
                etf_name=(
                    cls.ACCOUNT_ANALYSIS_NAME
                    if log.etf_code == cls.ACCOUNT_ANALYSIS_CODE
                    else etf_name or etf_names_from_market.get(log.etf_code, None)
                ),
            )
            for log, etf_name in rows
        ]

    @classmethod
    async def generate_account_analysis(
        cls,
        session: AsyncSession,
        user_id: int,
        account_balance: Optional[Decimal] = None,
    ) -> AccountAnalysisResponse:
        """生成账户级投资建议"""
        portfolios = await PortfolioService.get_with_market(session, user_id=user_id)
        summary = PortfolioService.build_summary_from_portfolios(portfolios)
        available_cash = float(account_balance) if account_balance is not None else 0.0

        if not portfolios:
            analysis = AccountAnalysisResponse(
                summary="当前账户暂无持仓，整体风险暴露较低。",
                position_advice="当前仓位偏低，可先保持观望并逐步建立仓位。",
                rebalance_advice="暂无调仓需求，建议先明确投资目标后再分批配置ETF。",
                risk_level="low",
                key_actions=[
                    "先建立关注ETF清单，避免一次性满仓",
                    "优先从宽基ETF开始分批建仓",
                ],
                confidence=85,
                created_at=cls.now_in_shanghai(),
            )
            session.add(AdviceLog(
                user_id=user_id,
                etf_code=cls.ACCOUNT_ANALYSIS_CODE,
                advice_type="account",
                reason=cls.format_account_analysis_reason(analysis),
                confidence=Decimal(str(analysis.confidence)),
                llm_provider=settings.llm_provider,
                llm_model=None,
            ))
            await session.flush()
            return analysis

        portfolio_summary_text = cls.format_account_summary(
            portfolios=portfolios,
            total_market_value=summary.total_market_value,
            total_cost=summary.total_cost,
            total_pnl=summary.total_pnl,
            total_pnl_pct=summary.total_pnl_pct,
            account_balance=available_cash,
            category_distribution=summary.category_distribution,
        )
        holdings_text = cls.format_account_holdings(portfolios, summary.total_market_value)
        prompt = cls.build_account_analysis_prompt(
            portfolio_summary_text=portfolio_summary_text,
            holdings_text=holdings_text,
            account_balance=available_cash,
        )

        llm = cls.get_llm_client()
        try:
            result_json = await llm.chat_json(prompt)
            key_actions = result_json.get("key_actions", [])
            if not isinstance(key_actions, list):
                key_actions = []

            analysis = AccountAnalysisResponse(
                summary=result_json.get("summary", "当前账户整体结构中性，建议结合风险偏好持续跟踪。"),
                position_advice=result_json.get("position_advice", "当前仓位基本合理，建议分批调整。"),
                rebalance_advice=result_json.get("rebalance_advice", "建议关注持仓集中度，必要时逐步再平衡。"),
                risk_level=result_json.get("risk_level", "medium"),
                key_actions=[str(item) for item in key_actions[:3] if str(item).strip()],
                confidence=float(result_json.get("confidence", 70)),
                created_at=cls.now_in_shanghai(),
            )
            session.add(AdviceLog(
                user_id=user_id,
                etf_code=cls.ACCOUNT_ANALYSIS_CODE,
                advice_type="account",
                reason=cls.format_account_analysis_reason(analysis),
                confidence=Decimal(str(analysis.confidence)),
                llm_provider=settings.llm_provider,
                llm_model=llm.model if hasattr(llm, 'model') else None,
            ))
            await session.flush()
            return analysis
        except Exception as e:
            analysis = AccountAnalysisResponse(
                summary="账户分析暂时失败，建议先根据总仓位和集中度人工复核。",
                position_advice="当前建议暂缓大幅加仓，等待分析恢复后再调整。",
                rebalance_advice=f"LLM调用失败: {str(e)}",
                risk_level="medium",
                key_actions=["稍后重试账户分析", "优先检查高权重持仓的风险集中度"],
                confidence=0,
                created_at=cls.now_in_shanghai(),
            )
            session.add(AdviceLog(
                user_id=user_id,
                etf_code=cls.ACCOUNT_ANALYSIS_CODE,
                advice_type="account",
                reason=cls.format_account_analysis_reason(analysis),
                confidence=Decimal("0"),
                llm_provider=settings.llm_provider,
                llm_model=llm.model if hasattr(llm, 'model') else None,
            ))
            await session.flush()
            return analysis

    @classmethod
    async def get_latest_account_analysis(
        cls,
        session: AsyncSession,
        user_id: int,
    ) -> Optional[AccountAnalysisResponse]:
        """获取最近一次账户级投资建议"""
        result = await session.execute(
            select(AdviceLog)
            .where(
                AdviceLog.user_id == user_id,
                AdviceLog.etf_code == cls.ACCOUNT_ANALYSIS_CODE,
                AdviceLog.advice_type == "account",
            )
            .order_by(AdviceLog.created_at.desc(), AdviceLog.id.desc())
            .limit(1)
        )
        log = result.scalar_one_or_none()
        if not log:
            return None

        return cls.parse_account_analysis_reason(log.reason, log.confidence, log.created_at)

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Portfolio, AdviceLog, EtfInfo
from schemas.advice import AdviceResponse, AdviceLogResponse, AccountAnalysisResponse
from schemas.portfolio import PortfolioWithMarket
from config import settings
from services.market_service import MarketService
from services.portfolio_service import PortfolioService
from services.news_service import NewsService
from services.llm import BaseLLMClient, OpenAIClient, DeepSeekClient, OllamaClient, GeminiClient, QwenClient


class AdvisorService:
    """智能决策服务"""

    ACCOUNT_ANALYSIS_CODE = "ACCOUNT"
    ACCOUNT_ANALYSIS_NAME = "账户分析"
    SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

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
            else:  # ollama
                cls._llm_client = OllamaClient(
                    base_url=settings.ollama_base_url,
                    model=settings.ollama_model,
                )
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
        news_summary: str = "暂无相关新闻",
        policy_news: str = "暂无政策新闻",
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
- RSI(14)={indicators.get('rsi', 'N/A')}
- MACD: DIF={indicators.get('dif', 'N/A')}, DEA={indicators.get('dea', 'N/A')}, 柱={indicators.get('macd_bar', 'N/A')}

## 相关新闻
{news_summary}

## 近期政策
{policy_news}

请综合考虑技术面、基本面、政策面和市场情绪，同时搜索最新的相关新闻和政策消息，给出投资建议。

输出要求：
1. advice_type: 操作建议，必须是以下五个值之一: "buy"(买入), "sell"(卖出), "hold"(持有), "add"(加仓), "reduce"(减仓)
2. reason: 分析理由，200字以内，需结合技术指标和新闻政策分析
3. confidence: 置信度，0-100之间的整数

请直接输出JSON对象，不要添加任何markdown标记或代码块符号:
{{"advice_type": "操作建议", "reason": "分析理由", "confidence": 置信度数值}}"""

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
        advices = []
        
        for p in portfolios:
            quote = quotes.get(p.etf_code)
            if not quote:
                continue
            
            # 计算盈亏
            market_value = float(p.shares) * quote.price
            cost = float(p.shares) * float(p.cost_price)
            pnl = market_value - cost
            pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0
            
            holding_days = None
            if p.buy_date:
                holding_days = (date.today() - p.buy_date).days
            
            # 获取历史K线
            kline_data = MarketService.get_history_kline(p.etf_code, days=60)
            kline_summary = cls.format_kline_summary(kline_data)
            
            # 计算技术指标
            indicators = MarketService.calculate_technical_indicators(kline_data)
            indicators_dict = {
                'ma5': indicators.ma5,
                'ma10': indicators.ma10,
                'ma20': indicators.ma20,
                'rsi': indicators.rsi14,
                'dif': indicators.macd_dif,
                'dea': indicators.macd_dea,
                'macd_bar': indicators.macd_histogram,
            }
            
            # 构造Prompt
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
            
            # 调用LLM
            try:
                result_json = await llm.chat_json(prompt)
                advice_type = result_json.get("advice_type", "hold")
                reason = result_json.get("reason", "无法解析理由")
                confidence = Decimal(str(result_json.get("confidence", 50)))
            except Exception as e:
                advice_type = "hold"
                reason = f"LLM调用失败: {str(e)}"
                confidence = Decimal("0")
            
            # 保存日志
            log = AdviceLog(
                user_id=user_id,
                etf_code=p.etf_code,
                advice_type=advice_type,
                reason=reason,
                confidence=confidence,
                llm_provider=settings.llm_provider,
                llm_model=llm.model if hasattr(llm, 'model') else None,
            )
            session.add(log)
            
            advices.append(AdviceResponse(
                etf_code=p.etf_code,
                etf_name=quote.name,
                advice_type=advice_type,
                reason=reason,
                confidence=confidence,
                current_price=quote.price,
                pnl_pct=pnl_pct,
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
        
        # 计算盈亏
        market_value = float(p.shares) * quote.price
        cost = float(p.shares) * float(p.cost_price)
        pnl = market_value - cost
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0
        
        holding_days = None
        if p.buy_date:
            holding_days = (date.today() - p.buy_date).days
        
        # 获取历史K线
        print(f"[AdvisorService] 开始获取历史K线: {p.etf_code}")
        kline_data = MarketService.get_history_kline(p.etf_code, days=60)
        print(f"[AdvisorService] 获取到 {len(kline_data)} 条K线数据")
        kline_summary = cls.format_kline_summary(kline_data)
        
        # 计算技术指标
        indicators = MarketService.calculate_technical_indicators(kline_data)
        indicators_dict = {
            'ma5': indicators.ma5,
            'ma10': indicators.ma10,
            'ma20': indicators.ma20,
            'rsi': indicators.rsi14,
            'dif': indicators.macd_dif,
            'dea': indicators.macd_dea,
            'macd_bar': indicators.macd_histogram,
        }
        
        # 获取相关新闻和政策
        print(f"[AdvisorService] 获取 {quote.name} 相关新闻...")
        etf_news = NewsService.get_etf_related_news(quote.name, limit=5)
        news_summary = NewsService.format_news_summary(etf_news)
        
        policy_news_list = NewsService.get_policy_news(limit=5)
        policy_news = NewsService.format_news_summary(policy_news_list)
        
        # 构造Prompt
        llm = cls.get_llm_client()
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
            news_summary=news_summary,
            policy_news=policy_news,
        )
        
        # 调用LLM
        try:
            print(f"\n{'='*60}")
            print(f"[AdvisorService] 发送给LLM的Prompt:")
            print(f"{'='*60}")
            print(prompt)
            print(f"{'='*60}\n")
            
            result_json = await llm.chat_json(prompt)
            
            print(f"[AdvisorService] LLM返回结果:")
            print(f"{'='*60}")
            print(f"{result_json}")
            print(f"{'='*60}\n")
            
            # 检查是否有错误
            if "error" in result_json:
                # 解析失败，使用原始响应作为理由
                advice_type = "hold"
                reason = f"AI分析结果（JSON解析失败）:\n{result_json.get('raw', '无响应内容')}"
                confidence = 30
            else:
                advice_type = result_json.get("advice_type", "hold")
                reason = result_json.get("reason", "无法解析理由")
                confidence = float(result_json.get("confidence", 50))
        except Exception as e:
            print(f"[AdvisorService] LLM调用失败: {e}")
            advice_type = "hold"
            reason = f"LLM调用失败: {str(e)}"
            confidence = 0.0
        
        # 保存日志
        log = AdviceLog(
            user_id=user_id,
            etf_code=p.etf_code,
            advice_type=advice_type,
            reason=reason,
            confidence=confidence,
            llm_provider=settings.llm_provider,
            llm_model=llm.model if hasattr(llm, 'model') else None,
        )
        session.add(log)
        await session.flush()
        
        return AdviceResponse(
            etf_code=p.etf_code,
            etf_name=quote.name,
            advice_type=advice_type,
            reason=reason,
            confidence=confidence,
            current_price=quote.price,
            pnl_pct=pnl_pct,
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
        summary = await PortfolioService.get_summary(session, user_id=user_id)
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

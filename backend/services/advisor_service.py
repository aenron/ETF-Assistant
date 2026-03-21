from datetime import date
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Portfolio, AdviceLog
from schemas.advice import AdviceResponse, AdviceLogResponse
from schemas.portfolio import PortfolioWithMarket
from config import settings
from services.market_service import MarketService
from services.portfolio_service import PortfolioService
from services.news_service import NewsService
from services.llm import BaseLLMClient, OpenAIClient, DeepSeekClient, OllamaClient, GeminiClient, QwenClient


class AdvisorService:
    """智能决策服务"""
    
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

请综合考虑技术面、基本面、政策面和市场情绪，如果可以的话，搜索最新的相关消息，给出投资建议。

输出要求：
1. advice_type: 操作建议，必须是以下五个值之一: "buy"(买入), "sell"(卖出), "hold"(持有), "add"(加仓), "reduce"(减仓)
2. reason: 分析理由，200字以内，需结合技术指标和新闻政策分析
3. confidence: 置信度，0-100之间的整数

请直接输出JSON对象，不要添加任何markdown标记或代码块符号:
{{"advice_type": "操作建议", "reason": "分析理由", "confidence": 置信度数值}}"""
    
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
        # 获取持仓
        query = select(Portfolio)
        if user_id:
            query = query.where(Portfolio.user_id == user_id)
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
            indicators = MarketService.calc_technical_indicators(kline_data)
            
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
                indicators=indicators,
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
                etf_code=p.etf_code,
                advice_type=advice_type,
                reason=reason,
                confidence=confidence,
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
        # 获取持仓
        query = select(Portfolio).where(Portfolio.id == portfolio_id)
        if user_id:
            query = query.where(Portfolio.user_id == user_id)
        
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
        kline_data = MarketService.get_history_kline(p.etf_code, days=60)
        kline_summary = cls.format_kline_summary(kline_data)
        
        # 计算技术指标
        indicators = MarketService.calc_technical_indicators(kline_data)
        
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
            indicators=indicators,
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
    
    @staticmethod
    async def get_history(
        session: AsyncSession, 
        limit: int = 50,
        user_id: Optional[int] = None,
    ) -> List[AdviceLogResponse]:
        """获取历史建议记录"""
        query = select(AdviceLog).order_by(AdviceLog.created_at.desc())
        if user_id:
            query = query.where(AdviceLog.user_id == user_id)
        query = query.limit(limit)
        
        result = await session.execute(query)
        logs = result.scalars().all()
        return [AdviceLogResponse.model_validate(log) for log in logs]

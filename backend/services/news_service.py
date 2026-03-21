"""新闻获取服务"""
import os
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import akshare as ak


class NewsService:
    """财经新闻获取服务"""
    
    @classmethod
    def get_market_news(cls, limit: int = 10) -> List[Dict[str, Any]]:
        """获取市场热点新闻"""
        try:
            print("[NewsService] >>> 获取市场热点新闻")
            df = ak.stock_news_em(symbol="财经")
            if df.empty:
                print("[NewsService] <<< 市场新闻为空")
                return []
            
            news_list = []
            for _, row in df.head(limit).iterrows():
                news_list.append({
                    "title": str(row.get("标题", "")),
                    "content": str(row.get("内容", ""))[:200] if row.get("内容") else "",
                    "source": str(row.get("来源", "")),
                    "publish_time": str(row.get("发布时间", "")),
                })
            print(f"[NewsService] <<< 成功获取 {len(news_list)} 条市场新闻")
            return news_list
        except Exception as e:
            print(f"[NewsService] <<< 获取市场新闻失败: {type(e).__name__}: {e}")
            return []
    
    @classmethod
    def get_etf_related_news(cls, etf_name: str, limit: int = 5) -> List[Dict[str, Any]]:
        """获取ETF相关新闻（根据名称关键词）"""
        try:
            # 提取关键词
            keywords = cls._extract_keywords(etf_name)
            print(f"[NewsService] >>> 获取ETF相关新闻: {etf_name}, 关键词: {keywords}")
            
            # 获取新闻
            df = ak.stock_news_em(symbol="财经")
            if df.empty:
                print("[NewsService] <<< 新闻数据为空")
                return []
            
            # 筛选相关新闻
            news_list = []
            for _, row in df.iterrows():
                title = str(row.get("标题", ""))
                content = str(row.get("内容", ""))
                
                # 检查是否包含关键词
                is_related = any(kw in title or kw in content for kw in keywords)
                
                if is_related:
                    news_list.append({
                        "title": title,
                        "content": content[:300] if content else "",
                        "source": str(row.get("来源", "")),
                        "publish_time": str(row.get("发布时间", "")),
                    })
                    
                    if len(news_list) >= limit:
                        break
            
            print(f"[NewsService] <<< 成功获取 {len(news_list)} 条相关新闻")
            return news_list
        except Exception as e:
            print(f"[NewsService] <<< 获取ETF相关新闻失败: {type(e).__name__}: {e}")
            return []
    
    @staticmethod
    def _extract_keywords(etf_name: str) -> List[str]:
        """从ETF名称提取关键词"""
        keywords = []
        
        # 宽基指数
        if "沪深300" in etf_name or "上证50" in etf_name:
            keywords.extend(["大盘", "蓝筹", "A股"])
        elif "中证500" in etf_name or "中证1000" in etf_name:
            keywords.extend(["中盘", "小盘", "成长"])
        elif "创业板" in etf_name:
            keywords.extend(["创业板", "成长", "科技"])
        elif "科创" in etf_name:
            keywords.extend(["科创板", "科技", "创新"])
        
        # 行业主题
        if "医药" in etf_name or "医疗" in etf_name:
            keywords.extend(["医药", "医疗", "生物", "药"])
        elif "芯片" in etf_name or "半导体" in etf_name:
            keywords.extend(["芯片", "半导体", "集成电路"])
        elif "消费" in etf_name or "白酒" in etf_name:
            keywords.extend(["消费", "白酒", "食品", "饮料"])
        elif "新能源" in etf_name or "光伏" in etf_name or "锂电" in etf_name:
            keywords.extend(["新能源", "光伏", "锂电", "电池", "储能"])
        elif "银行" in etf_name or "证券" in etf_name or "券商" in etf_name:
            keywords.extend(["银行", "证券", "券商", "金融"])
        elif "军工" in etf_name or "国防" in etf_name:
            keywords.extend(["军工", "国防", "武器"])
        elif "黄金" in etf_name or "白银" in etf_name:
            keywords.extend(["黄金", "白银", "贵金属", "大宗商品"])
        elif "红利" in etf_name:
            keywords.extend(["红利", "分红", "股息"])
        
        # 默认关键词
        if not keywords:
            keywords.append("市场")
        
        return keywords
    
    @classmethod
    def get_policy_news(cls, limit: int = 10) -> List[Dict[str, Any]]:
        """获取政策相关新闻"""
        try:
            print("[NewsService] >>> 获取政策相关新闻")
            df = ak.stock_news_em(symbol="财经")
            if df.empty:
                print("[NewsService] <<< 新闻数据为空")
                return []
            
            # 政策关键词
            policy_keywords = [
                "政策", "央行", "证监会", "银保监会", "发改委",
                "降息", "降准", "利率", "货币政策", "财政政策",
                "监管", "改革", "利好", "利空", "刺激",
            ]
            
            news_list = []
            for _, row in df.iterrows():
                title = str(row.get("标题", ""))
                content = str(row.get("内容", ""))
                
                # 检查是否包含政策关键词
                is_policy = any(kw in title or kw in content for kw in policy_keywords)
                
                if is_policy:
                    news_list.append({
                        "title": title,
                        "content": content[:300] if content else "",
                        "source": str(row.get("来源", "")),
                        "publish_time": str(row.get("发布时间", "")),
                    })
                    
                    if len(news_list) >= limit:
                        break
            
            print(f"[NewsService] <<< 成功获取 {len(news_list)} 条政策新闻")
            return news_list
        except Exception as e:
            print(f"[NewsService] <<< 获取政策新闻失败: {type(e).__name__}: {e}")
            return []
    
    @classmethod
    def format_news_summary(cls, news_list: List[Dict[str, Any]], max_items: int = 5) -> str:
        """格式化新闻摘要"""
        if not news_list:
            return "暂无相关新闻"
        
        lines = []
        for i, news in enumerate(news_list[:max_items], 1):
            title = news.get("title", "")[:50]
            source = news.get("source", "")
            lines.append(f"{i}. {title} ({source})")
        
        return "\n".join(lines)

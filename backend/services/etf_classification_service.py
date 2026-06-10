from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EtfClassification:
    code: str
    name: str
    asset_bucket: str
    region: str
    style: str
    risk_tags: list[str]
    macro_weights: dict[str, float]
    max_position_hint: float
    reason: str


class EtfClassificationService:
    """Rule-based ETF taxonomy used by macro rotation and exposure analysis."""

    @staticmethod
    def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword.lower() in text.lower() for keyword in keywords)

    @classmethod
    def classify(cls, code: str, name: str | None = None) -> EtfClassification:
        clean_code = (code or "").strip()
        text = f"{clean_code} {name or ''}".strip()
        risk_tags: list[str] = []

        asset_bucket = "其他"
        region = "CN"
        style = "其他"
        macro_weights = {"cn": 0.6, "us": 0.1, "global": 0.3}
        max_position_hint = 0.15
        reason = "未命中明确分类规则，按其他 ETF 处理。"

        if cls._has_any(text, ("货币", "现金", "短融", "同业存单")):
            asset_bucket = "债券现金"
            style = "现金"
            macro_weights = {"cn": 0.7, "us": 0.0, "global": 0.3}
            max_position_hint = 0.35
            risk_tags.append("防御资产")
            reason = "名称包含货币、现金或短融特征，归入债券现金资产桶。"
        elif cls._has_any(text, ("国债", "地方债", "政金债", "信用债", "可转债", "债券")):
            asset_bucket = "债券现金"
            style = "债券"
            macro_weights = {"cn": 0.75, "us": 0.05, "global": 0.2}
            max_position_hint = 0.35
            risk_tags.append("防御资产")
            reason = "名称包含债券或国债特征，归入债券现金资产桶。"
        elif cls._has_any(text, ("黄金", "白银", "贵金属", "原油", "油气", "能源", "煤炭", "有色", "铜", "铝", "化工", "豆粕", "农产品")):
            asset_bucket = "黄金商品"
            region = "GLOBAL"
            style = "商品"
            macro_weights = {"cn": 0.1, "us": 0.2, "global": 0.7}
            max_position_hint = 0.2
            risk_tags.append("商品")
            if cls._has_any(text, ("原油", "油气", "能源", "化工")):
                risk_tags.append("高波动")
            reason = "名称包含黄金、能源、有色或农产品特征，归入商品资产桶。"
        elif cls._has_any(text, ("纳指", "纳斯达克", "标普", "道琼斯", "美国", "德国", "法国", "日经", "海外", "全球")):
            asset_bucket = "美股成长" if cls._has_any(text, ("纳指", "纳斯达克", "科技", "100")) else "港股中概"
            region = "US" if cls._has_any(text, ("纳指", "纳斯达克", "标普", "道琼斯", "美国")) else "GLOBAL"
            style = "成长" if asset_bucket == "美股成长" else "宽基"
            macro_weights = {"cn": 0.0, "us": 0.7, "global": 0.3}
            max_position_hint = 0.18
            risk_tags.extend(["跨境", "汇率风险", "T+0风险"])
            reason = "名称包含海外或美股指数特征，按跨境权益 ETF 处理。"
        elif cls._has_any(text, ("恒生", "港股", "中概", "国企", "H股")):
            asset_bucket = "港股中概"
            region = "HK"
            style = "成长" if cls._has_any(text, ("科技", "互联网", "中概")) else "宽基"
            macro_weights = {"cn": 0.4, "us": 0.3, "global": 0.3}
            max_position_hint = 0.2
            risk_tags.extend(["跨境", "汇率风险", "T+0风险", "高波动"])
            reason = "名称包含港股、恒生或中概特征，受中国基本面和海外流动性共同影响。"
        elif cls._has_any(text, ("红利", "股息", "高股息", "央企红利")):
            asset_bucket = "A股宽基"
            region = "CN"
            style = "红利"
            macro_weights = {"cn": 0.75, "us": 0.05, "global": 0.2}
            max_position_hint = 0.25
            risk_tags.append("防御资产")
            reason = "名称包含红利或高股息特征，归入 A 股防御权益。"
        elif cls._has_any(text, ("沪深300", "中证500", "中证1000", "上证50", "A50", "深证100", "创业板", "科创50", "科创", "宽基", "全指")):
            asset_bucket = "A股成长" if cls._has_any(text, ("创业板", "科创", "双创")) else "A股宽基"
            region = "CN"
            style = "成长" if asset_bucket == "A股成长" else "宽基"
            macro_weights = {"cn": 0.75, "us": 0.05, "global": 0.2}
            max_position_hint = 0.35 if asset_bucket == "A股宽基" else 0.25
            if asset_bucket == "A股成长":
                risk_tags.append("高波动")
            reason = "名称包含 A 股主流宽基或成长宽基指数特征。"
        elif cls._has_any(text, ("芯片", "半导体", "人工智能", "AI", "机器人", "算力", "通信", "5G", "软件", "云计算", "科技", "新能源", "光伏", "锂电", "电池", "储能", "风电", "创新药", "生物", "医药")):
            asset_bucket = "A股成长"
            region = "CN"
            style = "成长"
            macro_weights = {"cn": 0.65, "us": 0.15, "global": 0.2}
            max_position_hint = 0.2
            risk_tags.append("高波动")
            reason = "名称包含科技、医药或新能源等成长行业特征。"
        elif cls._has_any(text, ("消费", "食品", "饮料", "白酒", "家电", "银行", "证券", "券商", "保险", "金融", "地产", "军工", "国防", "农业")):
            asset_bucket = "A股宽基"
            region = "CN"
            style = "周期" if cls._has_any(text, ("银行", "证券", "券商", "保险", "金融", "地产", "军工")) else "防御"
            macro_weights = {"cn": 0.7, "us": 0.05, "global": 0.25}
            max_position_hint = 0.2
            reason = "名称包含 A 股行业 ETF 特征，暂归入 A 股权益资产桶。"

        if clean_code.startswith(("513", "520", "159", "501")) and asset_bucket in {"港股中概", "美股成长"}:
            if "跨境" not in risk_tags:
                risk_tags.append("跨境")

        return EtfClassification(
            code=clean_code,
            name=name or "",
            asset_bucket=asset_bucket,
            region=region,
            style=style,
            risk_tags=list(dict.fromkeys(risk_tags)),
            macro_weights=macro_weights,
            max_position_hint=max_position_hint,
            reason=reason,
        )

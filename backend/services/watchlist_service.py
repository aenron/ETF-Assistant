from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Portfolio, WatchlistItem
from schemas.watchlist import WatchlistCreate, WatchlistItemResponse, WatchlistUpdate
from services.market_service import MarketService
from services.portfolio_service import PortfolioService


class WatchlistService:
    SUPPORTED_ASSET_TYPES = {"etf", "stock", "otc_fund", "cash", "money_fund"}

    @staticmethod
    def _clean_code(code: str | None) -> str:
        return (code or "").strip().upper()

    @staticmethod
    def _finite_float(value: Any) -> float | None:
        return PortfolioService._optional_finite_float(value)

    @classmethod
    async def _holding_context(cls, session: AsyncSession, user_id: int) -> dict[str, dict[str, Any]]:
        result = await session.execute(select(Portfolio).where(Portfolio.user_id == user_id))
        context: dict[str, dict[str, Any]] = {}
        codes = []
        portfolios = result.scalars().all()
        for portfolio in portfolios:
            code = cls._clean_code(portfolio.etf_code)
            if code:
                codes.append(code)
        quotes = await MarketService.get_cached_quotes_for_codes(codes) if codes else {}

        for portfolio in portfolios:
            code = cls._clean_code(portfolio.etf_code)
            if not code:
                continue
            quote = quotes.get(code)
            shares = cls._finite_float(portfolio.shares) or 0.0
            price = cls._finite_float(getattr(quote, "price", None))
            market_value = shares * price if price is not None else None
            item = context.setdefault(code, {"market_value": Decimal("0"), "has_quote": False})
            if market_value is not None:
                item["market_value"] += Decimal(str(market_value))
                item["has_quote"] = True
        return context

    @classmethod
    def _response_from_item(cls, item: WatchlistItem, quote, holding_context: dict[str, dict[str, Any]]) -> WatchlistItemResponse:
        holding = holding_context.get(cls._clean_code(item.code))
        holding_market_value = None
        if holding and holding.get("has_quote"):
            holding_market_value = cls._finite_float(holding.get("market_value"))
        quote_name = getattr(quote, "name", None) if quote else None
        return WatchlistItemResponse(
            id=item.id,
            code=item.code,
            name=item.name or quote_name,
            asset_type=item.asset_type,
            note=item.note,
            sort_order=item.sort_order,
            created_at=item.created_at,
            updated_at=item.updated_at,
            current_price=cls._finite_float(getattr(quote, "price", None)) if quote else None,
            change_pct=cls._finite_float(getattr(quote, "change_pct", None)) if quote else None,
            open_price=cls._finite_float(getattr(quote, "open_price", None)) if quote else None,
            high_price=cls._finite_float(getattr(quote, "high_price", None)) if quote else None,
            low_price=cls._finite_float(getattr(quote, "low_price", None)) if quote else None,
            volume=getattr(quote, "volume", None) if quote else None,
            amount=cls._finite_float(getattr(quote, "amount", None)) if quote else None,
            iopv=cls._finite_float(getattr(quote, "iopv", None)) if quote else None,
            premium_rate=cls._finite_float(getattr(quote, "premium_rate", None)) if quote else None,
            market_refreshed_at=getattr(quote, "refreshed_at", None) if quote else None,
            is_holding=holding is not None,
            holding_market_value=holding_market_value,
        )

    @classmethod
    async def list_items(cls, session: AsyncSession, user_id: int) -> list[WatchlistItemResponse]:
        result = await session.execute(
            select(WatchlistItem)
            .where(WatchlistItem.user_id == user_id)
            .order_by(WatchlistItem.sort_order.asc(), WatchlistItem.id.asc())
        )
        items = result.scalars().all()
        codes = [cls._clean_code(item.code) for item in items if item.code]
        quotes = await MarketService.get_cached_quotes_for_codes(codes) if codes else {}
        holding_context = await cls._holding_context(session, user_id)
        return [
            cls._response_from_item(item, quotes.get(cls._clean_code(item.code)), holding_context)
            for item in items
        ]

    @classmethod
    async def create(cls, session: AsyncSession, data: WatchlistCreate, user_id: int) -> WatchlistItemResponse:
        code = cls._clean_code(data.code)
        if not code:
            raise ValueError("代码不能为空")

        result = await session.execute(
            select(WatchlistItem).where(WatchlistItem.user_id == user_id, WatchlistItem.code == code)
        )
        item = result.scalar_one_or_none()
        if item is None:
            count_result = await session.execute(
                select(func.count()).select_from(WatchlistItem).where(WatchlistItem.user_id == user_id)
            )
            sort_order = int(count_result.scalar_one() or 0)
            item = WatchlistItem(
                user_id=user_id,
                code=code,
                name=(data.name or "").strip() or None,
                asset_type=data.asset_type if data.asset_type in cls.SUPPORTED_ASSET_TYPES else "etf",
                note=(data.note or "").strip() or None,
                sort_order=sort_order,
            )
            session.add(item)
        else:
            item.name = (data.name or item.name or "").strip() or item.name
            item.asset_type = data.asset_type if data.asset_type in cls.SUPPORTED_ASSET_TYPES else item.asset_type
            item.note = (data.note or item.note or "").strip() or item.note
        await session.commit()
        await session.refresh(item)

        quotes = await MarketService.get_cached_quotes_for_codes([code])
        holding_context = await cls._holding_context(session, user_id)
        return cls._response_from_item(item, quotes.get(code), holding_context)

    @classmethod
    async def update(cls, session: AsyncSession, item_id: int, data: WatchlistUpdate, user_id: int) -> WatchlistItemResponse | None:
        result = await session.execute(
            select(WatchlistItem).where(WatchlistItem.id == item_id, WatchlistItem.user_id == user_id)
        )
        item = result.scalar_one_or_none()
        if item is None:
            return None
        if data.name is not None:
            item.name = data.name.strip() or None
        if data.asset_type is not None:
            item.asset_type = data.asset_type if data.asset_type in cls.SUPPORTED_ASSET_TYPES else item.asset_type
        if data.note is not None:
            item.note = data.note.strip() or None
        if data.sort_order is not None:
            item.sort_order = data.sort_order
        await session.commit()
        await session.refresh(item)

        quotes = await MarketService.get_cached_quotes_for_codes([item.code])
        holding_context = await cls._holding_context(session, user_id)
        return cls._response_from_item(item, quotes.get(cls._clean_code(item.code)), holding_context)

    @classmethod
    async def delete(cls, session: AsyncSession, item_id: int, user_id: int) -> bool:
        result = await session.execute(
            delete(WatchlistItem)
            .where(WatchlistItem.id == item_id, WatchlistItem.user_id == user_id)
            .returning(WatchlistItem.id)
        )
        deleted_id = result.scalar_one_or_none()
        await session.commit()
        return deleted_id is not None

    @classmethod
    async def refresh_all(cls, session: AsyncSession, user_id: int) -> dict[str, Any]:
        result = await session.execute(
            select(WatchlistItem.code)
            .where(WatchlistItem.user_id == user_id)
            .distinct()
        )
        codes = sorted({cls._clean_code(code) for code in result.scalars().all() if code})
        if not codes:
            return {"success": True, "message": "无自选数据", "refreshed": 0, "codes": []}
        quotes = await MarketService.refresh_quotes(codes)
        return {
            "success": True,
            "message": f"已刷新 {len(quotes)} 个自选品种行情",
            "refreshed": len(quotes),
            "codes": codes,
        }

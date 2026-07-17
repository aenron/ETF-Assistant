from routers.portfolio import router as portfolio_router
from routers.market import router as market_router
from routers.advice import router as advice_router
from routers.assistant import router as assistant_router
from routers.admin import router as admin_router
from routers.multi_agent import router as multi_agent_router
from routers.strategy import router as strategy_router
from routers.watchlist import router as watchlist_router

__all__ = ["portfolio_router", "market_router", "advice_router", "assistant_router", "admin_router", "multi_agent_router", "strategy_router", "watchlist_router"]

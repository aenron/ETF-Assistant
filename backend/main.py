from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from database import init_db
from routers import portfolio_router, market_router, advice_router
from routers.auth import router as auth_router
from services.redis_service import RedisService


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化数据库
    await init_db()
    # 不再预加载行情，改为按需从Redis获取
    print("[Startup] 行情数据将按需从Redis缓存获取")
    yield
    # 关闭时清理资源
    await RedisService.close()


app = FastAPI(
    title="ETF投资智能体 API",
    description="ETF持仓管理与智能决策系统",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth_router)
app.include_router(portfolio_router)
app.include_router(market_router)
app.include_router(advice_router)


@app.get("/")
async def root():
    return {"message": "ETF投资智能体 API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    # reload=False 禁用自动重启
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)

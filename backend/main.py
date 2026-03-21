from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import text

from database import init_db, engine
from routers import portfolio_router, market_router, advice_router
from routers.auth import router as auth_router
from routers.llm_config import router as llm_config_router
from config import settings
from services.redis_service import RedisService
from services.scheduler import start_scheduler, shutdown_scheduler


async def run_migrations():
    """执行数据库迁移"""
    async with engine.begin() as conn:
        # advice_log 添加 llm_provider 和 llm_model 字段
        for col, col_type in [("llm_provider", "VARCHAR(30)"), ("llm_model", "VARCHAR(100)")]:
            try:
                await conn.execute(text(f"ALTER TABLE advice_log ADD COLUMN {col} {col_type}"))
                print(f"[Migration] 添加字段 advice_log.{col}")
            except Exception:
                pass  # 字段已存在


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化数据库
    if not settings.jwt_secret.strip():
        raise RuntimeError("JWT_SECRET 未配置，请在 .env 中设置")
    await init_db()
    await run_migrations()
    # 启动定时任务调度器
    start_scheduler()
    print("[Startup] 行情数据将按需从Redis缓存获取")
    yield
    # 关闭时清理资源
    shutdown_scheduler()
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
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth_router)
app.include_router(portfolio_router)
app.include_router(market_router)
app.include_router(advice_router)
app.include_router(llm_config_router)


@app.get("/")
async def root():
    return {"message": "ETF投资智能体 API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    # reload=False 禁用自动重启
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)

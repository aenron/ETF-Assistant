from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import func, select, text

from database import init_db, engine
from database import async_session_maker
from models.user import User
from routers import portfolio_router, market_router, advice_router, assistant_router, admin_router
from routers.auth import router as auth_router
from routers.llm_config import router as llm_config_router
from routers.notification_config import router as notification_config_router
from config import settings
from services.redis_service import RedisService
from services.scheduler import apply_scheduler_job_configs, start_scheduler, shutdown_scheduler


async def run_migrations():
    """执行数据库迁移"""
    migration_statements = [
        ("advice_log.llm_provider", "ALTER TABLE advice_log ADD COLUMN llm_provider VARCHAR(30)"),
        ("advice_log.llm_model", "ALTER TABLE advice_log ADD COLUMN llm_model VARCHAR(100)"),
        ("user_notification_config.chat_id", "ALTER TABLE user_notification_config ADD COLUMN chat_id VARCHAR(255)"),
        ("users.is_admin", "ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE NOT NULL"),
    ]

    for label, statement in migration_statements:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(statement))
            print(f"[Migration] 添加字段 {label}")
        except Exception as exc:
            # PostgreSQL 中某条 DDL 失败会中止当前事务，这里必须逐条单独执行。
            print(f"[Migration] 跳过字段 {label}: {exc}")


async def ensure_admin_user():
    """确保系统至少有一个管理员账号"""
    async with async_session_maker() as session:
        admin_count_result = await session.execute(
            select(func.count()).select_from(User).where(User.is_admin == True)
        )
        admin_count = admin_count_result.scalar_one()
        if admin_count > 0:
            return

        first_user_result = await session.execute(
            select(User).order_by(User.created_at.asc(), User.id.asc()).limit(1)
        )
        first_user = first_user_result.scalar_one_or_none()
        if not first_user:
            return

        first_user.is_admin = True
        await session.commit()
        print(f"[Startup] 已将首个用户 {first_user.username} 设置为管理员")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化数据库
    if not settings.jwt_secret.strip():
        raise RuntimeError("JWT_SECRET 未配置，请在 .env 中设置")
    await init_db()
    await run_migrations()
    await ensure_admin_user()
    # 启动定时任务调度器
    start_scheduler()
    await apply_scheduler_job_configs()
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
app.include_router(assistant_router)
app.include_router(llm_config_router)
app.include_router(notification_config_router)
app.include_router(admin_router)


@app.get("/")
async def root():
    return {"message": "ETF投资智能体 API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    # reload=False 禁用自动重启
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import func, select, text

from database import init_db, engine
from database import async_session_maker
from models.user import User
from routers import portfolio_router, market_router, advice_router, assistant_router, admin_router, multi_agent_router, strategy_router
from routers.macro import router as macro_router
from routers.auth import router as auth_router
from routers.llm_config import router as llm_config_router
from routers.notification_config import router as notification_config_router
from routers.watchlist import router as watchlist_router
from config import settings
from services.redis_service import RedisService
from services.scheduler import apply_scheduler_job_configs, start_scheduler, shutdown_scheduler
from services.strategy_service import StrategyService


async def run_migrations():
    """执行数据库迁移"""
    migration_statements = [
        ("advice_log.llm_provider", "ALTER TABLE advice_log ADD COLUMN llm_provider VARCHAR(30)"),
        ("advice_log.llm_model", "ALTER TABLE advice_log ADD COLUMN llm_model VARCHAR(100)"),
        ("assistant_session_message.status", "ALTER TABLE assistant_session_message ADD COLUMN status VARCHAR(20) DEFAULT 'done' NOT NULL"),
        ("assistant_session_message.run_id", "ALTER TABLE assistant_session_message ADD COLUMN run_id VARCHAR(64)"),
        ("assistant_session_message.status_idx", "CREATE INDEX IF NOT EXISTS ix_assistant_session_message_status ON assistant_session_message (status)"),
        ("assistant_session_message.run_id_idx", "CREATE INDEX IF NOT EXISTS ix_assistant_session_message_run_id ON assistant_session_message (run_id)"),
        ("user_notification_config.chat_id", "ALTER TABLE user_notification_config ADD COLUMN chat_id VARCHAR(255)"),
        ("users.is_admin", "ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE NOT NULL"),
        ("multi_agent_run.title", "ALTER TABLE multi_agent_run ADD COLUMN title VARCHAR(120)"),
        ("multi_agent_run.max_debate_rounds", "ALTER TABLE multi_agent_run ADD COLUMN max_debate_rounds INTEGER DEFAULT 3 NOT NULL"),
        ("multi_agent_run.collapse_debate_by_default", "ALTER TABLE multi_agent_run ADD COLUMN collapse_debate_by_default BOOLEAN DEFAULT TRUE NOT NULL"),
        ("portfolio.dca_track_override", "ALTER TABLE portfolio ADD COLUMN dca_track_override VARCHAR(20)"),
        ("portfolio.asset_type", "ALTER TABLE portfolio ADD COLUMN asset_type VARCHAR(20) DEFAULT 'etf' NOT NULL"),
        ("portfolio.asset_type_idx", "CREATE INDEX IF NOT EXISTS ix_portfolio_asset_type ON portfolio (asset_type)"),
        ("market_daily.amount", "ALTER TABLE market_daily ADD COLUMN amount NUMERIC(20, 4)"),
        ("portfolio_dca_state.pending_notify_key", "ALTER TABLE portfolio_dca_state ADD COLUMN pending_notify_key VARCHAR(200)"),
        ("portfolio_dca_state.pending_notify_reason", "ALTER TABLE portfolio_dca_state ADD COLUMN pending_notify_reason VARCHAR(100)"),
        ("index_valuation.pb", "ALTER TABLE index_valuation ADD COLUMN pb NUMERIC(12, 4)"),
        ("portfolio_dca_state.candidate_light", "ALTER TABLE portfolio_dca_state ADD COLUMN candidate_light VARCHAR(30)"),
        ("portfolio_dca_state.candidate_confirm_count", "ALTER TABLE portfolio_dca_state ADD COLUMN candidate_confirm_count INTEGER"),
        ("dca_index_mapping.table", "CREATE TABLE IF NOT EXISTS dca_index_mapping (id SERIAL PRIMARY KEY, etf_code VARCHAR(20), keyword VARCHAR(100), index_symbol VARCHAR(20) NOT NULL, index_name VARCHAR(100), enabled BOOLEAN DEFAULT TRUE NOT NULL, created_at TIMESTAMP DEFAULT NOW() NOT NULL, updated_at TIMESTAMP DEFAULT NOW() NOT NULL)"),
        ("dca_index_mapping.uq", "CREATE UNIQUE INDEX IF NOT EXISTS uq_dca_index_mapping_code_keyword ON dca_index_mapping (etf_code, keyword)"),
        ("dca_index_mapping.etf_code_idx", "CREATE INDEX IF NOT EXISTS ix_dca_index_mapping_etf_code ON dca_index_mapping (etf_code)"),
        ("dca_index_mapping.keyword_idx", "CREATE INDEX IF NOT EXISTS ix_dca_index_mapping_keyword ON dca_index_mapping (keyword)"),
        ("dca_signal_config.table", "CREATE TABLE IF NOT EXISTS dca_signal_config (id INTEGER PRIMARY KEY DEFAULT 1, valuation_deep_green_percentile NUMERIC(6, 2) DEFAULT 15 NOT NULL, valuation_green_percentile NUMERIC(6, 2) DEFAULT 30 NOT NULL, valuation_red_percentile NUMERIC(6, 2) DEFAULT 80 NOT NULL, valuation_min_sample_size INTEGER DEFAULT 250 NOT NULL, trend_short_ma_days INTEGER DEFAULT 20 NOT NULL, trend_medium_ma_days INTEGER DEFAULT 60 NOT NULL, trend_long_ma_days INTEGER DEFAULT 120 NOT NULL, trend_history_days INTEGER DEFAULT 140 NOT NULL, trend_slope_shift_days INTEGER DEFAULT 5 NOT NULL, trend_volume_ma_days INTEGER DEFAULT 20 NOT NULL, trend_volume_confirm_ratio NUMERIC(6, 3) DEFAULT 0.8 NOT NULL, trend_volume_expand_ratio NUMERIC(6, 3) DEFAULT 1.2 NOT NULL, trend_atr_days INTEGER DEFAULT 14 NOT NULL, trend_atr_base_multiplier NUMERIC(6, 3) DEFAULT 1.5 NOT NULL, trend_atr_mid_multiplier NUMERIC(6, 3) DEFAULT 1.8 NOT NULL, trend_atr_high_multiplier NUMERIC(6, 3) DEFAULT 2.0 NOT NULL, trend_atr_mid_volatility_pct NUMERIC(6, 3) DEFAULT 2.5 NOT NULL, trend_atr_high_volatility_pct NUMERIC(6, 3) DEFAULT 4.0 NOT NULL, light_confirm_count INTEGER DEFAULT 2 NOT NULL, updated_at TIMESTAMP DEFAULT NOW() NOT NULL)"),
        ("dca_signal_config.default", "INSERT INTO dca_signal_config (id) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM dca_signal_config WHERE id = 1)"),
        ("strategy_run_cache.table", "CREATE TABLE IF NOT EXISTS strategy_run_cache (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), strategy_id VARCHAR(50) NOT NULL, result_json TEXT NOT NULL, created_at TIMESTAMP DEFAULT NOW() NOT NULL, updated_at TIMESTAMP DEFAULT NOW() NOT NULL)"),
        ("strategy_run_cache.uq", "CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_run_cache_user_strategy ON strategy_run_cache (user_id, strategy_id)"),
        ("macro_cycle_state.table", "CREATE TABLE IF NOT EXISTS macro_cycle_state (id SERIAL PRIMARY KEY, region VARCHAR(20) DEFAULT 'cn' NOT NULL, cycle_phase VARCHAR(30) NOT NULL, growth_score NUMERIC(6, 2) DEFAULT 0 NOT NULL, inflation_score NUMERIC(6, 2) DEFAULT 0 NOT NULL, growth_trend VARCHAR(20) NOT NULL, inflation_trend VARCHAR(20) NOT NULL, confidence NUMERIC(6, 2) DEFAULT 50 NOT NULL, summary TEXT, dca_impact TEXT, source_note TEXT, source_type VARCHAR(20) DEFAULT 'auto' NOT NULL, override_until TIMESTAMP, observed_at TIMESTAMP DEFAULT NOW() NOT NULL, created_at TIMESTAMP DEFAULT NOW() NOT NULL, updated_at TIMESTAMP DEFAULT NOW() NOT NULL)"),
        ("macro_cycle_state.phase_idx", "CREATE INDEX IF NOT EXISTS ix_macro_cycle_state_cycle_phase ON macro_cycle_state (cycle_phase)"),
        ("macro_cycle_state.observed_idx", "CREATE INDEX IF NOT EXISTS ix_macro_cycle_state_observed_at ON macro_cycle_state (observed_at)"),
        ("macro_cycle_state.region", "ALTER TABLE macro_cycle_state ADD COLUMN region VARCHAR(20) DEFAULT 'cn' NOT NULL"),
        ("macro_cycle_state.region_idx", "CREATE INDEX IF NOT EXISTS ix_macro_cycle_state_region ON macro_cycle_state (region)"),
        ("macro_cycle_state.source_type", "ALTER TABLE macro_cycle_state ADD COLUMN source_type VARCHAR(20) DEFAULT 'auto' NOT NULL"),
        ("macro_cycle_state.override_until", "ALTER TABLE macro_cycle_state ADD COLUMN override_until TIMESTAMP"),
        ("macro_cycle_state.source_type_idx", "CREATE INDEX IF NOT EXISTS ix_macro_cycle_state_source_type ON macro_cycle_state (source_type)"),
        ("macro_indicator.table", "CREATE TABLE IF NOT EXISTS macro_indicator (id SERIAL PRIMARY KEY, region VARCHAR(20) DEFAULT 'cn' NOT NULL, indicator_code VARCHAR(50) NOT NULL, indicator_name VARCHAR(100) NOT NULL, category VARCHAR(30) NOT NULL, period VARCHAR(20) NOT NULL, value NUMERIC(14, 4) NOT NULL, previous_value NUMERIC(14, 4), trend VARCHAR(20) NOT NULL, unit VARCHAR(20), source VARCHAR(50) DEFAULT 'akshare' NOT NULL, source_note TEXT, source_function VARCHAR(100), source_column VARCHAR(100), raw_period VARCHAR(50), fetched_at TIMESTAMP DEFAULT NOW() NOT NULL, created_at TIMESTAMP DEFAULT NOW() NOT NULL, updated_at TIMESTAMP DEFAULT NOW() NOT NULL)"),
        ("macro_indicator.drop_old_uq", "DROP INDEX IF EXISTS uq_macro_indicator_code_period"),
        ("macro_indicator.uq", "CREATE UNIQUE INDEX IF NOT EXISTS uq_macro_indicator_region_code_period ON macro_indicator (region, indicator_code, period)"),
        ("macro_indicator.code_idx", "CREATE INDEX IF NOT EXISTS ix_macro_indicator_indicator_code ON macro_indicator (indicator_code)"),
        ("macro_indicator.category_idx", "CREATE INDEX IF NOT EXISTS ix_macro_indicator_category ON macro_indicator (category)"),
        ("macro_indicator.period_idx", "CREATE INDEX IF NOT EXISTS ix_macro_indicator_period ON macro_indicator (period)"),
        ("macro_indicator.region", "ALTER TABLE macro_indicator ADD COLUMN region VARCHAR(20) DEFAULT 'cn' NOT NULL"),
        ("macro_indicator.region_idx", "CREATE INDEX IF NOT EXISTS ix_macro_indicator_region ON macro_indicator (region)"),
        ("macro_indicator.source_function", "ALTER TABLE macro_indicator ADD COLUMN source_function VARCHAR(100)"),
        ("macro_indicator.source_column", "ALTER TABLE macro_indicator ADD COLUMN source_column VARCHAR(100)"),
        ("macro_indicator.raw_period", "ALTER TABLE macro_indicator ADD COLUMN raw_period VARCHAR(50)"),
        ("watchlist_item.table", "CREATE TABLE IF NOT EXISTS watchlist_item (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), code VARCHAR(20) NOT NULL, name VARCHAR(100), asset_type VARCHAR(20) DEFAULT 'etf' NOT NULL, note TEXT, sort_order INTEGER DEFAULT 0 NOT NULL, created_at TIMESTAMP DEFAULT NOW() NOT NULL, updated_at TIMESTAMP DEFAULT NOW() NOT NULL)"),
        ("watchlist_item.uq", "CREATE UNIQUE INDEX IF NOT EXISTS uq_watchlist_item_user_code ON watchlist_item (user_id, code)"),
        ("watchlist_item.user_idx", "CREATE INDEX IF NOT EXISTS ix_watchlist_item_user_id ON watchlist_item (user_id)"),
        ("watchlist_item.code_idx", "CREATE INDEX IF NOT EXISTS ix_watchlist_item_code ON watchlist_item (code)"),
        ("watchlist_item.asset_type_idx", "CREATE INDEX IF NOT EXISTS ix_watchlist_item_asset_type ON watchlist_item (asset_type)"),
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
    if settings.scheduler_enabled:
        start_scheduler()
        await apply_scheduler_job_configs()
        await StrategyService.restore_schedules()
        print("[Startup] 定时任务调度器已启用")
    else:
        print("[Startup] 定时任务调度器已禁用（SCHEDULER_ENABLED=false）")
    print("[Startup] 行情数据将按需从Redis缓存获取")
    yield
    # 关闭时清理资源
    if settings.scheduler_enabled:
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
app.include_router(macro_router)
app.include_router(multi_agent_router)
app.include_router(strategy_router)
app.include_router(watchlist_router)


@app.get("/")
async def root():
    return {"message": "ETF投资智能体 API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    # reload=False 禁用自动重启
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)

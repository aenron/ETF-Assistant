from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    # 数据库配置
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/etf"

    # JWT 配置
    jwt_secret: str = ""

    # CORS 配置
    cors_origins: list[str] = [
        "http://localhost:8123",
        "http://127.0.0.1:8123",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    
    # Redis 配置
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True
    
    # LLM 配置
    llm_provider: Literal["openai", "deepseek", "gemini", "qwen", "zhipu"] = "deepseek"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "deepseek-chat"
    
    # OpenAI 默认配置
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    
    # DeepSeek 默认配置
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    
    # Gemini 配置
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_enable_grounding: bool = True
    gemini_timeout_seconds: float = 600.0
    
    # 通义千问 配置
    qwen_api_key: str = ""
    qwen_model: str = "qwen-plus"
    qwen_enable_search: bool = True

    # 智谱配置
    zhipu_api_key: str = ""
    zhipu_model: str = "glm-4.5-air"
    zhipu_enable_web_search: bool = True

    # Tavily 联网搜索配置
    tavily_api_key: str = ""
    tavily_enabled: bool = False
    tavily_search_depth: Literal["advanced", "basic", "fast", "ultra-fast"] = "basic"
    tavily_topic: Literal["general", "news", "finance"] = "news"
    tavily_time_range: str = "week"
    tavily_max_results: int = 5
    tavily_timeout_seconds: float = 12.0
    
    # Bark 推送配置
    bark_key: str = ""
    bark_url: str = "https://api.day.app"
    
    # 注册邀请码
    invite_code: str = ""
    
    # 行情缓存天数
    market_cache_days: int = 60
    
    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

"""LLM配置路由"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from pydantic import BaseModel

from database import get_session
from routers.auth import get_current_user
from models.user import User
from config import settings


router = APIRouter(prefix="/api/llm", tags=["LLM配置"])


class LLMProvider(BaseModel):
    """LLM提供商"""
    id: str
    name: str
    description: str
    enabled: bool
    supports_search: bool


class LLMConfigResponse(BaseModel):
    """LLM配置响应"""
    current_provider: str
    providers: List[LLMProvider]


def tavily_search_enabled() -> bool:
    return bool(settings.tavily_enabled and settings.tavily_api_key.strip())


def provider_supports_search(provider: str) -> bool:
    if tavily_search_enabled():
        return True
    if provider == "gemini":
        return settings.gemini_enable_grounding
    if provider == "qwen":
        return settings.qwen_enable_search
    if provider == "zhipu":
        return settings.zhipu_enable_web_search
    return False


def build_providers() -> dict[str, LLMProvider]:
    tavily_suffix = "；已配置 Tavily 工具搜索" if tavily_search_enabled() else ""
    return {
        "openai": LLMProvider(
            id="openai",
            name="OpenAI GPT",
            description=f"OpenAI GPT系列模型{tavily_suffix}",
            enabled=bool(settings.openai_api_key),
            supports_search=provider_supports_search("openai"),
        ),
        "deepseek": LLMProvider(
            id="deepseek",
            name="DeepSeek",
            description=f"DeepSeek深度求索大模型{tavily_suffix}",
            enabled=bool(settings.deepseek_api_key),
            supports_search=provider_supports_search("deepseek"),
        ),
        "qwen": LLMProvider(
            id="qwen",
            name="通义千问",
            description=f"阿里云通义千问大模型，支持网络搜索{tavily_suffix}",
            enabled=bool(settings.qwen_api_key),
            supports_search=provider_supports_search("qwen"),
        ),
        "gemini": LLMProvider(
            id="gemini",
            name="Google Gemini",
            description=f"Google Gemini模型，支持Google搜索{tavily_suffix}",
            enabled=bool(settings.gemini_api_key),
            supports_search=provider_supports_search("gemini"),
        ),
        "zhipu": LLMProvider(
            id="zhipu",
            name="智谱 GLM",
            description=f"智谱 GLM 模型，支持内置 Web Search{tavily_suffix}",
            enabled=bool(settings.zhipu_api_key),
            supports_search=provider_supports_search("zhipu"),
        ),
    }


@router.get("/providers", response_model=LLMConfigResponse)
async def get_llm_providers(
    current_user: User = Depends(get_current_user),
):
    """获取可用的LLM提供商列表"""
    providers = build_providers()
    return LLMConfigResponse(
        current_provider=settings.llm_provider,
        providers=list(providers.values()),
    )


@router.post("/switch")
async def switch_llm_provider(
    provider: str,
    current_user: User = Depends(get_current_user),
):
    """切换LLM提供商"""
    providers = build_providers()
    if provider not in providers:
        return {"success": False, "message": f"不支持的LLM提供商: {provider}"}
    
    provider_info = providers[provider]
    if not provider_info.enabled:
        return {"success": False, "message": f"LLM提供商 {provider} 未配置API Key"}
    
    # 更新运行时配置
    settings.llm_provider = provider
    
    # 清除缓存的LLM客户端
    from services.advisor_service import AdvisorService
    AdvisorService._llm_client = None
    
    return {
        "success": True,
        "message": f"已切换到 {provider_info.name}",
        "provider": provider,
    }

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


# 支持的LLM提供商
PROVIDERS = {
    "openai": LLMProvider(
        id="openai",
        name="OpenAI GPT",
        description="OpenAI GPT系列模型",
        enabled=bool(settings.openai_api_key),
        supports_search=False,
    ),
    "deepseek": LLMProvider(
        id="deepseek",
        name="DeepSeek",
        description="DeepSeek深度求索大模型",
        enabled=bool(settings.deepseek_api_key),
        supports_search=True,
    ),
    "qwen": LLMProvider(
        id="qwen",
        name="通义千问",
        description="阿里云通义千问大模型，支持网络搜索",
        enabled=bool(settings.qwen_api_key),
        supports_search=True,
    ),
    "gemini": LLMProvider(
        id="gemini",
        name="Google Gemini",
        description="Google Gemini模型，支持Google搜索",
        enabled=bool(settings.gemini_api_key),
        supports_search=True,
    ),
    "ollama": LLMProvider(
        id="ollama",
        name="Ollama",
        description="本地Ollama模型",
        enabled=True,  # Ollama是本地的，默认可用
        supports_search=False,
    ),
}


@router.get("/providers", response_model=LLMConfigResponse)
async def get_llm_providers(
    current_user: User = Depends(get_current_user),
):
    """获取可用的LLM提供商列表"""
    return LLMConfigResponse(
        current_provider=settings.llm_provider,
        providers=list(PROVIDERS.values()),
    )


@router.post("/switch")
async def switch_llm_provider(
    provider: str,
    current_user: User = Depends(get_current_user),
):
    """切换LLM提供商"""
    if provider not in PROVIDERS:
        return {"success": False, "message": f"不支持的LLM提供商: {provider}"}
    
    provider_info = PROVIDERS[provider]
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

from abc import ABC, abstractmethod


class BaseLLMClient(ABC):
    """LLM客户端抽象基类"""
    
    @abstractmethod
    async def chat(self, prompt: str) -> str:
        """发送prompt并获取响应"""
        pass
    
    @abstractmethod
    async def chat_json(self, prompt: str) -> dict:
        """发送prompt并获取JSON响应"""
        pass

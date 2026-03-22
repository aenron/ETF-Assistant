from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


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

    async def chat_stream(self, prompt: str) -> AsyncIterator[str]:
        """流式发送prompt并获取响应，默认降级为一次性返回"""
        text = await self.chat(prompt)
        if text:
            yield text

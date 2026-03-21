import json
import httpx
from services.llm.base import BaseLLMClient


class OpenAIClient(BaseLLMClient):
    """OpenAI API客户端"""
    
    def __init__(
        self, 
        api_key: str, 
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini"
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
    
    async def chat(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    
    async def chat_json(self, prompt: str) -> dict:
        response = await self.chat(prompt)
        try:
            # 尝试提取JSON
            start = response.find("{")
            end = response.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(response[start:end])
            return {"error": "No JSON found", "raw": response}
        except json.JSONDecodeError:
            return {"error": "JSON decode failed", "raw": response}

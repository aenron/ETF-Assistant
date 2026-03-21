import json
import httpx
from services.llm.base import BaseLLMClient


class OllamaClient(BaseLLMClient):
    """Ollama本地模型客户端"""
    
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5:7b"):
        self.base_url = base_url.rstrip("/")
        self.model = model
    
    async def chat(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")
    
    async def chat_json(self, prompt: str) -> dict:
        response = await self.chat(prompt)
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(response[start:end])
            return {"error": "No JSON found", "raw": response}
        except json.JSONDecodeError:
            return {"error": "JSON decode failed", "raw": response}

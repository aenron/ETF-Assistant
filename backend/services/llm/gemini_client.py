import json
import httpx
from typing import Optional, Dict, Any, List
from services.llm.base import BaseLLMClient


class GeminiClient(BaseLLMClient):
    """Google Gemini API客户端，支持Google Search Grounding"""
    
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        enable_grounding: bool = True,
    ):
        self.api_key = api_key
        self.model = model
        self.enable_grounding = enable_grounding
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
    
    async def chat(self, prompt: str) -> str:
        """发送prompt并获取响应"""
        url = f"{self.base_url}/models/{self.model}:generateContent"
        
        # 定义JSON Schema for Structured Output
        response_schema = {
            "type": "object",
            "properties": {
                "advice_type": {
                    "type": "string",
                    "enum": ["buy", "sell", "hold", "add", "reduce"],
                    "description": "操作建议"
                },
                "reason": {
                    "type": "string",
                    "description": "分析理由"
                },
                "confidence": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "置信度"
                }
            },
            "required": ["advice_type", "reason", "confidence"]
        }
        
        # 构建请求体
        request_body: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
                "responseSchema": response_schema,  # Structured Output Schema
            }
        }
        
        # 启用Google Search Grounding
        if self.enable_grounding:
            request_body["tools"] = [
                {
                    "googleSearch": {}
                }
            ]
            print(f"[GeminiClient] 已启用 Google Search Grounding")
        
        print(f"[GeminiClient] 已启用 Structured Output (JSON Schema)")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                json=request_body,
            )
            response.raise_for_status()
            data = response.json()
            
            # 打印Grounding元数据
            if self.enable_grounding and "candidates" in data:
                candidate = data["candidates"][0]
                if "groundingMetadata" in candidate:
                    metadata = candidate["groundingMetadata"]
                    print(f"[GeminiClient] Grounding元数据:")
                    if "webSearchQueries" in metadata:
                        print(f"  - 搜索查询: {metadata['webSearchQueries']}")
                    if "groundingChunks" in metadata:
                        print(f"  - 来源数量: {len(metadata.get('groundingChunks', []))}")
            
            # 提取响应文本
            if "candidates" in data and len(data["candidates"]) > 0:
                candidate = data["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    for part in candidate["content"]["parts"]:
                        if "text" in part:
                            return part["text"]
            
            return json.dumps(data)
    
    async def chat_json(self, prompt: str) -> dict:
        """发送prompt并获取JSON响应"""
        response = await self.chat(prompt)
        try:
            # 清理markdown代码块标记
            text = response.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)
            
            # 尝试提取JSON
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                json_str = text[start:end]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    # JSON不完整，尝试补全
                    print(f"[GeminiClient] JSON不完整，尝试补全: ...{json_str[-50:]}")
                    # 尝试补全缺失的字段
                    if '"advice_type"' in json_str and '"reason"' in json_str:
                        # 提取已有的值
                        import re
                        advice_match = re.search(r'"advice_type"\s*:\s*"(\w+)"', json_str)
                        reason_match = re.search(r'"reason"\s*:\s*"([^"]*)"', json_str)
                        
                        if advice_match and reason_match:
                            return {
                                "advice_type": advice_match.group(1),
                                "reason": reason_match.group(1) + "...(内容被截断)",
                                "confidence": 50
                            }
                    return {"error": "JSON decode failed", "raw": response}
            return {"error": "No JSON found", "raw": response}
        except Exception as e:
            return {"error": f"Parse error: {e}", "raw": response}
    
    async def chat_with_grounding(self, prompt: str) -> Dict[str, Any]:
        """发送prompt并获取带Grounding信息的响应"""
        url = f"{self.base_url}/models/{self.model}:generateContent"
        
        request_body: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 2048,
            },
            "tools": [
                {
                    "googleSearch": {}
                }
            ]
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                json=request_body,
            )
            response.raise_for_status()
            data = response.json()
            
            result = {
                "text": "",
                "grounding_metadata": None,
                "search_queries": [],
            }
            
            if "candidates" in data and len(data["candidates"]) > 0:
                candidate = data["candidates"][0]
                
                # 提取响应文本
                if "content" in candidate and "parts" in candidate["content"]:
                    for part in candidate["content"]["parts"]:
                        if "text" in part:
                            result["text"] = part["text"]
                
                # 提取Grounding元数据
                if "groundingMetadata" in candidate:
                    metadata = candidate["groundingMetadata"]
                    result["grounding_metadata"] = metadata
                    
                    # 提取搜索查询
                    if "webSearchQueries" in metadata:
                        result["search_queries"] = metadata["webSearchQueries"]
            
            return result
    
    async def chat_json_with_sources(self, prompt: str) -> dict:
        """获取JSON响应并包含来源信息"""
        result = await self.chat_with_grounding(prompt)
        
        try:
            text = result["text"]
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                json_result = json.loads(text[start:end])
                # 添加来源信息
                if result["search_queries"]:
                    json_result["_search_queries"] = result["search_queries"]
                if result["grounding_metadata"]:
                    json_result["_grounding"] = True
                return json_result
            return {"error": "No JSON found", "raw": text}
        except json.JSONDecodeError:
            return {"error": "JSON decode failed", "raw": result["text"]}

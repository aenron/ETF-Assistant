"""Google Gemini API客户端（使用官方google-genai SDK）"""
import json
import re
from typing import Optional, Dict, Any, List
from google import genai
from google.genai import types
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
        self.model_name = model
        self.enable_grounding = enable_grounding
        # 创建客户端
        self.client = genai.Client(api_key=api_key)
    
    async def chat(self, prompt: str) -> str:
        """发送prompt并获取响应"""
        # 启用Google Search Grounding
        tools = None
        if self.enable_grounding:
            tools = [types.Tool(
                google_search=types.GoogleSearch()
            )]
            print(f"[GeminiClient] 已启用 Google Search Grounding")
        
        # 配置生成参数（tools放在config中）
        config = types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=8192,
            response_mime_type="application/json",
            tools=tools,
        )
        
        print(f"[GeminiClient] 已启用 Structured Output (JSON)")
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )
            
            # 打印Grounding元数据
            if self.enable_grounding and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                    metadata = candidate.grounding_metadata
                    print(f"[GeminiClient] Grounding元数据:")
                    if hasattr(metadata, 'web_search_queries'):
                        print(f"  - 搜索查询: {metadata.web_search_queries}")
                    if hasattr(metadata, 'grounding_chunks'):
                        print(f"  - 来源数量: {len(metadata.grounding_chunks or [])}")
            
            return response.text
            
        except Exception as e:
            print(f"[GeminiClient] 错误: {e}")
            return json.dumps({"error": str(e)})
    
    async def chat_json(self, prompt: str) -> dict:
        """发送prompt并获取JSON响应"""
        try:
            response = await self.chat(prompt)
            
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
            return {"error": f"Parse error: {e}", "raw": str(e)}
    
    async def chat_with_grounding(self, prompt: str) -> Dict[str, Any]:
        """发送prompt并获取带Grounding信息的响应"""
        tools = [types.Tool(google_search=types.GoogleSearch())] if self.enable_grounding else None
        
        config = types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=2048,
            tools=tools,
        )
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )
            
            result = {
                "text": response.text,
                "grounding_metadata": None,
                "search_queries": [],
            }
            
            # 提取Grounding元数据
            if response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                    metadata = candidate.grounding_metadata
                    result["grounding_metadata"] = metadata
                    if hasattr(metadata, 'web_search_queries'):
                        result["search_queries"] = metadata.web_search_queries or []
            
            return result
            
        except Exception as e:
            return {"text": "", "grounding_metadata": None, "search_queries": [], "error": str(e)}
    
    async def chat_json_with_sources(self, prompt: str) -> dict:
        """获取JSON响应并包含来源信息"""
        result = await self.chat_with_grounding(prompt)
        
        if "error" in result:
            return {"error": result["error"]}
        
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

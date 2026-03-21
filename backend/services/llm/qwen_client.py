"""通义千问 LLM 客户端（使用官方dashscope SDK）"""
from typing import Dict, Any, Optional
import json
import re
import dashscope
from dashscope import Generation


class QwenClient:
    """通义千问客户端（支持网络搜索）"""
    
    def __init__(
        self,
        api_key: str,
        model: str = "qwen-plus",
        enable_search: bool = True,
    ):
        self.api_key = api_key
        self.model = model
        self.enable_search = enable_search
        # 设置API Key
        dashscope.api_key = api_key
    
    async def chat(self, prompt: str) -> str:
        """发送prompt并获取响应"""
        messages = [{"role": "user", "content": prompt}]
        
        response = Generation.call(
            model=self.model,
            messages=messages,
            result_format="text",
            enable_search=self.enable_search,
        )
        
        if response.status_code == 200:
            return response.output.text
        else:
            print(f"[QwenClient] 错误: {response.code} - {response.message}")
            return ""
    
    async def chat_json(self, prompt: str) -> dict:
        """发送prompt并获取JSON响应"""
        messages = [
            {"role": "system", "content": "你是一个专业的ETF投资顾问，请严格按照JSON格式输出结果。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = Generation.call(
                model=self.model,
                messages=messages,
                result_format="message",
                enable_search=self.enable_search,
            )
            
            if response.status_code != 200:
                print(f"[QwenClient] 错误: {response.code} - {response.message}")
                return {"error": f"{response.code}: {response.message}"}
            
            # 打印搜索信息
            usage = response.usage
            if usage and "plugins" in usage:
                plugins = usage.get("plugins", {})
                if "search" in plugins:
                    search_info = plugins["search"]
                    print(f"[QwenClient] ✓ 网络搜索已启用: 搜索次数={search_info.get('count')}, 策略={search_info.get('strategy')}")
            
            # 获取内容
            content = response.output.choices[0].message.content
            print(f"[QwenClient] 原始响应: {content[:200]}...")
            
            # 解析JSON
            return self._parse_json(content)
            
        except Exception as e:
            print(f"[QwenClient] 请求失败: {e}")
            return {"error": f"请求失败: {e}"}
    
    def _parse_json(self, content: str) -> dict:
        """解析JSON响应，处理markdown代码块"""
        content = content.strip()
        
        # 处理 ```json ... ``` 格式
        if "```json" in content:
            match = re.search(r"```json\s*([\s\S]*?)\s*```", content)
            if match:
                content = match.group(1)
        elif "```" in content:
            match = re.search(r"```\s*([\s\S]*?)\s*```", content)
            if match:
                content = match.group(1)
        
        content = content.strip()
        
        # 尝试解析JSON
        try:
            result = json.loads(content)
            return result
        except json.JSONDecodeError:
            # 尝试提取JSON对象
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            
            print(f"[QwenClient] JSON解析失败: {content[:500]}")
            return {"error": "No JSON found", "raw": content[:500]}

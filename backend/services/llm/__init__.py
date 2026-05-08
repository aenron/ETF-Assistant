"""LLM client package with lazy exports to avoid optional dependency import cascades."""

from __future__ import annotations

from importlib import import_module

__all__ = ["BaseLLMClient", "OpenAIClient", "DeepSeekClient", "GeminiClient", "QwenClient", "ZhipuClient"]


def __getattr__(name: str):
    if name == "BaseLLMClient":
        return import_module("services.llm.base").BaseLLMClient
    if name == "OpenAIClient":
        return import_module("services.llm.openai_client").OpenAIClient
    if name == "DeepSeekClient":
        return import_module("services.llm.deepseek_client").DeepSeekClient
    if name == "GeminiClient":
        return import_module("services.llm.gemini_client").GeminiClient
    if name == "QwenClient":
        return import_module("services.llm.qwen_client").QwenClient
    if name == "ZhipuClient":
        return import_module("services.llm.zhipu_client").ZhipuClient
    raise AttributeError(name)

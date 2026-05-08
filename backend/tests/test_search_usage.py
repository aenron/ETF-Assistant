import unittest
from pathlib import Path
import importlib.util

base_path = Path(__file__).resolve().parents[1] / "services" / "llm" / "base.py"
spec = importlib.util.spec_from_file_location("llm_base_for_test", base_path)
base_module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(base_module)
BaseLLMClient = base_module.BaseLLMClient


class DummyLLMClient(BaseLLMClient):
    async def chat(self, prompt: str) -> str:
        return prompt

    async def chat_json(self, prompt: str) -> dict:
        return {"prompt": prompt}


class SearchUsageTests(unittest.TestCase):
    def test_reset_sets_enabled_state(self):
        client = DummyLLMClient()

        client.reset_search_usage(provider="gemini", enabled=True, source="google_grounding")
        usage = client.get_last_search_usage()

        self.assertIsNotNone(usage)
        self.assertEqual(usage.provider, "gemini")
        self.assertTrue(usage.enabled)
        self.assertIsNone(usage.used)
        self.assertEqual(usage.source, "google_grounding")

    def test_update_merges_queries_and_result_count(self):
        client = DummyLLMClient()

        client.reset_search_usage(provider="tavily", enabled=True, source="tavily_tool")
        client.update_search_usage(used=True, queries=["黄金 ETF 最新消息"], result_count=5)
        usage = client.get_last_search_usage()

        self.assertTrue(usage.used)
        self.assertEqual(usage.queries, ["黄金 ETF 最新消息"])
        self.assertEqual(usage.result_count, 5)

    def test_log_payload_is_structured(self):
        client = DummyLLMClient()

        client.reset_search_usage(provider="qwen", enabled=True, source="dashscope_search")
        client.update_search_usage(used=True, queries=["纳指 ETF 最新"], result_count=3, detail="count=1")
        payload = client.get_last_search_usage().to_log_payload(context="portfolio_advice")

        self.assertEqual(payload["context"], "portfolio_advice")
        self.assertEqual(payload["provider"], "qwen")
        self.assertTrue(payload["search_enabled"])
        self.assertTrue(payload["search_used"])
        self.assertEqual(payload["search_queries"], ["纳指 ETF 最新"])
        self.assertEqual(payload["search_result_count"], 3)
        self.assertEqual(payload["source"], "dashscope_search")


if __name__ == "__main__":
    unittest.main()

import importlib.util
from pathlib import Path
import sys
import types
import unittest


backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))
base_path = backend_root / "services" / "llm" / "base.py"
base_spec = importlib.util.spec_from_file_location("services.llm.base", base_path)
base_module = importlib.util.module_from_spec(base_spec)
assert base_spec is not None and base_spec.loader is not None
base_spec.loader.exec_module(base_module)

services_pkg = types.ModuleType("services")
llm_pkg = types.ModuleType("services.llm")
llm_pkg.base = base_module
services_pkg.llm = llm_pkg
sys.modules["services"] = services_pkg
sys.modules["services.llm"] = llm_pkg
sys.modules["services.llm.base"] = base_module

zhipu_path = backend_root / "services" / "llm" / "zhipu_client.py"
zhipu_spec = importlib.util.spec_from_file_location("zhipu_client_for_test", zhipu_path)
zhipu_module = importlib.util.module_from_spec(zhipu_spec)
assert zhipu_spec is not None and zhipu_spec.loader is not None
zhipu_spec.loader.exec_module(zhipu_module)
ZhipuClient = zhipu_module.ZhipuClient


class ZhipuSearchQueryTests(unittest.TestCase):
    def test_builds_query_from_instrument_prompt(self):
        prompt = """你是一名专业的ETF投资顾问。

## 品种信息
- 代码: 510300, 名称: 沪深300ETF
"""
        queries = ZhipuClient._build_search_queries(prompt)

        self.assertEqual(len(queries), 1)
        self.assertIn("510300", queries[0])
        self.assertIn("沪深300ETF", queries[0])

    def test_builds_query_from_latest_user_message_and_positions(self):
        prompt = """账户概况:
- 账户总金额: 100000

当前持仓:
- 510300 沪深300ETF | 份额 1000 | 成本 4.0000 | 现价 4.1000 | 盈亏 2.50% | 市值 4100
- 518880 黄金ETF | 份额 500 | 成本 5.0000 | 现价 5.2000 | 盈亏 4.00% | 市值 2600

用户最新问题:
最近黄金还能不能加仓？
"""
        queries = ZhipuClient._build_search_queries(prompt)

        self.assertGreaterEqual(len(queries), 1)
        self.assertIn("最近黄金还能不能加仓", queries[0])
        self.assertIn("最新", queries[0])


if __name__ == "__main__":
    unittest.main()

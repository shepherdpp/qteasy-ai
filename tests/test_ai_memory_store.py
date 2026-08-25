# coding=utf-8
# ======================================
# File: test_ai_memory_store.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# Unittest for qteasy ai memory store
# ======================================

import tempfile
import unittest

from qteasy_ai.memory_store import MemoryStore, merge_env_facts


class TestAiMemoryStore(unittest.TestCase):
    """测试 profile/env_facts/runs 最小落盘。"""

    def test_merge_env_facts_deep_merge_tables(self) -> None:
        """验证 merge_env_facts 深合并 tables 并刷新 updated_at。"""

        old = {
            "tushare": {"token_present": False, "token_source": "missing"},
            "tables": {
                "stock_daily": {"exists": True, "rows": 10},
                "index_daily": {"exists": False, "rows": 0},
            },
            "updated_at": "2020-01-01T00:00:00Z",
        }
        probe = {
            "tushare": {"token_present": True, "token_source": "qt_config"},
            "tables": {
                "index_daily": {"exists": True, "rows": 42, "pk_min": "20200101"},
                "trade_calendar": {"exists": True, "rows": 100},
            },
        }
        print("\n[TestAiMemoryStore] merge before:", old)
        print(" probe:", probe)
        merged = merge_env_facts(old, probe)
        print(" merge after:", merged)

        self.assertTrue(merged["tushare"]["token_present"])
        self.assertEqual(merged["tushare"]["token_source"], "qt_config")
        self.assertEqual(merged["tables"]["stock_daily"]["rows"], 10)
        self.assertEqual(merged["tables"]["index_daily"]["rows"], 42)
        self.assertTrue(merged["tables"]["index_daily"]["exists"])
        self.assertEqual(merged["tables"]["index_daily"]["pk_min"], "20200101")
        self.assertEqual(merged["tables"]["trade_calendar"]["rows"], 100)
        self.assertNotEqual(merged["updated_at"], "2020-01-01T00:00:00Z")
        self.assertTrue(str(merged["updated_at"]).endswith("Z"))

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            store.save_env_facts(merged)
            loaded = store.load_env_facts()
            print(" loaded after save:", loaded)
            self.assertEqual(loaded["tables"]["index_daily"]["rows"], 42)

    def test_memory_read_write_cycle(self) -> None:
        """验证记忆文件读写和 runs 列表。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            store.save_profile({"favorite_symbol": "000300.SH"})
            store.save_env_facts({"python": "3.9"})
            run_path = store.save_run("run_demo", {"status": "ok"})
            profile = store.load_profile()
            env_facts = store.load_env_facts()
            run_data = store.load_run("run_demo")
            run_ids = store.list_runs()

            print("\n[TestAiMemoryStore] run path:", run_path)
            print(" profile:", profile)
            print(" env_facts:", env_facts)
            print(" run_ids:", run_ids)

            self.assertEqual(profile["favorite_symbol"], "000300.SH")
            self.assertEqual(env_facts["python"], "3.9")
            self.assertEqual(run_data["status"], "ok")
            self.assertIn("run_demo", run_ids)


if __name__ == "__main__":
    unittest.main()

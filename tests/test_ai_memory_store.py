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

    def test_corrupt_env_facts_falls_back_to_default(self) -> None:
        """损坏的 env_facts.json 应降级为空字典并备份。"""

        print("\n[TestAiMemoryStore] corrupt env_facts fallback")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            corrupt_path = store.env_facts_path
            corrupt_path.write_text(
                '{\n  "tables": {\n    "trade_calendar": {\n      "pk_min": ',
                encoding="utf-8",
            )
            loaded = store.load_env_facts()
            backup = corrupt_path.with_suffix(corrupt_path.suffix + ".corrupt.json")
            print(" loaded:", loaded)
            print(" backup exists:", backup.exists(), backup)
            self.assertEqual(loaded, {})
            self.assertTrue(backup.exists())
            self.assertFalse(corrupt_path.exists())

    def test_save_env_facts_with_date_values(self) -> None:
        """env_facts 含 date 对象时应可序列化落盘。"""

        from datetime import date

        print("\n[TestAiMemoryStore] save env_facts with date")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            store.save_env_facts(
                {
                    "tables": {
                        "trade_calendar": {
                            "exists": True,
                            "rows": 10,
                            "pk_min": date(1990, 12, 19),
                            "pk_max": date(2026, 8, 25),
                        }
                    }
                }
            )
            loaded = store.load_env_facts()
            print(" loaded:", loaded)
            self.assertEqual(loaded["tables"]["trade_calendar"]["pk_min"], "1990-12-19")
            self.assertEqual(loaded["tables"]["trade_calendar"]["pk_max"], "2026-08-25")


if __name__ == "__main__":
    unittest.main()

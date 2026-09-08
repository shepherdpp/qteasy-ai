# coding=utf-8
# ======================================
# File: test_ai_workbench_journey.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-07
# Desc:
# Unittest for G.5 Catalog + HTTP Beginner Journey
# ======================================

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.workbench.http_app import create_app

_CORPUS = Path(__file__).resolve().parent / "ai_corpus" / "beginner_journey.json"
_CATALOG = Path(__file__).resolve().parents[1] / "docs" / "OFFICIAL_SKILL_CATALOG.md"


def _load_cases() -> List[Dict[str, Any]]:
    """读取 Beginner Journey 语料。"""

    with _CORPUS.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return list(payload.get("cases") or [])


class TestAiWorkbenchJourney(unittest.TestCase):
    """G.5：Catalog 对照 registry；Journey 走 HTTP plan_only。"""

    def test_catalog_covers_registry_p0(self) -> None:
        """Catalog 文档含全部 registry 注册名（无 P0 缺口）。"""

        print("\n[TestAiWorkbenchJourney] catalog vs registry")
        text = _CATALOG.read_text(encoding="utf-8")
        catalog_names = set(re.findall(r"`(qt\.ai\.[a-z0-9_.]+)`", text))
        registry_names = {meta.name for meta in build_default_registry().list_skills()}
        missing = sorted(registry_names - catalog_names)
        extra_ok = catalog_names - registry_names
        print(" registry:", sorted(registry_names))
        print(" catalog n:", len(catalog_names), "missing:", missing)
        print(" catalog-only:", sorted(extra_ok)[:12])
        self.assertFalse(missing, msg=f"P0 catalog gaps: {missing}")
        self.assertIn("qt.ai.data.read", catalog_names)
        self.assertIn("qt.ai.backtest.run_builtin", catalog_names)

    def test_http_beginner_journey_plan_only(self) -> None:
        """HTTP 表驱动 Journey：Ask 命中 KB；plan 一律 dry_run。"""

        print("\n[TestAiWorkbenchJourney] http journey")
        from starlette.testclient import TestClient

        cases = _load_cases()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            print(" user_kb:", store.user_kb_dir, "ok:", store.user_kb_partitions_ok())
            self.assertTrue(store.user_kb_partitions_ok())
            app = create_app(memory_store=store)
            print(" create_app user_kb still ok:", store.user_kb_partitions_ok())
            self.assertTrue(store.user_kb_partitions_ok())
            # 与 CLI 共用同一 store；显式注入 registry 与默认装配一致
            app = create_app(
                assistant=QteasyAssistant(memory_store=store, registry=build_default_registry())
            )
            client = TestClient(app)
            for case in cases:
                case_id = str(case.get("id") or "")
                query = str(case.get("query") or "")
                mode = str(case.get("mode") or "plan")
                if mode == "ask":
                    body = client.post("/v1/ask", json={"query": query}).json()
                    print(" ask", case_id, "sources:", body.get("sources"), "mode:", body.get("mode"))
                    self.assertEqual(body.get("mode"), "ask", msg=case_id)
                    self.assertIn("what_is_qteasy", body.get("sources") or [], msg=case_id)
                    continue
                body = client.post("/v1/plan", json={"query": query}).json()
                expected = str(case.get("expected_job") or "")
                if expected == "route_to_ask":
                    print(" plan", case_id, "routed mode:", body.get("mode"), "sources:", body.get("sources"))
                    self.assertEqual(body.get("mode"), "ask", msg=case_id)
                    continue
                job = ((body.get("sidebar") or {}).get("active_intent") or {}).get("job")
                status = (body.get("execution") or {}).get("status")
                print(" plan", case_id, "job:", job, "expected:", expected, "status:", status)
                self.assertEqual(status, "dry_run", msg=case_id)
                if expected:
                    self.assertEqual(job, expected, msg=case_id)
            ask_again = client.post("/v1/ask", json={"query": "什么是 qteasy"}).json()
            print(" ask not using user_kb, sources:", ask_again.get("sources"))
            self.assertIn("what_is_qteasy", ask_again.get("sources") or [])


if __name__ == "__main__":
    unittest.main()

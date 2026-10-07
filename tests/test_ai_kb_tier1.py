# coding=utf-8
# ======================================
# File: test_ai_kb_tier1.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-05
# Desc:
# Unittest for official KB Pack tier-1 (F.5)
# ======================================

import json
import tempfile
import unittest
from pathlib import Path

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.knowledge_base import KnowledgeBase
from qteasy_ai.memory_store import MemoryStore

_KB_DIR = Path(__file__).resolve().parents[1] / "qteasy_ai" / "kb"

_CARRIED = {
    "pt_ps_vs",
    "operator_run_freq",
    "ask_plan_agent",
    "side_effects_safety",
    "common_errors_nan",
    "common_errors_run_freq",
    "common_errors_date_window",
}

_NEW = {
    "what_is_qteasy",
    "getting_started",
    "data_three_entries",
    "backtest_intro",
    "optimize_intro",
    "refill_bounded",
    "strategy_builder_intro",
    "env_ready",
    "notebook_cli",
    "live_plan_only",
    "official_vs_user_kb",
}

_WHAT_QUERIES = (
    "什么是qteasy",
    "什么是 qteasy",
    "what is qteasy",
    "qteasy 是什么",
)

_F5_IDS = _CARRIED | _NEW
_LEGAL_TYPES = {"concept", "trap", "boundary", "pointer"}


def _write_probe(directory: str, payload: dict) -> None:
    """在临时目录写一条探针 JSON。"""

    path = Path(directory) / f"{payload['id']}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestAiKbTier1(unittest.TestCase):
    """官方 KB 子集与产品入门命中。"""

    def test_pack_size_and_ids(self) -> None:
        """F.5 十八 id 仍为官方库子集；总条数可超过原 15–25。"""

        print("\n[TestAiKbTier1] F.5 ids remain a subset")
        ids = sorted(path.stem for path in _KB_DIR.glob("*.json"))
        print(" ids:", ids)
        print(" count:", len(ids))
        print(" f5 missing:", sorted(_F5_IDS - set(ids)))
        self.assertTrue(_F5_IDS.issubset(set(ids)))
        self.assertIn("what_is_qteasy", ids)

    def test_loaded_entries_have_legal_type(self) -> None:
        """实库每条 type 属于 concept|trap|boundary|pointer。"""

        print("\n[TestAiKbTier1] loaded entry types")
        kb = KnowledgeBase()
        rows = [(entry.id, entry.type) for entry in kb._entries]
        print(" types:", rows)
        self.assertTrue(rows)
        for entry_id, entry_type in rows:
            self.assertIn(entry_type, _LEGAL_TYPES, msg=entry_id)

    def test_loader_rejects_illegal_type_and_relation(self) -> None:
        """未知 type、缺 type、非法 rel 失败；pointer 可加载。"""

        print("\n[TestAiKbTier1] loader type and relation checks")
        base = {
            "title": "Probe",
            "summary": "probe",
            "narrative": "probe",
        }
        rejected = (
            {"id": "probe_live", "type": "live", **base},
            {"id": "probe_missing", **base},
            {
                "id": "probe_rel",
                "type": "concept",
                "relations": [{"rel": "parent", "to": "what_is_qteasy"}],
                **base,
            },
        )
        for payload in rejected:
            with tempfile.TemporaryDirectory() as temp_dir:
                _write_probe(temp_dir, payload)
                with self.assertRaises(ValueError) as ctx:
                    KnowledgeBase(kb_dir=temp_dir)
                print(" rejected:", payload["id"], ctx.exception)

        with tempfile.TemporaryDirectory() as temp_dir:
            _write_probe(temp_dir, {"id": "probe_pointer", "type": "pointer", **base})
            kb = KnowledgeBase(kb_dir=temp_dir)
            loaded = [(entry.id, entry.type) for entry in kb._entries]
            print(" pointer load:", loaded)
            self.assertEqual(loaded, [("probe_pointer", "pointer")])

    def test_what_is_qteasy_ask_hits(self) -> None:
        """Mode-R Ask 产品入门不再 NOT_FOUND；零 skill。"""

        print("\n[TestAiKbTier1] what is qteasy")
        kb = KnowledgeBase()
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                registry=build_default_registry(),
            )
            for query in _WHAT_QUERIES:
                hits = kb.retrieve(query)
                payload = assistant.ask(query, response_style="raw")
                ids = [item.id for item in hits]
                print(" query:", query, "retrieve:", ids, "ask sources:", payload.get("sources"))
                print(" error:", payload.get("error"))
                self.assertTrue(ids, msg=query)
                self.assertIn("what_is_qteasy", ids, msg=query)
                self.assertTrue(payload.get("ok"), msg=query)
                self.assertIn("what_is_qteasy", payload.get("sources") or [], msg=query)
                self.assertNotIn("execution", payload)
                self.assertNotEqual((payload.get("error") or {}).get("code"), "NOT_FOUND")

    def test_coverage_getting_started_data_backtest_optimize(self) -> None:
        """入门 / 三入口 / 回测 / 优化各至少一条。"""

        print("\n[TestAiKbTier1] coverage queries")
        kb = KnowledgeBase()
        cases = (
            ("getting started", "getting_started"),
            ("get_history_data get_reference_data get_static_data", "data_three_entries"),
            ("how to backtest", "backtest_intro"),
            ("how to optimize", "optimize_intro"),
        )
        for query, expected in cases:
            hits = kb.retrieve(query)
            ids = [item.id for item in hits]
            print(" query:", query, "ids:", ids)
            self.assertIn(expected, ids, msg=query)

    def test_ask_still_zero_skill(self) -> None:
        """不改 Ask 零 skill 契约。"""

        print("\n[TestAiKbTier1] zero skill")
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                registry=build_default_registry(),
            )
            payload = assistant.ask("what is qteasy", response_style="raw")
            print(" keys:", sorted(payload.keys()))
            self.assertEqual(payload["mode"], "ask")
            self.assertNotIn("execution", payload)
            self.assertNotIn("plan", payload)


if __name__ == "__main__":
    unittest.main()

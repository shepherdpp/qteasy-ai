# coding=utf-8
# ======================================
# File: test_ai_user_kb_scaffold.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-05
# Desc:
# Unittest for user_kb scaffold (F.6)
# ======================================

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.knowledge_base import KnowledgeBase
from qteasy_ai.memory_store import USER_KB_RAW_PARTS, MemoryStore


class TestAiUserKbScaffold(unittest.TestCase):
    """用户 KB 骨架：分区、空 compile、Ask 不检索。"""

    def test_first_init_creates_partitions_and_readme(self) -> None:
        """首次 MemoryStore 初始化落下必有分区与英文 README。"""

        print("\n[TestAiUserKbScaffold] first init partitions")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            print(" user_kb_dir:", store.user_kb_dir)
            print(" partitions ok:", store.user_kb_partitions_ok())
            self.assertTrue(store.user_kb_dir.is_dir())
            self.assertTrue((store.user_kb_dir / "rules").is_dir())
            self.assertTrue((store.user_kb_dir / "compiled").is_dir())
            for part in USER_KB_RAW_PARTS:
                path = store.user_kb_dir / "raw" / part
                print(" raw part:", path)
                self.assertTrue(path.is_dir())
            readme = (store.user_kb_dir / "README.md").read_text(encoding="utf-8")
            print(" readme head:", readme.splitlines()[:3])
            self.assertIn("Ask mode", readme)
            self.assertIn("official", readme.lower())
            self.assertTrue(store.user_kb_partitions_ok())
            extra = store.user_kb_dir / "raw" / "notes"
            extra.mkdir()
            print(" extra allowed:", extra.exists())
            self.assertTrue(store.user_kb_partitions_ok())

    def test_missing_required_partition_fails(self) -> None:
        """删掉必有分区则检查失败。"""

        print("\n[TestAiUserKbScaffold] missing partition")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            shutil.rmtree(store.user_kb_dir / "rules")
            print(" partitions ok after delete:", store.user_kb_partitions_ok())
            self.assertFalse(store.user_kb_partitions_ok())

    def test_empty_compile_writes_catalog(self) -> None:
        """空库 compile 产出合法空 catalog。"""

        print("\n[TestAiUserKbScaffold] empty compile")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            catalog = store.compile_user_kb()
            path = store.user_kb_dir / "compiled" / "catalog.json"
            print(" catalog:", catalog)
            print(" path exists:", path.exists())
            self.assertEqual(catalog["entries"], [])
            self.assertEqual(catalog["version"], 1)
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            print(" on_disk:", on_disk)
            self.assertEqual(on_disk["entries"], [])

    def test_ask_does_not_search_user_kb(self) -> None:
        """Ask 同一进程不检索 user_kb；官方 kb 不被写入。"""

        print("\n[TestAiUserKbScaffold] ask ignores user_kb")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            decoy = store.user_kb_dir / "raw" / "research" / "decoy.json"
            decoy.write_text(
                json.dumps(
                    {
                        "id": "user_decoy_pt",
                        "keywords": ["pt", "ps", "vs", "explain"],
                        "title": "user decoy",
                        "narrative": "THIS IS USER DECOY AND MUST NOT APPEAR IN ASK",
                    }
                ),
                encoding="utf-8",
            )
            official_dir = Path(__file__).resolve().parents[1] / "qteasy_ai" / "kb"
            before = {path.name for path in official_dir.glob("*.json")}
            assistant = QteasyAssistant(memory_store=store, registry=build_default_registry())
            payload = assistant.ask("explain PT vs PS", response_style="raw")
            print(" sources:", payload.get("sources"))
            print(" answer head:", str(payload.get("answer", ""))[:160])
            self.assertNotIn("user_decoy_pt", payload.get("sources") or [])
            self.assertNotIn("USER DECOY", str(payload.get("answer") or ""))
            self.assertIn("pt_ps_vs", payload.get("sources") or [])
            after = {path.name for path in official_dir.glob("*.json")}
            print(" official kb unchanged:", before == after)
            self.assertEqual(before, after)
            kb_ids = [item.id for item in KnowledgeBase().retrieve("explain PT vs PS")]
            print(" official retrieve ids:", kb_ids)
            self.assertNotIn("user_decoy_pt", kb_ids)


if __name__ == "__main__":
    unittest.main()

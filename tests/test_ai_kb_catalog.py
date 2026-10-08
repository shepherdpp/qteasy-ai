# coding=utf-8
# ======================================
# File: test_ai_kb_catalog.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-07
# Desc:
# A3 策展地图、compile 生成物与目录第一检索
# ======================================

import json
import tempfile
import unittest
from pathlib import Path

from qteasy_ai.kb_catalog import (
    compile_catalog,
    dumps_catalog_json,
    normalize_question,
)
from qteasy_ai.knowledge_base import KnowledgeBase

_REPO = Path(__file__).resolve().parents[1]
_KB_DIR = _REPO / "qteasy_ai" / "kb"
_MAP_PATH = _KB_DIR / "_source" / "curation_map.json"
_GENERATED = _KB_DIR / "_generated"
_QTEASY_ROOT = _REPO.parent / "qteasy"
_REGISTRY_PATH = _KB_DIR / "_source" / "topic_registry.json"
_STARTER_TOPIC_IDS = (
    "capability",
    "onboarding",
    "data-downloading",
    "data-analysis",
    "strategy",
    "backtest",
    "optimize",
    "live_boundary",
)


def _write_topic_registry(source_dir: Path, topic_ids=("capability",)) -> None:
    """在临时 ``_source`` 写一份最小主题注册表。"""

    payload = {
        "topics": [{"id": topic_id, "scope": f"scope for {topic_id}"} for topic_id in topic_ids],
    }
    (source_dir / "topic_registry.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

_BACKTEST_QUESTIONS = (
    "如何用 qteasy 回测",
    "怎么回测",
    "how to backtest",
    "回测入门",
    "backtest intro",
    "run backtest",
)

# 这些原句必须留在目录外，证明未命中时仍走分型关键词。
_OUTSIDE_CATALOG = (
    "where does run_freq belong",
    "explain PT vs PS",
    "what is macd strategy",
    "list built-in strategies",
    "帮我写一个双均线策略",
)


class TestAiKbCatalog(unittest.TestCase):
    """策展地图与问句目录。"""

    def test_map_matches_json_and_generated_files(self) -> None:
        """地图行与 JSON 一致，且磁盘生成物等于 compile 内存结果。"""

        print("\n[TestAiKbCatalog] 地图与生成物一致")
        artifacts = compile_catalog(
            kb_dir=_KB_DIR,
            map_path=_MAP_PATH,
            qteasy_root=_QTEASY_ROOT,
        )
        payload = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
        rows = {row["id"]: row for row in payload["entries"]}
        json_ids = sorted(path.stem for path in _KB_DIR.glob("*.json"))
        print(" map ids:", sorted(rows))
        print(" json ids:", json_ids)
        self.assertEqual(sorted(rows), json_ids)
        self.assertEqual(len(json_ids), 18)

        for entry_id in json_ids:
            entry = json.loads((_KB_DIR / f"{entry_id}.json").read_text(encoding="utf-8"))
            row = rows[entry_id]
            print(
                " row:",
                entry_id,
                row["type"],
                row.get("manual_anchor", ""),
                "questions:",
                len(row["questions"]),
            )
            self.assertEqual(row["type"], entry["type"])
            self.assertEqual(row["topics"], entry["topics"])
            self.assertEqual(row["manual_anchor"], entry["manual_anchor"])
            self.assertEqual(row["relations"], entry["relations"])
            self.assertTrue(row["questions"])

        backtest_questions = rows["backtest_intro"]["questions"]
        print(" backtest questions:", backtest_questions)
        for question in _BACKTEST_QUESTIONS:
            self.assertIn(question, backtest_questions)

        catalog_path = _GENERATED / "question_catalog.json"
        index_path = _GENERATED / "type_index.json"
        markdown_path = _GENERATED / "CATALOG.md"
        catalog_text = catalog_path.read_text(encoding="utf-8")
        index_text = index_path.read_text(encoding="utf-8")
        markdown = markdown_path.read_text(encoding="utf-8")
        print(" catalog keys:", len(artifacts.question_catalog["questions"]))
        print(" type index:", {key: len(value) for key, value in artifacts.type_index["by_type"].items()})
        self.assertEqual(catalog_text, dumps_catalog_json(artifacts.question_catalog))
        self.assertEqual(index_text, dumps_catalog_json(artifacts.type_index))
        self.assertEqual(markdown, artifacts.catalog_markdown)
        self.assertEqual(artifacts.type_index["by_type"]["pointer"], [])
        self.assertNotIn("dry-run", markdown)
        self.assertNotIn("narrative", markdown.lower())
        self.assertIn("- topics: backtest", markdown)
        self.assertIn("- topics: capability, live_boundary", markdown)

    def test_dangling_relation_fails(self) -> None:
        """relation.to 指向不存在的官方 id 时 compile 失败。"""

        print("\n[TestAiKbCatalog] 悬空 relation")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            kb_dir = root / "kb"
            kb_dir.mkdir()
            entry = {
                "id": "solo_card",
                "title": "Solo",
                "summary": "probe",
                "narrative": "probe",
                "type": "concept",
                "topics": ["capability"],
                "manual_anchor": "",
                "relations": [{"rel": "see_also", "to": "missing_card"}],
                "tags": [],
                "keywords": [],
            }
            (kb_dir / "solo_card.json").write_text(
                json.dumps(entry, ensure_ascii=False),
                encoding="utf-8",
            )
            source = kb_dir / "_source"
            source.mkdir()
            curation = {
                "entries": [
                    {
                        "id": "solo_card",
                        "type": "concept",
                        "topics": ["capability"],
                        "manual_anchor": "",
                        "questions": ["solo question"],
                        "relations": [{"rel": "see_also", "to": "missing_card"}],
                    }
                ]
            }
            map_path = source / "curation_map.json"
            map_path.write_text(json.dumps(curation, ensure_ascii=False), encoding="utf-8")
            _write_topic_registry(source)
            with self.assertRaises(ValueError) as ctx:
                compile_catalog(kb_dir=kb_dir, map_path=map_path, qteasy_root=root)
            print(" error:", ctx.exception)
            self.assertIn("missing_card", str(ctx.exception))

    def test_catalog_gold_questions_pin_backtest_intro(self) -> None:
        """目录内回测金句定条为 backtest_intro，不落到 what_is_qteasy。"""

        print("\n[TestAiKbCatalog] 回测金句定条")
        kb = KnowledgeBase(
            list_func=lambda: ["macd", "dma"],
            doc_func=lambda sid: f"{sid} tunable parameters: fast, slow, signal.",
        )
        queries = _BACKTEST_QUESTIONS + ("How to backtest?",)
        for query in queries:
            hits = kb.retrieve(query)
            ids = [item.id for item in hits]
            print(" query:", query, "ids:", ids, "scores:", [(item.id, item.score) for item in hits])
            self.assertEqual(ids, ["backtest_intro"])

    def test_cjk_latin_boundary_space_is_same_catalog_key(self) -> None:
        """中英交界空格可有可无，两句定同一条。英文单词之间的空格保留。"""

        print("\n[TestAiKbCatalog] 中英交界空格同一键")
        spaced = "如何用 qteasy 回测？"
        tight = "如何用qteasy回测？"
        spaced_key = normalize_question(spaced)
        tight_key = normalize_question(tight)
        english_key = normalize_question("How to backtest?")
        print(" spaced key:", spaced_key)
        print(" tight key:", tight_key)
        print(" english key:", english_key)
        self.assertEqual(spaced_key, tight_key)
        self.assertEqual(spaced_key, "如何用qteasy回测")
        self.assertIn(" ", english_key)
        self.assertEqual(english_key, "how to backtest")

        kb = KnowledgeBase(
            list_func=lambda: ["macd", "dma"],
            doc_func=lambda sid: f"{sid} tunable parameters: fast, slow, signal.",
        )
        for query in (spaced, tight, "how to backtest"):
            hits = kb.retrieve(query)
            ids = [item.id for item in hits]
            print(" query:", query, "ids:", ids)
            self.assertEqual(ids, ["backtest_intro"])

    def test_cross_id_normalized_question_fails(self) -> None:
        """不同 id 规范化成同一键时 compile 失败。"""

        print("\n[TestAiKbCatalog] 异 id 规范键冲突")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            kb_dir = root / "kb"
            kb_dir.mkdir()
            rows = []
            for entry_id, question in (
                ("card_spaced", "用 qteasy"),
                ("card_tight", "用qteasy"),
            ):
                entry = {
                    "id": entry_id,
                    "title": entry_id,
                    "summary": "probe",
                    "narrative": "probe",
                    "type": "concept",
                    "topics": ["capability"],
                    "manual_anchor": "",
                    "relations": [],
                    "tags": [],
                    "keywords": [],
                }
                (kb_dir / f"{entry_id}.json").write_text(
                    json.dumps(entry, ensure_ascii=False),
                    encoding="utf-8",
                )
                rows.append({
                    "id": entry_id,
                    "type": "concept",
                    "topics": ["capability"],
                    "manual_anchor": "",
                    "questions": [question],
                    "relations": [],
                })
            source = kb_dir / "_source"
            source.mkdir()
            map_path = source / "curation_map.json"
            map_path.write_text(
                json.dumps({"entries": rows}, ensure_ascii=False),
                encoding="utf-8",
            )
            _write_topic_registry(source)
            with self.assertRaises(ValueError) as ctx:
                compile_catalog(kb_dir=kb_dir, map_path=map_path, qteasy_root=root)
            print(" error:", ctx.exception)
            self.assertIn("用qteasy", str(ctx.exception))
            self.assertIn("card_spaced", str(ctx.exception))
            self.assertIn("card_tight", str(ctx.exception))

    def test_outside_catalog_still_uses_keywords(self) -> None:
        """目录外 run_freq 原句仍独占 operator_run_freq。"""

        print("\n[TestAiKbCatalog] 目录外走关键词")
        artifacts = compile_catalog(
            kb_dir=_KB_DIR,
            map_path=_MAP_PATH,
            qteasy_root=_QTEASY_ROOT,
        )
        questions = artifacts.question_catalog["questions"]
        for query in _OUTSIDE_CATALOG:
            key = normalize_question(query)
            print(" outside key:", key, "in catalog:", key in questions)
            self.assertNotIn(key, questions)

        kb = KnowledgeBase(
            list_func=lambda: ["macd", "dma"],
            doc_func=lambda sid: f"{sid} tunable parameters: fast, slow, signal.",
        )
        query = "where does run_freq belong, Operator or qt.run?"
        hits = kb.retrieve(query)
        ids = [item.id for item in hits]
        key = normalize_question(query)
        print(" query:", query)
        print(" normalized:", key)
        print(" ids:", ids)
        print(" in catalog:", key in questions)
        self.assertNotIn(key, questions)
        self.assertEqual(ids, ["operator_run_freq"])

    def test_starter_registry_has_eight_topics_and_no_single_data(self) -> None:
        """起步注册表是计划里的八个 id，没有单一 data。"""

        print("\n[TestAiKbCatalog] 起步主题注册表")
        payload = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        ids = [row["id"] for row in payload["topics"]]
        print(" topic ids:", ids)
        self.assertEqual(ids, list(_STARTER_TOPIC_IDS))
        self.assertNotIn("data", ids)
        kb = KnowledgeBase()
        live_ids = [entry.id for entry in kb.menu_for_topics(["live_boundary"])]
        download_ids = [entry.id for entry in kb.menu_for_topics(["data-downloading"])]
        print(" live_boundary menu:", live_ids)
        print(" data-downloading menu:", download_ids)
        self.assertEqual(live_ids, ["live_plan_only", "side_effects_safety"])
        self.assertIn("refill_bounded", download_ids)
        self.assertNotIn("data_three_entries", download_ids)

    def test_unknown_topic_fails_compile_and_load(self) -> None:
        """未知主题在 compile 与加载时都失败。"""

        print("\n[TestAiKbCatalog] 未知主题失败")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            kb_dir = root / "kb"
            kb_dir.mkdir()
            entry = {
                "id": "solo_card",
                "title": "Solo",
                "summary": "probe",
                "narrative": "probe",
                "type": "concept",
                "topics": ["not-a-topic"],
                "manual_anchor": "",
                "relations": [],
            }
            (kb_dir / "solo_card.json").write_text(
                json.dumps(entry, ensure_ascii=False),
                encoding="utf-8",
            )
            source = kb_dir / "_source"
            source.mkdir()
            curation = {
                "entries": [
                    {
                        "id": "solo_card",
                        "type": "concept",
                        "topics": ["not-a-topic"],
                        "manual_anchor": "",
                        "questions": ["solo question"],
                        "relations": [],
                    }
                ]
            }
            (source / "curation_map.json").write_text(
                json.dumps(curation, ensure_ascii=False),
                encoding="utf-8",
            )
            _write_topic_registry(source, ("capability",))
            with self.assertRaises(ValueError) as ctx:
                compile_catalog(
                    kb_dir=kb_dir,
                    map_path=source / "curation_map.json",
                    qteasy_root=root,
                )
            print(" compile error:", ctx.exception)
            self.assertIn("not-a-topic", str(ctx.exception))
            self.assertIn("solo_card", str(ctx.exception))
            with self.assertRaises(ValueError) as load_ctx:
                KnowledgeBase(kb_dir=kb_dir)
            print(" load error:", load_ctx.exception)
            self.assertIn("not-a-topic", str(load_ctx.exception))

    def test_topics_mismatch_fails_compile(self) -> None:
        """地图与 JSON 的 topics 不一致时 compile 失败。"""

        print("\n[TestAiKbCatalog] topics 不一致")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            kb_dir = root / "kb"
            kb_dir.mkdir()
            entry = {
                "id": "solo_card",
                "title": "Solo",
                "summary": "probe",
                "narrative": "probe",
                "type": "concept",
                "topics": ["onboarding"],
                "manual_anchor": "",
                "relations": [],
            }
            (kb_dir / "solo_card.json").write_text(
                json.dumps(entry, ensure_ascii=False),
                encoding="utf-8",
            )
            source = kb_dir / "_source"
            source.mkdir()
            curation = {
                "entries": [
                    {
                        "id": "solo_card",
                        "type": "concept",
                        "topics": ["capability"],
                        "manual_anchor": "",
                        "questions": ["solo question"],
                        "relations": [],
                    }
                ]
            }
            (source / "curation_map.json").write_text(
                json.dumps(curation, ensure_ascii=False),
                encoding="utf-8",
            )
            _write_topic_registry(source, ("capability", "onboarding"))
            with self.assertRaises(ValueError) as ctx:
                compile_catalog(
                    kb_dir=kb_dir,
                    map_path=source / "curation_map.json",
                    qteasy_root=root,
                )
            print(" error:", ctx.exception)
            self.assertIn("topics mismatch", str(ctx.exception))
            self.assertIn("solo_card", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

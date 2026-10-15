# coding=utf-8
# ======================================
# File: test_ai_paraphrase_gold.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-10
# Desc:
# P1 同义句表：无模型只验收 gold，有模型替身验收 paraphrases
# ======================================

import json
import unittest
from pathlib import Path

from qteasy_ai.ask_engine import AskEngine
from qteasy_ai.kb_catalog import normalize_question
from qteasy_ai.knowledge_base import KnowledgeBase
from qteasy_ai.provider import FakeLLMProvider

_REPO = Path(__file__).resolve().parents[1]
_KB_DIR = _REPO / "qteasy_ai" / "kb"
_MAP_PATH = _KB_DIR / "_source" / "curation_map.json"
_GOLD_PATH = _KB_DIR / "_source" / "paraphrase_gold.json"
_CATALOG_PATH = _KB_DIR / "_generated" / "question_catalog.json"
_FOLLOWUP_PHRASES = ("第二项", "你刚才说的")
_BACKTEST_PARAPHRASES = ("如何用qteasy回测", "如何用qteasy进行回测")
_WRITER_ANSWER = "This answer only explains the selected card."


def _load_entries(path: Path) -> list:
    """读取 ``entries`` 列表。文件不存在时由调用方的测试失败。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload["entries"]
    if not isinstance(entries, list):
        raise AssertionError(f"{path.name} entries must be a list")
    return entries


class TestAiParaphraseGold(unittest.TestCase):
    """人手维护的同义句表，与策展地图对齐，分轨验收。"""

    def test_table_aligns_with_map_and_stays_out_of_catalog(self) -> None:
        """每个地图 id 一行；gold 对齐问句；同义句不写入问句目录。"""

        print("\n[TestAiParaphraseGold] 同义句表与地图对齐，且不进问句目录")
        map_rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        gold_rows = _load_entries(_GOLD_PATH)
        gold_ids = [row["id"] for row in gold_rows]
        print(" map ids:", sorted(map_rows))
        print(" gold ids:", gold_ids)
        self.assertEqual(sorted(gold_ids), sorted(map_rows))
        self.assertEqual(len(gold_ids), len(set(gold_ids)))

        catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))["questions"]
        gold_keys = set()
        for row in gold_rows:
            entry_id = row["id"]
            questions = map_rows[entry_id]["questions"]
            gold = row["gold"]
            paraphrases = row["paraphrases"]
            expect_ids = row["expect_ids"]
            print(" row:", entry_id)
            print(" gold:", gold)
            print(" map questions:", questions)
            print(" paraphrases:", paraphrases)
            print(" expect_ids:", expect_ids)
            self.assertEqual(gold, questions)
            self.assertTrue(paraphrases)
            gold_surface = {item.strip() for item in gold}
            for phrase in paraphrases:
                self.assertIsInstance(phrase, str)
                self.assertNotIn(phrase.strip(), gold_surface)
                self.assertTrue(phrase.strip())
                for banned in _FOLLOWUP_PHRASES:
                    self.assertNotIn(banned, phrase)
            for question in gold:
                for banned in _FOLLOWUP_PHRASES:
                    self.assertNotIn(banned, question)
                gold_keys.add(normalize_question(question))
            self.assertEqual(expect_ids, [entry_id])
            self.assertLessEqual(len(expect_ids), 3)
            self.assertIn(entry_id, expect_ids)
            self.assertEqual(expect_ids[0], entry_id)

        backtest = next(row for row in gold_rows if row["id"] == "backtest_intro")
        print(" backtest paraphrases:", backtest["paraphrases"])
        for phrase in _BACKTEST_PARAPHRASES:
            self.assertIn(phrase, backtest["paraphrases"])

        spaced = normalize_question("如何用 qteasy 回测")
        compact = normalize_question("如何用qteasy回测")
        print(" spaced gold key:", spaced, "->", catalog.get(spaced))
        print(" compact paraphrase key:", compact, "->", catalog.get(compact))
        self.assertEqual(spaced, compact)
        self.assertEqual(catalog[compact], "backtest_intro")

        for row in gold_rows:
            for phrase in row["paraphrases"]:
                key = normalize_question(phrase)
                print(" paraphrase key:", key, "in gold keys:", key in gold_keys, "catalog:", catalog.get(key))
                if key not in gold_keys:
                    self.assertNotIn(key, catalog)

    def test_offline_gold_hits_primary_card(self) -> None:
        """无 Provider 只跑 gold，sources 第一张是本行 id。"""

        print("\n[TestAiParaphraseGold] 无模型只验收金句")
        engine = AskEngine(knowledge_base=KnowledgeBase())
        self.assertIsNone(engine.provider)
        for row in _load_entries(_GOLD_PATH):
            entry_id = row["id"]
            for question in row["gold"]:
                payload = engine.ask(question).to_dict()
                print(" gold question:", question)
                print(" sources:", payload.get("sources"))
                print(" expected primary:", entry_id)
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["mode"], "ask")
                self.assertEqual(payload["sources"][0], entry_id)
                self.assertNotIn("plan_id", payload)
                self.assertNotIn("execution", payload)

    def test_provider_paraphrases_stay_inside_expect_ids(self) -> None:
        """有 Provider 的替身跑全部 paraphrases，sources 不越出 expect_ids。"""

        print("\n[TestAiParaphraseGold] 有模型替身验收同义句")
        map_topics = {row["id"]: row["topics"] for row in _load_entries(_MAP_PATH)}
        kb = KnowledgeBase()
        saw_backtest_sample = False
        for row in _load_entries(_GOLD_PATH):
            entry_id = row["id"]
            topics = map_topics[entry_id]
            expect_ids = row["expect_ids"]
            print(" card:", entry_id, "topics:", topics, "expect_ids:", expect_ids)
            self.assertGreaterEqual(len(topics), 1)
            self.assertLessEqual(len(topics), 2)
            for phrase in row["paraphrases"]:
                fake = FakeLLMProvider(replies=[
                    json.dumps({"topics": topics}, ensure_ascii=False),
                    json.dumps({"ids": expect_ids}, ensure_ascii=False),
                    _WRITER_ANSWER,
                ])
                engine = AskEngine(knowledge_base=kb, provider=fake)
                payload = engine.ask(phrase).to_dict()
                print(" paraphrase:", phrase)
                print(" sources:", payload.get("sources"))
                print(" expected primary:", expect_ids[0])
                print(" prompts:", len(fake.prompts))
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["mode"], "ask")
                self.assertNotIn("execution", payload)
                self.assertNotIn("plan_id", payload)
                self.assertNotIn("plan_id", payload["answer"])
                self.assertEqual(payload["sources"][0], expect_ids[0])
                for source in payload["sources"]:
                    self.assertIn(source, expect_ids)
                self.assertEqual(len(fake.prompts), 3)
                if phrase == "如何用qteasy回测":
                    saw_backtest_sample = True
                    print(" sample sources:", payload["sources"])
                    self.assertEqual(payload["sources"][0], "backtest_intro")
                    self.assertNotIn("what_is_qteasy", payload["sources"])
        print(" saw 如何用qteasy回测:", saw_backtest_sample)
        self.assertTrue(saw_backtest_sample)


if __name__ == "__main__":
    unittest.main()

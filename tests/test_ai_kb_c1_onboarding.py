# coding=utf-8
# ======================================
# File: test_ai_kb_c1_onboarding.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-11
# Desc:
# C1 总览窗口：金句抽检、主题、同义句行、零 skill
# ======================================

import json
import unittest
from pathlib import Path

from qteasy_ai.ask_engine import AskEngine
from qteasy_ai.knowledge_base import KnowledgeBase

_REPO = Path(__file__).resolve().parents[1]
_KB_DIR = _REPO / "qteasy_ai" / "kb"
_MAP_PATH = _KB_DIR / "_source" / "curation_map.json"
_GOLD_PATH = _KB_DIR / "_source" / "paraphrase_gold.json"
_REGISTRY_PATH = _KB_DIR / "_source" / "topic_registry.json"

# 抽检原句是目录里的普通问句。期望 id 是独立金标准。
_SPOT_CHECKS = (
    ("library_map", "qteasy 有哪些模块", ["overview"]),
    ("qteasy_advantages", "为什么用 qteasy 而不是自己写回测", ["overview"]),
    ("capability_map", "你能帮我做什么？", ["capability"]),
    ("install_and_env", "如何安装 TA-Lib", ["onboarding"]),
    ("faq_datasource", "数据库连不上怎么办", ["onboarding"]),
    ("get_help", "如何报告 bug", ["onboarding"]),
    ("getting_started", "一分钟跑通", ["onboarding"]),
    ("what_is_qteasy", "what is qteasy", ["overview"]),
)
_NEW_IDS = (
    "library_map",
    "qteasy_advantages",
    "capability_map",
    "install_and_env",
    "faq_datasource",
    "get_help",
)


def _load_entries(path: Path) -> list:
    """读取 ``entries`` 列表。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload["entries"]
    if not isinstance(entries, list):
        raise AssertionError(f"{path.name} entries must be a list")
    return entries


class TestAiKbC1Onboarding(unittest.TestCase):
    """C1 总览、优势、安装与求助的宽卡抽检。"""

    def test_overview_topic_and_card_topics(self) -> None:
        """overview 已注册且不占编号；抽检卡挂在计划规定的主题上。"""

        print("\n[TestAiKbC1Onboarding] overview 主题与各卡 topics")
        registry = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        topics = {row["id"]: row for row in registry["topics"]}
        print(" topic ids:", list(topics))
        self.assertIn("overview", topics)
        overview = topics["overview"]
        print(" overview:", overview)
        self.assertNotIn("map_item", overview)
        self.assertTrue(str(overview.get("scope") or "").strip())

        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        for entry_id, _question, expected_topics in _SPOT_CHECKS:
            print(" card:", entry_id, "topics:", rows[entry_id]["topics"], "expected:", expected_topics)
            self.assertEqual(rows[entry_id]["topics"], expected_topics)
            entry_path = _KB_DIR / f"{entry_id}.json"
            self.assertTrue(entry_path.is_file(), msg=entry_id)
            entry = json.loads(entry_path.read_text(encoding="utf-8"))
            self.assertEqual(entry["topics"], expected_topics)
            self.assertEqual(entry["type"], "concept")

    def test_new_cards_have_paraphrase_rows(self) -> None:
        """六张新卡在同义句表各有一行，gold 与地图问句相同。"""

        print("\n[TestAiKbC1Onboarding] 新卡同义句行")
        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        gold_rows = {row["id"]: row for row in _load_entries(_GOLD_PATH)}
        for entry_id in _NEW_IDS:
            print(" paraphrase row:", entry_id)
            print(" gold:", gold_rows[entry_id]["gold"])
            print(" map questions:", rows[entry_id]["questions"])
            print(" paraphrases:", gold_rows[entry_id]["paraphrases"])
            print(" expect_ids:", gold_rows[entry_id]["expect_ids"])
            self.assertEqual(gold_rows[entry_id]["gold"], rows[entry_id]["questions"])
            self.assertTrue(gold_rows[entry_id]["paraphrases"])
            self.assertEqual(gold_rows[entry_id]["expect_ids"], [entry_id])

    def test_spot_questions_hit_primary_card_without_plan(self) -> None:
        """无 Provider 金句的 sources 第一张是期望 id，且零 skill、无 plan_id。"""

        print("\n[TestAiKbC1Onboarding] 金句抽检零 skill")
        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        engine = AskEngine(knowledge_base=KnowledgeBase())
        self.assertIsNone(engine.provider)
        for entry_id, question, _topics in _SPOT_CHECKS:
            print(" question in map:", question in rows[entry_id]["questions"])
            self.assertIn(question, rows[entry_id]["questions"])
            payload = engine.ask(question).to_dict()
            print(" question:", question)
            print(" sources:", payload.get("sources"))
            print(" expected primary:", entry_id)
            print(" ok:", payload.get("ok"), "mode:", payload.get("mode"))
            self.assertTrue(payload["ok"], msg=question)
            self.assertEqual(payload["mode"], "ask")
            self.assertTrue(payload.get("sources"), msg=question)
            self.assertEqual(payload["sources"][0], entry_id)
            self.assertNotIn("plan_id", payload)
            self.assertNotIn("plan", payload)
            self.assertNotIn("execution", payload)


if __name__ == "__main__":
    unittest.main()

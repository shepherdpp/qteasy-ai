# coding=utf-8
# ======================================
# File: test_ai_kb_c2_data.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-24
# Desc:
# C2 数据概念：过程金句、主题侧、同义句行、零 skill
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
    ("datatype_lookup", "怎么查一个 DataType", ["data-analysis"]),
    ("data_filter", "怎么按行业筛选股票", ["data-analysis"]),
    ("datasource_local", "什么是 DataSource", ["data-downloading"]),
    ("datasource_local", "怎么看本地已经有哪些数据", ["data-downloading"]),
    ("data_channels", "下载时怎么指定数据通道", ["data-downloading"]),
    ("data_minimum", "起步要下载哪些表", ["data-downloading"]),
    ("data_three_entries", "三入口有什么区别", ["data-analysis"]),
    ("refill_bounded", "帮我下载", ["data-downloading"]),
)
_NEW_IDS = (
    "datatype_lookup",
    "data_filter",
    "datasource_local",
    "data_channels",
    "data_minimum",
)
_MINIMUM_TABLES = (
    "trade_calendar",
    "stock_basic",
    "index_basic",
    "index_daily",
    "stock_daily",
)


def _load_entries(path: Path) -> list:
    """读取 ``entries`` 列表。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload["entries"]
    if not isinstance(entries, list):
        raise AssertionError(f"{path.name} entries must be a list")
    return entries


class TestAiKbC2Data(unittest.TestCase):
    """C2 数据获取、管理、查找、筛选宽卡抽检。"""

    def test_no_single_data_topic_and_card_topics(self) -> None:
        """注册表没有单一 data；抽检卡挂在下载侧或分析侧。"""

        print("\n[TestAiKbC2Data] 主题侧与无单一 data")
        registry = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        topic_ids = [row["id"] for row in registry["topics"]]
        print(" topic ids:", topic_ids)
        self.assertNotIn("data", topic_ids)
        self.assertIn("data-downloading", topic_ids)
        self.assertIn("data-analysis", topic_ids)

        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        seen = set()
        for entry_id, _question, expected_topics in _SPOT_CHECKS:
            if entry_id in seen:
                continue
            seen.add(entry_id)
            print(" card:", entry_id, "topics:", rows[entry_id]["topics"], "expected:", expected_topics)
            self.assertEqual(rows[entry_id]["topics"], expected_topics)
            entry_path = _KB_DIR / f"{entry_id}.json"
            self.assertTrue(entry_path.is_file(), msg=entry_id)
            entry = json.loads(entry_path.read_text(encoding="utf-8"))
            self.assertEqual(entry["topics"], expected_topics)
            self.assertEqual(entry["type"], "concept")

    def test_new_cards_have_paraphrase_rows(self) -> None:
        """五张新卡在同义句表各有一行，gold 与地图问句相同。"""

        print("\n[TestAiKbC2Data] 新卡同义句行")
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
        """无 Provider 过程金句的 sources 第一张是期望 id，且零 skill、无 plan_id。"""

        print("\n[TestAiKbC2Data] 过程金句抽检零 skill")
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

    def test_local_overview_is_not_env_ready(self) -> None:
        """怎么看本地有哪些数据归 datasource_local，不是 env_ready。"""

        print("\n[TestAiKbC2Data] 本地 overview 不是 env_ready")
        engine = AskEngine(knowledge_base=KnowledgeBase())
        question = "怎么看本地已经有哪些数据"
        payload = engine.ask(question).to_dict()
        print(" sources:", payload.get("sources"))
        self.assertEqual(payload["sources"][0], "datasource_local")
        self.assertNotIn("env_ready", payload["sources"])

    def test_three_entries_narrative_and_minimum_tables(self) -> None:
        """三入口叙事含历史与参考入口；起步卡点名五张表。"""

        print("\n[TestAiKbC2Data] 三入口与起步表叙事")
        three = json.loads((_KB_DIR / "data_three_entries.json").read_text(encoding="utf-8"))
        print(" three narrative snippet:", three["narrative"][:240])
        self.assertIn("get_history_data", three["narrative"])
        self.assertIn("get_reference_data", three["narrative"])
        self.assertIn("get_kline", three["narrative"])

        minimum = json.loads((_KB_DIR / "data_minimum.json").read_text(encoding="utf-8"))
        print(" minimum narrative snippet:", minimum["narrative"][:280])
        for table in _MINIMUM_TABLES:
            print(" table named:", table)
            self.assertIn(table, minimum["narrative"])

    def test_download_handoff_explains_plan_and_dates(self) -> None:
        """办事下载句只解释切 Plan，并要求日期，无 plan_id。"""

        print("\n[TestAiKbC2Data] 帮我下载只解释切 Plan")
        engine = AskEngine(knowledge_base=KnowledgeBase())
        payload = engine.ask("帮我下载").to_dict()
        answer = payload.get("answer") or ""
        print(" sources:", payload.get("sources"))
        print(" answer:", answer[:320])
        self.assertEqual(payload["sources"], ["refill_bounded"])
        self.assertNotIn("plan_id", payload)
        self.assertNotIn("execution", payload)
        lower = answer.lower()
        self.assertTrue(
            ("plan" in lower) or ("Plan" in answer),
            msg="answer should mention switching to Plan",
        )
        self.assertTrue(
            ("date" in lower) or ("start" in lower) or ("end" in lower) or ("日期" in answer),
            msg="answer should require dates",
        )


if __name__ == "__main__":
    unittest.main()

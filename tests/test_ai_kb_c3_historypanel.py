# coding=utf-8
# ======================================
# File: test_ai_kb_c3_historypanel.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-27
# Desc:
# C3 HistoryPanel：shape / 分析 / plotly 过程金句与零 skill
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
    ("historypanel_basics", "HistoryPanel 的三维是什么", ["data-analysis"]),
    ("historypanel_analysis", "怎么用 HistoryPanel 做数据分析", ["data-analysis"]),
    ("historypanel_plot", "HistoryPanel 怎么用 plotly 画图", ["data-analysis"]),
)
_NEW_IDS = (
    "historypanel_basics",
    "historypanel_analysis",
    "historypanel_plot",
)


def _load_entries(path: Path) -> list:
    """读取 ``entries`` 列表。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload["entries"]
    if not isinstance(entries, list):
        raise AssertionError(f"{path.name} entries must be a list")
    return entries


class TestAiKbC3HistoryPanel(unittest.TestCase):
    """C3 HistoryPanel 容器 / 研究 / 出图宽卡抽检。"""

    def test_card_topics_are_data_analysis(self) -> None:
        """三张新卡挂在 data-analysis；注册表仍无单一 data。"""

        print("\n[TestAiKbC3HistoryPanel] 主题侧 data-analysis")
        registry = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        topic_ids = [row["id"] for row in registry["topics"]]
        print(" topic ids:", topic_ids)
        self.assertNotIn("data", topic_ids)
        self.assertIn("data-analysis", topic_ids)

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
        """三张新卡在同义句表各有一行，gold 与地图问句相同。"""

        print("\n[TestAiKbC3HistoryPanel] 新卡同义句行")
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

        print("\n[TestAiKbC3HistoryPanel] 过程金句抽检零 skill")
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

    def test_mece_seams_in_summaries(self) -> None:
        """三卡 summary 钉住容器 / 研究 / 渲染缝，analysis 点到正式回测。"""

        print("\n[TestAiKbC3HistoryPanel] MECE summary 缝")
        basics = json.loads((_KB_DIR / "historypanel_basics.json").read_text(encoding="utf-8"))
        analysis = json.loads((_KB_DIR / "historypanel_analysis.json").read_text(encoding="utf-8"))
        plot = json.loads((_KB_DIR / "historypanel_plot.json").read_text(encoding="utf-8"))
        print(" basics summary:", basics["summary"])
        print(" analysis summary:", analysis["summary"])
        print(" plot summary:", plot["summary"])
        self.assertIn("shape", basics["summary"].lower())
        self.assertIn("research", analysis["summary"].lower())
        self.assertIn("plot", plot["summary"].lower())
        self.assertTrue(
            ("not invent" in plot["narrative"].lower())
            or ("does not invent" in plot["narrative"].lower())
            or ("does not create" in plot["narrative"].lower()),
            msg="plot must say it does not invent indicator columns",
        )
        self.assertIn("Operator", analysis["narrative"])
        self.assertIn("backtest_intro", [r["to"] for r in analysis["relations"]])

    def test_three_entries_links_historypanel_basics(self) -> None:
        """data_three_entries 出边指向 historypanel_basics。"""

        print("\n[TestAiKbC3HistoryPanel] 三入口链到 HP basics")
        three = json.loads((_KB_DIR / "data_three_entries.json").read_text(encoding="utf-8"))
        targets = [r["to"] for r in three["relations"]]
        print(" three relations to:", targets)
        self.assertIn("historypanel_basics", targets)
        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        map_targets = [r["to"] for r in rows["data_three_entries"]["relations"]]
        print(" map three relations to:", map_targets)
        self.assertIn("historypanel_basics", map_targets)


if __name__ == "__main__":
    unittest.main()

# coding=utf-8
# ======================================
# File: test_ai_kb_c6_live.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-27
# Desc:
# C6 实盘边界宽卡：过程金句、MECE 缝、负向不诱导下单
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

_SPOT_CHECKS = (
    ("live_what", "模拟实盘是什么", ["live_boundary"], "concept"),
    ("live_plan_only", "会不会自动下单", ["live_boundary"], "boundary"),
)
_CARD_IDS = ("live_what", "live_plan_only")
_LEGACY_LIVE_QUERIES = (
    ("live trade", "live_plan_only"),
    ("never auto", "live_plan_only"),
)
_FORBIDDEN_CARD_IDS = (
    "live_cli_commands",
    "live_tui_commands",
    "xtquant_contract",
    "live_deploy_recipe",
    "tutorial_8_walkthrough",
)
_FORBIDDEN_PHRASES = ("已下单", "去监控")
_NEVER_AUTO_TOKENS = (
    "never auto",
    "live plan",
    "会不会自动下单",
    "auto execute",
    "side effect",
)


def _load_entries(path: Path) -> list:
    """读取 ``entries`` 列表。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload["entries"]
    if not isinstance(entries, list):
        raise AssertionError(f"{path.name} entries must be a list")
    return entries


def _relation_targets(entry: dict) -> list:
    """取出 relations 的 to 列表。"""

    return [item["to"] for item in entry.get("relations") or []]


class TestAiKbC6Live(unittest.TestCase):
    """C6 实盘边界宽卡抽检与 MECE 缝。"""

    def test_card_topics_and_types(self) -> None:
        """live_what / live_plan_only 挂在 live_boundary；类型符合计划。"""

        print("\n[TestAiKbC6Live] 主题与类型")
        registry = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        topic_ids = [row["id"] for row in registry["topics"]]
        print(" topic ids:", topic_ids)
        self.assertIn("live_boundary", topic_ids)

        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        for entry_id, _question, expected_topics, expected_type in _SPOT_CHECKS:
            print(" card:", entry_id, "topics:", rows[entry_id]["topics"], "type:", rows[entry_id]["type"])
            self.assertEqual(rows[entry_id]["topics"], expected_topics)
            self.assertEqual(rows[entry_id]["type"], expected_type)
            entry = json.loads((_KB_DIR / f"{entry_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(entry["topics"], expected_topics)
            self.assertEqual(entry["type"], expected_type)

    def test_paraphrase_rows_align_with_map(self) -> None:
        """两张卡同义句行 gold 与地图问句相同。"""

        print("\n[TestAiKbC6Live] 同义句行")
        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        gold_rows = {row["id"]: row for row in _load_entries(_GOLD_PATH)}
        for entry_id in _CARD_IDS:
            print(" paraphrase row:", entry_id)
            print(" gold:", gold_rows[entry_id]["gold"])
            print(" map questions:", rows[entry_id]["questions"])
            print(" paraphrases:", gold_rows[entry_id]["paraphrases"])
            self.assertEqual(gold_rows[entry_id]["gold"], rows[entry_id]["questions"])
            self.assertTrue(gold_rows[entry_id]["paraphrases"])
            self.assertEqual(gold_rows[entry_id]["expect_ids"][0], entry_id)

    def test_spot_questions_hit_primary_without_plan(self) -> None:
        """无 Provider：是什么 → live_what；会不会自动下单 → live_plan_only；无 plan_id。"""

        print("\n[TestAiKbC6Live] 过程金句零 skill")
        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        engine = AskEngine(knowledge_base=KnowledgeBase())
        self.assertIsNone(engine.provider)
        for entry_id, question, _topics, _type in _SPOT_CHECKS:
            self.assertIn(question, rows[entry_id]["questions"])
            payload = engine.ask(question).to_dict()
            print(" question:", question)
            print(" sources:", payload.get("sources"))
            print(" answer head:", (payload.get("answer") or "")[:160])
            self.assertTrue(payload["ok"], msg=question)
            self.assertEqual(payload["mode"], "ask")
            self.assertEqual(payload["sources"][0], entry_id)
            self.assertNotIn("plan_id", payload)
            self.assertNotIn("plan", payload)
            self.assertNotIn("execution", payload)
            answer = payload.get("answer") or ""
            for phrase in _FORBIDDEN_PHRASES:
                print(" forbidden in answer:", phrase, phrase in answer)
                self.assertNotIn(phrase, answer)

    def test_negative_copy_and_ask_does_not_start_trader(self) -> None:
        """正文无已下单/去监控；live_what 声明不启动 Trader；无命令/XtQuant 清单。"""

        print("\n[TestAiKbC6Live] 负向文案与不启动 Trader")
        live_what = json.loads((_KB_DIR / "live_what.json").read_text(encoding="utf-8"))
        live_plan = json.loads((_KB_DIR / "live_plan_only.json").read_text(encoding="utf-8"))
        for entry in (live_what, live_plan):
            blob = " ".join(
                [
                    entry.get("narrative") or "",
                    entry.get("summary") or "",
                    entry.get("risk_notes") or "",
                ]
            )
            print(" card:", entry["id"], "blob head:", blob[:120])
            for phrase in _FORBIDDEN_PHRASES:
                self.assertNotIn(phrase, blob)

        what_blob = " ".join(
            [
                live_what.get("narrative") or "",
                live_what.get("summary") or "",
                live_what.get("risk_notes") or "",
            ]
        )
        print(" trader start claim absent; does-not-start present")
        self.assertIn("does not start Trader", what_blob)
        self.assertNotIn("command cheat-sheet", what_blob.lower())
        self.assertNotIn("XtQuant", what_blob)
        self.assertNotIn("xtquant", what_blob.lower())
        self.assertNotIn("qt.run(op)", what_blob)

        plan_blob = " ".join(
            [
                live_plan.get("narrative") or "",
                live_plan.get("summary") or "",
                live_plan.get("risk_notes") or "",
            ]
        )
        self.assertIn("does not start Trader", plan_blob)

    def test_mece_keyword_and_question_seams(self) -> None:
        """live_what 不含 never-auto 族；副作用卡无裸 live/实盘；自动下单不以副作用为主卡。"""

        print("\n[TestAiKbC6Live] MECE 缝")
        live_what = json.loads((_KB_DIR / "live_what.json").read_text(encoding="utf-8"))
        side = json.loads((_KB_DIR / "side_effects_safety.json").read_text(encoding="utf-8"))
        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}

        what_kw = " ".join(live_what.get("keywords") or [])
        what_q = " ".join(rows["live_what"]["questions"])
        print(" live_what keywords:", what_kw)
        print(" live_what questions:", what_q)
        for token in _NEVER_AUTO_TOKENS:
            self.assertNotIn(token, what_kw)
            self.assertNotIn(token, what_q)

        side_kw = list(side.get("keywords") or [])
        print(" side_effects keywords:", side_kw)
        self.assertNotIn("live", side_kw)
        self.assertNotIn("实盘", side_kw)

        print(" live_what tos:", _relation_targets(live_what))
        self.assertIn("live_plan_only", _relation_targets(live_what))
        self.assertIn("backtest_intro", _relation_targets(live_what))
        self.assertIn("qteasy_advantages", _relation_targets(live_what))

        engine = AskEngine(knowledge_base=KnowledgeBase())
        auto = engine.ask("会不会自动下单").to_dict()
        print(" auto sources:", auto.get("sources"))
        self.assertEqual(auto["sources"][0], "live_plan_only")
        self.assertNotEqual(auto["sources"][0], "side_effects_safety")

    def test_legacy_live_gold_still_hits_plan_only(self) -> None:
        """既有 live trade / never auto 仍以 live_plan_only 开头。"""

        print("\n[TestAiKbC6Live] 既有 live 金句")
        engine = AskEngine(knowledge_base=KnowledgeBase())
        for question, expect_id in _LEGACY_LIVE_QUERIES:
            payload = engine.ask(question).to_dict()
            print(" question:", question)
            print(" sources:", payload.get("sources"))
            self.assertTrue(payload["ok"], msg=question)
            self.assertEqual(payload["sources"][0], expect_id)
            self.assertNotIn("plan_id", payload)

    def test_no_deploy_or_command_specialty_cards(self) -> None:
        """地图没有部署/命令/XtQuant 专卡。"""

        print("\n[TestAiKbC6Live] 禁专卡")
        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        print(" forbidden present:", [item for item in _FORBIDDEN_CARD_IDS if item in rows])
        for entry_id in _FORBIDDEN_CARD_IDS:
            self.assertNotIn(entry_id, rows)


if __name__ == "__main__":
    unittest.main()

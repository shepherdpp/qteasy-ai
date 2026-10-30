# coding=utf-8
# ======================================
# File: test_ai_kb_r4_workbench_entry.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-27
# Desc:
# R4 工作台入口卡：金句命中、无 plan_id、正文指向网页入口
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

_ENTRY_ID = "workbench_entry"
_SPOT_CHECKS = (
    (_ENTRY_ID, "Plan 在哪", ["onboarding"], "concept"),
    (_ENTRY_ID, "点哪个按钮", ["onboarding"], "concept"),
)
_FORBIDDEN_CARD_IDS = (
    "workbench_ui_manual",
    "workbench_cli_sheet",
    "workbench_tui_sheet",
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


class TestAiKbR4WorkbenchEntry(unittest.TestCase):
    """R4 工作台入口卡抽检。"""

    def test_card_topics_type_and_scope(self) -> None:
        """workbench_entry 挂 onboarding；主题 scope 含工作台入口。"""

        print("\n[TestAiKbR4WorkbenchEntry] 主题与类型")
        registry = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        onboarding = next(row for row in registry["topics"] if row["id"] == "onboarding")
        print(" onboarding scope:", onboarding["scope"])
        self.assertIn("工作台", onboarding["scope"])
        self.assertIn("Ask/Plan", onboarding["scope"])

        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        entry = json.loads((_KB_DIR / f"{_ENTRY_ID}.json").read_text(encoding="utf-8"))
        print(" map topics:", rows[_ENTRY_ID]["topics"], "type:", rows[_ENTRY_ID]["type"])
        self.assertEqual(rows[_ENTRY_ID]["topics"], ["onboarding"])
        self.assertEqual(rows[_ENTRY_ID]["type"], "concept")
        self.assertEqual(entry["topics"], ["onboarding"])
        self.assertEqual(entry["type"], "concept")

    def test_paraphrase_row_aligns_with_map(self) -> None:
        """同义句行 gold 与地图问句相同；expect 以本卡开头。"""

        print("\n[TestAiKbR4WorkbenchEntry] 同义句行")
        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        gold_rows = {row["id"]: row for row in _load_entries(_GOLD_PATH)}
        print(" gold:", gold_rows[_ENTRY_ID]["gold"])
        print(" map questions:", rows[_ENTRY_ID]["questions"])
        print(" paraphrases:", gold_rows[_ENTRY_ID]["paraphrases"])
        self.assertEqual(gold_rows[_ENTRY_ID]["gold"], rows[_ENTRY_ID]["questions"])
        self.assertTrue(gold_rows[_ENTRY_ID]["paraphrases"])
        self.assertEqual(gold_rows[_ENTRY_ID]["expect_ids"][0], _ENTRY_ID)

    def test_spot_questions_hit_primary_without_plan(self) -> None:
        """无 Provider：Plan 在哪 / 点哪个按钮 → workbench_entry；无 plan_id。"""

        print("\n[TestAiKbR4WorkbenchEntry] 过程金句零 skill")
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

    def test_narrative_points_to_web_not_preview_only(self) -> None:
        """正文含 Confirm / 徽章语义与 Ask 不代确认；非 preview 唯一下一步教程。"""

        print("\n[TestAiKbR4WorkbenchEntry] 正文指向网页入口")
        entry = json.loads((_KB_DIR / f"{_ENTRY_ID}.json").read_text(encoding="utf-8"))
        blob = " ".join(
            [
                entry.get("narrative") or "",
                entry.get("summary") or "",
                entry.get("risk_notes") or "",
            ]
        )
        print(" blob head:", blob[:200])
        self.assertIn("Confirm", blob)
        self.assertIn("Ask", blob)
        self.assertIn("Plan", blob)
        self.assertTrue(
            ("Ask ▾" in blob) or ("mode badge" in blob.lower()),
            msg="expected mode badge wording",
        )
        lowered = blob.lower()
        self.assertIn("never clicks confirm", lowered)
        # May mention assistant.preview only as something NOT to treat as sole next step.
        if "assistant.preview" in lowered:
            self.assertIn("do not treat", lowered)
            self.assertIn("only next step", lowered)

    def test_see_also_symmetric_with_ask_plan_agent(self) -> None:
        """与 ask_plan_agent 双向 see_also。"""

        print("\n[TestAiKbR4WorkbenchEntry] 对称边")
        entry = json.loads((_KB_DIR / f"{_ENTRY_ID}.json").read_text(encoding="utf-8"))
        ask_plan = json.loads((_KB_DIR / "ask_plan_agent.json").read_text(encoding="utf-8"))
        print(" workbench tos:", _relation_targets(entry))
        print(" ask_plan tos:", _relation_targets(ask_plan))
        self.assertIn("ask_plan_agent", _relation_targets(entry))
        self.assertIn(_ENTRY_ID, _relation_targets(ask_plan))

        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        self.assertIn("ask_plan_agent", _relation_targets(rows[_ENTRY_ID]))
        self.assertIn(_ENTRY_ID, _relation_targets(rows["ask_plan_agent"]))

    def test_no_second_ui_manual_card(self) -> None:
        """地图没有第二份 UI 手册专卡。"""

        print("\n[TestAiKbR4WorkbenchEntry] 禁专卡")
        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        print(" forbidden present:", [item for item in _FORBIDDEN_CARD_IDS if item in rows])
        for entry_id in _FORBIDDEN_CARD_IDS:
            self.assertNotIn(entry_id, rows)


if __name__ == "__main__":
    unittest.main()

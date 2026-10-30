# coding=utf-8
# ======================================
# File: test_ai_kb_c4_strategy.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-27
# Desc:
# C4 策略/信号宽卡：过程金句、MECE 缝、PT dict 与 run_freq 回归
# ======================================

import json
import unittest
from pathlib import Path

from qteasy_ai.ask_engine import AskEngine, _CARD_SYSTEM_PROMPT
from qteasy_ai.knowledge_base import KnowledgeBase
from qteasy_ai.provider import FakeLLMProvider

_REPO = Path(__file__).resolve().parents[1]
_KB_DIR = _REPO / "qteasy_ai" / "kb"
_MAP_PATH = _KB_DIR / "_source" / "curation_map.json"
_GOLD_PATH = _KB_DIR / "_source" / "paraphrase_gold.json"
_REGISTRY_PATH = _KB_DIR / "_source" / "topic_registry.json"

# 抽检原句是目录里的普通问句。期望 id 是独立金标准。
_SPOT_CHECKS = (
    ("strategy_overview", "策略、Operator 和 Group 各管什么", ["strategy"]),
    ("operator_create", "怎么创建 Operator", ["strategy"]),
    ("strategy_blender", "blender 是什么", ["strategy"]),
    ("builtin_strategy_lookup", "怎么查阅内置策略文档", ["strategy"]),
    ("strategy_bases", "三种策略基类有什么区别", ["strategy"]),
    ("strategy_bases", "每只股票用不同参数怎么设", ["strategy"]),
    ("strategy_realize", "自定义策略的 realize 要返回什么", ["strategy"]),
    ("strategy_trace", "怎么追踪策略中间变量", ["strategy"]),
)
_NEW_IDS = (
    "strategy_overview",
    "operator_create",
    "strategy_blender",
    "builtin_strategy_lookup",
    "strategy_bases",
    "strategy_realize",
    "strategy_trace",
)
_PT_DICT_QUERIES = (
    "PT 是不是 dict",
    "PT 是不是普通 dict",
)


def _load_entries(path: Path) -> list:
    """读取 ``entries`` 列表。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload["entries"]
    if not isinstance(entries, list):
        raise AssertionError(f"{path.name} entries must be a list")
    return entries


class TestAiKbC4Strategy(unittest.TestCase):
    """C4 策略 / 信号宽卡抽检与回归。"""

    def test_card_topics_are_strategy(self) -> None:
        """七张新卡挂在 strategy；注册表仍含 strategy。"""

        print("\n[TestAiKbC4Strategy] 主题侧 strategy")
        registry = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        topic_ids = [row["id"] for row in registry["topics"]]
        print(" topic ids:", topic_ids)
        self.assertIn("strategy", topic_ids)

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
        """七张新卡在同义句表各有一行，gold 与地图问句相同。"""

        print("\n[TestAiKbC4Strategy] 新卡同义句行")
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
        bases_questions = rows["strategy_bases"]["questions"]
        print(" strategy_bases questions:", bases_questions)
        self.assertIn("三种策略基类有什么区别", bases_questions)
        self.assertIn("每只股票用不同参数怎么设", bases_questions)

    def test_spot_questions_hit_primary_card_without_plan(self) -> None:
        """无 Provider 过程金句的 sources 第一张是期望 id，且零 skill、无 plan_id。"""

        print("\n[TestAiKbC4Strategy] 过程金句抽检零 skill")
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
        """summary / narrative 钉住 MECE 缝；pt_ps_vs 锚改到第 3 章。"""

        print("\n[TestAiKbC4Strategy] MECE summary 缝")
        bases = json.loads((_KB_DIR / "strategy_bases.json").read_text(encoding="utf-8"))
        blender = json.loads((_KB_DIR / "strategy_blender.json").read_text(encoding="utf-8"))
        realize = json.loads((_KB_DIR / "strategy_realize.json").read_text(encoding="utf-8"))
        trace = json.loads((_KB_DIR / "strategy_trace.json").read_text(encoding="utf-8"))
        create = json.loads((_KB_DIR / "operator_create.json").read_text(encoding="utf-8"))
        pt = json.loads((_KB_DIR / "pt_ps_vs.json").read_text(encoding="utf-8"))
        print(" bases summary:", bases["summary"])
        print(" blender summary:", blender["summary"])
        print(" realize summary:", realize["summary"])
        print(" trace summary:", trace["summary"])
        print(" create summary:", create["summary"])
        print(" pt_ps_vs anchor:", pt["manual_anchor"])
        self.assertIn("RuleIterator", bases["summary"])
        self.assertTrue(
            ("not a signal type" in bases["summary"].lower())
            or ("not signal type" in bases["summary"].lower())
            or ("not pt" in bases["summary"].lower()),
            msg="bases must say per-share parameter dict is not a signal type",
        )
        self.assertTrue(
            ("position target" not in blender["summary"].lower())
            or ("does not define" in blender["summary"].lower())
            or ("mixing" in blender["summary"].lower()),
            msg="blender summary must stay on mixing, not define PT",
        )
        self.assertTrue(
            ("does not define" in blender["narrative"].lower())
            or ("not define" in blender["narrative"].lower())
            or ("meaning of signal numbers" in blender["narrative"].lower())
            or ("signal meaning" in blender["narrative"].lower()),
            msg="blender narrative must defer PT meaning",
        )
        self.assertTrue(
            ("StrategyBuilder" in realize["summary"])
            or ("strategybuilder" in realize["summary"].lower()),
            msg="realize must point write-file to StrategyBuilder",
        )
        self.assertTrue(
            ("tutorial" in realize["narrative"].lower())
            or ("5–7" in realize["narrative"])
            or ("5-7" in realize["narrative"]),
            msg="realize must say tutorials 5-7 are out of scope",
        )
        self.assertTrue(
            ("FactorSorter" in trace["summary"] or "FactorSorter" in trace["narrative"])
            and ("GeneralStg" in trace["summary"] or "GeneralStg" in trace["narrative"]),
            msg="trace must mention FactorSorter / GeneralStg not adapted",
        )
        self.assertTrue(
            ("not a run mode" in trace["summary"].lower())
            or ("not a run mode" in trace["narrative"].lower())
            or ("not run mode" in (trace["summary"] + trace["narrative"]).lower()),
            msg="trace must say tracing is not a run mode",
        )
        self.assertTrue(
            ("is_ready" in create["summary"] or "is_ready" in create["narrative"])
            and (
                "normal" in (create["summary"] + create["narrative"]).lower()
                or "before backtest" in (create["summary"] + create["narrative"]).lower()
                or "false is fine" in (create["summary"] + create["narrative"]).lower()
            ),
            msg="operator_create must say False from is_ready before backtest can be normal",
        )
        self.assertEqual(
            pt["manual_anchor"],
            "docs/source/manage_strategies/3. group_and_blender.md",
        )
        self.assertIn("Position Target", pt["narrative"])

    def test_pt_dict_queries_hit_pt_ps_vs(self) -> None:
        """自然问句 PT 是不是 dict 的 sources 含 pt_ps_vs，无 plan_id。"""

        print("\n[TestAiKbC4Strategy] PT 是不是 dict")
        engine = AskEngine(knowledge_base=KnowledgeBase())
        self.assertIsNone(engine.provider)
        for question in _PT_DICT_QUERIES:
            payload = engine.ask(question).to_dict()
            print(" question:", question)
            print(" sources:", payload.get("sources"))
            print(" ok:", payload.get("ok"))
            self.assertTrue(payload["ok"], msg=question)
            self.assertIn("pt_ps_vs", payload.get("sources") or [])
            self.assertNotIn("plan_id", payload)
            self.assertNotIn("execution", payload)
            if "strategy_meta" in (payload.get("sources") or []):
                self.fail(
                    "strategy_meta squeezed out pt_ps_vs for %r; sources=%r"
                    % (question, payload.get("sources"))
                )

    def test_run_freq_regressions_stay_exclusive(self) -> None:
        """run_freq 归属与传错 trap 仍独占，不被新卡抢走。"""

        print("\n[TestAiKbC4Strategy] run_freq / trap 回归")
        engine = AskEngine(knowledge_base=KnowledgeBase())
        cases = (
            ("where does run_freq belong", ["operator_run_freq"]),
            ("where does run_freq belong, Operator or qt.run?", ["operator_run_freq"]),
            ("not a built-in parameter", ["common_errors_run_freq"]),
        )
        for question, expected in cases:
            payload = engine.ask(question).to_dict()
            print(" question:", question)
            print(" sources:", payload.get("sources"))
            print(" expected:", expected)
            self.assertTrue(payload["ok"], msg=question)
            self.assertEqual(payload["sources"], expected)
            self.assertNotIn("plan_id", payload)

        misroute = (
            "qt.run raised: config_key is not a built-in parameter key "
            "when I passed freq='d'"
        )
        payload = engine.ask(misroute).to_dict()
        print(" misroute question:", misroute)
        print(" misroute sources:", payload.get("sources"))
        self.assertTrue(payload["ok"], msg=misroute)
        self.assertIn(payload["sources"][0], ("common_errors_run_freq", "operator_run_freq"))
        self.assertNotIn(payload["sources"][0], _NEW_IDS)

    def test_strategy_builder_regression(self) -> None:
        """写策略问法仍命中 strategy_builder_intro。"""

        print("\n[TestAiKbC4Strategy] strategy_builder 回归")
        engine = AskEngine(knowledge_base=KnowledgeBase())
        payload = engine.ask("帮我写一个双均线策略").to_dict()
        print(" sources:", payload.get("sources"))
        self.assertTrue(payload["ok"])
        self.assertIn("strategy_builder_intro", payload["sources"])
        self.assertNotIn("plan_id", payload)

    def test_dual_question_stub_keeps_both_concepts(self) -> None:
        """替身双问返回两张 concept；点卡 system 仍含一问多卡条款。"""

        print("\n[TestAiKbC4Strategy] 双问替身 PT + blender")
        fake = FakeLLMProvider(
            replies=[
                json.dumps({"topics": ["strategy"]}, ensure_ascii=False),
                json.dumps({"ids": ["pt_ps_vs", "strategy_blender"]}, ensure_ascii=False),
                "PT is a target-weight signal; blender mixes signals in a Group.",
            ]
        )
        engine = AskEngine(knowledge_base=KnowledgeBase(), provider=fake)
        question = "PT 和 blender 分别是什么"
        payload = engine.ask(question).to_dict()
        print(" sources:", payload.get("sources"))
        print(" card system:", fake.system_prompts[1])
        self.assertTrue(payload["ok"])
        self.assertIn("pt_ps_vs", payload["sources"])
        self.assertIn("strategy_blender", payload["sources"])
        self.assertNotIn("plan_id", payload)
        card_system = fake.system_prompts[1].lower()
        self.assertIn("one question covers multiple matters", card_system)
        self.assertIn("one question covers multiple matters", _CARD_SYSTEM_PROMPT.lower())

    def test_relation_seams(self) -> None:
        """MECE 边：overview 出边、create↔freq、blender↔pt、realize↔builder/trace。"""

        print("\n[TestAiKbC4Strategy] relation 缝")
        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        overview = json.loads((_KB_DIR / "strategy_overview.json").read_text(encoding="utf-8"))
        create = json.loads((_KB_DIR / "operator_create.json").read_text(encoding="utf-8"))
        freq = json.loads((_KB_DIR / "operator_run_freq.json").read_text(encoding="utf-8"))
        blender = json.loads((_KB_DIR / "strategy_blender.json").read_text(encoding="utf-8"))
        pt = json.loads((_KB_DIR / "pt_ps_vs.json").read_text(encoding="utf-8"))
        bases = json.loads((_KB_DIR / "strategy_bases.json").read_text(encoding="utf-8"))
        realize = json.loads((_KB_DIR / "strategy_realize.json").read_text(encoding="utf-8"))
        builder = json.loads((_KB_DIR / "strategy_builder_intro.json").read_text(encoding="utf-8"))
        trace = json.loads((_KB_DIR / "strategy_trace.json").read_text(encoding="utf-8"))

        def _tos(entry: dict) -> list:
            return [item["to"] for item in entry.get("relations") or []]

        print(" overview tos:", _tos(overview))
        for target in (
            "operator_create",
            "strategy_blender",
            "strategy_bases",
            "builtin_strategy_lookup",
        ):
            self.assertIn(target, _tos(overview))
            self.assertIn(target, [r["to"] for r in rows["strategy_overview"]["relations"]])

        self.assertIn("operator_run_freq", _tos(create))
        self.assertIn("operator_create", _tos(freq))
        self.assertIn("pt_ps_vs", _tos(blender))
        self.assertIn("strategy_blender", _tos(pt))
        self.assertIn("pt_ps_vs", _tos(bases))
        self.assertIn("strategy_bases", _tos(pt))
        self.assertIn("strategy_builder_intro", _tos(realize))
        self.assertIn("strategy_realize", _tos(builder))
        self.assertIn("strategy_trace", _tos(realize))
        self.assertIn("strategy_realize", _tos(trace))
        self.assertNotIn("pt_ps_vs", _tos(create))


if __name__ == "__main__":
    unittest.main()

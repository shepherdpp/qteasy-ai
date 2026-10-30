# coding=utf-8
# ======================================
# File: test_ai_kb_c5_backtest.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-27
# Desc:
# C5 回测/优化宽卡：过程金句、MECE 缝、未来函数与作家通识
# ======================================

import json
import unittest
from pathlib import Path

from qteasy_ai.ask_engine import AskEngine
from qteasy_ai.knowledge_base import KnowledgeBase
from qteasy_ai.provider import FakeLLMProvider

_REPO = Path(__file__).resolve().parents[1]
_KB_DIR = _REPO / "qteasy_ai" / "kb"
_MAP_PATH = _KB_DIR / "_source" / "curation_map.json"
_GOLD_PATH = _KB_DIR / "_source" / "paraphrase_gold.json"
_REGISTRY_PATH = _KB_DIR / "_source" / "topic_registry.json"
_CATALOG_PATH = _KB_DIR / "_generated" / "question_catalog.json"

_SPOT_CHECKS = (
    ("backtest_intro", "回测是什么", ["backtest"]),
    ("backtest_config", "回测区间和成本怎么设", ["backtest"]),
    ("backtest_result", "回测结果看什么", ["backtest"]),
    ("backtest_trade_log", "交易日志在哪", ["backtest"]),
    ("backtest_engine", "回测为什么按时间步走", ["backtest"]),
    ("optimize_intro", "优化在做什么", ["optimize"]),
    ("optimize_config", "opti_sample_count 是什么", ["optimize"]),
    ("optimize_algorithms", "网格搜索和蒙特卡洛怎么选", ["optimize"]),
    ("optimize_result", "最优参数怎么读", ["optimize"]),
    ("lookahead_isolation", "qteasy 如何防止未来函数", ["overview"]),
)
_NEW_IDS = (
    "backtest_config",
    "backtest_result",
    "backtest_trade_log",
    "backtest_engine",
    "optimize_config",
    "optimize_algorithms",
    "optimize_result",
    "lookahead_isolation",
)
_PLAN_HANDOFF_QUERIES = (
    ("帮我回测", "backtest_intro"),
    ("帮我优化", "optimize_intro"),
)
_FORBIDDEN_CARD_IDS = (
    "backtest_evaluate",
    "out_of_sample",
    "rolling_window",
    "sample_out",
)
_PLAIN_DEF_MARKERS = (
    "rehearses a trading rule",
    "not a promise about the future",
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


class TestAiKbC5Backtest(unittest.TestCase):
    """C5 回测 / 优化宽卡抽检与回归。"""

    def test_card_topics_registered(self) -> None:
        """新卡主题挂在 backtest / optimize / overview；注册表仍含这三项。"""

        print("\n[TestAiKbC5Backtest] 主题侧")
        registry = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        topic_ids = [row["id"] for row in registry["topics"]]
        print(" topic ids:", topic_ids)
        self.assertIn("backtest", topic_ids)
        self.assertIn("optimize", topic_ids)
        self.assertIn("overview", topic_ids)

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
        """新卡与扩写卡在同义句表各有一行，gold 与地图问句相同。"""

        print("\n[TestAiKbC5Backtest] 同义句行")
        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        gold_rows = {row["id"]: row for row in _load_entries(_GOLD_PATH)}
        for entry_id, _question, _topics in _SPOT_CHECKS:
            print(" paraphrase row:", entry_id)
            print(" gold:", gold_rows[entry_id]["gold"])
            print(" map questions:", rows[entry_id]["questions"])
            print(" paraphrases:", gold_rows[entry_id]["paraphrases"])
            print(" expect_ids:", gold_rows[entry_id]["expect_ids"])
            self.assertEqual(gold_rows[entry_id]["gold"], rows[entry_id]["questions"])
            self.assertTrue(gold_rows[entry_id]["paraphrases"])
            self.assertEqual(gold_rows[entry_id]["expect_ids"][0], entry_id)

    def test_spot_questions_hit_primary_card_without_plan(self) -> None:
        """无 Provider 过程金句的 sources 第一张是期望 id，且零 skill、无 plan_id。"""

        print("\n[TestAiKbC5Backtest] 过程金句抽检零 skill")
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

    def test_backtest_intro_has_plain_definition(self) -> None:
        """回测是什么命中的卡含人话定义；办事句无 plan_id。"""

        print("\n[TestAiKbC5Backtest] 人话定义与办事句")
        intro = json.loads((_KB_DIR / "backtest_intro.json").read_text(encoding="utf-8"))
        narrative = intro["narrative"]
        print(" narrative head:", narrative[:160])
        for marker in _PLAIN_DEF_MARKERS:
            print(" marker present:", marker, marker in narrative)
            self.assertIn(marker, narrative)

        engine = AskEngine(knowledge_base=KnowledgeBase())
        for question, expect_id in _PLAN_HANDOFF_QUERIES:
            payload = engine.ask(question).to_dict()
            print(" question:", question)
            print(" sources:", payload.get("sources"))
            self.assertTrue(payload["ok"], msg=question)
            self.assertEqual(payload["sources"][0], expect_id)
            self.assertNotIn("plan_id", payload)
            self.assertNotIn("execution", payload)

        how = engine.ask("如何用qteasy回测").to_dict()
        why = engine.ask("为什么用 qteasy 而不是自己写回测").to_dict()
        print(" how sources:", how.get("sources"))
        print(" why sources:", why.get("sources"))
        self.assertEqual(how["sources"][0], "backtest_intro")
        self.assertEqual(why["sources"][0], "qteasy_advantages")

    def test_regressions_keep_existing_primary_cards(self) -> None:
        """频率、trace、HistoryPanel 收益率仍落原卡。"""

        print("\n[TestAiKbC5Backtest] 既有卡回归")
        engine = AskEngine(knowledge_base=KnowledgeBase())
        cases = (
            ("where does run_freq belong", "operator_run_freq"),
            ("怎么追踪策略中间变量", "strategy_trace"),
            ("HistoryPanel 怎么算收益率", "historypanel_analysis"),
        )
        for question, expect_id in cases:
            payload = engine.ask(question).to_dict()
            print(" question:", question)
            print(" sources:", payload.get("sources"))
            print(" expected:", expect_id)
            self.assertTrue(payload["ok"], msg=question)
            self.assertEqual(payload["sources"][0], expect_id)
            self.assertNotIn("plan_id", payload)

    def test_no_oos_or_evaluate_special_cards(self) -> None:
        """地图与目录没有样本外 / 滚动窗口 / 评价专卡；新卡正文不含前后各跑一次。"""

        print("\n[TestAiKbC5Backtest] 禁专卡与禁正文")
        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}
        catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))["questions"]
        print(" forbidden ids in map:", [item for item in _FORBIDDEN_CARD_IDS if item in rows])
        for entry_id in _FORBIDDEN_CARD_IDS:
            self.assertNotIn(entry_id, rows)
        blob = " ".join(list(rows.keys()) + list(catalog.keys()) + [str(v) for v in catalog.values()])
        for token in ("样本外", "滚动窗口", "out of sample", "rolling window", "backtest_evaluate"):
            print(" token absent:", token)
            self.assertNotIn(token, blob.lower() if token.isascii() else blob)

        for entry_id in _NEW_IDS + ("backtest_intro", "optimize_intro", "optimize_result"):
            entry = json.loads((_KB_DIR / f"{entry_id}.json").read_text(encoding="utf-8"))
            narrative = entry.get("narrative") or ""
            print(" card:", entry_id, "has split-twice phrase:", "前后各跑一次" in narrative)
            self.assertNotIn("前后各跑一次", narrative)
            self.assertNotIn("earlier window and a later window", narrative)

    def test_mece_keyword_and_relation_seams(self) -> None:
        """配置卡不抢频率词；日志卡不抢 trace；机制卡边与优势卡互指。"""

        print("\n[TestAiKbC5Backtest] MECE 缝")
        config = json.loads((_KB_DIR / "backtest_config.json").read_text(encoding="utf-8"))
        trade_log = json.loads((_KB_DIR / "backtest_trade_log.json").read_text(encoding="utf-8"))
        result = json.loads((_KB_DIR / "backtest_result.json").read_text(encoding="utf-8"))
        engine_card = json.loads((_KB_DIR / "backtest_engine.json").read_text(encoding="utf-8"))
        lookahead = json.loads((_KB_DIR / "lookahead_isolation.json").read_text(encoding="utf-8"))
        advantages = json.loads((_KB_DIR / "qteasy_advantages.json").read_text(encoding="utf-8"))
        realize = json.loads((_KB_DIR / "strategy_realize.json").read_text(encoding="utf-8"))
        rows = {row["id"]: row for row in _load_entries(_MAP_PATH)}

        config_kw = " ".join(config.get("keywords") or [])
        print(" config keywords:", config_kw)
        self.assertNotIn("run_freq", config_kw)
        self.assertNotIn("freq", config_kw.split())
        self.assertNotIn("运行频率", config_kw)
        self.assertIn("operator_run_freq", _relation_targets(config))

        log_kw = " ".join(trade_log.get("keywords") or [])
        print(" trade_log keywords:", log_kw)
        self.assertNotIn("trace", log_kw.lower())
        self.assertIn("strategy_trace", _relation_targets(trade_log))

        print(" result tos:", _relation_targets(result))
        self.assertIn("common_errors_nan", _relation_targets(result))
        print(" engine tos:", _relation_targets(engine_card))
        self.assertIn("lookahead_isolation", _relation_targets(engine_card))
        print(" lookahead tos:", _relation_targets(lookahead))
        self.assertIn("qteasy_advantages", _relation_targets(lookahead))
        self.assertIn("strategy_realize", _relation_targets(lookahead))
        self.assertIn("lookahead_isolation", _relation_targets(advantages))
        self.assertIn("lookahead_isolation", _relation_targets(realize))
        self.assertNotIn(
            "qteasy 如何防止未来函数",
            rows["qteasy_advantages"]["questions"],
        )
        self.assertIn(
            "qteasy 如何防止未来函数",
            rows["lookahead_isolation"]["questions"],
        )

    def test_writer_oos_clause_only_for_backtest_or_optimize(self) -> None:
        """替身：选中回测或优化卡时作家含前后段通识；只选数据卡时没有。"""

        print("\n[TestAiKbC5Backtest] 作家通识条款")
        kb = KnowledgeBase()
        clause_bits = (
            "earlier window and a later window",
            "cut date",
            "handbook comparison protocol",
        )

        fake_bt = FakeLLMProvider(
            replies=[
                json.dumps({"topics": ["backtest"]}, ensure_ascii=False),
                json.dumps({"ids": ["backtest_intro"]}, ensure_ascii=False),
                "Backtest rehearses rules on history.",
            ]
        )
        engine_bt = AskEngine(knowledge_base=kb, provider=fake_bt)
        payload_bt = engine_bt.ask("回测是什么").to_dict()
        writer_bt = fake_bt.system_prompts[2]
        print(" backtest writer:", writer_bt[-280:])
        print(" sources:", payload_bt.get("sources"))
        self.assertTrue(payload_bt["ok"])
        self.assertEqual(payload_bt["sources"][0], "backtest_intro")
        for bit in clause_bits:
            self.assertIn(bit, writer_bt)

        fake_opt = FakeLLMProvider(
            replies=[
                json.dumps({"topics": ["optimize"]}, ensure_ascii=False),
                json.dumps({"ids": ["optimize_intro"]}, ensure_ascii=False),
                "Optimize searches parameters.",
            ]
        )
        engine_opt = AskEngine(knowledge_base=kb, provider=fake_opt)
        payload_opt = engine_opt.ask("优化在做什么").to_dict()
        writer_opt = fake_opt.system_prompts[2]
        print(" optimize writer tail:", writer_opt[-200:])
        self.assertTrue(payload_opt["ok"])
        for bit in clause_bits:
            self.assertIn(bit, writer_opt)

        fake_data = FakeLLMProvider(
            replies=[
                json.dumps({"topics": ["data-analysis"]}, ensure_ascii=False),
                json.dumps({"ids": ["data_three_entries"]}, ensure_ascii=False),
                "Three entries for shapes.",
            ]
        )
        engine_data = AskEngine(knowledge_base=kb, provider=fake_data)
        payload_data = engine_data.ask("三入口有什么区别").to_dict()
        writer_data = fake_data.system_prompts[2]
        print(" data writer has oos clause:", "earlier window and a later window" in writer_data)
        print(" data sources:", payload_data.get("sources"))
        self.assertTrue(payload_data["ok"])
        self.assertNotIn("earlier window and a later window", writer_data)
        self.assertNotIn("cut date", writer_data)


if __name__ == "__main__":
    unittest.main()

# coding=utf-8
# ======================================
# File: test_ai_knowledge_base.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-28
# Desc:
# Unittest for qteasy-ai KnowledgeBase retrieval
# ======================================

import unittest

from qteasy_ai.knowledge_base import KnowledgeBase


class TestAiKnowledgeBase(unittest.TestCase):
    """测试策展 KnowledgeBase 的关键词/tag 检索。"""

    def setUp(self) -> None:
        self.kb = KnowledgeBase(
            list_func=lambda: ["macd", "dma"],
            doc_func=lambda sid: f"{sid} tunable parameters: fast, slow, signal.",
        )

    def test_retrieve_pt_ps_vs(self) -> None:
        """explain PT vs PS 应命中 pt_ps_vs，且文案为英文。"""

        print("\n[TestAiKnowledgeBase] retrieve PT/PS/VS")
        hits = self.kb.retrieve("explain PT vs PS")
        ids = [item.id for item in hits]
        print(" hit ids:", ids)
        print(" first narrative:", hits[0].narrative[:200] if hits else "")
        self.assertIn("pt_ps_vs", ids)
        self.assertIn("Position Target", hits[0].narrative)
        self.assertIn("PT", hits[0].narrative)
        self.assertIn("PS", hits[0].narrative)

    def test_retrieve_run_freq(self) -> None:
        """run_freq 问法应命中 operator_run_freq。"""

        print("\n[TestAiKnowledgeBase] retrieve run_freq")
        hits = self.kb.retrieve("where does run_freq belong, Operator or qt.run?")
        ids = [item.id for item in hits]
        print(" hit ids:", ids)
        print(" narrative:", hits[0].narrative[:240] if hits else "")
        self.assertIn("operator_run_freq", ids)
        self.assertIn("qt.run", hits[0].narrative)
        self.assertIn("Operator", hits[0].narrative)

    def test_retrieve_modes(self) -> None:
        """Ask/Plan/Agent 问法应命中 ask_plan_agent。"""

        print("\n[TestAiKnowledgeBase] retrieve modes")
        hits = self.kb.retrieve("difference between Ask Plan and Agent modes")
        ids = [item.id for item in hits]
        print(" hit ids:", ids)
        self.assertIn("ask_plan_agent", ids)
        self.assertIn("Ask", hits[0].narrative)
        self.assertIn("Plan", hits[0].narrative)

    def test_retrieve_common_errors(self) -> None:
        """缺日期窗 / NaN 价格应命中 common_errors。"""

        print("\n[TestAiKnowledgeBase] retrieve common errors")
        date_hits = self.kb.retrieve("get_history_data failed because start and end missing")
        nan_hits = self.kb.retrieve("what happens when trade price is NaN")
        print(" date ids:", [item.id for item in date_hits])
        print(" nan ids:", [item.id for item in nan_hits])
        print(" date narrative:", date_hits[0].narrative[:200] if date_hits else "")
        self.assertIn("common_errors", [item.id for item in date_hits])
        self.assertIn("start", date_hits[0].narrative.lower())
        self.assertIn("common_errors", [item.id for item in nan_hits])
        self.assertIn("NaN", nan_hits[0].narrative)

    def test_retrieve_side_effects_safety(self) -> None:
        """实盘/副作用问法应命中 side_effects_safety。"""

        print("\n[TestAiKnowledgeBase] retrieve safety")
        hits = self.kb.retrieve("will Agent auto execute live trade")
        ids = [item.id for item in hits]
        print(" hit ids:", ids)
        self.assertIn("side_effects_safety", ids)
        self.assertIn("live", hits[0].narrative.lower())

    def test_retrieve_strategy_meta_live_source(self) -> None:
        """策略问答走内置 API 数据源，不经 skill。"""

        print("\n[TestAiKnowledgeBase] strategy meta live")
        hits = self.kb.retrieve("what is macd strategy")
        ids = [item.id for item in hits]
        print(" hit ids:", ids)
        print(" narratives:", [item.narrative[:160] for item in hits])
        self.assertTrue(any(item.id == "strategy_meta" for item in hits))
        meta = next(item for item in hits if item.id == "strategy_meta")
        self.assertIn("macd", meta.narrative.lower())
        self.assertIn("fast", meta.narrative.lower())

    def test_retrieve_miss_returns_empty(self) -> None:
        """无关问法不应硬凑命中。"""

        print("\n[TestAiKnowledgeBase] miss")
        hits = self.kb.retrieve("quantum foam meaning of life xyzzy-no-match")
        print(" hits:", [item.id for item in hits])
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()

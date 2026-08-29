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

_MACD_KERNEL_ZH = (
    "MACD择时策略类，运用MACD均线策略，生成目标仓位百分比\n"
    "    策略参数:\n"
    "        s: int, 短周期指数平滑均线计算日期；\n"
    "        l: int, 长周期指数平滑均线计算日期；\n"
    "        m: int, MACD中间值DEA的计算周期；\n"
    "    信号类型:\n"
    "        PT型: 目标仓位百分比\n"
    "    信号规则:\n"
    "        1，当MACD值大于0时，设置仓位目标为1\n"
    "        2，当MACD值小于0时，设置仓位目标为0\n"
    "    策略属性缺省值:\n"
    "        默认参数: (12, 26, 9)\n"
)


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
        """run_freq 问法只命中 operator_run_freq，不 bleed 到 Ask/Plan 或错误合集。"""

        print("\n[TestAiKnowledgeBase] retrieve run_freq")
        hits = self.kb.retrieve("where does run_freq belong, Operator or qt.run?")
        ids = [item.id for item in hits]
        print(" hit ids:", ids)
        print(" scores:", [(item.id, item.score) for item in hits])
        print(" narrative:", hits[0].narrative[:240] if hits else "")
        self.assertEqual(ids, ["operator_run_freq"])
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
        """缺日期窗与 NaN 价格命中不同子题条目。"""

        print("\n[TestAiKnowledgeBase] retrieve common errors by subtopic")
        date_hits = self.kb.retrieve("get_history_data failed because start and end missing")
        nan_hits = self.kb.retrieve("what happens when trade price is NaN")
        print(" date ids:", [item.id for item in date_hits])
        print(" nan ids:", [item.id for item in nan_hits])
        print(" date narrative:", date_hits[0].narrative[:200] if date_hits else "")
        print(" nan python_code:", nan_hits[0].python_code if nan_hits else "")
        self.assertEqual(date_hits[0].id, "common_errors_date_window")
        self.assertIn("start", date_hits[0].narrative.lower())
        self.assertEqual(nan_hits[0].id, "common_errors_nan")
        self.assertIn("NaN", nan_hits[0].narrative)
        self.assertNotIn("get_history_data", nan_hits[0].python_code)

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

    def test_retrieve_strategy_meta_wraps_chinese_doc(self) -> None:
        """内核中文 docstring 不进入顶层 narrative，保留在 kernel_doc_zh。"""

        print("\n[TestAiKnowledgeBase] strategy meta English wrap")
        kb = KnowledgeBase(
            list_func=lambda: ["macd"],
            doc_func=lambda sid: _MACD_KERNEL_ZH,
        )
        hits = kb.retrieve("what is macd strategy")
        meta = next(item for item in hits if item.id == "strategy_meta")
        print(" narrative:", meta.narrative)
        print(" kernel_doc_zh prefix:", (meta.kernel_doc_zh or "")[:80])
        self.assertIn("PT", meta.narrative)
        self.assertIn("(12, 26, 9)", meta.narrative)
        self.assertNotIn("择时策略类", meta.narrative)
        self.assertIn("择时策略类", meta.kernel_doc_zh)

    def test_retrieve_miss_returns_empty(self) -> None:
        """无关问法不应硬凑命中。"""

        print("\n[TestAiKnowledgeBase] miss")
        hits = self.kb.retrieve("quantum foam meaning of life xyzzy-no-match")
        print(" hits:", [item.id for item in hits])
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()

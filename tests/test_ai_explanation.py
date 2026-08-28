# coding=utf-8
# ======================================
# File: test_ai_explanation.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-28
# Desc:
# Unittest for explanation_template depth
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant
from qteasy_ai.explanation import apply_explanation_depth
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.renderer import OutputRenderer


class TestAiExplanation(unittest.TestCase):
    """测试 explanation_depth 三档裁剪。"""

    def test_brief_drops_python_code(self) -> None:
        """brief：保留 narrative，python_code 为空。"""

        print("\n[TestAiExplanation] brief")
        channels = apply_explanation_depth(
            narrative="PT is Position Target.",
            python_code="print('pt')",
            result_preview="sources=['pt_ps_vs']",
            depth="brief",
            risk_notes="PT cash reuse is conditional.",
        )
        print(" narrative:", channels.narrative)
        print(" python_code:", repr(channels.python_code))
        print(" preview:", channels.result_preview)
        self.assertIn("Position Target", channels.narrative)
        self.assertEqual(channels.python_code, "")
        self.assertTrue(channels.result_preview)

    def test_standard_keeps_three_channels(self) -> None:
        """standard：三通道齐全，不追加 risk_notes。"""

        print("\n[TestAiExplanation] standard")
        channels = apply_explanation_depth(
            narrative="PT is Position Target.",
            python_code="print('pt')",
            result_preview="sources=['pt_ps_vs']",
            depth="standard",
            risk_notes="hidden in standard",
        )
        print(" channels:", channels)
        self.assertIn("Position Target", channels.narrative)
        self.assertIn("print", channels.python_code)
        self.assertIn("pt_ps_vs", channels.result_preview)
        self.assertNotIn("hidden in standard", channels.narrative)

    def test_deep_appends_risk_notes(self) -> None:
        """deep：narrative 含风险提示，并保留完整代码。"""

        print("\n[TestAiExplanation] deep")
        channels = apply_explanation_depth(
            narrative="PT is Position Target.",
            python_code="print('pt')",
            result_preview="sources=['pt_ps_vs']",
            depth="deep",
            risk_notes="PT cash reuse is conditional.",
        )
        print(" narrative:", channels.narrative)
        print(" python_code:", channels.python_code)
        self.assertIn("Position Target", channels.narrative)
        self.assertIn("Risk / assumptions", channels.narrative)
        self.assertIn("PT cash reuse", channels.narrative)
        self.assertIn("print", channels.python_code)

    def test_ask_depth_brief_and_deep(self) -> None:
        """Ask 入口透传 explanation_depth。"""

        print("\n[TestAiExplanation] ask depths")
        assistant = QteasyAssistant(memory_store=MemoryStore(base_dir=tempfile.mkdtemp()))
        brief = assistant.ask("explain PT vs PS", response_style="raw", explanation_depth="brief")
        deep = assistant.ask("explain PT vs PS", response_style="raw", explanation_depth="deep")
        print(" brief code:", repr(brief.get("python_code")))
        print(" deep narrative tail:", brief.get("narrative", "")[-80:], "||", deep.get("narrative", "")[-120:])
        self.assertEqual(brief.get("python_code"), "")
        self.assertIn("PT", brief.get("narrative", ""))
        self.assertTrue(deep.get("python_code"))
        self.assertIn("Risk", deep.get("narrative", ""))

    def test_renderer_uses_shared_template(self) -> None:
        """Plan pretty 经 renderer 走同一套深度模板。"""

        print("\n[TestAiExplanation] renderer depth")
        renderer = OutputRenderer()
        payload = {
            "plan": {"steps": [{"skill_name": "qt.ai.strategy_meta.list"}]},
            "execution": {
                "steps": [
                    {
                        "result": {
                            "metrics": {"count": 2},
                            "payload": {"strategies": ["macd", "dma"]},
                        }
                    }
                ]
            },
        }
        brief = renderer.render(payload, explanation_depth="brief")
        standard = renderer.render(payload, explanation_depth="standard")
        print(" brief code:", repr(brief.python_code))
        print(" standard code:", standard.python_code[:80])
        self.assertEqual(brief.python_code, "")
        self.assertIn("Listed built-in strategies", brief.narrative)
        self.assertIn("qt.built_in_list()", standard.python_code)


if __name__ == "__main__":
    unittest.main()

# coding=utf-8
# ======================================
# File: test_ai_output_renderer.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-20
# Desc:
# Unittest for qteasy ai output renderer
# ======================================

import unittest

from qteasy_ai.renderer import OutputRenderer


class TestAiOutputRenderer(unittest.TestCase):
    """测试输出渲染层。"""

    def test_render_strategy_list_output(self) -> None:
        """验证策略列表输出渲染字段。"""

        renderer = OutputRenderer()
        payload = {
            "plan": {
                "steps": [{"skill_name": "qt.ai.strategy_meta.list"}],
            },
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
        output = renderer.render(payload)
        print("\n[TestAiOutputRenderer] output:", output.to_dict())
        self.assertIn("Listed built-in strategies", output.narrative)
        self.assertIn("qt.built_in_list()", output.python_code)
        self.assertIn("macd", output.result_preview)

    def test_render_fallback_output(self) -> None:
        """验证 fallback 输出渲染。"""

        renderer = OutputRenderer()
        payload = {
            "plan": {"steps": [{"skill_name": "qt.ai.system.fallback"}]},
            "execution": {"steps": [{"result": {"payload": {"fallback_action": "plan_only", "hint": "manual confirm"}}}]},
        }
        output = renderer.render(payload)
        print("\n[TestAiOutputRenderer] fallback output:", output.to_dict())
        self.assertIn("system fallback", output.narrative)
        self.assertIn("fallback_action", output.narrative)
        self.assertIn("plan_only", output.narrative)

    def test_dry_run_does_not_claim_executed(self) -> None:
        """dry_run pretty 不得使用 successfully/completed。"""

        print("\n[TestAiOutputRenderer] dry_run narrative")
        renderer = OutputRenderer()
        payload = {
            "plan": {
                "steps": [{"skill_name": "qt.ai.strategy_meta.list"}],
                "execution_mode": "dry_run",
            },
            "execution": {"status": "dry_run", "steps": []},
        }
        output = renderer.render(payload)
        print(" narrative:", output.narrative)
        self.assertIn("Dry-run plan (not executed)", output.narrative)
        self.assertNotIn("successfully", output.narrative.lower())
        self.assertNotIn("completed", output.narrative.lower())


if __name__ == "__main__":
    unittest.main()

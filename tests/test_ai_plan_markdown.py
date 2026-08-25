# coding=utf-8
# ======================================
# File: test_ai_plan_markdown.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-25
# Desc:
# Unittest for ToolPlan → plan.md rendering
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant
from qteasy_ai.contracts import SkillSideEffects, ToolPlan, ToolStep, new_plan_id
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.plan_markdown import tool_plan_to_markdown


class TestAiPlanMarkdown(unittest.TestCase):
    """测试 plan.md 单向双轨。"""

    def test_two_step_plan_markdown_contains_skills_and_effects(self) -> None:
        """固定 2-step plan 的 md 含 skill 名与副作用标签。"""

        print("\n[TestAiPlanMarkdown] two-step markdown")
        plan = ToolPlan(
            plan_id=new_plan_id(),
            user_query="check env",
            mode="plan",
            execution_mode="dry_run",
            assumptions={"planner": "hybrid_candidate_stage_b0"},
            steps=[
                ToolStep(
                    step_id="step_1",
                    skill_name="qt.ai.env.check_tushare",
                    inputs={},
                    side_effects=SkillSideEffects(description="readonly"),
                ),
                ToolStep(
                    step_id="step_2",
                    skill_name="qt.ai.visual.export_kline",
                    inputs={"shares": "000300.SH"},
                    side_effects=SkillSideEffects(filesystem_write=True, description="export image file"),
                ),
            ],
        )
        md = tool_plan_to_markdown(plan)
        print(" plan_md:\n", md)
        self.assertIn("qt.ai.env.check_tushare", md)
        self.assertIn("qt.ai.visual.export_kline", md)
        self.assertIn("readonly", md)
        self.assertIn("filesystem_write", md)
        self.assertIn("hybrid_candidate_stage_b0", md)

    def test_plan_payload_includes_plan_md_and_persists_file(self) -> None:
        """plan() raw payload 含非空 plan_md，persist 时落 runs/*.plan.md。"""

        print("\n[TestAiPlanMarkdown] payload and persist")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            assistant = QteasyAssistant(memory_store=store)
            payload = assistant.plan(
                "list built-in strategies",
                response_style="raw",
                persist="audit",
            )
            plan_md = payload.get("plan_md", "")
            print(" plan_md snippet:", plan_md[:200])
            print(" run_id:", payload.get("run_id"))
            self.assertTrue(isinstance(plan_md, str) and len(plan_md) > 0)
            self.assertIn("qt.ai.strategy_meta.list", plan_md)
            run_id = payload["run_id"]
            md_path = store.runs_dir / f"{run_id}.plan.md"
            print(" md_path exists:", md_path.exists(), md_path)
            self.assertTrue(md_path.exists())
            disk_md = md_path.read_text(encoding="utf-8")
            self.assertIn("qt.ai.strategy_meta.list", disk_md)


if __name__ == "__main__":
    unittest.main()

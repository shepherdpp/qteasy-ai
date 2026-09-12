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
from qteasy_ai.provider import FakeLLMProvider


class TestAiPlanMarkdown(unittest.TestCase):
    """测试 plan.md 单向双轨（G.10 Mode-R 叙事 + mermaid）。"""

    def _two_step_plan(self) -> ToolPlan:
        """固定两步只读+写文件计划。"""

        return ToolPlan(
            plan_id=new_plan_id(),
            user_query="check env then export",
            mode="plan",
            execution_mode="dry_run",
            assumptions={
                "planner": "hybrid_candidate_stage_b0",
                "gold_lock": "A1",
                "hybrid_intent": "env.ready",
                "shares": "000300.SH",
            },
            planner_trace={"intent_job": "env.ready"},
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
                    depends_on=["step_1"],
                    side_effects=SkillSideEffects(
                        filesystem_write=True,
                        description="export image file",
                    ),
                ),
            ],
        )

    def test_two_step_plan_markdown_contains_skills_and_effects(self) -> None:
        """固定 2-step plan 的 md 含 skill、副作用、mermaid，不含内部 dump。"""

        print("\n[TestAiPlanMarkdown] two-step markdown")
        plan = self._two_step_plan()
        md = tool_plan_to_markdown(plan)
        print(" plan_md:\n", md)
        self.assertIn("# Plan", md)
        self.assertNotIn("# ToolPlan", md)
        self.assertIn("qt.ai.env.check_tushare", md)
        self.assertIn("qt.ai.visual.export_kline", md)
        self.assertIn("readonly", md)
        self.assertIn("filesystem_write", md)
        self.assertIn("```mermaid", md)
        self.assertIn("flowchart TD", md)
        self.assertIn("step_1 --> step_2", md)
        self.assertIn("shares: 000300.SH", md)
        self.assertNotIn("gold_lock", md)
        self.assertNotIn("hybrid_intent", md)
        self.assertNotIn("hybrid_candidate_stage_b0", md)

    def test_mode_r_is_deterministic_without_provider(self) -> None:
        """无 Provider 时两次渲染正文相同。"""

        print("\n[TestAiPlanMarkdown] deterministic mode-r")
        plan = self._two_step_plan()
        first = tool_plan_to_markdown(plan)
        second = tool_plan_to_markdown(plan)
        print(" equal:", first == second, "len:", len(first))
        self.assertEqual(first, second)
        self.assertNotIn("## Why this plan", first)

    def test_fake_llm_why_overlay_kept_when_allowed(self) -> None:
        """合法 Why 叠段保留，Mode-R 步骤仍在。"""

        print("\n[TestAiPlanMarkdown] allowed why overlay")
        plan = self._two_step_plan()
        why = (
            "This plan checks Tushare first, then exports a k-line with "
            "qt.ai.visual.export_kline for 000300.SH."
        )
        provider = FakeLLMProvider(replies=[why])
        md = tool_plan_to_markdown(plan, provider=provider)
        print(" md head:\n", "\n".join(md.splitlines()[:20]))
        self.assertIn("## Why this plan", md)
        self.assertIn(why, md)
        self.assertIn("qt.ai.env.check_tushare", md)
        self.assertIn("```mermaid", md)
        self.assertEqual(len(provider.replies), 0)

    def test_fake_llm_invented_skill_is_dropped(self) -> None:
        """Why 捏造未出现的 skill 时丢弃叠段。"""

        print("\n[TestAiPlanMarkdown] drop invented skill")
        plan = self._two_step_plan()
        invented = (
            "Skip the probe and run qt.ai.backtest.run_builtin on CSI 300 instead."
        )
        provider = FakeLLMProvider(replies=[invented])
        md = tool_plan_to_markdown(plan, provider=provider)
        print(" has why:", "## Why this plan" in md)
        print(" has invented skill:", "qt.ai.backtest.run_builtin" in md)
        self.assertNotIn("## Why this plan", md)
        self.assertNotIn("qt.ai.backtest.run_builtin", md)
        self.assertIn("qt.ai.env.check_tushare", md)
        self.assertIn("qt.ai.visual.export_kline", md)

    def test_fake_llm_metric_is_dropped(self) -> None:
        """Why 写入 drawdown 等指标时丢弃叠段。"""

        print("\n[TestAiPlanMarkdown] drop metric why")
        plan = self._two_step_plan()
        provider = FakeLLMProvider(replies=["Expected max drawdown is 12%."])
        md = tool_plan_to_markdown(plan, provider=provider)
        print(" has why:", "## Why this plan" in md)
        self.assertNotIn("## Why this plan", md)
        self.assertNotIn("drawdown", md.lower())

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
            print(" plan_md snippet:", plan_md[:240])
            print(" run_id:", payload.get("run_id"))
            self.assertTrue(isinstance(plan_md, str) and len(plan_md) > 0)
            self.assertIn("qt.ai.strategy_meta.list", plan_md)
            self.assertIn("# Plan", plan_md)
            self.assertNotIn("# ToolPlan", plan_md)
            self.assertNotIn("gold_lock", plan_md)
            self.assertNotIn("hybrid_intent", plan_md)
            self.assertIn("List built-in strategies", plan_md)
            self.assertIn("```mermaid", plan_md)
            run_id = payload["run_id"]
            md_path = store.runs_dir / f"{run_id}.plan.md"
            print(" md_path exists:", md_path.exists(), md_path)
            self.assertTrue(md_path.exists())
            disk_md = md_path.read_text(encoding="utf-8")
            self.assertIn("qt.ai.strategy_meta.list", disk_md)
            self.assertNotIn("# ToolPlan", disk_md)

    def test_oneshot_run_list_has_no_plan_md(self) -> None:
        """一次性 run list 仍 success，无新 *.plan.md。"""

        print("\n[TestAiPlanMarkdown] oneshot run no plan.md")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            assistant = QteasyAssistant(memory_store=store)
            before = list(store.runs_dir.glob("*.plan.md"))
            payload = assistant.run(
                "list built-in strategies",
                response_style="raw",
                persist="audit",
            )
            after = list(store.runs_dir.glob("*.plan.md"))
            status = str((payload.get("execution") or {}).get("status") or "")
            print(" status:", status)
            print(" md before:", before, "after:", after)
            print(" plan_md_file:", payload.get("plan_md_file"))
            self.assertEqual(status, "success")
            self.assertEqual(before, after)
            self.assertFalse(str(payload.get("plan_md_file") or "").strip())
            self.assertFalse(str(payload.get("plan_md") or "").strip())


if __name__ == "__main__":
    unittest.main()

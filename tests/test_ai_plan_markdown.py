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

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.contracts import SkillSideEffects, ToolPlan, ToolStep, new_plan_id
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.plan_markdown import plan_artifact_title, run_group_title, tool_plan_to_markdown
from qteasy_ai.planner import Planner
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

    def test_plan_artifact_title_uses_first_skill_and_hex(self) -> None:
        """显示名用人话第一步 + hex；不改 plan_id 格式。"""

        print("\n[TestAiPlanMarkdown] plan artifact display title")
        pid = new_plan_id()
        print(" plan_id:", pid)
        self.assertRegex(pid, r"^plan_[0-9a-f]{12}$")
        titled = plan_artifact_title(
            pid,
            steps=[{"skill_name": "qt.ai.strategy_meta.list"}],
        )
        print(" titled:", titled)
        self.assertNotEqual(titled, "plan.md")
        self.assertIn("List", titled)
        self.assertIn(pid.replace("plan_", "")[:8], titled)
        empty = plan_artifact_title("plan_ab12cd34ef56", steps=[])
        print(" empty steps:", empty)
        self.assertTrue(empty.startswith("Plan ·"))
        self.assertIn("ab12cd34", empty)

    def test_run_group_title_uses_first_skill_and_hex(self) -> None:
        """孤儿 run 显示名用人话第一步 + run 短 hex；字典 summary 不覆盖标题。"""

        print("\n[TestAiPlanMarkdown] orphan run group title")
        rid = "run_5632abcd1234"
        titled = run_group_title(
            rid,
            steps=[{
                "skill_name": "qt.ai.data.read",
                "summary": {"message": "not a title"},
            }],
        )
        print(" titled:", titled)
        self.assertEqual(
            titled,
            "Read market data (history / reference / static) · 5632abcd",
        )
        empty = run_group_title("run_ab12cd34ef56", steps=[])
        print(" empty steps:", empty)
        self.assertEqual(empty, "Run · ab12cd34")

    def test_optimize_plan_states_date_source_and_ai_defaults(self) -> None:
        """优化计划写明日期来源，以及 AI 默认 opti_method / opti_sample_count。"""

        print("\n[TestAiPlanMarkdown] optimize date source and AI defaults")
        plan = Planner(build_default_registry(), env_facts={}).build_plan(
            "optimize DMA parameters",
            mode="plan",
        )
        md = tool_plan_to_markdown(plan)
        print(" plan_md:\n", md)
        self.assertIn("qt.ai.optimize.run_builtin", md)
        self.assertIn("opti_method=montecarlo", md)
        self.assertIn("opti_sample_count=32", md)
        self.assertIn("AI default", md)
        self.assertIn("kernel", md)
        self.assertNotIn("drawdown", md.lower())
        self.assertNotIn("hit_count", md.lower())

    def test_chinese_query_without_provider_stays_english(self) -> None:
        """无 Provider 时中文问句仍是英文 Mode-R。"""

        print("\n[TestAiPlanMarkdown] chinese query mode-r stays english")
        plan = self._two_step_plan()
        plan.user_query = "请导出 K 线"
        md = tool_plan_to_markdown(plan)
        print(" head:", md.splitlines()[:6])
        self.assertIn("# Plan", md)
        self.assertIn("You asked: 请导出 K 线", md)
        self.assertNotIn("## Why this plan", md)

    def test_chinese_provider_rewrites_prose_and_keeps_code_mermaid(self) -> None:
        """中文问句 + Provider：散文跟用户语言，mermaid 仍是代码生成的。"""

        print("\n[TestAiPlanMarkdown] chinese provider rewrite")
        plan = self._two_step_plan()
        plan.user_query = "请先检查环境再导出 K 线"
        mode_r = tool_plan_to_markdown(plan)
        zh = (
            "# 计划\n\n"
            "先检查环境，再导出 K 线。\n\n"
            "1. 检查 Tushare（`qt.ai.env.check_tushare`）\n"
            "2. 导出 K 线（`qt.ai.visual.export_kline`）\n"
            "预期产物是图表文件，没有收益数字。\n"
        )
        provider = FakeLLMProvider(replies=[zh])
        md = tool_plan_to_markdown(plan, provider=provider)
        print(" md:\n", md)
        self.assertIn("先检查环境", md)
        self.assertIn("qt.ai.env.check_tushare", md)
        self.assertIn("qt.ai.visual.export_kline", md)
        self.assertNotIn("## What will run", md)
        self.assertNotIn("## Why this plan", md)
        self.assertIn("```mermaid", md)
        self.assertIn("step_1 --> step_2", md)
        fence = mode_r.index("```mermaid")
        fence_end = mode_r.index("```", fence + 3) + 3
        self.assertIn(mode_r[fence:fence_end], md)
        self.assertNotIn("gold_lock", md)

    def test_chinese_provider_metric_falls_back_to_english(self) -> None:
        """中文改写若夹带回撤数字则丢弃，留英文 Mode-R。"""

        print("\n[TestAiPlanMarkdown] chinese rewrite dropped on metric")
        plan = self._two_step_plan()
        plan.user_query = "请导出 K 线"
        provider = FakeLLMProvider(
            replies=["计划会把最大回撤降到 12%，并调用 qt.ai.env.check_tushare 与 qt.ai.visual.export_kline。"]
        )
        md = tool_plan_to_markdown(plan, provider=provider)
        print(" has plan heading:", "# Plan" in md)
        print(" has drawdown:", "回撤" in md or "drawdown" in md.lower())
        self.assertIn("# Plan", md)
        self.assertIn("You asked:", md)
        self.assertNotIn("回撤", md)
        self.assertNotIn("drawdown", md.lower())

    def test_factor_ic_plan_lists_declared_slot_hints(self) -> None:
        """因子 IC 的 plan.md 写出两列的 label 与 hint，不写出技能参数 method。"""

        print("\n[TestAiPlanMarkdown] factor IC slots in plan.md")
        plan = ToolPlan(
            plan_id=new_plan_id(),
            user_query="factor IC summary for selection pool",
            mode="plan",
            execution_mode="dry_run",
            assumptions={"shares": "000001.SZ 000002.SZ"},
            planner_trace={"intent_job": "research.factor_ic"},
            steps=[
                ToolStep(
                    step_id="step_1",
                    skill_name="qt.ai.research.factor_ic_summary",
                    inputs={
                        "shares": "000001.SZ 000002.SZ",
                        "start": "20240101",
                        "end": "20240331",
                        "factor_htype": "close",
                        "return_htype": "volume",
                        "method": "spearman",
                    },
                    side_effects=SkillSideEffects(description="readonly"),
                ),
            ],
        )
        md = tool_plan_to_markdown(plan)
        print(" plan_md:\n", md)
        self.assertIn("factor_htype=close", md)
        self.assertIn("return_htype=volume", md)
        self.assertIn("- Factor column: close", md)
        self.assertIn("  One local history column, such as close.", md)
        self.assertIn("- Return column: volume", md)
        self.assertIn(
            "  One different local history column, such as volume. "
            "This skill does not compute or shift return columns.",
            md,
        )
        self.assertNotIn("method", md)

    def _one_step(self, skill: str) -> ToolPlan:
        """单步计划，用来抽查某个 skill 的人读投影。"""

        return ToolPlan(
            plan_id=new_plan_id(),
            user_query=f"run {skill}",
            mode="plan",
            execution_mode="dry_run",
            steps=[
                ToolStep(
                    step_id="step_1",
                    skill_name=skill,
                    inputs={},
                    side_effects=SkillSideEffects(description="readonly"),
                ),
            ],
        )

    def test_skill_expected_artifact_projects_into_plan_md(self) -> None:
        """原先走兜底的三个 skill，plan.md 写出产物句与入口或读写。"""

        print("\n[TestAiPlanMarkdown] skill expected artifact projection")
        registry = build_default_registry()
        skills = (
            "qt.ai.strategy_meta.list",
            "qt.ai.env.overview_tables",
            "qt.ai.insight.summarize_backtest",
        )
        for skill in skills:
            meta = registry.get_metadata(skill)
            expect = str(meta.expected_artifact or "").strip()
            plan = self._one_step(skill)
            md = tool_plan_to_markdown(plan, registry=registry)
            print(" skill:", skill)
            print(" expect:", expect)
            print(" entrypoints:", list(meta.qteasy_entrypoints or []))
            print(" plan_md:\n", md)
            self.assertTrue(expect)
            self.assertIn(expect, md)
            self.assertIn(f"Calls: `{skill}`", md)
            self.assertIn("Reads / writes:", md)
            result_section = md.split("## Expected result", 1)[1]
            print(" expected result section:\n", result_section)
            self.assertIn(expect, result_section)
            entries = [str(item) for item in (meta.qteasy_entrypoints or []) if str(item).strip()]
            if entries:
                self.assertIn(entries[0], md)
            self.assertNotIn("performance figures are unknown", md)
            self.assertNotIn("JSON wins", md)
            self.assertNotIn("High side effects", md)
            self.assertNotIn("Reads as:", md)
            self.assertIn("Nothing runs until you confirm.", md)

    def test_every_builtin_skill_declares_expected_artifact(self) -> None:
        """每个内置 skill 都有人读预期句，且不含指标词与通用空话。"""

        print("\n[TestAiPlanMarkdown] every skill expected_artifact")
        registry = build_default_registry()
        metas = registry.list_skills()
        print(" count:", len(metas))
        self.assertGreaterEqual(len(metas), 20)
        banned = (
            "performance figures are unknown",
            "drawdown",
            "hit_count",
            "sharpe",
            "回撤",
        )
        for meta in metas:
            text = str(meta.expected_artifact or "").strip()
            print(" ", meta.name, ":", text)
            self.assertTrue(text, meta.name)
            lowered = text.lower()
            for word in banned:
                self.assertNotIn(word, lowered, meta.name)

    def test_missing_registry_skips_generic_fallback(self) -> None:
        """没有 registry 时只写 Calls，不用通用空话。"""

        print("\n[TestAiPlanMarkdown] no registry fallback")
        plan = self._one_step("qt.ai.env.overview_tables")
        md = tool_plan_to_markdown(plan)
        print(" plan_md:\n", md)
        self.assertIn("Calls qt.ai.env.overview_tables.", md)
        self.assertNotIn("performance figures are unknown", md)
        self.assertNotIn("JSON wins", md)
        self.assertNotIn("High side effects", md)
        self.assertNotIn("Reads as:", md)

    def test_empty_expected_artifact_synthesizes_summary_and_entrypoint(self) -> None:
        """字段为空时用 summary 与第一个入口名合成。"""

        class _Meta:
            """缺 expected_artifact 的假元数据。"""

            summary = "List things."
            qteasy_entrypoints = ["qteasy.built_in_list"]
            expected_artifact = ""

        class _Registry:
            """只返回上面那条假元数据。"""

            def get_metadata(self, skill_name: str) -> _Meta:
                return _Meta()

        print("\n[TestAiPlanMarkdown] synthesize empty expected_artifact")
        plan = self._one_step("qt.ai.strategy_meta.list")
        md = tool_plan_to_markdown(plan, registry=_Registry())
        print(" plan_md:\n", md)
        self.assertIn("List things. Calls qteasy.built_in_list.", md)
        self.assertIn("reads `qteasy.built_in_list`", md)


if __name__ == "__main__":
    unittest.main()

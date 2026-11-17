# coding=utf-8
# ======================================
# File: test_ai_open_workflow.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-10
# Desc:
# Unittest for G.7 Catalog workflow fork (open design loop)
# ======================================

import unittest
from typing import Optional

from qteasy_ai.app import build_default_registry
from qteasy_ai.intents import load_default_catalog
from qteasy_ai.planner import Planner, ToolPlan
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.session import ConversationState


class TestAiOpenWorkflow(unittest.TestCase):
    """Catalog ``workflow: open`` 分叉；系统 Job open 不变。"""

    def setUp(self) -> None:
        self.catalog = load_default_catalog()
        self.registry = build_default_registry()

    def test_job_workflow_field(self) -> None:
        """factor_explore 为 open；IC / builder 仍 closed；系统 open 缺省 closed。"""

        print("\n[TestAiOpenWorkflow] job_workflow field")
        print(" factor_explore:", self.catalog.job_workflow("research.factor_explore"))
        print(" factor_ic:", self.catalog.job_workflow("research.factor_ic"))
        print(" builder:", self.catalog.job_workflow("strategy.builder"))
        print(" system open:", self.catalog.job_workflow("open"))
        self.assertEqual(self.catalog.job_workflow("research.factor_explore"), "open")
        self.assertEqual(self.catalog.job_workflow("research.factor_ic"), "closed")
        self.assertEqual(self.catalog.job_workflow("strategy.builder"), "closed")
        self.assertEqual(self.catalog.job_workflow("open"), "closed")

    def test_gold_explore_does_not_enter_empty_design_loop(self) -> None:
        """Mode-R 金句不再把 steps 掏空成设计环。"""

        print("\n[TestAiOpenWorkflow] explore gold not empty design")
        query = "explore a useful momentum factor for hs300"
        plan = Planner(self.registry, env_facts={}).build_plan(query, mode="plan")
        names = [step.skill_name for step in plan.steps]
        print(" intent:", plan.planner_trace.get("intent_job"))
        print(" skills:", names)
        print(" design_loop:", (plan.assumptions or {}).get("design_loop"))
        self.assertEqual(plan.planner_trace.get("intent_job"), "research.factor_explore")
        self.assertFalse(bool((plan.assumptions or {}).get("design_loop")))

    def test_named_ic_gold_asks_for_missing_slots(self) -> None:
        """裸句缺代码、日期和列名时出澄清，不出可执行 IC 步。"""

        print("\n[TestAiOpenWorkflow] bare factor IC clarifies")
        plan = Planner(self.registry, env_facts={}).build_plan(
            "factor IC summary for selection pool", mode="plan"
        )
        names = [step.skill_name for step in plan.steps]
        inputs = plan.steps[0].inputs if plan.steps else {}
        print(" intent:", plan.planner_trace.get("intent_job"), "skills:", names)
        print(" missing_info:", inputs.get("missing_info"))
        print(" clarification:", (plan.assumptions or {}).get("clarification"))
        self.assertEqual(plan.planner_trace.get("intent_job"), "research.factor_ic")
        self.assertEqual(names, ["qt.ai.system.fallback"])
        self.assertEqual(inputs.get("fallback_action"), "clarify_required")
        missing = str(inputs.get("missing_info") or "")
        self.assertIn("shares", missing)
        self.assertIn("htype", missing)
        self.assertNotIn("qt.ai.research.factor_ic_summary", names)
        clar = (plan.assumptions or {}).get("clarification") or {}
        self.assertTrue(clar)
        pending = [item for item in (clar.get("pending") or []) if isinstance(item, dict)]
        pending_names = [str(item.get("name") or "") for item in pending]
        print(" pending names:", pending_names)
        print(" step_index:", clar.get("step_index"), "step_total:", clar.get("step_total"))
        self.assertGreaterEqual(len(pending), 2)
        self.assertEqual(int(clar.get("step_index") or 0), 1)
        self.assertEqual(int(clar.get("step_total") or 0), len(pending))
        self.assertNotIn("options", clar)
        self.assertNotIn("X of N", str(clar.get("confirm_prompt") or ""))
        self.assertNotIn("N more after this", str(clar.get("confirm_prompt") or ""))
        self.assertFalse((plan.assumptions or {}).get("design_loop"))

    def test_factor_ic_unknown_column_clarifies(self) -> None:
        """pct_chg 不是 history 列时澄清，不出 IC 步。"""

        print("\n[TestAiOpenWorkflow] unknown pct_chg clarifies")
        query = (
            "factor IC of close vs pct_chg for 000001.SZ,000002.SZ "
            "from 20240101 to 20240331"
        )
        plan = Planner(self.registry, env_facts={}).build_plan(query, mode="plan")
        names = [step.skill_name for step in plan.steps]
        inputs = plan.steps[0].inputs if plan.steps else {}
        print(" skills:", names)
        print(" missing_info:", inputs.get("missing_info"))
        self.assertEqual(names, ["qt.ai.system.fallback"])
        self.assertEqual(inputs.get("fallback_action"), "clarify_required")
        self.assertEqual(inputs.get("missing_info"), "return_htype")
        clar = (plan.assumptions or {}).get("clarification") or {}
        pending = [item for item in (clar.get("pending") or []) if isinstance(item, dict)]
        names_pending = [str(item.get("name") or "") for item in pending]
        print(" pending:", names_pending)
        print(" errors:", [item.get("error") for item in pending])
        self.assertEqual(names_pending, ["return_htype"])
        accepted = (plan.assumptions or {}).get("accepted_steps") or []
        written = (accepted[0].get("inputs") or {}) if accepted else {}
        print(" accepted inputs:", written)
        self.assertEqual(written.get("factor_htype"), "close")
        self.assertNotEqual(written.get("return_htype"), "pct_chg")
        self.assertNotIn("two local history columns", str(clar.get("confirm_prompt") or ""))
        self.assertNotIn("qt.ai.research.factor_ic_summary", names)

    def test_factor_ic_known_columns_keep_all_symbols(self) -> None:
        """close vs volume 保留两只代码和两侧列名。"""

        print("\n[TestAiOpenWorkflow] close vs volume keeps symbols")
        query = (
            "factor IC of close vs volume for 000001.SZ,000002.SZ "
            "from 20240101 to 20240331"
        )
        plan = Planner(self.registry, env_facts={}).build_plan(query, mode="plan")
        names = [step.skill_name for step in plan.steps]
        inputs = plan.steps[0].inputs if plan.steps else {}
        print(" intent:", plan.planner_trace.get("intent_job"))
        print(" skills:", names)
        print(" inputs:", inputs)
        self.assertEqual(plan.planner_trace.get("intent_job"), "research.factor_ic")
        self.assertEqual(names, ["qt.ai.research.factor_ic_summary"])
        self.assertEqual(inputs.get("shares"), "000001.SZ,000002.SZ")
        self.assertEqual(inputs.get("start"), "20240101")
        self.assertEqual(inputs.get("end"), "20240331")
        self.assertEqual(inputs.get("factor_htype"), "close")
        self.assertEqual(inputs.get("return_htype"), "volume")

    def _factor_ic_shares(self, plan: ToolPlan) -> Optional[str]:
        """已确认的代码在 IC 步上；被挡住时留在已收下的快照里。"""

        for step in plan.steps:
            if step.skill_name == "qt.ai.research.factor_ic_summary":
                return (step.inputs or {}).get("shares")
        for row in (plan.assumptions or {}).get("accepted_steps") or []:
            if row.get("skill_name") == "qt.ai.research.factor_ic_summary":
                return (row.get("inputs") or {}).get("shares")
        return None

    def _factor_ic_replan(self, slots: dict) -> ToolPlan:
        """用已确认槽、跳过分类，重出因子 IC 计划。原句不含代码，已确认的输入只复查形式。"""

        query = "factor IC summary for selection pool"
        session = ConversationState.empty("factor-ic-reclarify")
        session.start_task(query=query, job="research.factor_ic")
        for name, value in slots.items():
            session.set_slot(name, value, source="user", confirmed=True)
        return Planner(self.registry, env_facts={}).build_plan(
            query,
            mode="plan",
            session=session,
            skip_classify=True,
        )

    def test_factor_ic_confirmed_bad_column_names_the_slot(self) -> None:
        """已确认的 pct_chg 重出计划时仍澄清，文案点名该列。"""

        print("\n[TestAiOpenWorkflow] confirmed pct_chg replan clarifies")
        plan = self._factor_ic_replan(
            {
                "shares": "000001.SZ,000002.SZ",
                "start": "20240101",
                "end": "20240331",
                "factor_htype": "pct_chg",
                "return_htype": "volume",
            }
        )
        names = [step.skill_name for step in plan.steps]
        inputs = plan.steps[0].inputs if plan.steps else {}
        clar = (plan.assumptions or {}).get("clarification") or {}
        prompt = str(clar.get("confirm_prompt") or "")
        pending = [str(item.get("name") or "") for item in (clar.get("pending") or []) if isinstance(item, dict)]
        print(" skills:", names)
        print(" missing_info:", inputs.get("missing_info"))
        print(" pending:", pending)
        print(" confirm_prompt:", prompt)
        print(" shares:", self._factor_ic_shares(plan))
        self.assertEqual(names, ["qt.ai.system.fallback"])
        self.assertEqual(inputs.get("missing_info"), "factor_htype")
        self.assertEqual(pending, ["factor_htype"])
        self.assertNotIn("shares", pending)
        self.assertEqual(self._factor_ic_shares(plan), "000001.SZ,000002.SZ")
        factor = next(item for item in (clar.get("pending") or []) if item.get("name") == "factor_htype")
        print(" factor error:", factor.get("error"))
        print(" factor hint:", factor.get("hint"))
        self.assertIn("pct_chg", str(factor.get("error") or ""))
        self.assertIn("close", str(factor.get("hint") or ""))
        self.assertNotIn("close and volume", str(factor.get("hint") or ""))
        self.assertNotIn("close and volume", prompt)
        self.assertIn("Factor column", prompt)
        self.assertNotIn("qt.ai.research.factor_ic_summary", names)

    def test_factor_ic_confirmed_legal_slots_emit_ic_step(self) -> None:
        """已确认的 close / volume 与两只代码、日期齐全时出 IC 步。"""

        print("\n[TestAiOpenWorkflow] confirmed close vs volume emits IC")
        plan = self._factor_ic_replan(
            {
                "shares": "000001.SZ,000002.SZ",
                "start": "20240101",
                "end": "20240331",
                "factor_htype": "close",
                "return_htype": "volume",
            }
        )
        names = [step.skill_name for step in plan.steps]
        inputs = plan.steps[0].inputs if plan.steps else {}
        print(" skills:", names)
        print(" inputs:", inputs)
        print(" clarification:", (plan.assumptions or {}).get("clarification"))
        self.assertEqual(names, ["qt.ai.research.factor_ic_summary"])
        self.assertEqual(inputs.get("shares"), "000001.SZ,000002.SZ")
        self.assertEqual(inputs.get("factor_htype"), "close")
        self.assertEqual(inputs.get("return_htype"), "volume")
        self.assertFalse((plan.assumptions or {}).get("clarification"))

    def test_factor_ic_comma_pair_reopens_only_the_field_that_received_it(self) -> None:
        """close, volume 写在 factor 上、return 已是 close 时，只重开 factor。"""

        print("\n[TestAiOpenWorkflow] comma pair stays on factor_htype")
        plan = self._factor_ic_replan(
            {
                "shares": "000001.SZ,000002.SZ",
                "start": "20240101",
                "end": "20240331",
                "factor_htype": "close, volume",
                "return_htype": "close",
            }
        )
        clar = (plan.assumptions or {}).get("clarification") or {}
        pending = [str(item.get("name") or "") for item in (clar.get("pending") or []) if isinstance(item, dict)]
        factor = next(item for item in (clar.get("pending") or []) if item.get("name") == "factor_htype")
        print(" pending:", pending)
        print(" error:", factor.get("error"))
        print(" missing_info:", plan.steps[0].inputs.get("missing_info") if plan.steps else None)
        print(" shares:", self._factor_ic_shares(plan))
        self.assertEqual(pending, ["factor_htype"])
        self.assertNotIn("shares", pending)
        self.assertEqual(self._factor_ic_shares(plan), "000001.SZ,000002.SZ")
        self.assertIn("close, volume", str(factor.get("error") or ""))
        self.assertNotIn("return_htype", pending)
        self.assertEqual(plan.steps[0].inputs.get("missing_info"), "factor_htype")

    def test_factor_ic_two_segments_fill_the_empty_partner(self) -> None:
        """两段列名写在 Return 上时停在这一题，不拆进空着的 Factor。"""

        print("\n[TestAiOpenWorkflow] two column names stay on return")
        session = ConversationState.empty("factor-ic-split-read")
        session.start_task(query="factor IC summary for selection pool", job="research.factor_ic")
        plan = Planner(self.registry, env_facts={}).build_plan(
            "factor IC summary for selection pool",
            mode="plan",
            session=session,
            skip_classify=True,
            card_text={
                "shares": "000001.SZ,000002.SZ",
                "start": "20240101",
                "end": "20240331",
                "return_htype": "close, volume",
            },
        )
        clar = (plan.assumptions or {}).get("clarification") or {}
        pending = [str(item.get("name") or "") for item in (clar.get("pending") or []) if isinstance(item, dict)]
        accepted = (plan.assumptions or {}).get("accepted_steps") or []
        written = (accepted[0].get("inputs") or {}) if accepted else {}
        print(" skills:", [step.skill_name for step in plan.steps])
        print(" pending:", pending)
        print(" accepted:", written)
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(pending, ["factor_htype", "return_htype"])
        self.assertIn("close, volume", str((clar.get("pending") or [{}])[-1].get("error") or ""))
        self.assertNotEqual(written.get("factor_htype"), "close")
        self.assertNotEqual(written.get("return_htype"), "volume")

    def test_factor_ic_occupied_partner_rejects_only_the_current_field(self) -> None:
        """Factor 已有值时，Return 上的两段只重开 Return。"""

        print("\n[TestAiOpenWorkflow] occupied partner rejects return only")
        plan = self._factor_ic_replan(
            {
                "shares": "000001.SZ,000002.SZ",
                "start": "20240101",
                "end": "20240331",
                "factor_htype": "volume",
                "return_htype": "close, volume",
            }
        )
        clar = (plan.assumptions or {}).get("clarification") or {}
        pending = [str(item.get("name") or "") for item in (clar.get("pending") or []) if isinstance(item, dict)]
        print(" pending:", pending)
        print(" shares:", self._factor_ic_shares(plan))
        self.assertEqual(pending, ["return_htype"])
        self.assertEqual(self._factor_ic_shares(plan), "000001.SZ,000002.SZ")
        self.assertIn("close, volume", str(clar["pending"][0].get("error") or ""))

    def test_factor_ic_extra_partner_does_not_split(self) -> None:
        """同 kind 的空伙伴不是恰好一个时，不拆，只拒绝当前格。"""

        print("\n[TestAiOpenWorkflow] same history column rejects the later field")
        from qteasy_ai.slot_graph import accept_slot_value

        session = ConversationState.empty("factor-ic-same")
        session.start_task(query="factor IC summary for selection pool", job="research.factor_ic")
        plan = Planner(self.registry, env_facts={}).build_plan(
            "factor IC summary for selection pool",
            mode="plan",
            session=session,
            skip_classify=True,
            card_text={
                "shares": "000001.SZ,000002.SZ",
                "start": "20240101",
                "end": "20240331",
                "factor_htype": "close",
                "return_htype": "close",
            },
        )
        clar = (plan.assumptions or {}).get("clarification") or {}
        pending = [str(item.get("name") or "") for item in (clar.get("pending") or []) if isinstance(item, dict)]
        print(" pending:", pending)
        print(" error:", (clar.get("pending") or [{}])[0].get("error") if clar.get("pending") else None)
        accepted = (plan.assumptions or {}).get("accepted_steps") or []
        written = (accepted[0].get("inputs") or {}) if accepted else {}
        print(" accepted:", written)
        self.assertEqual(pending, ["return_htype"])
        self.assertEqual(written.get("factor_htype"), "close")
        self.assertNotEqual(written.get("return_htype"), "close")
        unknown = accept_slot_value({"name": "x", "type": "string"}, "close", "close")
        print(" unknown:", unknown)
        self.assertEqual(unknown, "close")

    def test_factor_ic_slots_match_skill_schema_and_skip_internal_fields(self) -> None:
        """slots 五格都在 schema 里；method / min_assets 不进澄清卡。"""

        print("\n[TestAiOpenWorkflow] factor IC slot registry")
        meta = self.registry.get_metadata("qt.ai.research.factor_ic_summary")
        declared = [str(item.get("name") or "") for item in self.catalog.job_slots("research.factor_ic")]
        print(" declared:", declared)
        print(" schema:", sorted(meta.inputs_schema))
        for name in declared:
            self.assertIn(name, meta.inputs_schema)
        for name in ("shares", "start", "end", "factor_htype", "return_htype"):
            self.assertIn(name, declared)
        self.assertIn("method", meta.inputs_schema)
        self.assertIn("min_assets", meta.inputs_schema)
        plan = Planner(self.registry, env_facts={}).build_plan(
            "factor IC summary for selection pool",
            mode="plan",
        )
        pending = [
            str(item.get("name") or "")
            for item in ((plan.assumptions or {}).get("clarification") or {}).get("pending") or []
            if isinstance(item, dict)
        ]
        print(" pending:", pending)
        self.assertNotIn("method", pending)
        self.assertNotIn("min_assets", pending)
        self.assertEqual(pending, ["factor_htype", "return_htype", "shares", "start", "end"])

    def test_factor_ic_control_patches_emit_both_split_values(self) -> None:
        """控件提交的两段列名留在当前格，修订补丁不另造伙伴格。"""

        print("\n[TestAiOpenWorkflow] control patches keep both names on one field")
        import tempfile

        from qteasy_ai.app import QteasyAssistant
        from qteasy_ai.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                registry=self.registry,
            )
            sid = "factor-ic-split"
            asst.plan("factor IC summary for selection pool", response_style="raw", session_id=sid)
            second = asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={
                    "shares": "000001.SZ,000002.SZ",
                    "start": "20240101",
                    "end": "20240331",
                    "return_htype": "close, volume",
                },
            )
            revision = ((second.get("plan") or {}).get("assumptions") or {}).get("slot_revision") or {}
            inputs = ((second.get("plan") or {}).get("steps") or [{}])[0].get("inputs") or {}
            print(" revision:", revision)
            print(" inputs:", inputs)
            clar = ((second.get("plan") or {}).get("assumptions") or {}).get("clarification") or {}
            pending = [str(item.get("name") or "") for item in (clar.get("pending") or []) if isinstance(item, dict)]
            print(" pending:", pending)
            self.assertEqual(revision.get("return_htype"), "close, volume")
            self.assertNotIn("factor_htype", revision)
            self.assertEqual((second.get("plan") or {}).get("steps", [{}])[0].get("skill_name"), "qt.ai.system.fallback")
            self.assertIn("return_htype", pending)
            self.assertIn("factor_htype", pending)
            self.assertNotEqual(inputs.get("factor_htype"), "close")
            self.assertNotEqual(inputs.get("return_htype"), "volume")

    def test_system_open_job_still_legal_dag(self) -> None:
        """系统 Job open 仍走合法边 DAG，不是设计环。"""

        print("\n[TestAiOpenWorkflow] system open job")
        import json

        fake = FakeLLMProvider(
            replies=[
                json.dumps({"job": "open"}),
                json.dumps(
                    {
                        "steps": [
                            {"skill_name": "qt.ai.strategy_meta.list", "inputs": {}},
                        ]
                    }
                ),
            ]
        )
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "xyzzy unmatched formula 12345", mode="plan"
        )
        names = [step.skill_name for step in plan.steps]
        print(" intent:", plan.planner_trace.get("intent_job"), "skills:", names)
        print(" design_loop:", (plan.assumptions or {}).get("design_loop"))
        self.assertEqual(plan.planner_trace.get("intent_job"), "open")
        self.assertEqual(names, ["qt.ai.strategy_meta.list"])
        self.assertFalse((plan.assumptions or {}).get("design_loop"))

    def test_followup_does_not_persist_design(self) -> None:
        """Composer 跟进是新 Task，不写 active_design。"""

        print("\n[TestAiOpenWorkflow] follow-up no design persist")
        import tempfile

        from qteasy_ai.app import QteasyAssistant
        from qteasy_ai.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                registry=self.registry,
            )
            sid = "g7-hyp"
            asst.plan(
                "explore a useful momentum factor for hs300",
                response_style="raw",
                session_id=sid,
            )
            second = asst.plan(
                "hypothesis: short-term reversal on hs300",
                response_style="raw",
                session_id=sid,
            )
            state = asst.session_store.load(sid)
            users = [row.get("text") for row in state.messages if row.get("kind") == "user_text"]
            print(" users:", users)
            print(" job:", state.task.job if state.task else None)
            print(" dumped:", sorted(state.to_dict().keys()))
            print(" second skills:", [item.get("skill_name") for item in ((second.get("plan") or {}).get("steps") or [])])
            self.assertIn("hypothesis: short-term reversal on hs300", users)
            self.assertFalse(hasattr(state, "active_design"))
            self.assertNotIn("active_design", state.to_dict())


class TestAiClarifyEmitS1(unittest.TestCase):
    """Path A S1：出卡载荷 step 字段、per-step options、无顶层 options。"""

    def test_finalize_truncates_options_and_sets_steps(self) -> None:
        """options>5 只留前 5，并写 step_index/total；去掉顶层 options。"""

        print("\n[TestAiClarifyEmitS1] finalize truncates options")
        from qteasy_ai.slot_decl import finalize_clarification_for_emit

        opts = [{"id": f"id{i}", "label": f"L{i}"} for i in range(7)]
        blob = finalize_clarification_for_emit(
            {
                "confirm_prompt": "Pick one.",
                "options": [{"id": "top", "label": "Top"}],
                "pending": [
                    {"name": "strategy_id", "hint": "Pick.", "options": opts},
                    {"name": "start", "hint": "YYYYMMDD."},
                ],
            }
        )
        pending = blob["pending"]
        print(" step:", blob.get("step_index"), blob.get("step_total"))
        print(" strategy options:", [item.get("id") for item in pending[0].get("options") or []])
        print(" hint:", pending[0].get("hint"))
        print(" top options key:", "options" in blob)
        self.assertEqual(blob["step_index"], 1)
        self.assertEqual(blob["step_total"], 2)
        self.assertNotIn("options", blob)
        self.assertEqual(len(pending[0]["options"]), 5)
        self.assertEqual(pending[0]["options"][0]["id"], "id0")
        self.assertEqual(pending[0]["options"][-1]["id"], "id4")
        self.assertIn("open input", str(pending[0].get("hint") or "").lower())
        self.assertNotIn("options", pending[1])

    def test_strategy_clarify_options_on_pending_no_type_skip(self) -> None:
        """策略澄清：chips 在 pending 项上；正文无 type skip；无顶层 options。"""

        print("\n[TestAiClarifyEmitS1] strategy clarify emit shape")
        from qteasy_ai.app import build_default_registry

        plan = Planner(build_default_registry(), env_facts={}).build_plan(
            "请帮我列出内置交易策略的参数",
            mode="plan",
        )
        clar = (plan.assumptions or {}).get("clarification") or {}
        pending = [item for item in (clar.get("pending") or []) if isinstance(item, dict)]
        print(" intent:", plan.planner_trace.get("intent_job"))
        print(" pending:", pending)
        print(" prompt:", clar.get("confirm_prompt"))
        print(" step:", clar.get("step_index"), clar.get("step_total"))
        self.assertTrue(clar)
        self.assertNotIn("options", clar)
        self.assertNotIn("type skip", str(clar.get("confirm_prompt") or "").lower())
        strategy = next((item for item in pending if item.get("name") == "strategy_id"), None)
        self.assertIsNotNone(strategy)
        options = list((strategy or {}).get("options") or [])
        print(" options:", [item.get("id") for item in options])
        self.assertLessEqual(len(options), 5)
        from qteasy_ai.slot_graph import strategy_id_options

        self.assertEqual([str(item.get("id") or "") for item in options], strategy_id_options())
        self.assertEqual(int(clar.get("step_index") or 0), 1)
        self.assertEqual(int(clar.get("step_total") or 0), len(pending))


if __name__ == "__main__":
    unittest.main()

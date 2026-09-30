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
        self.assertTrue((plan.assumptions or {}).get("clarification"))
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
        self.assertIn("pct_chg", str(pending[0].get("error") or ""))
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

    def _factor_ic_replan(self, slots: dict) -> ToolPlan:
        """用已确认槽、跳过分类，重出因子 IC 计划。"""

        session = ConversationState.empty("factor-ic-reclarify")
        session.start_task(query="factor IC summary for selection pool", job="research.factor_ic")
        for name, value in slots.items():
            session.set_slot(name, value, source="user", confirmed=True)
        return Planner(self.registry, env_facts={}).build_plan(
            "factor IC summary for selection pool",
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
        self.assertEqual(names, ["qt.ai.system.fallback"])
        self.assertEqual(inputs.get("missing_info"), "factor_htype")
        self.assertEqual(pending, ["factor_htype"])
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
        self.assertEqual(pending, ["factor_htype"])
        self.assertIn("close, volume", str(factor.get("error") or ""))
        self.assertNotIn("return_htype", pending)
        self.assertEqual(plan.steps[0].inputs.get("missing_info"), "factor_htype")

    def test_factor_ic_two_segments_fill_the_empty_partner(self) -> None:
        """两段合法列名填进空着的 Return，且 Factor 为空时拆成两格。"""

        print("\n[TestAiOpenWorkflow] split return into empty factor")
        from qteasy_ai.slot_decl import interpret_declared_slots

        declarations = self.catalog.job_slots("research.factor_ic")
        verdict = interpret_declared_slots(
            declarations,
            {
                "shares": "000001.SZ,000002.SZ",
                "start": "20240101",
                "end": "20240331",
                "factor_htype": "",
                "return_htype": "close, volume",
            },
            is_history_column=Planner._is_history_panel_htype,
        )
        print(" patches:", verdict["patches"])
        print(" pending:", [item.get("name") for item in verdict["pending"]])
        self.assertEqual(verdict["patches"].get("return_htype"), "close")
        self.assertEqual(verdict["patches"].get("factor_htype"), "volume")
        self.assertEqual(verdict["pending"], [])
        plan = self._factor_ic_replan(
            {
                "shares": "000001.SZ,000002.SZ",
                "start": "20240101",
                "end": "20240331",
                "return_htype": "close, volume",
            }
        )
        inputs = plan.steps[0].inputs if plan.steps else {}
        print(" skills:", [step.skill_name for step in plan.steps])
        print(" inputs:", inputs)
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.research.factor_ic_summary")
        self.assertEqual(inputs.get("return_htype"), "close")
        self.assertEqual(inputs.get("factor_htype"), "volume")

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
        self.assertEqual(pending, ["return_htype"])
        self.assertIn("close, volume", str(clar["pending"][0].get("error") or ""))

    def test_factor_ic_extra_partner_does_not_split(self) -> None:
        """同 kind 的空伙伴不是恰好一个时，不拆，只拒绝当前格。"""

        print("\n[TestAiOpenWorkflow] zero or many partners do not split")
        from qteasy_ai.slot_decl import interpret_declared_slots

        rows = [
            {
                "name": "a",
                "label": "A",
                "hint": "One column, such as close.",
                "cardinality": "one",
                "value_kind": "history_panel_column",
            },
            {
                "name": "b",
                "label": "B",
                "hint": "One column, such as volume.",
                "cardinality": "one",
                "value_kind": "history_panel_column",
            },
            {
                "name": "c",
                "label": "C",
                "hint": "One column, such as high.",
                "cardinality": "one",
                "value_kind": "history_panel_column",
            },
        ]
        verdict = interpret_declared_slots(
            rows,
            {"a": "close, volume", "b": "", "c": ""},
            is_history_column=lambda name: name in {"close", "volume"},
        )
        print(" patches:", verdict["patches"])
        print(" pending:", [(item["name"], item["error"]) for item in verdict["pending"]])
        self.assertEqual(verdict["patches"], {})
        self.assertEqual([item["name"] for item in verdict["pending"]], ["a", "b", "c"])
        self.assertIn("close, volume", verdict["pending"][0]["error"])
        unknown = interpret_declared_slots(
            [{
                "name": "x",
                "label": "X",
                "hint": "One value.",
                "cardinality": "one",
                "value_kind": "not_a_kind",
            }],
            {"x": "close"},
            is_history_column=lambda _name: True,
        )
        print(" unknown:", unknown["pending"])
        self.assertEqual(unknown["values"], {})
        self.assertEqual(unknown["pending"][0]["name"], "x")
        self.assertIn("close", unknown["pending"][0]["error"])

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
        self.assertEqual(pending, ["shares", "start", "end", "factor_htype", "return_htype"])

    def test_factor_ic_control_patches_emit_both_split_values(self) -> None:
        """控件把两段列名写入空槽时，修订补丁同时带上伙伴格。"""

        print("\n[TestAiOpenWorkflow] control patches split both columns")
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
            notices = [
                str(row.get("text") or "")
                for row in (second.get("human_cards") or [])
                if row.get("kind") == "mode_notice"
            ]
            print(" notices:", notices)
            self.assertEqual(revision.get("return_htype"), "close")
            self.assertEqual(revision.get("factor_htype"), "volume")
            self.assertEqual(inputs.get("return_htype"), "close")
            self.assertEqual(inputs.get("factor_htype"), "volume")
            joined = "\n".join(notices)
            self.assertIn("Accepted Return column = close.", joined)
            self.assertIn("Filled Factor column = volume from Return column.", joined)

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


if __name__ == "__main__":
    unittest.main()

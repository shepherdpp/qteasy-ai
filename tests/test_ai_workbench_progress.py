# coding=utf-8
# ======================================
# File: test_ai_workbench_progress.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-07
# Desc:
# Unittest for PlanExecutor on_step (G.2)
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.contracts import SkillMetadata, SkillSideEffects, ToolPlan, ToolStep
from qteasy_ai.executor import PlanExecutor
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.registry import SkillRegistry
from qteasy_ai.workbench.mapper import map_assistant_payload, step_needs_confirm


class TestAiWorkbenchProgress(unittest.TestCase):
    """G.2：on_step 顺序与 dry_run 不执行。"""

    def test_on_step_order_matches_step_ids(self) -> None:
        """两步只读 plan confirm=True：回调顺序 = step_id，含 result.ok。"""

        print("\n[TestAiWorkbenchProgress] on_step order")
        registry = SkillRegistry()
        seen = []

        def make_handler(tag: str):
            def handler(**kwargs):
                seen.append(tag)
                return {"ok": True, "tag": tag, "kwargs": kwargs}

            return handler

        for name, tag in (("qt.ai.test.a", "a"), ("qt.ai.test.b", "b")):
            meta = SkillMetadata(
                name=name,
                version="0.1.0",
                summary="readonly test",
                inputs_schema={},
                outputs_schema={"ok": "bool"},
                side_effects=SkillSideEffects(description="readonly"),
            )
            registry.register(meta, make_handler(tag))

        callbacks = []

        def on_step(record) -> None:
            callbacks.append(record)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            executor = PlanExecutor(registry=registry, memory_store=store)
            plan = ToolPlan(
                plan_id="plan_two",
                user_query="two steps",
                execution_mode="execute",
                steps=[
                    ToolStep(step_id="step_1", skill_name="qt.ai.test.a", inputs={}),
                    ToolStep(step_id="step_2", skill_name="qt.ai.test.b", inputs={}),
                ],
            )
            payload = executor.execute(plan, confirm=True, on_step=on_step)
            ids = [item.step_id for item in callbacks]
            oks = [item.result.get("ok") for item in callbacks]
            print(" handler order:", seen)
            print(" callback ids:", ids)
            print(" callback oks:", oks)
            print(" status:", payload["execution"]["status"])
            self.assertEqual(seen, ["a", "b"])
            self.assertEqual(ids, ["step_1", "step_2"])
            self.assertEqual(oks, [True, True])
            self.assertEqual(payload["execution"]["status"], "success")

    def test_dry_run_skips_handlers_and_real_ok_callbacks(self) -> None:
        """confirm=False：不调 handler；回调无真实 ok 执行结果。"""

        print("\n[TestAiWorkbenchProgress] dry_run no handler")
        registry = SkillRegistry()
        called = {"n": 0}

        def handler(**kwargs):
            called["n"] += 1
            return {"ok": True}

        meta = SkillMetadata(
            name="qt.ai.test.step",
            version="0.1.0",
            summary="test",
            inputs_schema={},
            outputs_schema={"ok": "bool"},
            side_effects=SkillSideEffects(description="readonly"),
        )
        registry.register(meta, handler)
        callbacks = []
        executor = PlanExecutor(registry=registry)
        plan = ToolPlan(
            plan_id="plan_dry",
            user_query="dry",
            execution_mode="dry_run",
            steps=[ToolStep(step_id="step_1", skill_name="qt.ai.test.step", inputs={})],
        )
        payload = executor.execute(plan, confirm=False, on_step=lambda rec: callbacks.append(rec))
        print(" handler called:", called["n"])
        print(" callbacks:", callbacks)
        print(" status:", payload["execution"]["status"])
        self.assertEqual(called["n"], 0)
        self.assertEqual(payload["execution"]["status"], "dry_run")
        real_ok = [item for item in callbacks if getattr(item, "result", {}).get("ok") is True]
        self.assertEqual(real_ok, [])

    def test_plan_high_side_effect_stays_dry_run(self) -> None:
        """槽齐 refill plan 仍 dry_run；needs_confirm；未经 run_plan 不 execute。"""

        print("\n[TestAiWorkbenchProgress] refill plan not auto execute")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            assistant = QteasyAssistant(memory_store=store, registry=build_default_registry())
            payload = assistant.plan(
                "download daily data from 20180101 to 20231231",
                response_style="raw",
            )
            state = map_assistant_payload(payload, query="download daily data from 20180101 to 20231231")
            dumped = state.to_dict()
            skills = [s["skill_name"] for s in (dumped["plan_card"] or {}).get("steps") or []]
            print(" skills:", skills)
            print(" execution:", dumped["execution"]["status"])
            print(" needs_confirm:", (dumped["plan_card"] or {}).get("needs_confirm"))
            self.assertEqual(dumped["execution"]["status"], "dry_run")
            self.assertIn("qt.ai.data.refill_basic_equity_and_index", skills)
            self.assertTrue(dumped["plan_card"]["needs_confirm"])
            self.assertTrue(step_needs_confirm("qt.ai.data.refill_basic_equity_and_index"))
            runs = [p for p in store.list_runs()]
            print(" run files:", runs)
            for run_id in runs:
                rec = store.load_run(run_id)
                print(" run status:", rec.get("execution", {}).get("status"))
                self.assertEqual(rec.get("execution", {}).get("status"), "dry_run")


if __name__ == "__main__":
    unittest.main()

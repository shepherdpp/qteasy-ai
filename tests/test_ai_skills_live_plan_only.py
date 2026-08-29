# coding=utf-8
# ======================================
# File: test_ai_skills_live_plan_only.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-29
# Desc:
# Unittest for qt.ai.pipeline.live_trade_plan_only
# ======================================

import ast
import tempfile
import unittest
from pathlib import Path

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner
from qteasy_ai.skills.live_plan import build_live_trade_plan_only_skill


class TestAiLivePlanOnlySkill(unittest.TestCase):
    """测试实盘只出 plan，永不下单。"""

    def test_handler_returns_forbidden_checklist(self) -> None:
        """handler 输出英文清单且 execution_forbidden。"""

        print("\n[TestAiLivePlanOnlySkill] checklist")
        meta, handler = build_live_trade_plan_only_skill()
        result = handler(query="start live trade now")
        payload = result.get("payload") or {}
        print(" ok:", result["ok"])
        print(" payload:", payload)
        print(" warnings:", result.get("warnings"))
        self.assertTrue(result["ok"])
        self.assertFalse(meta.side_effects.network)
        self.assertFalse(meta.side_effects.filesystem_write)
        self.assertFalse(meta.side_effects.local_state_change)
        self.assertTrue(payload.get("execution_forbidden"))
        self.assertEqual(result["metrics"]["execution_forbidden"], 1)
        checklist = payload.get("checklist") or []
        self.assertGreaterEqual(len(checklist), 3)
        joined = " ".join(str(item) for item in checklist)
        self.assertIn("backtest", joined.lower())
        self.assertIn("Live trading is never auto-executed", " ".join(result.get("warnings") or []))

    def test_module_has_no_live_engine_import(self) -> None:
        """源码不得 import 实盘执行模块。"""

        print("\n[TestAiLivePlanOnlySkill] no live-engine import")
        path = Path(__file__).resolve().parents[1] / "qteasy_ai" / "skills" / "live_plan.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(str(node.module or ""))
        print(" imports:", imported)
        blob = " ".join(imported).lower()
        self.assertNotIn("trader", blob)
        self.assertNotIn("broker", blob)

    def test_planner_live_query_uses_plan_only_skill(self) -> None:
        """start live trade now → live_trade_plan_only，dry_run。"""

        print("\n[TestAiLivePlanOnlySkill] planner routing")
        planner = Planner(build_default_registry(), env_facts={})
        plan = planner.build_plan("start live trade now", mode="plan")
        print(" skill:", plan.steps[0].skill_name, "mode:", plan.execution_mode)
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.pipeline.live_trade_plan_only")
        self.assertEqual(plan.execution_mode, "dry_run")
        run_plan = planner.build_plan("start live trade now", mode="run")
        print(" run execution_mode:", run_plan.execution_mode, "skill:", run_plan.steps[0].skill_name)
        self.assertEqual(run_plan.steps[0].skill_name, "qt.ai.pipeline.live_trade_plan_only")
        self.assertNotEqual(run_plan.steps[0].skill_name, "qt.ai.system.fallback")

    def test_assistant_run_does_not_auto_execute_live(self) -> None:
        """Agent run 执行的是 plan-only skill，payload 仍 execution_forbidden。"""

        print("\n[TestAiLivePlanOnlySkill] agent run still plan-only")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            payload = assistant.run(
                "start live trade now",
                response_style="raw",
                persist="none",
            )
            step = payload["execution"]["steps"][0]
            result = step["result"]
            inner = result.get("payload") or {}
            print(" skill:", step.get("skill_name"))
            print(" execution_forbidden:", inner.get("execution_forbidden"))
            print(" result ok:", result.get("ok"))
            self.assertEqual(step["skill_name"], "qt.ai.pipeline.live_trade_plan_only")
            self.assertTrue(inner.get("execution_forbidden"))
            self.assertTrue(result.get("ok"))


if __name__ == "__main__":
    unittest.main()

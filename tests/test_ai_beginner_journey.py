# coding=utf-8
# ======================================
# File: test_ai_beginner_journey.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-05
# Desc:
# Unittest for E.4 Beginner Journey 语料
# ======================================

import json
import unittest
from pathlib import Path
from typing import Any, Dict, List

from qteasy_ai.app import build_default_registry
from qteasy_ai.planner import Planner

_CORPUS = Path(__file__).resolve().parent / "ai_corpus" / "beginner_journey.json"


def _load_cases() -> List[Dict[str, Any]]:
    """读取 Beginner Journey 语料。"""

    with _CORPUS.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return list(payload.get("cases") or [])


class TestAiBeginnerJourney(unittest.TestCase):
    """表驱动：Mode-R plan 步的 Job 与 skill 序列。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()
        self.planner = Planner(self.registry, provider=None, env_facts={})
        self.cases = _load_cases()

    def test_beginner_journey_plan_cases(self) -> None:
        """plan 步：intent_job 与 skill 序列等于表内期望；Ask 占位跳过。"""

        plan_cases = [item for item in self.cases if str(item.get("mode") or "") == "plan"]
        ask_cases = [item for item in self.cases if str(item.get("mode") or "") == "ask"]
        print("\n[TestAiBeginnerJourney] total:", len(self.cases), "plan:", len(plan_cases), "ask:", len(ask_cases))
        self.assertEqual(len(self.cases), 18)
        self.assertEqual(len(plan_cases), 17)
        self.assertEqual(len(ask_cases), 1)
        for case in ask_cases:
            print(
                " skip ask:",
                case.get("id"),
                "query:",
                case.get("query"),
                "notes:",
                case.get("notes"),
            )
        stage_counts: Dict[str, int] = {}
        for case in plan_cases:
            case_id = str(case.get("id") or "")
            query = str(case.get("query") or "")
            expected_job = str(case.get("expected_job") or "")
            expected_skills = list(case.get("expected_skills") or [])
            forbidden = list(case.get("forbidden_skills") or [])
            stage = str(case.get("stage") or "")
            plan = self.planner.build_plan(query, mode="plan")
            names = [step.skill_name for step in plan.steps]
            intent = str(plan.planner_trace.get("intent_job") or "")
            print(
                " id:",
                case_id,
                "stage:",
                stage,
                "query:",
                query[:48],
                "expected_job:",
                expected_job,
                "actual_job:",
                intent,
                "expected_skills:",
                expected_skills,
                "actual_skills:",
                names,
                "rationale:",
                plan.planner_trace.get("rationale"),
            )
            self.assertEqual(intent, expected_job, msg=case_id)
            self.assertEqual(names, expected_skills, msg=case_id)
            for skill_name in forbidden:
                self.assertNotIn(skill_name, names, msg=case_id)
            fallback_action = case.get("expected_fallback_action")
            if fallback_action:
                actual_action = plan.steps[0].inputs.get("fallback_action")
                print(" fallback_action:", actual_action, "expected:", fallback_action)
                self.assertEqual(actual_action, fallback_action, msg=case_id)
            missing = case.get("expected_missing_info")
            if missing:
                actual_missing = plan.steps[0].inputs.get("missing_info")
                print(" missing_info:", actual_missing, "expected:", missing)
                self.assertEqual(actual_missing, missing, msg=case_id)
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        print("\n[TestAiBeginnerJourney] plan stage counts:", stage_counts)
        for stage in ("1", "2", "3", "4", "5"):
            print(" stage:", stage, "n:", stage_counts.get(stage, 0))
            self.assertGreater(stage_counts.get(stage, 0), 0, msg=stage)


if __name__ == "__main__":
    unittest.main()

# coding=utf-8
# ======================================
# File: test_ai_corpus_regression.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-20
# Desc:
# Unittest for qteasy ai corpus regression
# ======================================

import json
import unittest
from pathlib import Path

from qteasy_ai.app import QteasyAssistant

_FALLBACK_ERROR = {
    "clarify_required": "CLARIFY_REQUIRED",
    "not_supported_yet": "NOT_SUPPORTED_YET",
    "plan_only": "PLAN_ONLY",
}


def _plan_fallback_action(payload: dict) -> str:
    """从 plan 第一步读取 fallback_action。"""

    steps = ((payload.get("plan") or {}).get("steps") or [])
    if not steps:
        return ""
    return str((steps[0].get("inputs") or {}).get("fallback_action") or "")


def _fallback_from_run(payload: dict) -> tuple[str, str]:
    """G.9 clarify / not_supported 可在 dry_run 下空 execution.steps。"""

    steps = (payload.get("execution") or {}).get("steps") or []
    if steps:
        result = steps[0].get("result") or {}
        action = str((result.get("payload") or {}).get("fallback_action") or "")
        error_code = str((result.get("error") or {}).get("code") or "")
        if action and error_code:
            return action, error_code
    action = _plan_fallback_action(payload)
    if payload.get("clarification"):
        return action or "clarify_required", "CLARIFY_REQUIRED"
    if action:
        return action, _FALLBACK_ERROR.get(action, "")
    return action, str(((payload.get("error") or {}).get("code") or ""))


def _error_from_run(payload: dict) -> dict:
    """结构化错误：优先 execution.steps，否则 plan fallback / clarification。"""

    steps = (payload.get("execution") or {}).get("steps") or []
    if steps:
        error = (steps[0].get("result") or {}).get("error") or {}
        if error.get("code"):
            return error
    action = _plan_fallback_action(payload)
    code = _FALLBACK_ERROR.get(action, "")
    if payload.get("clarification") and not code:
        code = "CLARIFY_REQUIRED"
    hint = ""
    plan_steps = ((payload.get("plan") or {}).get("steps") or [])
    if plan_steps:
        hint = str((plan_steps[0].get("inputs") or {}).get("hint") or "")
    if not hint and isinstance(payload.get("clarification"), dict):
        hint = str(payload["clarification"].get("confirm_prompt") or "")
    if not hint and isinstance(payload.get("error"), dict):
        return payload["error"]
    return {"code": code, "message": hint or code}


class TestAiCorpusRegression(unittest.TestCase):
    """测试 AI 语料回归。"""

    @staticmethod
    def _load_cases(file_name: str) -> list[dict]:
        corpus_path = Path(__file__).resolve().parent / "ai_corpus" / file_name
        with corpus_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("cases", [])

    def test_current_capability_corpus(self) -> None:
        """验证已实现能力语料路由与 ask 语义。"""

        assistant = QteasyAssistant()
        cases = self._load_cases("current_capabilities.json")
        print("\n[TestAiCorpusRegression] current capability cases:", len(cases))
        for case in cases:
            query = case["query"]
            mode = case.get("mode", "plan")
            if mode == "ask":
                payload = assistant.ask(query, response_style="raw")
                print(
                    " ask case:",
                    case["id"],
                    "mode:",
                    payload.get("mode"),
                    "ok:",
                    payload.get("ok"),
                    "sources:",
                    payload.get("sources"),
                )
                print(" ask answer:", str(payload.get("answer", ""))[:300])
                self.assertEqual(payload.get("mode"), "ask")
                self.assertNotIn("execution", payload)
                self.assertTrue(payload.get("plan") in (None, {}) or payload.get("plan", {}).get("steps") in (None, []))
                answer = str(payload.get("answer", ""))
                self.assertIn("PT", answer)
                self.assertIn("PS", answer)
                self.assertTrue(payload.get("sources"))
            else:
                payload = assistant.plan(query, response_style="raw")
                steps = payload["plan"]["steps"]
                intent_job = (payload.get("plan") or {}).get("planner_trace", {}).get("intent_job")
                print(" plan case:", case["id"], "job:", intent_job, "skills:", [s["skill_name"] for s in steps])
                self.assertGreaterEqual(len(steps), 1)
                self.assertEqual(steps[0]["skill_name"], case["expected_skill"])
                if "expected_job" in case:
                    self.assertEqual(intent_job, case["expected_job"])
                if "expected_skills" in case:
                    self.assertEqual(
                        [s["skill_name"] for s in steps],
                        case["expected_skills"],
                    )
                self.assertTrue(str(payload.get("plan_md", "")).strip())

    def test_future_capability_fallback_corpus(self) -> None:
        """验证前瞻语料回退行为。"""

        assistant = QteasyAssistant()
        cases = self._load_cases("future_capabilities.json")
        print("\n[TestAiCorpusRegression] future capability cases:", len(cases))
        for case in cases:
            payload = assistant.run(case["query"], response_style="raw")
            action, error_code = _fallback_from_run(payload)
            print(
                " future case:",
                case["id"],
                "action:",
                action,
                "error:",
                error_code,
                "exec_steps:",
                len((payload.get("execution") or {}).get("steps") or []),
            )
            self.assertEqual(action, case["expected_fallback_action"])
            self.assertIn(error_code, ["PLAN_ONLY", "NOT_SUPPORTED_YET", "CLARIFY_REQUIRED"])

    def test_error_corpus_consistency(self) -> None:
        """验证错误语料结构化错误一致性。"""

        assistant = QteasyAssistant()
        cases = self._load_cases("error_corpus.json")
        print("\n[TestAiCorpusRegression] error cases:", len(cases))
        for case in cases:
            payload = assistant.run(case["query"], response_style="raw")
            status = (payload.get("execution") or {}).get("status")
            steps = (payload.get("execution") or {}).get("steps") or []
            error = _error_from_run(payload)
            print(" error case:", case["id"], "status:", status, "steps:", len(steps))
            print("  error:", error)
            self.assertTrue(steps or payload.get("clarification") or payload.get("error"))
            self.assertIn(error.get("code", ""), case["expected_error_codes"])
            self.assertIn("message", error)

    def test_user_friendly_output_has_required_fields(self) -> None:
        """验证 user_friendly 输出包含 narrative/code/preview。"""

        assistant = QteasyAssistant()
        output = assistant.plan("list built-in strategies", response_style="user_friendly")
        output_dict = output.to_dict()
        print("\n[TestAiCorpusRegression] user_friendly output:", output_dict)
        self.assertTrue(output_dict["narrative"])
        self.assertTrue(output_dict["python_code"])
        self.assertIn("result_preview", output_dict)
        self.assertIn("raw", output_dict)

    def test_strategy_parameter_query_routes_to_get(self) -> None:
        """验证策略参数查询命中 strategy_meta.get。"""

        assistant = QteasyAssistant()
        payload = assistant.plan("请列出MACD策略的所有可调参数", response_style="raw")
        first_step = payload["plan"]["steps"][0]
        print("\n[TestAiCorpusRegression] strategy parameter step:", first_step)
        self.assertEqual(first_step["skill_name"], "qt.ai.strategy_meta.get")
        self.assertTrue(str(first_step["inputs"].get("strategy_id", "")).strip())

    def test_parameter_query_without_strategy_id_returns_clear_fallback(self) -> None:
        """验证参数查询缺少策略名时返回可解释 fallback。"""

        assistant = QteasyAssistant()
        output = assistant.plan("请告诉我这个策略的可调参数", response_style="user_friendly")
        output_dict = output.to_dict()
        raw_step = output_dict["raw"]["plan"]["steps"][0]
        step_inputs = raw_step["inputs"]
        print("\n[TestAiCorpusRegression] clear fallback step:", raw_step)
        print(" fallback narrative:", output_dict["narrative"])
        self.assertEqual(raw_step["skill_name"], "qt.ai.system.fallback")
        self.assertEqual(step_inputs.get("fallback_action"), "clarify_required")
        self.assertTrue(step_inputs.get("reason"))
        self.assertTrue(step_inputs.get("missing_info"))
        self.assertTrue(step_inputs.get("next_step"))
        self.assertIn("reason:", output_dict["narrative"])
        self.assertIn("missing_info:", output_dict["narrative"])
        self.assertIn("next_step:", output_dict["narrative"])


if __name__ == "__main__":
    unittest.main()

# coding=utf-8
# ======================================
# File: test_ai_ask.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-28
# Desc:
# Unittest for qteasy-ai AskEngine target state
# ======================================

import unittest

from qteasy_ai.ask_engine import AskEngine
from qteasy_ai.knowledge_base import KnowledgeBase
from qteasy_ai.provider import FakeLLMProvider


class CountingExecutor:
    """计数包装：Ask 路径若误调 PlanExecutor 会失败。"""

    def __init__(self) -> None:
        self.execute_calls = 0

    def execute(self, *args, **kwargs):
        self.execute_calls += 1
        raise AssertionError("PlanExecutor must not be called in Ask target state.")


class CountingRegistry:
    """计数包装：Ask 路径若误调 skill handler 会失败。"""

    def __init__(self) -> None:
        self.call_count = 0

    def call(self, *args, **kwargs):
        self.call_count += 1
        raise AssertionError("Skill handler must not be called in Ask target state.")


class TestAiAskEngine(unittest.TestCase):
    """测试 Ask 目标态：LLMClient + KnowledgeBase，零 skill / 零 Executor。"""

    def setUp(self) -> None:
        self.kb = KnowledgeBase(
            list_func=lambda: ["macd", "dma"],
            doc_func=lambda sid: f"{sid} tunable parameters: fast, slow, signal.",
        )
        self.executor = CountingExecutor()
        self.registry = CountingRegistry()

    def _assert_no_plan_execution(self, payload: dict) -> None:
        """断言 Ask 载荷不含可执行 plan steps / execution。"""

        print(" payload keys:", sorted(payload.keys()))
        print(" mode:", payload.get("mode"))
        print(" sources:", payload.get("sources"))
        self.assertEqual(payload.get("mode"), "ask")
        self.assertNotIn("execution", payload)
        plan = payload.get("plan")
        if plan is not None:
            self.assertEqual(plan.get("steps") or [], [])

    def test_offline_explain_pt_ps(self) -> None:
        """无 Provider 时 Offline 路径仍给出 PT/PS 英文答案与 sources。"""

        print("\n[TestAiAskEngine] offline PT vs PS")
        engine = AskEngine(knowledge_base=self.kb)
        result = engine.ask("explain PT vs PS")
        payload = result.to_dict()
        print(" answer:", payload.get("answer", "")[:400])
        print(" sources:", payload.get("sources"))
        print(" ok:", payload.get("ok"))
        self._assert_no_plan_execution(payload)
        self.assertTrue(payload["ok"])
        self.assertIn("pt_ps_vs", payload["sources"])
        self.assertIn("PT", payload["answer"])
        self.assertIn("PS", payload["answer"])
        self.assertIn("Position Target", payload["answer"])
        self.assertEqual(self.executor.execute_calls, 0)
        self.assertEqual(self.registry.call_count, 0)
        self.assertIsNone(getattr(engine, "executor", None))
        self.assertIsNone(getattr(engine, "registry", None))

    def test_ask_does_not_call_executor_or_skill(self) -> None:
        """AskEngine 不持有、不调用 Executor / Registry。"""

        print("\n[TestAiAskEngine] zero skill / zero executor")
        engine = AskEngine(knowledge_base=self.kb)
        result = engine.ask("explain PT vs PS")
        print(" execute_calls:", self.executor.execute_calls)
        print(" registry_calls:", self.registry.call_count)
        print(" engine attrs executor/registry:", hasattr(engine, "executor"), hasattr(engine, "registry"))
        self.assertEqual(self.executor.execute_calls, 0)
        self.assertEqual(self.registry.call_count, 0)
        self.assertFalse(hasattr(engine, "executor") and engine.executor is not None)
        self.assertNotIn("steps", result.to_dict().get("plan") or {})

    def test_fake_llm_prompt_includes_retrieved_docs(self) -> None:
        """FakeLLM 的 prompt 必须包含检索到的 KB 片段。"""

        print("\n[TestAiAskEngine] FakeLLM grounds on KB")
        fake = FakeLLMProvider(
            replies=["PT is Position Target. PS is a proportional order signal. Grounded on KB."]
        )
        engine = AskEngine(knowledge_base=self.kb, provider=fake)
        result = engine.ask("explain PT vs PS")
        payload = result.to_dict()
        print(" prompts:", fake.prompts)
        print(" answer:", payload["answer"])
        print(" sources:", payload["sources"])
        self.assertEqual(len(fake.prompts), 1)
        self.assertIn("Position Target", fake.prompts[0])
        self.assertIn("pt_ps_vs", fake.prompts[0])
        self.assertIn("PT", payload["answer"])
        self.assertIn("pt_ps_vs", payload["sources"])
        self.assertEqual(self.executor.execute_calls, 0)

    def test_kb_miss_returns_not_found_and_suggests_plan(self) -> None:
        """KB 未命中 → 英文 not_found，建议改用 Plan，禁止空库瞎编。"""

        print("\n[TestAiAskEngine] KB miss")
        fake = FakeLLMProvider(replies=["I made this up without sources."])
        engine = AskEngine(knowledge_base=self.kb, provider=fake)
        result = engine.ask("quantum foam meaning of life xyzzy-no-match")
        payload = result.to_dict()
        print(" ok:", payload.get("ok"))
        print(" error:", payload.get("error"))
        print(" answer:", payload.get("answer"))
        print(" fake prompts:", fake.prompts)
        self.assertFalse(payload["ok"])
        error = payload.get("error") or {}
        self.assertEqual(error.get("code"), "NOT_FOUND")
        self.assertIn("plan", payload["answer"].lower())
        self.assertEqual(fake.prompts, [])
        self._assert_no_plan_execution(payload)

    def test_plan_like_query_suggests_plan_without_steps(self) -> None:
        """列出策略并执行类请求应提示改用 Plan，不生成 steps。"""

        print("\n[TestAiAskEngine] plan-like query")
        engine = AskEngine(knowledge_base=self.kb)
        result = engine.ask("list built-in strategies")
        payload = result.to_dict()
        print(" answer:", payload.get("answer"))
        print(" ok:", payload.get("ok"))
        print(" sources:", payload.get("sources"))
        self.assertEqual(payload["mode"], "ask")
        self.assertIn("plan", payload["answer"].lower())
        self.assertNotIn("execution", payload)
        plan = payload.get("plan")
        self.assertTrue(plan is None or plan.get("steps") in (None, []))
        self.assertEqual(self.executor.execute_calls, 0)
        self.assertEqual(self.registry.call_count, 0)

    def test_offline_run_freq_sources_only_operator(self) -> None:
        """Offline run_freq 问句 sources 仅为 operator_run_freq。"""

        print("\n[TestAiAskEngine] offline run_freq sources")
        engine = AskEngine(knowledge_base=self.kb)
        result = engine.ask("where does run_freq belong")
        payload = result.to_dict()
        print(" sources:", payload.get("sources"))
        print(" answer:", payload.get("answer", "")[:300])
        self._assert_no_plan_execution(payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["sources"], ["operator_run_freq"])
        self.assertIn("Operator", payload["answer"])

    def test_offline_nan_python_code_matches_topic(self) -> None:
        """Offline NaN 问句 python_code 不得是日期窗 get_history_data 示例。"""

        print("\n[TestAiAskEngine] offline NaN python_code")
        engine = AskEngine(knowledge_base=self.kb)
        result = engine.ask("what happens when trade price is NaN")
        payload = result.to_dict()
        print(" sources:", payload.get("sources"))
        print(" python_code:", payload.get("python_code"))
        print(" answer:", payload.get("answer", "")[:300])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["sources"], ["common_errors_nan"])
        self.assertIn("NaN", payload["answer"])
        self.assertNotIn("get_history_data", payload.get("python_code") or "")

    def test_offline_macd_narrative_is_english(self) -> None:
        """Offline macd 顶层 narrative 为英文；中文 kernel 不进 answer。"""

        print("\n[TestAiAskEngine] offline macd English wrap")
        macd_zh = (
            "MACD择时策略类，运用MACD均线策略，生成目标仓位百分比\n"
            "    信号类型:\n"
            "        PT型: 目标仓位百分比\n"
            "        默认参数: (12, 26, 9)\n"
        )
        kb = KnowledgeBase(
            list_func=lambda: ["macd"],
            doc_func=lambda sid: macd_zh,
        )
        engine = AskEngine(knowledge_base=kb)
        result = engine.ask("what is macd strategy")
        payload = result.to_dict()
        print(" sources:", payload.get("sources"))
        print(" answer:", payload.get("answer", "")[:400])
        hits = (payload.get("raw") or {}).get("hits") or []
        meta = next(item for item in hits if item.get("id") == "strategy_meta")
        print(" kernel prefix:", (meta.get("kernel_doc_zh") or "")[:80])
        self.assertIn("strategy_meta", payload["sources"])
        self.assertIn("PT", payload["answer"])
        self.assertIn("(12, 26, 9)", payload["answer"])
        self.assertNotIn("择时策略类", payload["answer"])
        self.assertIn("择时策略类", meta.get("kernel_doc_zh") or "")

    def test_assistant_ask_and_preview_wiring(self) -> None:
        """QteasyAssistant.ask 走 AskEngine；preview 等于 plan dry_run。"""

        print("\n[TestAiAskEngine] assistant wiring")
        import tempfile

        from qteasy_ai.app import QteasyAssistant
        from qteasy_ai.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(memory_store=MemoryStore(base_dir=temp_dir))
            ask_payload = assistant.ask("explain PT vs PS", response_style="raw")
            print(" ask mode:", ask_payload.get("mode"), "sources:", ask_payload.get("sources"))
            print(" ask runs after ask:", assistant.memory_store.list_runs())
            self.assertEqual(ask_payload["mode"], "ask")
            self.assertNotIn("execution", ask_payload)
            self.assertIn("PT", ask_payload["answer"])
            self.assertEqual(assistant.memory_store.list_runs(), [])
            preview_payload = assistant.preview(
                "list built-in strategies",
                response_style="raw",
                persist="none",
            )
            print(" preview skills:", [s["skill_name"] for s in preview_payload["plan"]["steps"]])
            self.assertEqual(preview_payload["execution"]["status"], "dry_run")
            self.assertEqual(
                preview_payload["plan"]["steps"][0]["skill_name"],
                "qt.ai.strategy_meta.list",
            )


if __name__ == "__main__":
    unittest.main()

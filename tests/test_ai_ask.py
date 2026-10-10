# coding=utf-8
# ======================================
# File: test_ai_ask.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-28
# Desc:
# Unittest for qteasy-ai AskEngine target state
# ======================================

import json
import tempfile
import unittest
from pathlib import Path

from qteasy_ai.ask_engine import AskEngine
from qteasy_ai.knowledge_base import KnowledgeBase
from qteasy_ai.provider import FakeLLMProvider

_NEEDS_PROVIDER_MESSAGE = (
    "Follow-up questions, references to earlier turns, and relations need a configured language model. "
    "Without a provider, Ask only answers a self-contained question."
)
_OFFLINE_NOT_FOUND_MESSAGE = "No matching knowledge snippet. Try Plan mode for executable requests."
_OFFLINE_NOT_FOUND_ANSWER = (
    "No matching qteasy knowledge snippet was found for this question. "
    "Ask will not invent an answer from an empty knowledge base. "
    "If you want to list strategies, download data, backtest, or optimize, "
    "use Plan or preview instead of Ask."
)
_NAN_TITLE = "NaN trade prices must not be filled"
_NAN_SUMMARY = (
    "NaN trade prices (halt / missing bar) must not be filled with 1; "
    "skip that symbol on that bar."
)
_DATA_TITLE = "Three data entry points"
_DATA_SUMMARY = (
    "qteasy reads data through history, reference, and static channels — "
    "not a single catch-all API."
)
_BACKTEST_TITLE = "Built-in strategy backtest"
_BACKTEST_SUMMARY = (
    "Plan a built-in backtest with strategy_id and an explicit date window; "
    "confirm before run."
)
_NAN_ANSWER = "NAN-ANSWER-MARKER"
_DATA_ANSWER = "DATA-ANSWER-MARKER"
_PLAN_READY_BODY = "PLAN-READY-BODY-MARKER"
_CLARIFY_BODY = "CLARIFY-BODY-MARKER"
_RESULT_BODY = "RESULT-BODY-MARKER"


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
            replies=[
                '{"topics":["strategy"]}',
                '{"ids":["pt_ps_vs"]}',
                "PT is Position Target. PS is a proportional order signal. Grounded on KB.",
            ]
        )
        engine = AskEngine(knowledge_base=self.kb, provider=fake)
        result = engine.ask("explain PT vs PS")
        payload = result.to_dict()
        print(" prompts:", [len(item) for item in fake.prompts])
        print(" system:", fake.system_prompts)
        print(" answer:", payload["answer"])
        print(" sources:", payload["sources"])
        self.assertEqual(len(fake.prompts), 3)
        self.assertNotIn("Position Target", fake.prompts[0])
        self.assertIn("Position Target", fake.prompts[2])
        self.assertIn("pt_ps_vs", fake.prompts[2])
        self.assertIn("same language", fake.system_prompts[2].lower())
        self.assertIn("same language as the Question", fake.prompts[2])
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
        self.assertEqual(len(fake.prompts), 1)
        self.assertNotIn("Knowledge snippets", fake.prompts[0])
        self.assertNotIn("I made this up", payload["answer"])
        self._assert_no_plan_execution(payload)

    def test_executable_phrasing_still_zero_skill(self) -> None:
        """办事句进 Ask 仍零 skill；sources 来自 KB，不短路劝退。"""

        print("\n[TestAiAskEngine] executable phrasing stays in Ask")
        engine = AskEngine(knowledge_base=self.kb)
        result = engine.ask("list built-in strategies")
        payload = result.to_dict()
        print(" answer:", str(payload.get("answer", ""))[:300])
        print(" ok:", payload.get("ok"))
        print(" sources:", payload.get("sources"))
        self._assert_no_plan_execution(payload)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload.get("sources"))
        self.assertEqual(self.executor.execute_calls, 0)
        self.assertEqual(self.registry.call_count, 0)

    def test_codegen_query_hits_strategy_builder_intro(self) -> None:
        """写策略问法进 KB，命中 strategy_builder_intro，不写盘、不调 skill。"""

        print("\n[TestAiAskEngine] codegen ask hits intro")
        engine = AskEngine(knowledge_base=self.kb)
        result = engine.ask("帮我写一个双均线策略")
        payload = result.to_dict()
        print(" sources:", payload.get("sources"))
        print(" answer:", str(payload.get("answer", ""))[:300])
        self._assert_no_plan_execution(payload)
        self.assertTrue(payload["ok"])
        self.assertIn("strategy_builder_intro", payload["sources"])
        self.assertEqual(self.executor.execute_calls, 0)
        self.assertEqual(self.registry.call_count, 0)

    def test_a3_intro_queries_hit_curated_pages(self) -> None:
        """A3 概念语料命中 intro 页，不被 plan-like 短路。"""

        print("\n[TestAiAskEngine] A3 intro queries")
        engine = AskEngine(knowledge_base=self.kb)
        cases = (
            ("回测入门", "backtest_intro"),
            ("优化入门", "optimize_intro"),
            ("strategybuilder", "strategy_builder_intro"),
        )
        for query, kb_id in cases:
            payload = engine.ask(query).to_dict()
            print(" query:", query, "sources:", payload.get("sources"))
            self._assert_no_plan_execution(payload)
            self.assertTrue(payload["ok"])
            self.assertIn(kb_id, payload["sources"])

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

    def _protocol(
            self,
            topics: list,
            ids: list,
            answer: str = "回测需要明确的 strategy_id 和日期窗口。",
    ) -> FakeLLMProvider:
        """替身按定主题、点卡、作家的顺序返回协议 JSON。"""

        replies = [json.dumps({"topics": topics}, ensure_ascii=False)]
        if ids is not None:
            replies.append(json.dumps({"ids": ids}, ensure_ascii=False))
            replies.append(answer)
        return FakeLLMProvider(replies=replies)

    def test_provider_backtest_paraphrases_start_with_backtest_intro(self) -> None:
        """不带空格的回测问法走主题点卡，sources 以 backtest_intro 开头。"""

        print("\n[TestAiAskEngine] 有模型回测同义句")
        narrative = "A built-in backtest Job needs"
        for query in ("如何用qteasy回测", "如何用qteasy进行回测"):
            fake = self._protocol(["backtest"], ["backtest_intro"])
            engine = AskEngine(knowledge_base=self.kb, provider=fake)
            payload = engine.ask(query).to_dict()
            print(" query:", query)
            print(" sources:", payload.get("sources"))
            print(" topic prompt has narrative:", narrative in fake.prompts[0])
            print(" card prompt has narrative:", narrative in fake.prompts[1])
            print(" writer prompt has narrative:", narrative in fake.prompts[2])
            self._assert_no_plan_execution(payload)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["sources"][0], "backtest_intro")
            self.assertNotIn("what_is_qteasy", payload["sources"])
            self.assertIn("回测解释", fake.prompts[0])
            self.assertNotIn("backtest_intro", fake.prompts[0])
            self.assertNotIn(narrative, fake.prompts[0])
            self.assertNotIn("如何用 qteasy 回测", fake.prompts[0])
            self.assertNotIn("run backtest", fake.prompts[0])
            self.assertNotIn(narrative, fake.prompts[1])
            self.assertIn("backtest_intro", fake.prompts[1])
            self.assertIn(narrative, fake.prompts[2])
            self.assertNotIn("plan_id", payload["answer"])

    def test_provider_drops_unknown_topic_and_keeps_backtest(self) -> None:
        """未知主题被丢掉，剩下的 backtest 仍点卡。"""

        print("\n[TestAiAskEngine] 丢掉未知主题")
        fake = self._protocol(["backtest", "no-such"], ["backtest_intro"])
        engine = AskEngine(knowledge_base=self.kb, provider=fake)
        payload = engine.ask("如何用qteasy进行回测").to_dict()
        print(" sources:", payload.get("sources"))
        print(" card prompt:", fake.prompts[1][:240])
        self.assertEqual(payload["sources"], ["backtest_intro"])
        self.assertIn("backtest_intro", fake.prompts[1])
        self.assertNotIn("what_is_qteasy", fake.prompts[1])
        self.assertEqual(len(fake.prompts), 3)

    def test_provider_unknown_uncertain_and_illegal_json_skip_writer(self) -> None:
        """只剩未知主题、uncertain、非法 JSON 都不调作家。"""

        print("\n[TestAiAskEngine] 定主题失败不作文")
        cases = (
            ['{"topics":["no-such"]}'],
            ['{"uncertain": true}'],
            ["not json"],
            ['{"topics":["backtest","optimize","strategy"]}'],
        )
        for replies in cases:
            fake = FakeLLMProvider(replies=list(replies))
            engine = AskEngine(knowledge_base=self.kb, provider=fake)
            payload = engine.ask("如何用qteasy回测").to_dict()
            print(" replies:", replies, "prompts:", len(fake.prompts), "code:", (payload.get("error") or {}).get("code"))
            self.assertFalse(payload["ok"])
            self.assertEqual((payload.get("error") or {}).get("code"), "NOT_FOUND")
            self.assertEqual(payload["sources"], [])
            self.assertEqual(len(fake.prompts), 1)
            self.assertNotIn("Knowledge snippets", fake.prompts[0])

    def test_provider_card_miss_and_uncertain_skip_writer(self) -> None:
        """点卡 id 不在菜单、uncertain 或空校验都不调作家。"""

        print("\n[TestAiAskEngine] 点卡失败不作文")
        card_replies = (
            '{"ids":["what_is_qteasy"]}',
            '{"uncertain": true}',
            "still not json",
        )
        for card_reply in card_replies:
            fake = FakeLLMProvider(replies=['{"topics":["backtest"]}', card_reply, "should not be the answer"])
            engine = AskEngine(knowledge_base=self.kb, provider=fake)
            payload = engine.ask("如何用qteasy回测").to_dict()
            print(" card reply:", card_reply, "prompts:", len(fake.prompts), "sources:", payload.get("sources"))
            self.assertFalse(payload["ok"])
            self.assertEqual((payload.get("error") or {}).get("code"), "NOT_FOUND")
            self.assertEqual(len(fake.prompts), 2)
            self.assertNotIn("should not be the answer", payload["answer"])
            self.assertNotIn("A built-in backtest Job needs", "".join(fake.prompts))

    def test_provider_trap_is_answered_alone(self) -> None:
        """同一菜单里点中 trap 时，作家只读 trap，不拌 concept。"""

        print("\n[TestAiAskEngine] trap 单独作答")
        fake = self._protocol(
            ["backtest"],
            ["backtest_intro", "common_errors_nan"],
            answer="NaN prices are skipped.",
        )
        engine = AskEngine(knowledge_base=self.kb, provider=fake)
        payload = engine.ask("trade price is NaN during backtest").to_dict()
        print(" sources:", payload.get("sources"))
        print(" writer has concept:", "A built-in backtest Job needs" in fake.prompts[2])
        print(" writer has trap:", "must not be filled" in fake.prompts[2])
        self.assertEqual(payload["sources"], ["common_errors_nan"])
        self.assertIn("must not be filled", fake.prompts[2])
        self.assertNotIn("A built-in backtest Job needs", fake.prompts[2])

    def test_provider_appends_strategy_meta_only_for_concrete_id(self) -> None:
        """点卡成功后，具体策略 id 才追加 strategy_meta；泛词不追加。"""

        print("\n[TestAiAskEngine] strategy_meta 只跟具体 id")
        concrete = self._protocol(["strategy"], ["pt_ps_vs"], answer="MACD is a built-in strategy.")
        engine = AskEngine(knowledge_base=self.kb, provider=concrete)
        concrete_payload = engine.ask("what is macd strategy").to_dict()
        print(" concrete sources:", concrete_payload.get("sources"))
        self.assertEqual(concrete_payload["sources"][0], "pt_ps_vs")
        self.assertIn("strategy_meta", concrete_payload["sources"])
        self.assertIn("Matched strategy_id=macd", concrete.prompts[2])

        generic = self._protocol(["strategy"], ["strategy_builder_intro"], answer="策略是 Operator 上的信号。")
        generic_engine = AskEngine(knowledge_base=self.kb, provider=generic)
        generic_payload = generic_engine.ask("策略是什么").to_dict()
        print(" generic sources:", generic_payload.get("sources"))
        self.assertEqual(generic_payload["sources"], ["strategy_builder_intro"])
        self.assertNotIn("strategy_meta", generic_payload["sources"])

    def test_history_index_lists_successful_ask_cards_only(self) -> None:
        """索引只收成功 Ask 卡：失败卡、计划卡、澄清卡和结果卡都不占轮次。"""

        print("\n[TestAiAskEngine] 成功 Ask 卡才进索引")
        from qteasy_ai.ask_engine import build_ask_history_index

        messages = [
            {"kind": "user_text", "text": "停牌", "payload": {}},
            {
                "kind": "ask",
                "text": _NAN_ANSWER,
                "payload": {"sources": ["common_errors_nan", "backtest_intro"]},
            },
            {"kind": "user_text", "text": "这句失败了", "payload": {}},
            {"kind": "ask", "text": _OFFLINE_NOT_FOUND_ANSWER, "payload": {"sources": []}},
            {
                "kind": "error",
                "text": _OFFLINE_NOT_FOUND_MESSAGE,
                "payload": {"code": "NOT_FOUND"},
            },
            {"kind": "plan_ready", "text": _PLAN_READY_BODY, "payload": {"plan_id": "p1"}},
            {"kind": "clarify", "text": _CLARIFY_BODY, "payload": {}},
            {"kind": "result", "text": _RESULT_BODY, "payload": {}},
            {"kind": "user_text", "text": "三入口", "payload": {}},
            {
                "kind": "ask",
                "text": _DATA_ANSWER,
                "payload": {
                    "sources": ["data_three_entries", "missing_card"],
                    "ask_focus": {
                        "topic": "data-analysis",
                        "sources": ["data_three_entries", "missing_card"],
                    },
                },
            },
        ]
        index = build_ask_history_index(messages, self.kb)
        print(" turns:", [(card.turn, card.card_id) for card in index])
        print(" users:", [card.user_text for card in index])
        self.assertEqual(
            [(card.turn, card.kind, card.card_id, card.title, card.summary) for card in index],
            [
                (1, "ask", "common_errors_nan", _NAN_TITLE, _NAN_SUMMARY),
                (1, "ask", "backtest_intro", _BACKTEST_TITLE, _BACKTEST_SUMMARY),
                (2, "ask", "data_three_entries", _DATA_TITLE, _DATA_SUMMARY),
            ],
        )
        self.assertEqual(index[0].user_text, "停牌")
        self.assertEqual(index[0].answer_text, _NAN_ANSWER)
        self.assertEqual(index[1].user_text, "停牌")
        self.assertEqual(index[1].answer_text, _NAN_ANSWER)
        self.assertEqual(index[2].user_text, "三入口")
        self.assertEqual(index[2].answer_text, _DATA_ANSWER)
        blob = " ".join(card.user_text + card.answer_text + card.card_id for card in index)
        print(" withheld from index rows:", blob)
        self.assertNotIn(_PLAN_READY_BODY, blob)
        self.assertNotIn(_CLARIFY_BODY, blob)
        self.assertNotIn(_RESULT_BODY, blob)
        self.assertNotIn("这句失败了", blob)
        self.assertNotIn("missing_card", blob)

    def test_prior_excerpt_menu_stays_in_named_topic(self) -> None:
        """指代前文时，点卡才看到被点名轮次；菜单不并入 session 里的其它主题。"""

        print("\n[TestAiAskEngine] 指代只展开被点名轮次")
        from qteasy_ai.app import QteasyAssistant
        from qteasy_ai.memory_store import MemoryStore
        from qteasy_ai.provider import FakeLLMProvider

        nan_line = _ask_index_line(1, "common_errors_nan", _NAN_TITLE, _NAN_SUMMARY)
        data_line = _ask_index_line(2, "data_three_entries", _DATA_TITLE, _DATA_SUMMARY)
        fake = FakeLLMProvider(replies=[
            '{"topics":["backtest"]}',
            '{"ids":["common_errors_nan"]}',
            _NAN_ANSWER,
            '{"topics":["data-analysis"]}',
            '{"ids":["data_three_entries"]}',
            _DATA_ANSWER,
            '{"prior":[{"turn":1,"sources":["common_errors_nan"]}]}',
            '{"ids":["common_errors_nan"]}',
            "WRITER-FINE",
        ])
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                provider=fake,
            )
            first = assistant.ask("停牌", response_style="raw", session_id="a7-prior")
            second = assistant.ask("参考数据", response_style="raw", session_id="a7-prior")
            print(" first sources:", first.get("sources"))
            print(" second sources:", second.get("sources"))
            self.assertEqual(first.get("sources"), ["common_errors_nan"])
            self.assertEqual(second.get("sources"), ["data_three_entries"])
            before = len(fake.prompts)
            third = assistant.ask(
                "把你前面讲过的限制再讲一遍",
                response_style="raw",
                session_id="a7-prior",
            )
            topic_prompt = fake.prompts[before]
            card_prompt = fake.prompts[before + 1]
            writer_prompt = fake.prompts[before + 2]
            menu_ids = set(_menu_line_ids(card_prompt))
            focus = (third.get("raw") or {}).get("ask_focus") or {}
            print(" topic prompt:", topic_prompt)
            print(" card prompt:", card_prompt)
            print(" menu ids:", sorted(menu_ids))
            print(" sources:", third.get("sources"))
            print(" writer has history answers:", _NAN_ANSWER in writer_prompt, _DATA_ANSWER in writer_prompt)
            self._assert_no_plan_execution(third)
            self.assertEqual(len(fake.prompts) - before, 3)
            self.assertIn(nan_line, topic_prompt)
            self.assertIn(data_line, topic_prompt)
            self.assertNotIn(_NAN_ANSWER, topic_prompt)
            self.assertNotIn(_DATA_ANSWER, topic_prompt)
            self.assertNotIn("停牌", topic_prompt)
            self.assertNotIn("参考数据", topic_prompt)
            self.assertNotIn("ask_focus", topic_prompt)
            self.assertNotIn("The engine should not trade that symbol on that bar", topic_prompt)
            self.assertIn("User: 停牌", card_prompt)
            self.assertIn(f"Answer shown: {_NAN_ANSWER}", card_prompt)
            self.assertNotIn(_DATA_ANSWER, card_prompt)
            self.assertNotIn("参考数据", card_prompt)
            self.assertEqual(menu_ids, {"backtest_intro", "common_errors_nan"})
            self.assertNotIn("data_three_entries", card_prompt)
            self.assertIn("optimize_intro", card_prompt)
            self.assertNotIn(_NAN_ANSWER, writer_prompt)
            self.assertNotIn(_DATA_ANSWER, writer_prompt)
            self.assertIn("The engine should not trade that symbol on that bar", writer_prompt)
            self.assertEqual(third.get("sources"), ["common_errors_nan"])
            self.assertEqual(focus.get("topic"), "backtest")
            self.assertEqual(focus.get("sources"), ["common_errors_nan"])
            self.assertIsNone(assistant.session_store.load("a7-prior").task)
            self.assertNotIn("plan_id", third.get("answer") or "")

    def test_new_question_topic_prompt_is_one_line_index(self) -> None:
        """已有成功 Ask 时，判成新问题的定主题提示只有一句话索引。"""

        print("\n[TestAiAskEngine] 新问题只带一句话索引")
        from qteasy_ai.app import QteasyAssistant
        from qteasy_ai.memory_store import MemoryStore
        from qteasy_ai.provider import FakeLLMProvider

        nan_line = _ask_index_line(1, "common_errors_nan", _NAN_TITLE, _NAN_SUMMARY)
        fake = FakeLLMProvider(replies=[
            '{"topics":["backtest"]}',
            '{"ids":["common_errors_nan"]}',
            _NAN_ANSWER,
            '{"topics":["backtest"]}',
            '{"ids":["backtest_intro"]}',
            "回测需要明确的 strategy_id 和日期窗口。",
        ])
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                provider=fake,
            )
            first = assistant.ask("停牌", response_style="raw", session_id="a7-new")
            print(" first sources:", first.get("sources"))
            self.assertEqual(first.get("sources"), ["common_errors_nan"])
            before = len(fake.prompts)
            second = assistant.ask("如何用qteasy回测", response_style="raw", session_id="a7-new")
            topic_prompt = fake.prompts[before]
            card_prompt = fake.prompts[before + 1]
            writer_prompt = fake.prompts[before + 2]
            print(" topic prompt:", topic_prompt)
            print(" card has named turns:", "Named turns:" in card_prompt)
            print(" sources:", second.get("sources"))
            self._assert_no_plan_execution(second)
            self.assertTrue(topic_prompt.startswith("Topic registry:"))
            self.assertIn("Ask history index:", topic_prompt)
            self.assertIn(nan_line, topic_prompt)
            self.assertNotIn(_NAN_ANSWER, topic_prompt)
            self.assertNotIn("停牌", topic_prompt)
            self.assertNotIn("ask_focus", topic_prompt)
            self.assertNotIn("A built-in backtest Job needs", topic_prompt)
            self.assertNotIn("Named turns:", card_prompt)
            self.assertNotIn("Answer shown:", card_prompt)
            self.assertNotIn(_NAN_ANSWER, card_prompt)
            self.assertNotIn("停牌", card_prompt)
            self.assertNotIn(_NAN_ANSWER, writer_prompt)
            self.assertIn("A built-in backtest Job needs", writer_prompt)
            self.assertEqual(second.get("sources"), ["backtest_intro"])

    def test_bad_prior_or_uncertain_does_not_call_writer(self) -> None:
        """点名对不上或 uncertain 时不调用作家，也不退回猜卡。"""

        print("\n[TestAiAskEngine] 非法点名不调用作家")
        from qteasy_ai.app import QteasyAssistant
        from qteasy_ai.memory_store import MemoryStore
        from qteasy_ai.provider import FakeLLMProvider

        cases = (
            ('{"prior":[{"turn":9,"sources":["common_errors_nan"]}]}', "轮次不在索引"),
            ('{"prior":[{"turn":1,"sources":["data_three_entries"]}]}', "source 不属于该轮"),
            ('{"uncertain": true}', "uncertain"),
            (
                '{"topics":["backtest"],"prior":[{"turn":1,"sources":["common_errors_nan"]}]}',
                "同时给出 topics 和 prior",
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                provider=FakeLLMProvider(replies=[
                    '{"topics":["backtest"]}',
                    '{"ids":["common_errors_nan"]}',
                    _NAN_ANSWER,
                ]),
            )
            first = assistant.ask("停牌", response_style="raw", session_id="a7-miss")
            print(" first sources:", first.get("sources"))
            self.assertEqual(first.get("sources"), ["common_errors_nan"])
            for reply, label in cases:
                probe = FakeLLMProvider(replies=[reply, "SHOULD-NOT-WRITE"])
                assistant.ask_engine.provider = probe
                missed = assistant.ask(label, response_style="raw", session_id="a7-miss")
                print(" case:", label)
                print(" prompts:", len(probe.prompts), "code:", (missed.get("error") or {}).get("code"))
                print(" leftover replies:", probe.replies)
                print(" sources:", missed.get("sources"))
                self.assertEqual(len(probe.prompts), 1)
                self.assertEqual(probe.replies, ["SHOULD-NOT-WRITE"])
                self.assertNotIn("SHOULD-NOT-WRITE", probe.prompts[0])
                self.assertFalse(missed.get("ok"))
                self.assertEqual((missed.get("error") or {}).get("code"), "NOT_FOUND")
                self.assertEqual((missed.get("error") or {}).get("message"), _OFFLINE_NOT_FOUND_MESSAGE)
                self.assertEqual(missed.get("sources"), [])
                self.assertNotIn("data-downloading", missed.get("answer") or "")

    def test_plan_ready_text_stays_out_of_ask_prompts(self) -> None:
        """定主题提示不读 plan_ready、clarify 或 result 的正文。"""

        print("\n[TestAiAskEngine] 不读计划卡和结果卡")
        from qteasy_ai.app import QteasyAssistant
        from qteasy_ai.memory_store import MemoryStore
        from qteasy_ai.provider import FakeLLMProvider

        fake = FakeLLMProvider(replies=[
            '{"topics":["backtest"]}',
            '{"ids":["common_errors_nan"]}',
            _NAN_ANSWER,
            '{"topics":["backtest"]}',
            '{"ids":["backtest_intro"]}',
            "回测需要明确的日期窗口。",
        ])
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                provider=fake,
            )
            first = assistant.ask("停牌", response_style="raw", session_id="a7-kinds")
            print(" first sources:", first.get("sources"))
            self.assertEqual(first.get("sources"), ["common_errors_nan"])
            state = assistant.session_store.load("a7-kinds")
            state.append_messages([
                {"kind": "plan_ready", "text": _PLAN_READY_BODY, "payload": {"plan_id": "p-a7"}},
                {"kind": "clarify", "text": _CLARIFY_BODY, "payload": {}},
                {"kind": "result", "text": _RESULT_BODY, "payload": {}},
            ])
            assistant.session_store.save(state)
            before = len(fake.prompts)
            second = assistant.ask("如何用qteasy回测", response_style="raw", session_id="a7-kinds")
            topic_prompt = fake.prompts[before]
            print(" topic prompt has plan body:", _PLAN_READY_BODY in topic_prompt)
            print(" sources:", second.get("sources"))
            self.assertIn(
                _ask_index_line(1, "common_errors_nan", _NAN_TITLE, _NAN_SUMMARY),
                topic_prompt,
            )
            self.assertNotIn(_PLAN_READY_BODY, topic_prompt)
            self.assertNotIn(_CLARIFY_BODY, topic_prompt)
            self.assertNotIn(_RESULT_BODY, topic_prompt)
            self.assertNotIn(_PLAN_READY_BODY, fake.prompts[before + 1])
            self.assertNotIn(_PLAN_READY_BODY, fake.prompts[before + 2])
            self.assertEqual(second.get("sources"), ["backtest_intro"])

    def test_second_item_follows_model_json(self) -> None:
        """「第二项」只跟随模型 JSON，代码不按这四个字打开数据主题。"""

        print("\n[TestAiAskEngine] 第二项跟随 JSON")
        from qteasy_ai.app import QteasyAssistant
        from qteasy_ai.memory_store import MemoryStore
        from qteasy_ai.provider import FakeLLMProvider

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            fake = FakeLLMProvider(replies=[
                '{"topics":["backtest"]}',
                '{"ids":["common_errors_nan"]}',
                _NAN_ANSWER,
                '{"topics":["backtest"]}',
                '{"ids":["backtest_intro"]}',
                "回测需要明确的日期窗口。",
            ])
            assistant = QteasyAssistant(memory_store=store, provider=fake)
            first = assistant.ask("停牌", response_style="raw", session_id="a7-ordinal")
            print(" first sources:", first.get("sources"))
            self.assertEqual(first.get("sources"), ["common_errors_nan"])
            before = len(fake.prompts)
            second = assistant.ask("第二项", response_style="raw", session_id="a7-ordinal")
            topic_prompt = fake.prompts[before]
            card_prompt = fake.prompts[before + 1]
            menu_ids = set(_menu_line_ids(card_prompt))
            print(" topic prompt starts:", topic_prompt.splitlines()[0])
            print(" menu ids:", sorted(menu_ids))
            print(" sources:", second.get("sources"))
            self._assert_no_plan_execution(second)
            self.assertEqual(len(fake.prompts) - before, 3)
            self.assertTrue(topic_prompt.startswith("Topic registry:"))
            self.assertIn("Ask history index:", topic_prompt)
            self.assertEqual(menu_ids, {"backtest_intro", "common_errors_nan"})
            self.assertNotIn("data-downloading", card_prompt)
            self.assertNotIn("data-analysis", card_prompt)
            self.assertNotIn("data_three_entries", card_prompt)
            self.assertNotIn("env_ready", card_prompt)
            self.assertNotIn("Resolved ask_focus:", card_prompt)
            self.assertEqual(second.get("sources"), ["backtest_intro"])

            plain = self._protocol(["backtest"], ["backtest_intro"], answer="回测需要明确的日期窗口。")
            bare = QteasyAssistant(memory_store=store, provider=plain)
            payload = bare.ask("第二项", response_style="raw")
            print(" no-session topic prompt:", plain.prompts[0])
            print(" no-session sources:", payload.get("sources"))
            self.assertEqual(len(plain.prompts), 3)
            self.assertTrue(plain.prompts[0].startswith("Topic registry:"))
            self.assertNotIn("Ask history index:", plain.prompts[0])
            self.assertNotIn('"prior"', plain.prompts[0])
            self.assertNotIn("ask_focus", plain.prompts[0])
            self.assertEqual(set(_menu_line_ids(plain.prompts[1])), {"backtest_intro", "common_errors_nan"})
            self.assertNotIn("data_three_entries", plain.prompts[1])
            self.assertEqual(payload.get("sources"), ["backtest_intro"])
            self.assertNotIn("session", payload)

    def test_offline_self_contained_hit_and_history_miss(self) -> None:
        """无 Provider：自足金句仍命中；有历史但本句未命中时说明需要大模型。"""

        print("\n[TestAiAskEngine] 无 Provider 的单句天花板")
        from qteasy_ai.app import QteasyAssistant
        from qteasy_ai.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(memory_store=MemoryStore(base_dir=temp_dir))
            empty = assistant.ask("第二项", response_style="raw", session_id="a7-offline-empty")
            print(" empty code:", (empty.get("error") or {}).get("code"))
            print(" empty message:", (empty.get("error") or {}).get("message"))
            self.assertFalse(empty.get("ok"))
            self.assertEqual((empty.get("error") or {}).get("code"), "NOT_FOUND")
            self.assertEqual((empty.get("error") or {}).get("message"), _OFFLINE_NOT_FOUND_MESSAGE)
            self.assertEqual(empty.get("answer"), _OFFLINE_NOT_FOUND_ANSWER)
            self.assertEqual(empty.get("sources"), [])
            self.assertNotIn("data-downloading", empty.get("answer") or "")
            self.assertIsNone(assistant.session_store.load("a7-offline-empty").task)

            hit = assistant.ask("停牌", response_style="raw", session_id="a7-offline-hist")
            print(" gold sources:", hit.get("sources"))
            print(" gold answer:", (hit.get("answer") or "")[:180])
            self.assertTrue(hit.get("ok"))
            self.assertEqual(hit.get("sources"), ["common_errors_nan"])
            self.assertIn("must not be filled with 1", hit.get("answer") or "")
            missed = assistant.ask("第二项", response_style="raw", session_id="a7-offline-hist")
            print(" history miss message:", (missed.get("error") or {}).get("message"))
            print(" history miss sources:", missed.get("sources"))
            self.assertFalse(missed.get("ok"))
            self.assertEqual((missed.get("error") or {}).get("code"), "NOT_FOUND")
            self.assertEqual((missed.get("error") or {}).get("message"), _NEEDS_PROVIDER_MESSAGE)
            self.assertEqual(missed.get("answer"), _NEEDS_PROVIDER_MESSAGE)
            self.assertEqual(missed.get("sources"), [])
            self.assertNotIn("data-downloading", missed.get("answer") or "")
            self.assertNotIn("data-analysis", missed.get("answer") or "")
            self.assertNotIn("data_three_entries", missed.get("answer") or "")
            again = assistant.ask("停牌", response_style="raw", session_id="a7-offline-hist")
            print(" gold again sources:", again.get("sources"))
            self.assertTrue(again.get("ok"))
            self.assertEqual(again.get("sources"), ["common_errors_nan"])
            self.assertIn("must not be filled with 1", again.get("answer") or "")
            self.assertIsNone(assistant.session_store.load("a7-offline-hist").task)

    def test_provider_depth1_neighbor_is_allowed_only_with_menu_card(self) -> None:
        """深度 1 邻居可与菜单卡一起入选；只点邻居则 NOT_FOUND。"""

        print("\n[TestAiAskEngine] 深度 1 邻居降为邀请")
        with tempfile.TemporaryDirectory() as temp_dir:
            kb_dir = _write_neighbor_kb(Path(temp_dir))
            kb = KnowledgeBase(kb_dir=kb_dir, list_func=lambda: [], doc_func=lambda sid: "")
            paired = self._protocol(["backtest"], ["menu_card", "neighbor_card"], answer="只答菜单卡")
            paired_payload = AskEngine(knowledge_base=kb, provider=paired).ask("回测和旁边那张").to_dict()
            see_also = _see_also_line("Neighbor title", "Neighbor summary.")
            print(" paired sources:", paired_payload.get("sources"))
            print(" card prompt:", paired.prompts[1])
            print(" writer has neighbor body:", "NEIGHBOR BODY" in paired.prompts[2])
            print(" writer has see_also:", see_also in paired.prompts[2])
            self.assertEqual(paired_payload["sources"], ["menu_card"])
            self.assertIn("edge see_also -> neighbor_card: Neighbor title", paired.prompts[1])
            self.assertIn("edge see_also <- incoming_card: Incoming title", paired.prompts[1])
            self.assertNotIn("NEIGHBOR BODY", paired.prompts[1])
            self.assertNotIn("NEIGHBOR BODY", paired.prompts[2])
            self.assertIn("MENU BODY", paired.prompts[2])
            self.assertIn(see_also, paired.prompts[2])
            self.assertNotIn("没有策展关联", paired.prompts[2])

            alone = FakeLLMProvider(replies=[
                '{"topics":["backtest"]}',
                '{"ids":["neighbor_card"]}',
                "should not write",
            ])
            alone_payload = AskEngine(knowledge_base=kb, provider=alone).ask("只点邻居").to_dict()
            print(" alone prompts:", len(alone.prompts), "sources:", alone_payload.get("sources"))
            self.assertFalse(alone_payload["ok"])
            self.assertEqual(len(alone.prompts), 2)
            self.assertNotIn("NEIGHBOR BODY", "".join(alone.prompts))

            incoming = self._protocol(
                ["backtest"],
                ["menu_card", "incoming_card"],
                answer="只答菜单卡",
            )
            incoming_payload = AskEngine(knowledge_base=kb, provider=incoming).ask("入边邻居").to_dict()
            incoming_line = _see_also_line("Incoming title", "Incoming summary.")
            print(" incoming sources:", incoming_payload.get("sources"))
            print(" writer has incoming body:", "INCOMING BODY" in incoming.prompts[2])
            self.assertEqual(incoming_payload["sources"], ["menu_card"])
            self.assertIn(incoming_line, incoming.prompts[2])
            self.assertNotIn("INCOMING BODY", incoming.prompts[2])

    def test_relation_compose_clauses_cover_four_rels(self) -> None:
        """四种 rel 各按注册表合编；不看问句表面。"""

        print("\n[TestAiAskEngine] 四种 rel 只邀请或列举")
        cases = (
            {
                "rel": "see_also",
                "target": "beta",
                "title": "Beta title",
                "narrative": "NARR-BETA",
                "line": _see_also_line("Beta title", "Beta title summary."),
                "answer": "主答之后列举一句。",
            },
            {
                "rel": "next_topic",
                "target": "gamma",
                "title": "Gamma title",
                "narrative": "NARR-GAMMA",
                "line": _invite_line("Gamma title"),
                "answer": "主答之后邀请下一张。",
            },
            {
                "rel": "contrasts_with",
                "target": "delta",
                "title": "Delta title",
                "narrative": "NARR-DELTA",
                "line": _invite_line("Delta title"),
                "answer": "只问一侧时不展开对照。",
            },
            {
                "rel": "plan_handoff",
                "target": "epsilon",
                "title": "Epsilon title",
                "narrative": "NARR-EPSILON",
                "line": _plan_invite_line("Epsilon title"),
                "answer": "解释之后可以切到 Plan。",
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for case in cases:
                kb = KnowledgeBase(
                    kb_dir=_write_pair_kb(
                        root / case["rel"],
                        case["rel"],
                        case["target"],
                        case["title"],
                        case["narrative"],
                    ),
                    list_func=lambda: [],
                    doc_func=lambda sid: "",
                )
                query = f"probe {case['rel']} without special casing"
                fake = self._protocol(["backtest"], ["alpha", case["target"]], answer=case["answer"])
                payload = AskEngine(knowledge_base=kb, provider=fake).ask(query).to_dict()
                encoded = json.dumps(payload, ensure_ascii=False)
                print(" rel:", case["rel"])
                print(" sources:", payload.get("sources"))
                print(" writer has line:", case["line"] in fake.prompts[2])
                print(" writer has narrative:", case["narrative"] in fake.prompts[2])
                self._assert_no_plan_execution(payload)
                self.assertEqual(payload["sources"], ["alpha"])
                self.assertNotIn(case["target"], payload["sources"])
                self.assertIn(case["line"], fake.prompts[2])
                self.assertNotIn(case["narrative"], fake.prompts[2])
                self.assertNotIn("没有策展关联", fake.prompts[2])
                self.assertNotIn(_CONTRAST_CLAUSE, fake.prompts[2])
                self.assertEqual(payload["answer"], case["answer"])
                self.assertNotIn("plan_id", payload["answer"])
                self.assertNotIn("plan_id", encoded)

    def test_selected_cards_without_edge_state_no_curated_relation(self) -> None:
        """选中集内部没有边时只答这些卡，并说明没有策展关联。"""

        print("\n[TestAiAskEngine] 无策展边")
        with tempfile.TemporaryDirectory() as temp_dir:
            kb = KnowledgeBase(
                kb_dir=_write_relation_kb(Path(temp_dir)),
                list_func=lambda: [],
                doc_func=lambda sid: "",
            )
            fake = self._protocol(
                ["backtest"],
                ["alpha", "zeta"],
                answer="只说明这两张卡，没有策展关联。",
            )
            payload = AskEngine(knowledge_base=kb, provider=fake).ask("alpha 和 zeta 有什么关系").to_dict()
            print(" sources:", payload.get("sources"))
            print(" writer:", fake.prompts[2])
            self._assert_no_plan_execution(payload)
            self.assertEqual(payload["sources"], ["alpha", "zeta"])
            self.assertIn("没有策展关联", fake.prompts[2])
            self.assertNotIn(_CONTRAST_CLAUSE, fake.prompts[2])
            self.assertNotIn("NARR-ZETA", fake.prompts[1])
            self.assertIn("NARR-ZETA", fake.prompts[2])
            self.assertEqual(payload["answer"], "只说明这两张卡，没有策展关联。")

    def test_depth2_id_is_dropped_and_body_stays_out(self) -> None:
        """深度 2 的 id 丢掉，正文不进作家提示。"""

        print("\n[TestAiAskEngine] 深度 2 不爬")
        with tempfile.TemporaryDirectory() as temp_dir:
            kb = KnowledgeBase(
                kb_dir=_write_relation_kb(Path(temp_dir)),
                list_func=lambda: [],
                doc_func=lambda sid: "",
            )
            fake = self._protocol(
                ["backtest"],
                ["alpha", "beta", "eta"],
                answer="只保留一跳。",
            )
            payload = AskEngine(knowledge_base=kb, provider=fake).ask("沿边再看一张").to_dict()
            print(" sources:", payload.get("sources"))
            print(" prompts mention NARR-ETA:", "NARR-ETA" in "".join(fake.prompts))
            print(" writer has beta body:", "NARR-BETA" in fake.prompts[2])
            self._assert_no_plan_execution(payload)
            self.assertEqual(payload["sources"], ["alpha"])
            self.assertNotIn("beta", payload["sources"])
            self.assertNotIn("eta", payload["sources"])
            self.assertNotIn("NARR-ETA", "".join(fake.prompts))
            self.assertNotIn("NARR-BETA", fake.prompts[2])
            self.assertIn(_see_also_line("Beta title", "Beta title summary."), fake.prompts[2])

    def test_official_contrast_sources_include_both_cards(self) -> None:
        """实库 contrasts_with：两边 id 都在 sources，合编句不依赖问句原文。"""

        print("\n[TestAiAskEngine] 实库 contrasts_with")
        queries = ("回测和优化有什么差别", "surface wording is not the route")
        for query in queries:
            fake = self._protocol(
                ["backtest", "optimize"],
                ["backtest_intro", "optimize_intro"],
                answer="回测跑一次，优化搜索参数。",
            )
            payload = AskEngine(knowledge_base=self.kb, provider=fake).ask(query).to_dict()
            encoded = json.dumps(payload, ensure_ascii=False)
            print(" query:", query)
            print(" sources:", payload.get("sources"))
            print(" writer has contrast:", _CONTRAST_CLAUSE in fake.prompts[2])
            print(" writer has optimize narrative:", "qt.ai.optimize.run_builtin" in fake.prompts[2])
            self._assert_no_plan_execution(payload)
            self.assertEqual(payload["sources"], ["backtest_intro", "optimize_intro"])
            self.assertIn("backtest_intro", payload["sources"])
            self.assertIn("optimize_intro", payload["sources"])
            self.assertIn(_CONTRAST_CLAUSE, fake.prompts[2])
            self.assertIn("qt.ai.optimize.run_builtin", fake.prompts[2])
            self.assertNotIn("没有策展关联", fake.prompts[2])
            self.assertNotIn("plan_id", payload["answer"])
            self.assertNotIn("plan_id", encoded)

    def test_backtest_only_demotes_optimize_to_invitation(self) -> None:
        """只点回测主题时，模型返回的优化卡不进正文，只留邀请。"""

        print("\n[TestAiAskEngine] 回测题不展开优化正文")
        fake = self._protocol(
            ["backtest"],
            ["backtest_intro", "optimize_intro"],
            answer="回测需要 strategy_id。",
        )
        payload = AskEngine(knowledge_base=self.kb, provider=fake).ask("如何进行回测").to_dict()
        invite = _invite_line("Built-in parameter optimization")
        print(" sources:", payload.get("sources"))
        print(" writer has optimize narrative:", "qt.ai.optimize.run_builtin" in fake.prompts[2])
        print(" writer has invite:", invite in fake.prompts[2])
        self._assert_no_plan_execution(payload)
        self.assertEqual(payload["sources"], ["backtest_intro"])
        self.assertIn("A built-in backtest Job needs", fake.prompts[2])
        self.assertNotIn("qt.ai.optimize.run_builtin", fake.prompts[2])
        self.assertIn(invite, fake.prompts[2])
        self.assertNotIn(_CONTRAST_CLAUSE, fake.prompts[2])
        self.assertNotIn("没有策展关联", fake.prompts[2])
        self.assertNotIn("plan_id", payload["answer"])
        self.assertNotIn("plan_id", json.dumps(payload, ensure_ascii=False))

    def test_optimize_menu_shows_backtest_and_does_not_deny_relation(self) -> None:
        """只点优化主题时，菜单能看见回测边，答案不说没有策展关联。"""

        print("\n[TestAiAskEngine] 优化题邀请回测")
        fake = self._protocol(["optimize"], ["optimize_intro"], answer="优化需要 strategy_id。")
        payload = AskEngine(knowledge_base=self.kb, provider=fake).ask("如何进行优化").to_dict()
        invite = _invite_line("Built-in strategy backtest")
        print(" sources:", payload.get("sources"))
        print(" card prompt:", fake.prompts[1])
        print(" writer has backtest narrative:", "A built-in backtest Job needs" in fake.prompts[2])
        self._assert_no_plan_execution(payload)
        self.assertIn("backtest_intro", fake.prompts[1])
        self.assertIn("contrasts_with", fake.prompts[1])
        self.assertEqual(payload["sources"], ["optimize_intro"])
        self.assertIn(invite, fake.prompts[2])
        self.assertNotIn("A built-in backtest Job needs", fake.prompts[2])
        self.assertNotIn("没有策展关联", fake.prompts[2])
        self.assertNotIn("plan_id", payload["answer"])
        self.assertNotIn("plan_id", json.dumps(payload, ensure_ascii=False))

    def test_offline_backtest_stays_on_one_card(self) -> None:
        """无模型回测金句仍只定 backtest_intro，不沿边对比。"""

        print("\n[TestAiAskEngine] 无模型不沿边")
        payload = AskEngine(knowledge_base=self.kb).ask("how to backtest").to_dict()
        print(" sources:", payload.get("sources"))
        print(" answer has 没有策展关联:", "没有策展关联" in payload.get("answer", ""))
        self._assert_no_plan_execution(payload)
        self.assertEqual(payload["sources"], ["backtest_intro"])
        self.assertNotIn("optimize_intro", payload["sources"])
        self.assertNotIn("没有策展关联", payload["answer"])


_CONTRAST_CLAUSE = (
    "Composition contrast: organize the answer as a contrast between the linked cards."
)


def _invite_line(title: str) -> str:
    """默认邀请金句。"""

    return (
        f"Invitation: if you want to know more about {title}, you can ask next. "
        "Do not expand that card in this answer."
    )


def _plan_invite_line(title: str) -> str:
    """plan_handoff 邀请金句。"""

    return (
        "Invitation plan_handoff: you can switch to Plan to go further. "
        "Do not emit plan_id, steps, or a confirmable plan. "
        f"Related title: {title}."
    )


def _see_also_line(title: str, summary: str) -> str:
    """see_also 列举金句。"""

    return f"Related see_also: {title}. {summary}"


def _ask_index_line(turn: int, card_id: str, title: str, summary: str) -> str:
    """定主题提示里的一句话索引金标准。"""

    return f"- turn {turn} kind=ask id={card_id} title={title} summary={summary}"



def _menu_line_ids(prompt: str) -> list:
    """点卡提示里以「- id:」开头的菜单 id，不含边行。"""

    found = []
    for line in str(prompt or "").splitlines():
        if not line.startswith("- ") or ":" not in line:
            continue
        found.append(line[2:].split(":", 1)[0].strip())
    return found


def _write_neighbor_kb(root: Path) -> Path:
    """临时库：回测菜单卡指向 strategy 邻居，另一张卡反向指向菜单卡。"""

    kb_dir = root / "kb"
    kb_dir.mkdir()
    source = kb_dir / "_source"
    source.mkdir()
    registry = {
        "topics": [
            {"id": "backtest", "scope": "回测解释"},
            {"id": "strategy", "scope": "策略、信号、Operator"},
        ]
    }
    (source / "topic_registry.json").write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
    (source / "relation_registry.json").write_text(
        json.dumps(_RELATION_REGISTRY, ensure_ascii=False),
        encoding="utf-8",
    )
    cards = (
        {
            "id": "menu_card",
            "title": "Menu title",
            "summary": "Menu summary.",
            "narrative": "MENU BODY",
            "type": "concept",
            "topics": ["backtest"],
            "manual_anchor": "",
            "relations": [{"rel": "see_also", "to": "neighbor_card"}],
        },
        {
            "id": "neighbor_card",
            "title": "Neighbor title",
            "summary": "Neighbor summary.",
            "narrative": "NEIGHBOR BODY",
            "type": "concept",
            "topics": ["strategy"],
            "manual_anchor": "",
            "relations": [],
        },
        {
            "id": "incoming_card",
            "title": "Incoming title",
            "summary": "Incoming summary.",
            "narrative": "INCOMING BODY",
            "type": "concept",
            "topics": ["strategy"],
            "manual_anchor": "",
            "relations": [{"rel": "see_also", "to": "menu_card"}],
        },
    )
    for card in cards:
        (kb_dir / f"{card['id']}.json").write_text(
            json.dumps(card, ensure_ascii=False),
            encoding="utf-8",
        )
    return kb_dir


def _write_pair_kb(root: Path, rel: str, target_id: str, title: str, narrative: str) -> Path:
    """临时库：回测菜单上的 alpha 用一条边连到 strategy 上的对方。"""

    kb_dir = root / "kb"
    kb_dir.mkdir(parents=True)
    source = kb_dir / "_source"
    source.mkdir()
    registry = {
        "topics": [
            {"id": "backtest", "scope": "回测解释"},
            {"id": "strategy", "scope": "策略、信号、Operator"},
        ]
    }
    (source / "topic_registry.json").write_text(
        json.dumps(registry, ensure_ascii=False),
        encoding="utf-8",
    )
    (source / "relation_registry.json").write_text(
        json.dumps(_RELATION_REGISTRY, ensure_ascii=False),
        encoding="utf-8",
    )
    cards = (
        _relation_card(
            "alpha",
            "Alpha title",
            "NARR-ALPHA",
            ["backtest"],
            [{"rel": rel, "to": target_id}],
        ),
        _relation_card(target_id, title, narrative, ["strategy"], []),
    )
    for card in cards:
        (kb_dir / f"{card['id']}.json").write_text(
            json.dumps(card, ensure_ascii=False),
            encoding="utf-8",
        )
    return kb_dir


def _write_relation_kb(root: Path) -> Path:
    """临时库：alpha 用四条已注册边连到邻居，zeta 无边，eta 在第二跳。"""

    kb_dir = root / "kb"
    kb_dir.mkdir()
    source = kb_dir / "_source"
    source.mkdir()
    registry = {
        "topics": [
            {"id": "backtest", "scope": "回测解释"},
            {"id": "strategy", "scope": "策略、信号、Operator"},
        ]
    }
    (source / "topic_registry.json").write_text(
        json.dumps(registry, ensure_ascii=False),
        encoding="utf-8",
    )
    (source / "relation_registry.json").write_text(
        json.dumps(_RELATION_REGISTRY, ensure_ascii=False),
        encoding="utf-8",
    )
    cards = (
        _relation_card(
            "alpha",
            "Alpha title",
            "NARR-ALPHA",
            ["backtest"],
            [
                {"rel": "see_also", "to": "beta"},
                {"rel": "next_topic", "to": "gamma"},
                {"rel": "contrasts_with", "to": "delta"},
                {"rel": "plan_handoff", "to": "epsilon"},
            ],
        ),
        _relation_card("beta", "Beta title", "NARR-BETA", ["strategy"], [
            {"rel": "see_also", "to": "eta"},
        ]),
        _relation_card("gamma", "Gamma title", "NARR-GAMMA", ["strategy"], []),
        _relation_card("delta", "Delta title", "NARR-DELTA", ["strategy"], []),
        _relation_card("epsilon", "Epsilon title", "NARR-EPSILON", ["strategy"], []),
        _relation_card("zeta", "Zeta title", "NARR-ZETA", ["backtest"], []),
        _relation_card("eta", "Eta title", "NARR-ETA", ["strategy"], []),
    )
    for card in cards:
        (kb_dir / f"{card['id']}.json").write_text(
            json.dumps(card, ensure_ascii=False),
            encoding="utf-8",
        )
    return kb_dir


def _relation_card(
        card_id: str,
        title: str,
        narrative: str,
        topics: list,
        relations: list,
) -> dict:
    """一张临时策展卡。"""

    return {
        "id": card_id,
        "title": title,
        "summary": f"{title} summary.",
        "narrative": narrative,
        "type": "concept",
        "topics": topics,
        "manual_anchor": "",
        "relations": relations,
    }


_RELATION_REGISTRY = {
    "relations": [
        {"id": "see_also", "compose": "appendix"},
        {"id": "next_topic", "compose": "next_card"},
        {"id": "contrasts_with", "compose": "contrast"},
        {"id": "plan_handoff", "compose": "plan_switch"},
    ]
}


if __name__ == "__main__":
    unittest.main()

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

    def test_provider_ask_focus_is_prompt_only(self) -> None:
        """显式 ask_focus 只进入定主题提示，缺省不写焦点字段。"""

        print("\n[TestAiAskEngine] ask_focus 只进提示")
        focused = self._protocol(["backtest"], ["backtest_intro"])
        engine = AskEngine(knowledge_base=self.kb, provider=focused)
        engine.ask("如何用qteasy回测", ask_focus={"menu_item": 3, "topic": "backtest"})
        print(" focused topic prompt:", focused.prompts[0])
        self.assertIn("Current ask_focus:", focused.prompts[0])
        self.assertIn('"menu_item": 3', focused.prompts[0])
        self.assertNotIn("第二项", focused.prompts[0])

        plain = self._protocol(["backtest"], ["backtest_intro"])
        AskEngine(knowledge_base=self.kb, provider=plain).ask("第二项")
        print(" plain topic prompt has ask_focus:", "ask_focus" in plain.prompts[0])
        self.assertNotIn("ask_focus", plain.prompts[0])
        self.assertNotIn("data-downloading", plain.prompts[1])

    def test_session_second_item_opens_data_topics(self) -> None:
        """同一 session 先问能力再问「第二项」，点卡菜单只含两个数据主题。"""

        print("\n[TestAiAskEngine] session 第二项打开数据主题")
        from qteasy_ai.app import QteasyAssistant
        from qteasy_ai.memory_store import MemoryStore
        from qteasy_ai.provider import FakeLLMProvider
        from qteasy_ai.session import latest_ask_focus

        data_topics = ["data-downloading", "data-analysis"]
        fake = FakeLLMProvider(replies=[
            '{"topics":["capability"]}',
            '{"ids":["what_is_qteasy"]}',
            "qteasy 可以回答概念、取数、回测和优化。",
            '{"ids":["data_three_entries"]}',
            "历史、参考和静态是三条数据入口。",
            '{"uncertain": true}',
            '{"topics":["backtest"]}',
            '{"ids":["backtest_intro"]}',
            "回测需要明确的 strategy_id 和日期窗口。",
        ])
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                provider=fake,
            )
            first = assistant.ask(
                "你能帮我做什么",
                response_style="raw",
                session_id="a4-focus",
            )
            first_focus = (first.get("raw") or {}).get("ask_focus") or {}
            print(" first sources:", first.get("sources"))
            print(" first focus:", first_focus)
            self._assert_no_plan_execution(first)
            self.assertEqual(first.get("sources"), ["what_is_qteasy"])
            self.assertEqual(first_focus.get("topic"), "capability")
            self.assertEqual(first_focus.get("menu_item"), 1)
            self.assertIsNone(assistant.session_store.load("a4-focus").task)

            before_second = len(fake.prompts)
            second = assistant.ask("第二项", response_style="raw", session_id="a4-focus")
            card_prompt = fake.prompts[before_second]
            menu_ids = _menu_line_ids(card_prompt)
            kb = assistant.ask_engine.knowledge_base
            menu = kb.menu_for_topics(data_topics)
            allowed = {entry.id for entry in menu} | kb._depth1_neighbor_ids([entry.id for entry in menu])
            second_focus = (second.get("raw") or {}).get("ask_focus") or {}
            stored = latest_ask_focus(assistant.session_store.load("a4-focus"))
            print(" second prompts added:", len(fake.prompts) - before_second)
            print(" card prompt:", card_prompt)
            print(" menu ids:", menu_ids)
            print(" allowed:", sorted(allowed))
            print(" second sources:", second.get("sources"))
            print(" second focus:", second_focus)
            print(" stored focus:", stored)
            self._assert_no_plan_execution(second)
            self.assertTrue(card_prompt.startswith("Cards in the selected topics:"))
            self.assertIn("Resolved ask_focus:", card_prompt)
            self.assertEqual(len(fake.prompts) - before_second, 2)
            self.assertTrue(menu_ids)
            self.assertTrue(set(menu_ids) <= allowed)
            for entry in menu:
                self.assertIn(entry.id, menu_ids)
            self.assertNotIn("what_is_qteasy", menu_ids)
            self.assertEqual(second.get("sources"), ["data_three_entries"])
            for source_id in second.get("sources") or []:
                topics = set(kb._by_id[source_id].topics)
                print(" source topics:", source_id, sorted(topics))
                self.assertTrue(topics & set(data_topics))
            self.assertEqual(second_focus.get("topic"), data_topics)
            self.assertEqual(second_focus.get("menu_item"), 2)
            self.assertNotEqual(second_focus.get("topic"), "data")
            self.assertEqual(stored, second_focus)
            self.assertIsNone(assistant.session_store.load("a4-focus").task)
            self.assertNotIn("plan_id", second.get("answer") or "")

            before_miss = len(fake.prompts)
            missed = assistant.ask("do not change the topic", response_style="raw", session_id="a4-focus")
            print(" miss code:", (missed.get("error") or {}).get("code"))
            print(" miss topic prompt has focus:", "Current ask_focus:" in fake.prompts[before_miss])
            print(" focus after miss:", latest_ask_focus(assistant.session_store.load("a4-focus")))
            self.assertFalse(missed.get("ok"))
            self.assertEqual((missed.get("error") or {}).get("code"), "NOT_FOUND")
            self.assertIn("Current ask_focus:", fake.prompts[before_miss])
            self.assertIn("data-downloading", fake.prompts[before_miss])
            self.assertEqual(
                latest_ask_focus(assistant.session_store.load("a4-focus")),
                second_focus,
            )

            before_third = len(fake.prompts)
            third = assistant.ask(
                "如何用qteasy回测",
                response_style="raw",
                session_id="a4-focus",
            )
            third_focus = (third.get("raw") or {}).get("ask_focus") or {}
            print(" follow-up topic prompt:", fake.prompts[before_third])
            print(" third sources:", third.get("sources"))
            print(" third focus:", third_focus)
            self.assertTrue(fake.prompts[before_third].startswith("Topic registry:"))
            self.assertIn("Current ask_focus:", fake.prompts[before_third])
            self.assertIn("data-downloading", fake.prompts[before_third])
            self.assertIn("data-analysis", fake.prompts[before_third])
            self.assertEqual(third.get("sources"), ["backtest_intro"])
            self.assertEqual(third_focus.get("topic"), "backtest")
            self.assertEqual(third_focus.get("menu_item"), 3)
            self.assertEqual(latest_ask_focus(assistant.session_store.load("a4-focus")), third_focus)
            self.assertIsNone(assistant.session_store.load("a4-focus").task)

    def test_ordinal_suffix_skips_topic_model(self) -> None:
        """「第三项再解释一下」按 map_item 定主题，不调用定主题模型。"""

        print("\n[TestAiAskEngine] 序号后缀跳过定主题")
        fake = FakeLLMProvider(replies=[
            '{"ids":["backtest_intro"]}',
            "回测解释对应能力地图第三项。",
        ])
        engine = AskEngine(knowledge_base=self.kb, provider=fake)
        payload = engine.ask("第三项再解释一下", resolve_menu_ordinal=True).to_dict()
        focus = (payload.get("raw") or {}).get("ask_focus") or {}
        print(" prompts:", len(fake.prompts))
        print(" card prompt:", fake.prompts[0])
        print(" sources:", payload.get("sources"))
        print(" focus:", focus)
        self._assert_no_plan_execution(payload)
        self.assertEqual(len(fake.prompts), 2)
        self.assertTrue(fake.prompts[0].startswith("Cards in the selected topics:"))
        self.assertIn("Resolved ask_focus:", fake.prompts[0])
        self.assertIn("backtest_intro", fake.prompts[0])
        self.assertNotIn("data_three_entries", fake.prompts[0])
        self.assertEqual(payload.get("sources"), ["backtest_intro"])
        self.assertEqual(focus.get("topic"), "backtest")
        self.assertEqual(focus.get("menu_item"), 3)

    def test_no_session_ordinal_is_not_parsed(self) -> None:
        """没有 session_id 时「第二项」不展开成两个数据主题。"""

        print("\n[TestAiAskEngine] 无 session 不解析第二项")
        from qteasy_ai.app import QteasyAssistant
        from qteasy_ai.memory_store import MemoryStore

        fake = self._protocol(["backtest"], ["backtest_intro"], answer="回测需要明确的日期窗口。")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                provider=fake,
            )
            payload = assistant.ask("第二项", response_style="raw")
            focus = (payload.get("raw") or {}).get("ask_focus") or {}
            print(" topic prompt:", fake.prompts[0])
            print(" card prompt:", fake.prompts[1])
            print(" sources:", payload.get("sources"))
            print(" focus:", focus)
            self._assert_no_plan_execution(payload)
            self.assertTrue(fake.prompts[0].startswith("Topic registry:"))
            self.assertNotIn("Current ask_focus:", fake.prompts[0])
            self.assertNotIn("Resolved ask_focus:", fake.prompts[1])
            self.assertIn("backtest_intro", fake.prompts[1])
            self.assertNotIn("data_three_entries", fake.prompts[1])
            self.assertNotIn("env_ready", fake.prompts[1])
            self.assertEqual(payload.get("sources"), ["backtest_intro"])
            self.assertNotEqual(focus.get("topic"), ["data-downloading", "data-analysis"])
            self.assertNotEqual(focus.get("menu_item"), 2)
            self.assertNotIn("session", payload)

    def test_session_without_provider_does_not_parse_ordinal(self) -> None:
        """无 Provider 的 session 仍走目录，不把「第二项」写成数据焦点。"""

        print("\n[TestAiAskEngine] 无 Provider 不解析第二项")
        from qteasy_ai.app import QteasyAssistant
        from qteasy_ai.memory_store import MemoryStore
        from qteasy_ai.session import latest_ask_focus

        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(memory_store=MemoryStore(base_dir=temp_dir))
            payload = assistant.ask("第二项", response_style="raw", session_id="a4-offline")
            state = assistant.session_store.load("a4-offline")
            print(" ok:", payload.get("ok"), "code:", (payload.get("error") or {}).get("code"))
            print(" sources:", payload.get("sources"))
            print(" stored focus:", latest_ask_focus(state))
            print(" task:", state.task)
            self.assertFalse(payload.get("ok"))
            self.assertEqual((payload.get("error") or {}).get("code"), "NOT_FOUND")
            self.assertEqual(payload.get("sources"), [])
            self.assertNotIn("ask_focus", payload.get("raw") or {})
            self.assertIsNone(latest_ask_focus(state))
            self.assertIsNone(state.task)

    def test_provider_depth1_neighbor_is_allowed_only_with_menu_card(self) -> None:
        """深度 1 邻居可与菜单卡一起入选；只点邻居则 NOT_FOUND。"""

        print("\n[TestAiAskEngine] 深度 1 邻居")
        with tempfile.TemporaryDirectory() as temp_dir:
            kb_dir = _write_neighbor_kb(Path(temp_dir))
            kb = KnowledgeBase(kb_dir=kb_dir, list_func=lambda: [], doc_func=lambda sid: "")
            paired = self._protocol(["backtest"], ["menu_card", "neighbor_card"], answer="menu plus neighbor")
            paired_payload = AskEngine(knowledge_base=kb, provider=paired).ask("回测和旁边那张").to_dict()
            print(" paired sources:", paired_payload.get("sources"))
            print(" card prompt:", paired.prompts[1])
            self.assertEqual(paired_payload["sources"], ["menu_card", "neighbor_card"])
            self.assertIn("edge see_also -> neighbor_card: Neighbor title", paired.prompts[1])
            self.assertNotIn("NEIGHBOR BODY", paired.prompts[1])
            self.assertIn("NEIGHBOR BODY", paired.prompts[2])
            self.assertIn("MENU BODY", paired.prompts[2])

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
                answer="menu plus incoming",
            )
            incoming_payload = AskEngine(knowledge_base=kb, provider=incoming).ask("入边邻居").to_dict()
            print(" incoming sources:", incoming_payload.get("sources"))
            self.assertEqual(incoming_payload["sources"], ["menu_card", "incoming_card"])


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


if __name__ == "__main__":
    unittest.main()

# coding=utf-8
# ======================================
# File: test_ai_session_gate.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-05
# Desc:
# Unittest for SessionGate：填槽 / 新 Task 转移表；S5 Web card_only
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.session import ConversationState
from qteasy_ai.session_gate import SessionGate, answers_pending_slot, merge_facts


def _backtest_session(*, complete: bool = False, clarifying: bool = True) -> ConversationState:
    """构造活跃 backtest 会话。"""

    state = ConversationState.empty("g1")
    state.start_task(query="backtest", job="backtest.builtin")
    state.set_slot("strategy_id", "macd", source="user", confirmed=True)
    state.task.plan_id = "plan-bt"
    if complete:
        state.task.set_missing([])
        state.task.mark_done()
    elif clarifying:
        state.task.set_missing(["end"])
    else:
        state.task.set_missing([])
        state.task.mark_ready()
    return state


class TestAiSessionGate(unittest.TestCase):
    """CLI / 默认允许 Composer 填槽；ready/done 一律新 Task。"""

    def test_fill_slot_end_year_no_classify(self) -> None:
        """CLI：缺 end 时「到 2023 年」为 fill_slot。"""

        print("\n[TestAiSessionGate] fill_slot end year")
        gate = SessionGate(provider=None)
        session = _backtest_session()
        print(" status:", session.task_status(), "missing:", session.task.missing)
        decision = gate.classify(session, "到 2023 年")
        print(" kind:", decision.kind, "patches:", decision.patches, "source:", decision.source)
        self.assertEqual(session.task_status(), "clarifying")
        self.assertEqual(decision.kind, "fill_slot")
        self.assertEqual(decision.patches.get("end"), "20231231")
        self.assertEqual(decision.source, "rule")

    def test_bband_fills_strategy_id_when_clarifying(self) -> None:
        """CLI：pending strategy_id 时「bband」填槽。"""

        print("\n[TestAiSessionGate] bband fills strategy_id")
        gate = SessionGate(provider=None)
        session = ConversationState.empty("g-bband")
        session.start_task(query="params", job="strategy.meta")
        session.task.set_missing(["strategy_id"])
        session.task.set_pending(
            {
                "confirm_prompt": "Which strategy?",
                "step_index": 1,
                "step_total": 1,
                "pending": [
                    {
                        "name": "strategy_id",
                        "options": [{"id": "bband", "label": "Bollinger Band"}],
                    }
                ],
            }
        )
        print(" status:", session.task_status(), "answers:", answers_pending_slot(session, "bband"))
        decision = gate.classify(session, "bband")
        print(" kind:", decision.kind, "patches:", decision.patches)
        self.assertEqual(decision.kind, "fill_slot")
        self.assertEqual(decision.patches.get("strategy_id"), "bband")

    def test_ready_composer_is_new_task_not_change_slot(self) -> None:
        """ready 时「改用沪深300」是新 Task，不是 change_slot。"""

        print("\n[TestAiSessionGate] ready composer new_intent")
        gate = SessionGate(provider=None)
        session = _backtest_session(clarifying=False)
        decision = gate.classify(session, "改用沪深300")
        print(" kind:", decision.kind, "status:", session.task_status(), "patches:", decision.patches)
        self.assertEqual(session.task_status(), "ready")
        self.assertEqual(decision.kind, "new_intent")
        merge_facts(session, {"shares": "000300.SH"}, source="user", confirmed=True)
        print(" slot after control merge:", session.task.slots["shares"].to_dict())
        self.assertEqual(session.task.slots["shares"].value, "000300.SH")

    def test_kline_after_complete_is_new_intent(self) -> None:
        """完成态 +「读取沪深300 K线」→ 新 Task，不是填槽。"""

        print("\n[TestAiSessionGate] completed kline new_intent")
        gate = SessionGate(provider=None)
        session = ConversationState.empty("meta-done")
        session.start_task(query="meta", job="strategy.meta")
        session.task.plan_id = "plan-old"
        session.task.mark_done()
        query = "请帮我读取最近一年沪深300指数的K线数据"
        decision = gate.classify(session, query)
        print(" kind:", decision.kind, "rationale:", decision.rationale, "status:", session.task.status)
        self.assertEqual(decision.kind, "new_intent")
        self.assertEqual(decision.patches, {})
        self.assertEqual(session.task.status, "done")

    def test_strategy_id_token_after_ready_is_new_intent(self) -> None:
        """已 ready 后「strategy_id swma」是新 Task。"""

        print("\n[TestAiSessionGate] ready strategy_id token new_intent")
        gate = SessionGate(provider=None)
        session = _backtest_session(clarifying=False)
        decision = gate.classify(session, "strategy_id swma")
        print(" kind:", decision.kind, "status:", session.task_status())
        self.assertEqual(decision.kind, "new_intent")

    def test_new_intent_skips_without_abandon_card(self) -> None:
        """未执行的回测上换题：new_intent，不要闭合 abandon 卡。"""

        print("\n[TestAiSessionGate] new_intent skip no abandon")
        gate = SessionGate(provider=None)
        session = _backtest_session(clarifying=False)
        decision = gate.classify(session, "再帮我优化参数")
        print(" kind:", decision.kind)
        print(" job still:", session.task.job)
        self.assertEqual(decision.kind, "new_intent")
        self.assertFalse(hasattr(decision, "needs_abandon"))
        self.assertEqual(session.task.job, "backtest.builtin")
        self.assertEqual(session.session_id, "g1")

    def test_execute_plan_and_discuss_only(self) -> None:
        """口头执行 / 只讨论 优先于完成态一律 new_intent。"""

        print("\n[TestAiSessionGate] execute_plan discuss_only")
        gate = SessionGate(provider=None)
        session = _backtest_session(complete=True)
        run_it = gate.classify(session, "请执行上面的计划")
        print(" execute:", run_it.kind, run_it.patches)
        self.assertEqual(run_it.kind, "execute_plan")
        named = gate.classify(session, "请运行计划plan_a2c183f29899")
        print(" named:", named.kind, named.patches)
        self.assertEqual(named.kind, "execute_plan")
        self.assertEqual(named.patches.get("plan_id"), "plan_a2c183f29899")
        talk = gate.classify(session, "本次只讨论，什么是 qteasy")
        print(" discuss:", talk.kind)
        self.assertEqual(talk.kind, "discuss_only")

    def test_skip_clarify_utterance(self) -> None:
        """CLI：澄清中 typed skip → skip_clarify。"""

        print("\n[TestAiSessionGate] skip clarify")
        gate = SessionGate(provider=None)
        session = _backtest_session()
        session.task.set_pending({"confirm_prompt": "Which strategy?"})
        decision = gate.classify(session, "跳过")
        print(" kind:", decision.kind)
        self.assertEqual(decision.kind, "skip_clarify")

    def test_block_running_high_side_effect(self) -> None:
        """高副作用 running 时 Composer 不得静默取消。"""

        print("\n[TestAiSessionGate] block running")
        gate = SessionGate(provider=None)
        session = _backtest_session(clarifying=False)
        session.task.mark_running()
        session.task.high_side_effect = True
        decision = gate.classify(session, "请列出所有内置交易策略")
        print(" kind:", decision.kind, "status:", session.task_status())
        self.assertEqual(decision.kind, "block_running")

    def test_background_running_allows_new_intent(self) -> None:
        """后台运行时 Composer 开新话题，不静默取消。"""

        print("\n[TestAiSessionGate] background allows new intent")
        from qteasy_ai.session import clear_live_running, mark_live_background, register_live_running

        gate = SessionGate(provider=None)
        session = _backtest_session(clarifying=False)
        session.task.mark_running()
        session.task.high_side_effect = True
        register_live_running(session.session_id, task_id=session.task.id)
        mark_live_background(session.session_id)
        try:
            decision = gate.classify(session, "请列出所有内置交易策略")
            print(" kind:", decision.kind)
            self.assertEqual(decision.kind, "new_intent")
        finally:
            clear_live_running(session.session_id)

    def test_completed_task_allows_new_job(self) -> None:
        """任务完成后同句可走新 Job。"""

        print("\n[TestAiSessionGate] completed allows new job")
        gate = SessionGate(provider=None)
        session = _backtest_session(complete=True)
        decision = gate.classify(session, "再帮我优化参数")
        print(" kind:", decision.kind)
        self.assertEqual(decision.kind, "new_intent")


class TestAiWebClarifyComposerGate(unittest.TestCase):
    """S5：Web clarifying 只认 patches/skip；Composer 非空=换题。"""

    def test_web_composer_bband_is_new_task_not_fill(self) -> None:
        """allow_composer_slot_fill=False：澄清中「bband」换题，不填槽。"""

        print("\n[TestAiWebClarifyComposerGate] web bband new task")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-web-bband"
            first = asst.plan(
                "请帮我列出内置交易策略的参数",
                response_style="raw",
                session_id=sid,
            )
            session = asst.session_store.load(sid)
            kinds1 = [item["kind"] for item in (first.get("human_cards") or [])]
            print(" first kinds:", kinds1)
            print(" status:", session.task.status if session.task else None)
            print(" missing:", session.task.missing if session.task else None)
            self.assertIn("clarify", kinds1)
            self.assertEqual(session.task.status, "clarifying")
            old_task_id = session.task.id

            second = asst.plan(
                "bband",
                response_style="raw",
                session_id=sid,
                allow_composer_slot_fill=False,
            )
            after = asst.session_store.load(sid)
            kinds2 = [item["kind"] for item in (second.get("human_cards") or [])]
            notice = next((item for item in kinds2 if item == "mode_notice"), None)
            notice_card = next(
                (item for item in (second.get("human_cards") or []) if item.get("kind") == "mode_notice"),
                None,
            )
            print(" second kinds:", kinds2)
            print(" notice:", None if notice_card is None else notice_card.get("text"))
            print(" old task:", old_task_id, "new task:", after.task.id if after.task else None)
            print(" new status:", after.task.status if after.task else None)
            print(" strategy slot:", after.task.slots.get("strategy_id") if after.task else None)
            self.assertIsNotNone(notice_card)
            self.assertIn("Previous topic skipped.", str((notice_card or {}).get("text") or ""))
            self.assertNotEqual(after.task.id, old_task_id)
            # 未把 bband 填进原澄清槽（换题后新 Task 不应继承已答 strategy_id=bband 为 confirmed 填槽路径）
            slot = after.task.slots.get("strategy_id") if after.task else None
            if slot is not None:
                print(" strategy value/confirmed:", slot.value, slot.confirmed)
            self.assertNotIn("CLARIFICATION_SKIPPED", str(second.get("error") or {}))

    def test_web_composer_typed_skip_is_new_task(self) -> None:
        """Web clarifying：Composer「跳过」不是 CLARIFICATION_SKIPPED，而是换题。"""

        print("\n[TestAiWebClarifyComposerGate] web typed skip new task")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-web-skip"
            asst.plan("请帮我列出内置交易策略的参数", response_style="raw", session_id=sid)
            before = asst.session_store.load(sid)
            self.assertEqual(before.task.status, "clarifying")
            old_id = before.task.id
            payload = asst.plan(
                "跳过",
                response_style="raw",
                session_id=sid,
                allow_composer_slot_fill=False,
            )
            after = asst.session_store.load(sid)
            kinds = [item["kind"] for item in (payload.get("human_cards") or [])]
            err = payload.get("error") or {}
            notice = next(
                (item for item in (payload.get("human_cards") or []) if item.get("kind") == "mode_notice"),
                None,
            )
            print(" kinds:", kinds)
            print(" error:", err)
            print(" notice:", None if notice is None else notice.get("text"))
            print(" task:", old_id, "->", after.task.id if after.task else None, after.task.status if after.task else None)
            self.assertNotEqual(str(err.get("code") or ""), "CLARIFICATION_SKIPPED")
            self.assertNotIn("Clarification skipped", str(err.get("message") or ""))
            self.assertIsNotNone(notice)
            self.assertIn("Previous topic skipped.", str((notice or {}).get("text") or ""))
            self.assertNotEqual(after.task.id, old_id)

    def test_web_control_patches_still_fill(self) -> None:
        """控件 patches 仍填槽，不写 user_text 为填槽证据。"""

        print("\n[TestAiWebClarifyComposerGate] patches fill")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-web-patches"
            asst.plan("请帮我列出内置交易策略的参数", response_style="raw", session_id=sid)
            before = asst.session_store.load(sid)
            users_before = [m for m in before.messages if m.get("kind") == "user_text"]
            print(" clarifying:", before.task.status, "users:", len(users_before))
            self.assertEqual(before.task.status, "clarifying")
            filled = asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"strategy_id": "macd"},
                allow_composer_slot_fill=False,
            )
            after = asst.session_store.load(sid)
            users_after = [m for m in after.messages if m.get("kind") == "user_text"]
            kinds = [item["kind"] for item in (filled.get("human_cards") or [])]
            slot = after.task.slots.get("strategy_id") if after.task else None
            print(" kinds:", kinds)
            print(" users after:", len(users_after), "slot:", None if slot is None else slot.to_dict())
            print(" status:", after.task.status if after.task else None)
            self.assertEqual(len(users_after), len(users_before))
            self.assertIsNotNone(slot)
            self.assertEqual(slot.value, "macd")
            self.assertTrue(slot.confirmed)
            notice = next(
                (item for item in (filled.get("human_cards") or []) if item.get("kind") == "mode_notice"),
                None,
            )
            print(" notice:", None if notice is None else notice.get("text"))
            self.assertTrue(
                notice is None or "Previous topic skipped." not in str(notice.get("text") or "")
            )

    def test_cli_default_still_fills_bband(self) -> None:
        """默认 allow_composer_slot_fill=True：澄清中 bband 仍填槽。"""

        print("\n[TestAiWebClarifyComposerGate] cli default fill")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-cli-bband"
            asst.plan("请帮我列出内置交易策略的参数", response_style="raw", session_id=sid)
            before = asst.session_store.load(sid)
            old_id = before.task.id
            filled = asst.plan("bband", response_style="raw", session_id=sid)
            after = asst.session_store.load(sid)
            slot = after.task.slots.get("strategy_id") if after.task else None
            print(" task id:", old_id, after.task.id if after.task else None)
            print(" status:", after.task.status if after.task else None)
            print(" slot:", None if slot is None else slot.to_dict())
            self.assertEqual(after.task.id, old_id)
            self.assertIsNotNone(slot)
            self.assertEqual(str(slot.value), "bband")
            self.assertTrue(slot.confirmed)
            notice = next(
                (item for item in (filled.get("human_cards") or []) if item.get("kind") == "mode_notice"),
                None,
            )
            print(" notice:", None if notice is None else notice.get("text"))
            self.assertTrue(
                notice is None or "Previous topic skipped." not in str(notice.get("text") or "")
            )

    def test_http_plan_composer_while_clarifying_is_new_task(self) -> None:
        """POST /v1/plan 无 patches：clarifying 下 Composer 换题。"""

        print("\n[TestAiWebClarifyComposerGate] http composer new task")
        from starlette.testclient import TestClient

        from qteasy_ai.workbench.http_app import create_app

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            asst = QteasyAssistant(memory_store=store, registry=build_default_registry())
            app = create_app(assistant=asst)
            client = TestClient(app)
            sid = "s-http-web"
            first = client.post("/v1/plan", json={"query": "请帮我列出内置交易策略的参数", "session_id": sid})
            self.assertEqual(first.status_code, 200)
            before = asst.session_store.load(sid)
            print(" first status:", before.task.status if before.task else None)
            self.assertEqual(before.task.status, "clarifying")
            old_id = before.task.id
            second = client.post("/v1/plan", json={"query": "bband", "session_id": sid})
            self.assertEqual(second.status_code, 200)
            body = second.json()
            after = asst.session_store.load(sid)
            cards = body.get("human_cards") or body.get("messages") or []
            # DTO 可能把卡放在 messages
            if not any(isinstance(c, dict) and c.get("kind") == "mode_notice" for c in cards):
                cards = [m for m in after.messages if isinstance(m, dict)]
            notice_texts = [
                str(c.get("text") or "")
                for c in cards
                if isinstance(c, dict) and c.get("kind") == "mode_notice"
            ]
            print(" notice texts:", notice_texts)
            print(" task:", old_id, "->", after.task.id if after.task else None)
            self.assertTrue(any("Previous topic skipped." in t for t in notice_texts))
            self.assertNotEqual(after.task.id, old_id)


if __name__ == "__main__":
    unittest.main()

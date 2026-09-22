# coding=utf-8
# ======================================
# File: test_ai_session_gate.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-05
# Desc:
# Unittest for SessionGate：填槽 / 新 Task 转移表
# ======================================

import unittest

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
    """Composer 转移表：clarifying 填槽，ready/done 一律新 Task。"""

    def test_fill_slot_end_year_no_classify(self) -> None:
        """缺 end 时「到 2023 年」为 fill_slot。"""

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
        """pending strategy_id 时「bband」填槽。"""

        print("\n[TestAiSessionGate] bband fills strategy_id")
        gate = SessionGate(provider=None)
        session = ConversationState.empty("g-bband")
        session.start_task(query="params", job="strategy.meta")
        session.task.set_missing(["strategy_id"])
        session.task.set_pending(
            {
                "confirm_prompt": "Which strategy?",
                "options": [{"id": "bband", "label": "Bollinger Band"}],
                "pending": [{"name": "strategy_id"}],
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
        """澄清中 skip → skip_clarify。"""

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

    def test_completed_task_allows_new_job(self) -> None:
        """任务完成后同句可走新 Job。"""

        print("\n[TestAiSessionGate] completed allows new job")
        gate = SessionGate(provider=None)
        session = _backtest_session(complete=True)
        decision = gate.classify(session, "再帮我优化参数")
        print(" kind:", decision.kind)
        self.assertEqual(decision.kind, "new_intent")


if __name__ == "__main__":
    unittest.main()

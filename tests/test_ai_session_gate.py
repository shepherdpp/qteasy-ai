# coding=utf-8
# ======================================
# File: test_ai_session_gate.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-05
# Desc:
# Unittest for SessionGate 三分类
# ======================================

import json
import unittest

from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.session import ConversationState
from qteasy_ai.session_gate import SessionGate, merge_facts


def _backtest_session(*, complete: bool = False) -> ConversationState:
    """构造活跃 backtest 会话。"""

    state = ConversationState.empty("g1")
    state.active_intent = {"job": "backtest.builtin", "flags": {}}
    state.set_slot("strategy_id", "macd", source="user", confirmed=True)
    state.missing = ["end"]
    state.current_plan_id = "plan-bt"
    state.task_complete = complete
    return state


class TestAiSessionGate(unittest.TestCase):
    """测试 Mode-R 金句与 Mode-D followup 协议。"""

    def test_fill_slot_end_year_no_classify(self) -> None:
        """缺 end 时「到 2023 年」为 fill_slot。"""

        print("\n[TestAiSessionGate] fill_slot end year")
        gate = SessionGate(provider=None)
        session = _backtest_session()
        decision = gate.classify(session, "到 2023 年")
        print(" kind:", decision.kind, "patches:", decision.patches, "source:", decision.source)
        self.assertEqual(decision.kind, "fill_slot")
        self.assertEqual(decision.patches.get("end"), "20231231")
        self.assertEqual(decision.source, "rule")

    def test_change_slot_shares(self) -> None:
        """「改用沪深300」覆盖 shares，source=user confirmed。"""

        print("\n[TestAiSessionGate] change_slot shares")
        gate = SessionGate(provider=None)
        session = _backtest_session()
        session.missing = []
        decision = gate.classify(session, "改用沪深300")
        print(" kind:", decision.kind, "patches:", decision.patches)
        self.assertEqual(decision.kind, "change_slot")
        self.assertEqual(decision.patches.get("shares"), "000300.SH")
        merge_facts(session, decision.patches, source="user", confirmed=True)
        print(" slot:", session.slots["shares"].to_dict())
        self.assertEqual(session.slots["shares"].value, "000300.SH")
        self.assertEqual(session.slots["shares"].source, "user")
        self.assertTrue(session.slots["shares"].confirmed)

    def test_new_intent_needs_abandon_keeps_session(self) -> None:
        """未确认回测时「再帮我优化」要放弃确认，不是 Job 栈。"""

        print("\n[TestAiSessionGate] new_intent abandon")
        gate = SessionGate(provider=None)
        session = _backtest_session()
        session.missing = []
        decision = gate.classify(session, "再帮我优化参数")
        print(" kind:", decision.kind, "needs_abandon:", decision.needs_abandon)
        print(" active still:", session.active_intent)
        self.assertEqual(decision.kind, "new_intent")
        self.assertTrue(decision.needs_abandon)
        self.assertEqual(session.active_intent["job"], "backtest.builtin")
        session.awaiting_abandon = True
        confirm = gate.classify(session, "放弃")
        print(" abandon confirm:", confirm.kind, confirm.abandon_confirmed)
        self.assertEqual(confirm.kind, "new_intent")
        self.assertTrue(confirm.abandon_confirmed)
        self.assertEqual(session.session_id, "g1")
        session.turns.append({"query": "再帮我优化参数"})
        print(" turns remain:", session.turns)
        self.assertEqual(len(session.turns), 1)

    def test_awaiting_abandon_blocks_llm_followup(self) -> None:
        """awaiting_abandon 时优先规则门，不被 LLM confirm 绕过。"""

        print("\n[TestAiSessionGate] awaiting_abandon ignores llm")
        provider = FakeLLMProvider(
            replies=[json.dumps({"followup": "confirm", "patches": {}})]
        )
        gate = SessionGate(provider=provider)
        session = _backtest_session()
        session.missing = []
        session.awaiting_abandon = True
        decision = gate.classify(session, "list built-in strategies")
        print(" kind:", decision.kind, "abandon_confirmed:", decision.abandon_confirmed)
        self.assertEqual(decision.kind, "clarify")
        self.assertFalse(decision.abandon_confirmed)

    def test_completed_task_allows_new_job(self) -> None:
        """任务完成后同句可走新 Job。"""

        print("\n[TestAiSessionGate] completed allows new job")
        gate = SessionGate(provider=None)
        session = _backtest_session(complete=True)
        session.missing = []
        decision = gate.classify(session, "再帮我优化参数")
        print(" kind:", decision.kind, "needs_abandon:", decision.needs_abandon)
        self.assertEqual(decision.kind, "new_intent")
        self.assertFalse(decision.needs_abandon)

    def test_completed_task_blocks_llm_fill_slot(self) -> None:
        """task_complete 后即使 LLM 说 fill_slot，也强制 new_intent。"""

        print("\n[TestAiSessionGate] completed blocks llm fill_slot")
        provider = FakeLLMProvider(
            replies=[
                json.dumps(
                    {
                        "followup": "fill_slot",
                        "patches": {
                            "strategy_type": "择时策略",
                            "short_ma": 20,
                            "long_ma": 60,
                        },
                    }
                )
            ]
        )
        gate = SessionGate(provider=provider)
        session = ConversationState.empty("meta-done")
        session.active_intent = {"job": "strategy.meta", "flags": {}}
        session.task_complete = True
        session.current_plan_id = "plan-old"
        query = "帮我写一个基于 20/60 日均线金叉死叉的择时策略，并用 2015–2020 年沪深300做回测"
        decision = gate.classify(session, query)
        print(" kind:", decision.kind, "rationale:", decision.rationale, "patches:", decision.patches)
        self.assertEqual(decision.kind, "new_intent")
        self.assertEqual(decision.rationale, "new_after_complete")
        self.assertEqual(decision.patches, {})

    def test_mode_d_valid_followup(self) -> None:
        """FakeLLM 合法 followup JSON 才接受。"""

        print("\n[TestAiSessionGate] mode-d valid json")
        fake = FakeLLMProvider(
            replies=[json.dumps({"followup": "fill_slot", "patches": {"end": "20231231"}})]
        )
        gate = SessionGate(provider=fake)
        session = _backtest_session()
        decision = gate.classify(session, "到年底")
        print(" kind:", decision.kind, "patches:", decision.patches, "source:", decision.source)
        self.assertEqual(decision.kind, "fill_slot")
        self.assertEqual(decision.patches["end"], "20231231")
        self.assertEqual(decision.source, "llm")

    def test_mode_d_steps_or_unknown_kind_clarify(self) -> None:
        """含 steps 或未知 kind → clarify。"""

        print("\n[TestAiSessionGate] mode-d illegal")
        fake = FakeLLMProvider(
            replies=[
                json.dumps({"followup": "fill_slot", "patches": {}, "steps": [{"skill": "x"}]}),
                json.dumps({"followup": "invented", "patches": {}}),
            ]
        )
        gate = SessionGate(provider=fake)
        session = _backtest_session()
        first = gate.classify(session, "补一下")
        second = gate.classify(session, "再补")
        print(" first:", first.kind, first.rationale)
        print(" second:", second.kind, second.rationale)
        self.assertEqual(first.kind, "clarify")
        self.assertEqual(second.kind, "clarify")


if __name__ == "__main__":
    unittest.main()
